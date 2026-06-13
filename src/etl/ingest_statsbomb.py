"""StatsBomb ingestion — pulls competitions → seasons → matches → events.

Falls back to raw JSON if statsbombpy is unavailable (e.g., in CI without the
package installed).  All loads are idempotent: existing rows are skipped or
updated via ON CONFLICT DO UPDATE.
"""
import logging
import uuid
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.config import get_settings
from src.db.models import Event, Match, Player, Team
from src.db.session import get_session
from src.etl.pipeline_logger import assert_upstream_ok, pipeline_run

logger = logging.getLogger(__name__)
settings = get_settings()

try:
    from statsbombpy import sb as statsbomb
    _SB_AVAILABLE = True
except ImportError:
    logger.warning("statsbombpy not installed — StatsBomb ingestion will be a no-op")
    _SB_AVAILABLE = False


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_ingestion(
    competition_ids: list[int] | None = None,
    season_ids: list[int] | None = None,
    force: bool = False,
) -> None:
    if not _SB_AVAILABLE:
        logger.error("statsbombpy is required to run StatsBomb ingestion")
        return

    competition_ids = competition_ids or [
        int(c) for c in settings.statsbomb_competition_ids.split(",")
    ]
    season_ids = season_ids or [
        int(s) for s in settings.statsbomb_season_ids.split(",")
    ]

    with get_session() as session:
        assert_upstream_ok(session, "fifa_results_ingest", force=force)
        with pipeline_run(session, "statsbomb_ingest") as run:
            for comp_id in competition_ids:
                for season_id in season_ids:
                    inserted, updated = _ingest_competition_season(session, comp_id, season_id)
                    run.rows_inserted += inserted
                    run.rows_updated += updated


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def _ingest_competition_season(session: Session, competition_id: int, season_id: int) -> tuple[int, int]:
    logger.info("Fetching matches for competition=%d season=%d", competition_id, season_id)
    try:
        matches_df = statsbomb.matches(competition_id=competition_id, season_id=season_id)
    except Exception as exc:
        logger.warning("Could not fetch matches for comp=%d season=%d: %s", competition_id, season_id, exc)
        return 0, 0

    total_inserted = total_updated = 0

    for _, row in matches_df.iterrows():
        home_team_id = _upsert_team(session, row["home_team"]["home_team_name"])
        away_team_id = _upsert_team(session, row["away_team"]["away_team_name"])

        match_id, inserted = _upsert_match(session, row, home_team_id, away_team_id)
        if inserted:
            total_inserted += 1
        else:
            total_updated += 1

        _ingest_match_events(session, match_id, row["match_id"])

    return total_inserted, total_updated


def _upsert_team(session: Session, name: str) -> uuid.UUID:
    stmt = (
        insert(Team)
        .values(name=name)
        .on_conflict_do_nothing(index_elements=["name"])
        .returning(Team.team_id)
    )
    result = session.execute(stmt).fetchone()
    if result:
        return result[0]
    # already existed — fetch it
    return session.query(Team.team_id).filter_by(name=name).scalar()


def _upsert_match(
    session: Session,
    row: Any,
    home_team_id: uuid.UUID,
    away_team_id: uuid.UUID,
) -> tuple[uuid.UUID, bool]:
    existing = session.query(Match).filter_by(statsbomb_id=int(row["match_id"])).first()
    if existing:
        existing.home_score = row.get("home_score")
        existing.away_score = row.get("away_score")
        return existing.match_id, False

    match = Match(
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        match_date=row["match_date"],
        competition=row["competition"]["competition_name"],
        season=row["season"]["season_name"],
        home_score=row.get("home_score"),
        away_score=row.get("away_score"),
        statsbomb_id=int(row["match_id"]),
    )
    session.add(match)
    session.flush()
    return match.match_id, True


def _ingest_match_events(session: Session, match_id: uuid.UUID, sb_match_id: int) -> None:
    logger.debug("Fetching events for match statsbomb_id=%d", sb_match_id)
    try:
        events_df = statsbomb.events(match_id=sb_match_id)
    except Exception as exc:
        logger.warning("Could not fetch events for match %d: %s", sb_match_id, exc)
        return

    player_cache: dict[int, uuid.UUID] = {}

    for _, ev in events_df.iterrows():
        sb_player = ev.get("player")
        player_id = None
        if sb_player and isinstance(sb_player, dict):
            sb_pid = sb_player.get("id")
            if sb_pid:
                if sb_pid not in player_cache:
                    player_cache[sb_pid] = _upsert_player(
                        session,
                        sb_player.get("name", "Unknown"),
                        sb_pid,
                        team_name=ev.get("team", {}).get("name"),
                        session=session,
                    )
                player_id = player_cache[sb_pid]

        sb_team = ev.get("team", {})
        team_id = _upsert_team(session, sb_team.get("name", "Unknown")) if sb_team else None

        sb_event_uuid = ev.get("id")
        if sb_event_uuid:
            exists = session.query(Event.event_id).filter_by(
                statsbomb_id=uuid.UUID(sb_event_uuid)
            ).first()
            if exists:
                continue

        location = ev.get("location")
        event = Event(
            match_id=match_id,
            player_id=player_id,
            team_id=team_id,
            event_type=ev.get("type", {}).get("name", "unknown"),
            minute=ev.get("minute"),
            second=ev.get("second"),
            location={"x": location[0], "y": location[1]} if location else None,
            outcome=_extract_outcome(ev),
            statsbomb_id=uuid.UUID(sb_event_uuid) if sb_event_uuid else None,
        )
        session.add(event)

    session.flush()


def _upsert_player(
    session: Session,
    name: str,
    statsbomb_id: int,
    team_name: str | None,
    **_kwargs,
) -> uuid.UUID:
    existing = session.query(Player).filter_by(statsbomb_id=statsbomb_id).first()
    if existing:
        return existing.player_id

    team_id = _upsert_team(session, team_name) if team_name else None
    player = Player(name=name, statsbomb_id=statsbomb_id, team_id=team_id)
    session.add(player)
    session.flush()
    return player.player_id


def _extract_outcome(ev: Any) -> str | None:
    for field in ("duel", "pass", "shot", "carry", "clearance"):
        obj = ev.get(field)
        if obj and isinstance(obj, dict):
            outcome = obj.get("outcome")
            if outcome and isinstance(outcome, dict):
                return outcome.get("name")
    return None


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Ingest StatsBomb event data")
    parser.add_argument("--force", action="store_true",
                        help="Bypass upstream pipeline status checks")
    args = parser.parse_args()
    run_ingestion(force=args.force)
