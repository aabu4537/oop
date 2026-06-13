"""Phase 4 — Monte Carlo World Cup tournament simulator.

Uses a Poisson goal model calibrated to Elo ratings to simulate match scorelines.
Group standings are resolved by points → goal difference → goals for.
Knockout ties go to extra time (reduced Poisson) then Elo-weighted penalty shootout.

Run:
    python -m src.simulation.engine                  # 2026-style groups, 10 000 sims
    python -m src.simulation.engine --sims 50000
    python -m src.simulation.engine --seed 0
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
# Average goals per team per international match
_MU = _cfg.sim_mu
# Stages ordered from most to least exclusive
STAGES = ["champion", "final", "semi_final", "quarter_final", "round_of_16", "group_stage"]
# Reverse order (group_stage first) used for range comparisons
_STAGE_IDX = {s: i for i, s in enumerate(reversed(STAGES))}

# Ordered from least to most exclusive — used to assign round labels dynamically
_ROUND_NAMES = ["round_of_64", "round_of_32", "round_of_16",
                "quarter_final", "semi_final", "final", "champion"]


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Team:
    name: str
    elo: float
    group: str = ""


# ---------------------------------------------------------------------------
# Goal model — pure functions
# ---------------------------------------------------------------------------

def goal_lambdas(home_elo: float, away_elo: float) -> tuple[float, float]:
    """Expected goals for home and away teams derived from Elo ratings.

    Uses a symmetric Poisson model: the geometric mean of both lambdas equals
    _MU, and their ratio equals the Elo strength ratio.
    """
    scale = 10 ** ((home_elo - away_elo) / 800.0)  # tempered (÷2 of std Elo scale)
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
    """Simulate a knockout match; draws go to extra time then penalties."""
    hg, ag = simulate_scoreline(home.elo, away.elo, rng)
    if hg != ag:
        return home if hg > ag else away

    # Extra time — reduced scoring rate
    hg2, ag2 = int(rng.poisson(_cfg.sim_extra_time_rate)), int(rng.poisson(_cfg.sim_extra_time_rate))
    if hg2 != ag2:
        return home if hg2 > ag2 else away

    # Penalties — slight Elo advantage
    p_home = 0.5 + _cfg.sim_penalty_elo_factor * np.tanh(
        (home.elo - away.elo) / _cfg.sim_penalty_elo_scale
    )
    return home if rng.random() < p_home else away


# ---------------------------------------------------------------------------
# Group stage
# ---------------------------------------------------------------------------

def simulate_group(teams: list[Team], rng: np.random.Generator) -> list[Team]:
    """Simulate round-robin group; return teams sorted by points, GD, GF."""
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
    """Standard WC bracket: pair A1 vs B2, B1 vs A2, C1 vs D2, etc."""
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
    """One full simulation run. Returns {team_name: furthest_stage_reached}."""
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
    # Assign stage names dynamically so the engine works for any power-of-2 bracket
    n_rounds = int(np.log2(len(current)))
    round_stages = _ROUND_NAMES[-n_rounds:]  # already ordered: QF → SF → Final → Champion

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
    """Simulate tournament n_sims times; return stage-reach probability table.

    Each row is a team; columns are the reachable stages for this tournament
    (champion → group_stage). A probability represents the fraction of
    simulations in which a team reached at least that stage.
    """
    rng = np.random.default_rng(seed)
    all_teams = [t.name for teams in groups.values() for t in teams]

    # Determine which stages are reachable for this bracket size
    n_bracket = len(groups) * 2
    n_rounds = int(np.log2(n_bracket)) if n_bracket >= 2 else 0
    reachable = set(_ROUND_NAMES[-n_rounds:]) | {"group_stage", "round_of_16"}
    active_stages = [s for s in STAGES if s in reachable]

    stage_rank = {s: i for i, s in enumerate(reversed(active_stages))}
    counts: dict[str, dict[str, int]] = {t: {s: 0 for s in active_stages} for t in all_teams}

    for sim in range(n_sims):
        result = _simulate_once(groups, rng)
        for team, furthest in result.items():
            furthest_rank = stage_rank.get(furthest, 0)
            for stage, rank in stage_rank.items():
                if rank <= furthest_rank:
                    counts[team][stage] += 1

        if (sim + 1) % 2000 == 0:
            logger.info("Completed %d / %d simulations", sim + 1, n_sims)

    rows = [
        {"team": team, **{s: round(counts[team][s] / n_sims, 4) for s in active_stages}}
        for team in all_teams
    ]
    return pd.DataFrame(rows).sort_values("champion", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Sample 2026 World Cup groups (illustrative Elo ratings)
# ---------------------------------------------------------------------------

SAMPLE_2026_GROUPS: dict[str, list[Team]] = {
    "A": [Team("USA",      1836, "A"), Team("Canada",   1714, "A"), Team("Mexico",   1782, "A"), Team("Jamaica",  1514, "A")],
    "B": [Team("Spain",    2104, "B"), Team("Croatia",  1951, "B"), Team("Morocco",  1792, "B"), Team("Japan",    1786, "B")],
    "C": [Team("France",   2060, "C"), Team("Germany",  1939, "C"), Team("Portugal", 1966, "C"), Team("Senegal",  1713, "C")],
    "D": [Team("Brazil",   2058, "D"), Team("Argentina",2142, "D"), Team("Colombia", 1876, "D"), Team("Ecuador",  1746, "D")],
    "E": [Team("England",  1966, "E"), Team("Netherlands",1938,"E"), Team("Iran",    1654, "E"), Team("Wales",    1729, "E")],
    "F": [Team("Belgium",  1931, "F"), Team("Switzerland",1870,"F"), Team("Serbia",  1832, "F"), Team("Cameroon", 1563, "F")],
    "G": [Team("Uruguay",  1896, "G"), Team("South Korea",1734,"G"), Team("Ghana",  1562, "G"), Team("Australia", 1726, "G")],
    "H": [Team("Denmark",  1892, "H"), Team("Tunisia",  1624, "H"), Team("Poland",  1791, "H"), Team("Saudi Arabia",1620,"H")],
}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Monte Carlo World Cup Simulator")
    parser.add_argument("--sims", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    logger.info("Running %d simulations ...", args.sims)
    df = run_monte_carlo(SAMPLE_2026_GROUPS, n_sims=args.sims, seed=args.seed)

    pd.set_option("display.float_format", "{:.1%}".format)
    pd.set_option("display.max_rows", 40)
    print("\n=== World Cup 2026 Simulation Results ===\n")
    print(df.to_string(index=False))
