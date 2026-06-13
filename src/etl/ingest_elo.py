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
    50 — Major continental championships (EURO, Copa América, AFCON, Asian Cup, Gold Cup)
    40 — World Cup / continental qualifying
    20 — Friendlies and all other matches

Constants
    Starting Elo : 1500
    Home advantage : 100 Elo points (0 on neutral ground)
    GD multiplier cap : 2.0
"""
import math
import logging
from datetime import date, datetime, timezone

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from src.db.models import Team
from src.db.session import get_session
from src.etl.pipeline_logger import pipeline_run

logger = logging.getLogger(__name__)

_START_ELO = 1500.0
_HOME_ADV = 100.0
_GD_CAP = 2.0

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
    ORDER BY m.match_date ASC
""")


# ---------------------------------------------------------------------------
# Public helpers (exported for tests)
# ---------------------------------------------------------------------------

def k_factor(tournament: str | None) -> float:
    """Base K-factor for a tournament, before goal-difference scaling."""
    t = (tournament or "").lower()
    if "qualif" in t or "qualification" in t:
        return 40.0
    if _is_world_cup_final(t):
        return 60.0
    if _is_major_continental(t):
        return 50.0
    return 20.0


def gd_multiplier(home_score: int, away_score: int) -> float:
    """Scale K by goal difference, capped at 2.0."""
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
) -> tuple[float, float]:
    """Return updated (r_home, r_away) after one match.

    Args:
        neutral:    True when the match was played at a neutral venue — removes
                    the home-advantage offset from the expected-score calculation.
        match_date: Date of this match; used for recency decay.
        max_date:   Latest match date in the full dataset.  Matches more than
                    4 years older than max_date have their rating contribution
                    pulled 10 % back toward 1500 for each additional year.
    """
    adv = 0.0 if neutral else _HOME_ADV
    k_eff = k_factor(tournament) * gd_multiplier(home_score, away_score)

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

    # Recency decay — applied once per year beyond the 4-year window
    if match_date is not None and max_date is not None:
        years_old = (max_date - match_date).days / 365.25
        if years_old > 4:
            years_beyond = int(years_old) - 4
            for _ in range(years_beyond):
                r_home = r_home + 0.10 * (_START_ELO - r_home)
                r_away = r_away + 0.10 * (_START_ELO - r_away)

    return r_home, r_away


def calculate_elos(rows: list, max_date: date | None = None) -> dict[str, float]:
    """Process match rows chronologically; return final Elo per team name."""
    ratings: dict[str, float] = {}
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
        )
    return ratings


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _is_world_cup_final(t: str) -> bool:
    return "world cup" in t and "qualif" not in t and "qualification" not in t


def _is_major_continental(t: str) -> bool:
    return any(
        kw in t
        for kw in (
            "uefa euro",
            "european championship",
            "copa america",
            "copa américa",
            "africa cup of nations",
            "african cup of nations",
            "afc asian cup",
            "gold cup",
            "concacaf championship",
            "nations league",
        )
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_ingestion() -> None:
    with get_session() as session:
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
    logging.basicConfig(level=logging.INFO)
    run_ingestion()
