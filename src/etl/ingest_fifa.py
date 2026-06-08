"""FIFA / international match results ingestion.

Source: martj42/international_results dataset on GitHub (CSV, no auth required).
Falls back gracefully if the network is unavailable.

Each row in the CSV represents one international match. We insert teams and
matches idempotently, deduplicating on (home_team, away_team, match_date).
"""
import csv
import io
import logging
import time
from datetime import date, datetime, timezone

import requests

from src.db.models import Match, Team
from src.db.session import get_session
from src.etl.pipeline_logger import pipeline_run

logger = logging.getLogger(__name__)

_RESULTS_CSV_URL = (
    "https://raw.githubusercontent.com/martj42/international_results/master/results.csv"
)
_HEADERS = {
    "User-Agent": "football-analytics-bot/1.0"
}
_TIMEOUT = 30
_RETRY_BACKOFF = [1, 2, 4]


def run_ingestion(url: str = _RESULTS_CSV_URL) -> None:
    with get_session() as session:
        with pipeline_run(session, "fifa_results_ingest") as run:
            rows = _fetch_csv(url)
            inserted = _load_rows(session, rows)
            run.rows_inserted = inserted
            logger.info("FIFA results ingestion complete — %d matches inserted", inserted)


def _fetch_csv(url: str) -> list[dict]:
    last_exc: Exception | None = None
    for delay in [0] + _RETRY_BACKOFF:
        if delay:
            time.sleep(delay)
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
            resp.raise_for_status()
            reader = csv.DictReader(io.StringIO(resp.text))
            return list(reader)
        except requests.RequestException as exc:
            logger.warning("FIFA CSV fetch failed: %s", exc)
            last_exc = exc
    raise RuntimeError(f"Failed to fetch FIFA CSV from {url}") from last_exc


def _load_rows(session, rows: list[dict]) -> int:
    inserted = 0
    team_cache: dict[str, object] = {}

    def get_or_create_team(name: str):
        if name in team_cache:
            return team_cache[name]
        team = session.query(Team).filter_by(name=name).first()
        if not team:
            team = Team(name=name)
            session.add(team)
            session.flush()
        team_cache[name] = team.team_id
        return team.team_id

    for row in rows:
        try:
            home_name = row["home_team"].strip()
            away_name = row["away_team"].strip()
            match_date = date.fromisoformat(row["date"])
            home_score = int(row["home_score"]) if row["home_score"] else None
            away_score = int(row["away_score"]) if row["away_score"] else None
            competition = row.get("tournament", "").strip() or None
        except (KeyError, ValueError) as exc:
            logger.debug("Skipping malformed row %s: %s", row, exc)
            continue

        home_team_id = get_or_create_team(home_name)
        away_team_id = get_or_create_team(away_name)

        # idempotency check: skip if this exact fixture already exists
        exists = (
            session.query(Match)
            .filter_by(
                home_team_id=home_team_id,
                away_team_id=away_team_id,
                match_date=match_date,
            )
            .first()
        )
        if exists:
            continue

        match = Match(
            home_team_id=home_team_id,
            away_team_id=away_team_id,
            match_date=match_date,
            competition=competition,
            home_score=home_score,
            away_score=away_score,
        )
        session.add(match)
        inserted += 1

        # flush every 500 rows to avoid unbounded memory growth
        if inserted % 500 == 0:
            session.flush()
            logger.info("Flushed %d matches so far…", inserted)

    session.flush()
    return inserted


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_ingestion()
