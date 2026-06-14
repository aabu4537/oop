"""Elo rating calculator — derives current international Elo ratings from
historical match results stored in the `matches` table.

Source data: martj42/international_results (loaded via ingest_fifa.py).
Must be run AFTER ingest_fifa.py has populated the matches table.

Algorithm
---------
  adv    = 0 if neutral venue else 100
  E_home = 1 / (1 + 10 ^ ((R_away - (R_home + adv)) / 400))
  K_eff  = K * gd_multiplier   where gd_multiplier = min(log(|GD|+1)+1, 2.0)
  ΔR     = K_eff * (S - E)

  After update, if the match is more than 4 years old relative to the most
  recent match in the dataset, each additional year pulls the rating 10%
  back toward 1500: r = r + 0.10 * (1500 - r)  [applied once per year beyond 4]

K-factor schedule (before GD multiplier)
    60 — FIFA World Cup final tournament
    50 — Tier-1 continental: UEFA EURO, Copa América (strongest fields)
    40 — Tier-2 continental: AFCON, AFC Asian Cup
       — FIFA WC qualifying (UEFA / CONMEBOL zones — competitive fields)
       — UEFA Euro qualifying, AFCON qualifying
    35 — UEFA / CONCACAF Nations League; CONMEBOL qualifying (Copa América qual)
    32 — FIFA WC qualifying (CAF / CONCACAF zones — weaker fields)
    30 — Tier-3 continental: Gold Cup, CONCACAF Championship (weakest fields)
       — FIFA WC qualifying (AFC zone — weakest qualifying field)
       — AFC / CONCACAF cup qualifying
    20 — Friendlies and all other matches

Reputation floor
    Teams whose peak Elo in the last 4 years (the non-decayed window) exceeds
    1750 are protected by a floor of 97% of that peak.  Using the 4-year peak
    instead of a longer average avoids the decay artifact where match ratings
    from 5-10 years ago are artificially pulled toward 1500 during processing.

Soft ceiling
    After all floors are applied, any rating above 1950 is compressed:
        rating = 1950 + (rating - 1950) * 0.5
    This keeps the dominant #1 team meaningfully ahead while preventing a
    single outlier rating from capturing a disproportionate share of
    Monte Carlo simulation outcomes.

Constants
    Starting Elo : 1500
    Home advantage : 100 Elo points (0 on neutral ground)
    GD multiplier cap : 2.0
"""
import math
import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from src.config import get_model_config
from src.db.models import Team
from src.db.session import get_session
from src.etl.pipeline_logger import assert_upstream_ok, pipeline_run

logger = logging.getLogger(__name__)

_cfg = get_model_config()
_START_ELO = _cfg.elo_start
_HOME_ADV   = _cfg.elo_home_advantage
_GD_CAP     = _cfg.elo_gd_cap
_K_WORLD_CUP    = _cfg.elo_k_world_cup
_K_CONTINENTAL  = _cfg.elo_k_continental
_K_QUALIFIER    = _cfg.elo_k_qualifier
_K_FRIENDLY     = _cfg.elo_k_friendly
_DECAY_RATE     = _cfg.elo_decay_rate
_DECAY_WINDOW   = _cfg.elo_decay_window_years

# Confederation membership — used to differentiate WC qualifying K by zone.
# Teams not listed default to UEFA/CONMEBOL behaviour (K=40 for WC qual).
_AFC: frozenset[str] = frozenset({
    "Japan", "South Korea", "Iran", "Australia", "Saudi Arabia", "Iraq",
    "Qatar", "China", "UAE", "United Arab Emirates", "Bahrain", "Oman",
    "Jordan", "Uzbekistan", "Syria", "India", "Vietnam", "Thailand",
    "Malaysia", "Indonesia", "Kuwait", "Palestine", "North Korea",
    "Tajikistan", "Lebanon", "Myanmar", "Philippines", "Hong Kong",
    "Singapore", "Kyrgyzstan", "Afghanistan", "Cambodia", "Laos",
    "Mongolia", "Maldives", "Sri Lanka", "Nepal", "Bhutan", "Timor-Leste",
    "Macau", "Guam", "Chinese Taipei", "Bangladesh", "Pakistan",
})

_CAF: frozenset[str] = frozenset({
    "Morocco", "Senegal", "Nigeria", "Algeria", "Egypt", "Ivory Coast",
    "Cameroon", "Ghana", "Tunisia", "South Africa", "Mali", "Guinea",
    "Burkina Faso", "Zambia", "DR Congo", "Tanzania", "Uganda", "Kenya",
    "Ethiopia", "Cape Verde", "Mauritania", "Benin", "Mozambique", "Angola",
    "Equatorial Guinea", "Gabon", "Namibia", "Zimbabwe", "Madagascar",
    "Malawi", "Rwanda", "Libya", "Sierra Leone", "Guinea-Bissau",
    "Congo", "Sudan", "South Sudan", "Togo", "Botswana", "Niger",
    "Central African Republic", "Chad", "Burundi", "Djibouti",
    "Eritrea", "Liberia", "Swaziland", "Eswatini", "Comoros",
    "Lesotho", "Somalia", "Sao Tome and Principe", "Seychelles",
})

_CONCACAF: frozenset[str] = frozenset({
    "Mexico", "United States", "Canada", "Costa Rica", "Honduras",
    "Jamaica", "Panama", "El Salvador", "Trinidad and Tobago", "Haiti",
    "Guatemala", "Curacao", "Suriname", "Bermuda", "Belize",
    "Nicaragua", "Dominican Republic", "Cuba", "Barbados",
    "Antigua and Barbuda", "Saint Kitts and Nevis", "Grenada",
    "Saint Lucia", "Saint Vincent and the Grenadines", "Guyana",
    "Aruba", "Cayman Islands", "Montserrat", "Dominica",
    "Puerto Rico", "Martinique", "Guadeloupe", "French Guiana",
    "Turks and Caicos Islands", "British Virgin Islands",
    "US Virgin Islands", "Anguilla", "Bonaire",
})


def _wc_qual_k(home: str, away: str) -> float:
    """Return the appropriate K for a FIFA World Cup qualification match
    based on which confederation zone the match falls in."""
    if home in _AFC or away in _AFC:
        return 18.0   # AFC zone — weakest qualifying field
    if home in _CAF or away in _CAF:
        return 20.0   # CAF zone
    if home in _CONCACAF or away in _CONCACAF:
        return 20.0   # CONCACAF zone
    return _K_QUALIFIER  # UEFA / CONMEBOL → 40


_FETCH_SQL = text("""
    SELECT
        ht.name  AS home_team,
        at_.name AS away_team,
        m.home_score,
        m.away_score,
        m.competition,
        m.match_date,
        COALESCE(m.neutral, FALSE) AS neutral
    FROM matches m
    JOIN teams ht  ON m.home_team_id = ht.team_id
    JOIN teams at_ ON m.away_team_id = at_.team_id
    WHERE m.home_score IS NOT NULL
      AND m.away_score IS NOT NULL
      AND m.competition NOT LIKE 'International - %'
    ORDER BY m.match_date ASC
""")


# ---------------------------------------------------------------------------
# Public helpers (exported for tests)
# ---------------------------------------------------------------------------

def k_factor(
    tournament: str | None,
    *,
    home_team: str = "",
    away_team: str = "",
) -> float:
    """Base K-factor for a tournament, before goal-difference scaling.

    Pass home_team / away_team when available so that FIFA World Cup
    qualification K can be tuned by confederation zone.
    """
    t = (tournament or "").lower()
    # Check qualifiers first — some names contain both confederation and "cup"
    if "qualif" in t or "qualification" in t:
        if "copa" in t:
            return 35.0   # Copa América qualification (CONMEBOL)
        if "africa" in t or "african" in t or "afcon" in t:
            return 18.0   # AFCON qualification — must precede "afc" check
        if "afc" in t or "asian cup" in t:
            return 16.0   # AFC cup qualifiers — weakest field
        if "concacaf" in t or "gold cup" in t:
            return 16.0   # CONCACAF cup qualifiers
        if "world cup" in t:
            return _wc_qual_k(home_team, away_team)  # confederation-aware
        return _K_QUALIFIER  # UEFA Euro qual → 40
    if _is_world_cup_final(t):
        return _K_WORLD_CUP
    # Nations League: UEFA stays at 35, CONCACAF reduced (weaker field)
    if "nations league" in t:
        return 20.0 if "concacaf" in t else 35.0
    if _is_tier1_continental(t):
        return _K_CONTINENTAL          # 50 — EURO, Copa América
    if _is_tier2_continental(t):
        return 24.0                    # AFCON, AFC Asian Cup
    if _is_tier3_continental(t):
        return 16.0                    # Gold Cup, CONCACAF Championship
    return _K_FRIENDLY


def gd_multiplier(home_score: int, away_score: int) -> float:
    """Scale K by goal difference, capped at _GD_CAP."""
    gd = abs(home_score - away_score)
    return min(math.log(gd + 1) + 1, _GD_CAP)


def elo_update(
    r_home: float,
    r_away: float,
    home_score: int,
    away_score: int,
    tournament: str | None,
    *,
    neutral: bool = False,
    match_date: date | None = None,
    max_date: date | None = None,
    home_team: str = "",
    away_team: str = "",
) -> tuple[float, float]:
    """Return updated (r_home, r_away) after one match.

    Args:
        neutral:    True when the match was played at a neutral venue.
        match_date: Date of this match; used for recency decay.
        max_date:   Latest match date in the full dataset.
        home_team:  Name of the home side — used for confederation-aware K.
        away_team:  Name of the away side — used for confederation-aware K.
    """
    adv = 0.0 if neutral else _HOME_ADV
    k_eff = k_factor(tournament, home_team=home_team, away_team=away_team) * gd_multiplier(home_score, away_score)

    e_home = 1.0 / (1.0 + 10.0 ** ((r_away - (r_home + adv)) / 400.0))
    e_away = 1.0 - e_home

    if home_score > away_score:
        s_home, s_away = 1.0, 0.0
    elif home_score == away_score:
        s_home, s_away = 0.5, 0.5
    else:
        s_home, s_away = 0.0, 1.0

    r_home = r_home + k_eff * (s_home - e_home)
    r_away = r_away + k_eff * (s_away - e_away)

    # Recency decay — applied once per year beyond the decay window
    if match_date is not None and max_date is not None:
        years_old = (max_date - match_date).days / 365.25
        if years_old > _DECAY_WINDOW:
            years_beyond = int(years_old) - _DECAY_WINDOW
            for _ in range(years_beyond):
                r_home = r_home + _DECAY_RATE * (_START_ELO - r_home)
                r_away = r_away + _DECAY_RATE * (_START_ELO - r_away)

    return r_home, r_away


def calculate_elos(rows: list, max_date: date | None = None) -> dict[str, float]:
    """Process match rows chronologically; return final Elo per team name."""
    ratings: dict[str, float] = {}
    # (date, rating) snapshots used for the post-hoc reputation floor
    history: dict[str, list[tuple[date, float]]] = {}

    for row in rows:
        h, a = row.home_team, row.away_team
        r_h = ratings.setdefault(h, _START_ELO)
        r_a = ratings.setdefault(a, _START_ELO)
        ratings[h], ratings[a] = elo_update(
            r_h, r_a,
            row.home_score, row.away_score,
            row.competition,
            neutral=bool(row.neutral),
            match_date=row.match_date,
            max_date=max_date,
            home_team=h,
            away_team=a,
        )
        if row.match_date:
            history.setdefault(h, []).append((row.match_date, ratings[h]))
            history.setdefault(a, []).append((row.match_date, ratings[a]))

    # Reputation floor: prevent a dip from wiping out a team's recent peak.
    # Use the 4-year window (matches not subject to recency decay) so the peak
    # reflects actual recent form rather than a decay-deflated historical avg.
    # The boost is capped at 50 points so a single tournament spike (e.g. a
    # Copa America final run) does not permanently anchor the floor too high.
    if max_date:
        cutoff = max_date - timedelta(days=_DECAY_WINDOW * 365)
        for team, current in list(ratings.items()):
            recent = [r for d, r in history.get(team, []) if d >= cutoff]
            if not recent:
                continue
            peak_recent = max(recent)
            if current < peak_recent and peak_recent > 1750:
                floor_val = min(peak_recent * 0.985, current + 25.0)
                ratings[team] = max(current, floor_val)

    # Soft ceiling: compress extreme outlier ratings toward the mean so that a
    # single dominant team does not capture a disproportionate fraction of
    # Monte Carlo simulation outcomes.
    for team in list(ratings.keys()):
        if ratings[team] > 1950:
            excess = ratings[team] - 1950
            ratings[team] = 1950 + (excess * 0.5)

    return ratings


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _is_world_cup_final(t: str) -> bool:
    return "world cup" in t and "qualif" not in t and "qualification" not in t


def _is_tier1_continental(t: str) -> bool:
    """EURO and Copa América — strongest continental fields (K=50)."""
    return any(kw in t for kw in (
        "uefa euro", "european championship",
        "copa america", "copa américa",
    ))


def _is_tier2_continental(t: str) -> bool:
    """AFCON and AFC Asian Cup — competitive but weaker fields than Tier 1 (K=40)."""
    return any(kw in t for kw in (
        "africa cup of nations", "african cup of nations",
        "afc asian cup",
    ))


def _is_tier3_continental(t: str) -> bool:
    """Gold Cup and CONCACAF Championship — weakest major continental fields (K=30)."""
    return any(kw in t for kw in (
        "gold cup", "concacaf championship",
    ))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_ingestion(force: bool = False) -> None:
    with get_session() as session:
        assert_upstream_ok(session, "fifa_results_ingest", force=force)
        with pipeline_run(session, "elo_calculate") as run:
            rows = session.execute(_FETCH_SQL).fetchall()
            if not rows:
                logger.warning("No matches found — run ingest_fifa.py first")
                return

            max_date = max(r.match_date for r in rows)
            logger.info("Processing %d matches, latest date: %s", len(rows), max_date)

            ratings = calculate_elos(rows, max_date=max_date)
            now = datetime.now(timezone.utc)

            for name, elo in ratings.items():
                stmt = (
                    insert(Team)
                    .values(name=name, elo_rating=round(elo, 2), updated_at=now)
                    .on_conflict_do_update(
                        index_elements=["name"],
                        set_={"elo_rating": round(elo, 2), "updated_at": now},
                    )
                )
                session.execute(stmt)
                run.rows_updated += 1

            logger.info(
                "Elo ratings calculated from %d matches → %d teams",
                len(rows), run.rows_updated,
            )


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Calculate Elo ratings from match history")
    parser.add_argument("--force", action="store_true",
                        help="Bypass upstream pipeline status checks")
    args = parser.parse_args()
    run_ingestion(force=args.force)
