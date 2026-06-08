"""Elo ratings scraper — fetches current world football Elo ratings from eloratings.net.

Parses the HTML table and upserts each team's Elo rating into the `teams` table.
Designed to be re-run on any schedule; existing rows are updated in place.
"""
import logging
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup
from sqlalchemy.dialects.postgresql import insert

from src.config import get_settings
from src.db.models import Team
from src.db.session import get_session
from src.etl.pipeline_logger import pipeline_run

logger = logging.getLogger(__name__)
settings = get_settings()

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; football-analytics-bot/1.0; "
        "+https://github.com/your-repo/football-analytics)"
    )
}
_TIMEOUT = 15
_RETRY_BACKOFF = [1, 2, 4]


def run_ingestion() -> None:
    with get_session() as session:
        with pipeline_run(session, "elo_ingest") as run:
            ratings = _scrape_elo_ratings()
            for name, elo in ratings.items():
                _upsert_team_elo(session, name, elo)
                run.rows_updated += 1
            logger.info("Upserted %d Elo ratings", run.rows_updated)


def _scrape_elo_ratings() -> dict[str, float]:
    url = f"{settings.elo_base_url}/en/world"
    html = _fetch_with_retry(url)
    return _parse_elo_table(html)


def _fetch_with_retry(url: str) -> str:
    last_exc: Exception | None = None
    for delay in [0] + _RETRY_BACKOFF:
        if delay:
            time.sleep(delay)
        try:
            response = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
            response.raise_for_status()
            return response.text
        except requests.RequestException as exc:
            logger.warning("Elo fetch attempt failed (%s): %s", url, exc)
            last_exc = exc
    raise RuntimeError(f"Failed to fetch {url} after retries") from last_exc


def _parse_elo_table(html: str) -> dict[str, float]:
    soup = BeautifulSoup(html, "lxml")
    ratings: dict[str, float] = {}

    # eloratings.net renders a table with class "maintable"
    table = soup.find("table", class_="maintable")
    if table is None:
        # fallback: grab the first table with numeric ratings
        table = soup.find("table")

    if table is None:
        logger.warning("No Elo table found in page HTML")
        return ratings

    for row in table.find_all("tr")[1:]:  # skip header
        cells = row.find_all("td")
        if len(cells) < 4:
            continue
        try:
            name = cells[1].get_text(strip=True)
            elo = float(cells[3].get_text(strip=True).replace(",", ""))
            if name and elo:
                ratings[name] = elo
        except (ValueError, IndexError):
            continue

    logger.info("Parsed %d Elo ratings from page", len(ratings))
    return ratings


def _upsert_team_elo(session, name: str, elo: float) -> None:
    stmt = (
        insert(Team)
        .values(name=name, elo_rating=elo, updated_at=datetime.now(timezone.utc))
        .on_conflict_do_update(
            index_elements=["name"],
            set_={"elo_rating": elo, "updated_at": datetime.now(timezone.utc)},
        )
    )
    session.execute(stmt)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_ingestion()
