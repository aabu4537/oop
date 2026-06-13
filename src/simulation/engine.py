"""Phase 4 — Monte Carlo World Cup tournament simulator.

Uses a Poisson goal model calibrated to Elo ratings to simulate match scorelines.
OOP composite (when available in team_metrics) is blended in as an Elo-equivalent
boost: effective_elo = elo + oop_elo_scale * oop_zscore.
Group standings are resolved by points → goal difference → goals for.
Knockout ties go to extra time (reduced Poisson) then Elo-weighted penalty shootout.

Run:
    python -m src.simulation.engine                  # pull from DB, 10 000 sims
    python -m src.simulation.engine --sims 50000
    python -m src.simulation.engine --seed 0
    python -m src.simulation.engine --no-db          # use hardcoded fallback ratings
"""
from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.config import get_model_config

logger = logging.getLogger(__name__)

_cfg = get_model_config()
_MU = _cfg.sim_mu
STAGES = ["champion", "final", "semi_final", "quarter_final", "round_of_16", "group_stage"]
_STAGE_IDX = {s: i for i, s in enumerate(reversed(STAGES))}
_ROUND_NAMES = ["round_of_64", "round_of_32", "round_of_16",
                "quarter_final", "semi_final", "final", "champion"]

# Canonical group assignments for WC 2026 — names match teams.name in DB
WC_2026_GROUPS: dict[str, list[str]] = {
    "A": ["United States", "Canada",       "Mexico",      "Jamaica"],
    "B": ["Spain",         "Croatia",      "Morocco",     "Japan"],
    "C": ["France",        "Germany",      "Portugal",    "Senegal"],
    "D": ["Brazil",        "Argentina",    "Colombia",    "Ecuador"],
    "E": ["England",       "Netherlands",  "Iran",        "Wales"],
    "F": ["Belgium",       "Switzerland",  "Serbia",      "Cameroon"],
    "G": ["Uruguay",       "South Korea",  "Ghana",       "Australia"],
    "H": ["Denmark",       "Tunisia",      "Poland",      "Saudi Arabia"],
}

# Display names for teams whose DB name differs from the familiar short form
_DISPLAY_NAME: dict[str, str] = {
    "United States": "USA",
}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Team:
    name: str
    elo: float          # effective Elo (base Elo + OOP boost)
    group: str = ""
    display_name: str = ""

    def __post_init__(self) -> None:
        if not self.display_name:
            self.display_name = _DISPLAY_NAME.get(self.name, self.name)


# ---------------------------------------------------------------------------
# Goal model — pure functions
# ---------------------------------------------------------------------------

def goal_lambdas(home_elo: float, away_elo: float) -> tuple[float, float]:
    """Expected goals derived from effective Elo (base + OOP boost)."""
    scale = 10 ** ((home_elo - away_elo) / 800.0)
    return _MU * scale, _MU / scale


def simulate_scoreline(
    home_elo: float, away_elo: float, rng: np.random.Generator
) -> tuple[int, int]:
    lam_h, lam_a = goal_lambdas(home_elo, away_elo)
    return int(rng.poisson(lam_h)), int(rng.poisson(lam_a))


# ---------------------------------------------------------------------------
# Match simulation
# ---------------------------------------------------------------------------

def simulate_knockout_match(home: Team, away: Team, rng: np.random.Generator) -> Team:
    hg, ag = simulate_scoreline(home.elo, away.elo, rng)
    if hg != ag:
        return home if hg > ag else away

    hg2, ag2 = int(rng.poisson(_cfg.sim_extra_time_rate)), int(rng.poisson(_cfg.sim_extra_time_rate))
    if hg2 != ag2:
        return home if hg2 > ag2 else away

    p_home = 0.5 + _cfg.sim_penalty_elo_factor * np.tanh(
        (home.elo - away.elo) / _cfg.sim_penalty_elo_scale
    )
    return home if rng.random() < p_home else away


# ---------------------------------------------------------------------------
# Group stage
# ---------------------------------------------------------------------------

def simulate_group(teams: list[Team], rng: np.random.Generator) -> list[Team]:
    stats: dict[str, dict] = {
        t.name: {"pts": 0, "gd": 0, "gf": 0, "team": t} for t in teams
    }

    for i in range(len(teams)):
        for j in range(i + 1, len(teams)):
            h, a = teams[i], teams[j]
            hg, ag = simulate_scoreline(h.elo, a.elo, rng)

            stats[h.name]["gf"] += hg
            stats[h.name]["gd"] += hg - ag
            stats[a.name]["gf"] += ag
            stats[a.name]["gd"] += ag - hg

            if hg > ag:
                stats[h.name]["pts"] += 3
            elif hg == ag:
                stats[h.name]["pts"] += 1
                stats[a.name]["pts"] += 1
            else:
                stats[a.name]["pts"] += 3

    ranking = sorted(
        stats.values(),
        key=lambda s: (s["pts"], s["gd"], s["gf"]),
        reverse=True,
    )
    return [s["team"] for s in ranking]


# ---------------------------------------------------------------------------
# Full tournament simulation
# ---------------------------------------------------------------------------

def _build_r16_bracket(winners: list[Team], runners: list[Team]) -> list[Team]:
    bracket: list[Team] = []
    for i in range(0, len(winners), 2):
        j = i + 1
        bracket.append(winners[i])
        bracket.append(runners[j] if j < len(runners) else runners[0])
        bracket.append(winners[j] if j < len(winners) else winners[0])
        bracket.append(runners[i])
    return bracket


def _simulate_once(
    groups: dict[str, list[Team]], rng: np.random.Generator
) -> dict[str, str]:
    results: dict[str, str] = {
        t.name: "group_stage" for teams in groups.values() for t in teams
    }

    winners: list[Team] = []
    runners: list[Team] = []
    for group_teams in groups.values():
        ranked = simulate_group(group_teams, rng)
        winners.append(ranked[0])
        runners.append(ranked[1])
        for t in ranked[:2]:
            results[t.name] = "round_of_16"

    bracket = _build_r16_bracket(winners, runners)

    current = bracket
    n_rounds = int(np.log2(len(current)))
    round_stages = _ROUND_NAMES[-n_rounds:]

    for stage in round_stages:
        next_round: list[Team] = []
        for k in range(0, len(current), 2):
            winner = simulate_knockout_match(current[k], current[k + 1], rng)
            results[winner.name] = stage
            next_round.append(winner)
        current = next_round

    return results


def run_monte_carlo(
    groups: dict[str, list[Team]],
    n_sims: int = 10_000,
    seed: int = 42,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    all_teams = [t for teams in groups.values() for t in teams]

    n_bracket = len(groups) * 2
    n_rounds = int(np.log2(n_bracket)) if n_bracket >= 2 else 0
    reachable = set(_ROUND_NAMES[-n_rounds:]) | {"group_stage", "round_of_16"}
    active_stages = [s for s in STAGES if s in reachable]

    stage_rank = {s: i for i, s in enumerate(reversed(active_stages))}
    counts: dict[str, dict[str, int]] = {t.name: {s: 0 for s in active_stages} for t in all_teams}

    for sim in range(n_sims):
        result = _simulate_once(groups, rng)
        for team_name, furthest in result.items():
            furthest_rank = stage_rank.get(furthest, 0)
            for stage, rank in stage_rank.items():
                if rank <= furthest_rank:
                    counts[team_name][stage] += 1

        if (sim + 1) % 2000 == 0:
            logger.info("Completed %d / %d simulations", sim + 1, n_sims)

    rows = [
        {
            "team": t.display_name,
            "elo": round(t.elo, 1),
            **{s: round(counts[t.name][s] / n_sims, 4) for s in active_stages},
        }
        for t in all_teams
    ]
    return pd.DataFrame(rows).sort_values("champion", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# DB loader — pulls live Elo + OOP from the database
# ---------------------------------------------------------------------------

def load_groups_from_db(
    assignments: dict[str, list[str]],
    fallback: dict[str, list[Team]],
) -> dict[str, list[Team]]:
    """Build groups dict using live Elo from teams table and OOP from team_metrics.

    OOP composite is converted to an Elo-equivalent boost via z-score normalisation
    across all teams that have metric data:
        effective_elo = base_elo + sim_oop_elo_scale * oop_zscore

    Teams missing from the DB fall back to their hardcoded values.
    Teams with no OOP data get a 0 boost (pure Elo).
    """
    from sqlalchemy import text
    from src.db.session import get_session

    all_names = [name for names in assignments.values() for name in names]

    with get_session() as session:
        # Base Elo
        elo_rows = session.execute(
            text("SELECT name, elo_rating FROM teams WHERE name = ANY(:names)"),
            {"names": all_names},
        ).fetchall()
        elo_map: dict[str, float] = {r.name: r.elo_rating for r in elo_rows if r.elo_rating}

        # Average OOP composite per team (across all their StatsBomb matches)
        oop_rows = session.execute(
            text("""
                SELECT t.name, AVG(tm.oop_composite) AS avg_oop
                FROM team_metrics tm
                JOIN teams t ON t.team_id = tm.team_id
                WHERE tm.oop_composite IS NOT NULL
                  AND t.name = ANY(:names)
                GROUP BY t.name
            """),
            {"names": all_names},
        ).fetchall()
        oop_map: dict[str, float] = {r.name: r.avg_oop for r in oop_rows}

    # Z-score OOP across teams that have data
    oop_boost: dict[str, float] = {}
    if oop_map:
        values = np.array(list(oop_map.values()))
        mu, sigma = values.mean(), values.std()
        if sigma > 0:
            for name, val in oop_map.items():
                oop_boost[name] = _cfg.sim_oop_elo_scale * (val - mu) / sigma
        logger.info(
            "OOP data found for %d / %d teams — boost range [%.1f, %.1f] Elo pts",
            len(oop_map), len(all_names),
            min(oop_boost.values()), max(oop_boost.values()),
        )
    else:
        logger.info("No OOP data in team_metrics — using pure Elo ratings")

    # Build fallback lookup: name → Team (from hardcoded groups)
    fallback_lookup: dict[str, Team] = {
        t.name: t for teams in fallback.values() for t in teams
    }

    groups: dict[str, list[Team]] = {}
    for group, names in assignments.items():
        teams: list[Team] = []
        for name in names:
            if name in elo_map:
                base_elo = elo_map[name]
                boost = oop_boost.get(name, 0.0)
                effective_elo = base_elo + boost
                teams.append(Team(name=name, elo=effective_elo, group=group))
                if boost:
                    logger.debug("%s: base=%.1f oop_boost=%.1f → %.1f", name, base_elo, boost, effective_elo)
            elif name in fallback_lookup:
                logger.warning("'%s' not in DB — using hardcoded Elo %.1f", name, fallback_lookup[name].elo)
                t = fallback_lookup[name]
                teams.append(Team(name=t.name, elo=t.elo, group=group))
            else:
                logger.error("'%s' not found in DB or fallback — skipping", name)
        groups[group] = teams

    return groups


# ---------------------------------------------------------------------------
# Hardcoded fallback ratings (used with --no-db or when DB is unavailable)
# ---------------------------------------------------------------------------

FALLBACK_GROUPS: dict[str, list[Team]] = {
    "A": [Team("United States", 1836, "A"), Team("Canada",      1714, "A"), Team("Mexico",    1782, "A"), Team("Jamaica",      1514, "A")],
    "B": [Team("Spain",         2104, "B"), Team("Croatia",     1951, "B"), Team("Morocco",   1792, "B"), Team("Japan",        1786, "B")],
    "C": [Team("France",        2060, "C"), Team("Germany",     1939, "C"), Team("Portugal",  1966, "C"), Team("Senegal",      1713, "C")],
    "D": [Team("Brazil",        2058, "D"), Team("Argentina",   2142, "D"), Team("Colombia",  1876, "D"), Team("Ecuador",      1746, "D")],
    "E": [Team("England",       1966, "E"), Team("Netherlands", 1938, "E"), Team("Iran",      1654, "E"), Team("Wales",        1729, "E")],
    "F": [Team("Belgium",       1931, "F"), Team("Switzerland", 1870, "F"), Team("Serbia",    1832, "F"), Team("Cameroon",     1563, "F")],
    "G": [Team("Uruguay",       1896, "G"), Team("South Korea", 1734, "G"), Team("Ghana",     1562, "G"), Team("Australia",    1726, "G")],
    "H": [Team("Denmark",       1892, "H"), Team("Tunisia",     1624, "H"), Team("Poland",    1791, "H"), Team("Saudi Arabia", 1620, "H")],
}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Monte Carlo World Cup Simulator")
    parser.add_argument("--sims", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--no-db", action="store_true", help="Use hardcoded fallback ratings")
    args = parser.parse_args()

    if args.no_db:
        groups = FALLBACK_GROUPS
        logger.info("Using hardcoded fallback Elo ratings")
    else:
        try:
            groups = load_groups_from_db(WC_2026_GROUPS, FALLBACK_GROUPS)
        except Exception as exc:
            logger.warning("DB load failed (%s) — falling back to hardcoded ratings", exc)
            groups = FALLBACK_GROUPS

    logger.info("Running %d simulations ...", args.sims)
    df = run_monte_carlo(groups, n_sims=args.sims, seed=args.seed)

    pd.set_option("display.max_rows", 40)
    stage_cols = [c for c in df.columns if c not in ("team", "elo")]
    display_df = df.copy()
    for col in stage_cols:
        display_df[col] = display_df[col].map("{:.1%}".format)
    print("\n=== World Cup 2026 Simulation Results (Elo + OOP) ===\n")
    print(display_df.to_string(index=False))
