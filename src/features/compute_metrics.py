"""Phase 2 — Feature engineering: compute off-ball metrics from event data.

Four per-90-minute metrics are derived from StatsBomb event types:
  press_intensity      — Pressure events per 90 min
  run_frequency        — Carry events per 90 min
  space_creation_idx   — (Carry + completed Dribble) events per 90 min
  def_line_engagement  — (Clearance + Interception + Ball Recovery) per 90 min

The pipeline is idempotent: re-running skips matches already in player_metrics
unless explicit match_ids are provided (which forces recompute).
"""
import logging
import uuid
from typing import Sequence

import pandas as pd
from sqlalchemy.orm import Session

from src.db.models import Event, PlayerMetric
from src.db.session import get_session
from src.etl.loaders import upsert_player_metrics, upsert_team_metrics
from src.etl.pipeline_logger import pipeline_run

logger = logging.getLogger(__name__)

_PRESSURE = "Pressure"
_CARRY = "Carry"
_DRIBBLE = "Dribble"
_DRIBBLE_COMPLETE = "Complete"
_DEFENSIVE_TYPES = frozenset({"Clearance", "Interception", "Ball Recovery"})


# ---------------------------------------------------------------------------
# Pure computation — no DB access
# ---------------------------------------------------------------------------

def compute_player_metrics(events_df: pd.DataFrame) -> pd.DataFrame:
    """Map raw events to per-player per-match metrics.

    Input columns : match_id, player_id, team_id, event_type, outcome, minute
    Output columns: match_id, player_id, team_id,
                    press_intensity, run_frequency, space_creation_idx, def_line_engagement
    """
    _EMPTY_COLS = [
        "match_id", "player_id", "team_id",
        "press_intensity", "run_frequency", "space_creation_idx", "def_line_engagement",
    ]
    if events_df.empty:
        return pd.DataFrame(columns=_EMPTY_COLS)

    df = events_df.copy()
    df["is_pressure"] = df["event_type"] == _PRESSURE
    df["is_carry"] = df["event_type"] == _CARRY
    df["is_dribble_complete"] = (df["event_type"] == _DRIBBLE) & (df["outcome"] == _DRIBBLE_COMPLETE)
    df["is_defensive"] = df["event_type"].isin(_DEFENSIVE_TYPES)

    agg = (
        df.groupby(["match_id", "player_id", "team_id"], sort=False)
        .agg(
            pressure_count=("is_pressure", "sum"),
            carry_count=("is_carry", "sum"),
            dribble_complete_count=("is_dribble_complete", "sum"),
            defensive_count=("is_defensive", "sum"),
            max_minute=("minute", "max"),
        )
        .reset_index()
    )

    minutes = agg["max_minute"].clip(lower=1)  # floor at 1 to avoid division by zero
    agg["press_intensity"] = (agg["pressure_count"] / minutes * 90).round(4)
    agg["run_frequency"] = (agg["carry_count"] / minutes * 90).round(4)
    agg["space_creation_idx"] = (
        (agg["carry_count"] + agg["dribble_complete_count"]) / minutes * 90
    ).round(4)
    agg["def_line_engagement"] = (agg["defensive_count"] / minutes * 90).round(4)

    return agg[_EMPTY_COLS]


def compute_team_metrics(player_metrics_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate player metrics to team level.

    Input columns : match_id, player_id, team_id, press_intensity, run_frequency,
                    space_creation_idx, def_line_engagement
    Output columns: match_id, team_id,
                    avg_press_intensity, avg_space_creation, avg_run_frequency, def_line_engagement
    """
    _EMPTY_COLS = [
        "match_id", "team_id",
        "avg_press_intensity", "avg_space_creation", "avg_run_frequency", "def_line_engagement",
    ]
    if player_metrics_df.empty:
        return pd.DataFrame(columns=_EMPTY_COLS)

    team = (
        player_metrics_df.groupby(["match_id", "team_id"], sort=False)
        .agg(
            avg_press_intensity=("press_intensity", "mean"),
            avg_space_creation=("space_creation_idx", "mean"),
            avg_run_frequency=("run_frequency", "mean"),
            def_line_engagement=("def_line_engagement", "mean"),
        )
        .round(4)
        .reset_index()
    )
    return team[_EMPTY_COLS]


# ---------------------------------------------------------------------------
# DB I/O
# ---------------------------------------------------------------------------

def _fetch_events(
    session: Session,
    match_ids: Sequence[uuid.UUID] | None = None,
) -> pd.DataFrame:
    """Load events from the DB.

    If match_ids is None, fetches only matches that have no player_metrics yet.
    If match_ids is provided, fetches those matches unconditionally (force-recompute).
    """
    query = session.query(
        Event.match_id,
        Event.player_id,
        Event.team_id,
        Event.event_type,
        Event.outcome,
        Event.minute,
    ).filter(Event.player_id.isnot(None))

    if match_ids is not None:
        query = query.filter(Event.match_id.in_(match_ids))
    else:
        processed = session.query(PlayerMetric.match_id).distinct().subquery()
        query = query.filter(Event.match_id.notin_(processed))

    rows = query.all()
    if not rows:
        return pd.DataFrame(
            columns=["match_id", "player_id", "team_id", "event_type", "outcome", "minute"]
        )

    return pd.DataFrame(rows, columns=["match_id", "player_id", "team_id", "event_type", "outcome", "minute"])


def _persist(session: Session, player_df: pd.DataFrame, team_df: pd.DataFrame) -> int:
    """Upsert player and team metrics; returns total player rows written."""
    for _, row in player_df.iterrows():
        upsert_player_metrics(
            session,
            player_id=row["player_id"],
            match_id=row["match_id"],
            press_intensity=float(row["press_intensity"]),
            run_frequency=float(row["run_frequency"]),
            space_creation_idx=float(row["space_creation_idx"]),
            def_line_engagement=float(row["def_line_engagement"]),
        )

    for _, row in team_df.iterrows():
        upsert_team_metrics(
            session,
            team_id=row["team_id"],
            match_id=row["match_id"],
            avg_press_intensity=float(row["avg_press_intensity"]),
            avg_space_creation=float(row["avg_space_creation"]),
            avg_run_frequency=float(row["avg_run_frequency"]),
            def_line_engagement=float(row["def_line_engagement"]),
        )

    return len(player_df)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_pipeline(match_ids: Sequence[uuid.UUID] | None = None) -> None:
    """Compute and persist off-ball metrics.

    Args:
        match_ids: If provided, recomputes these specific matches (idempotent overwrite).
                   If None, processes only matches with no existing player_metrics.
    """
    with get_session() as session:
        with pipeline_run(session, "feature_engineering") as run:
            events_df = _fetch_events(session, match_ids)

            if events_df.empty:
                logger.info("No unprocessed events found — nothing to compute")
                return

            n_matches = events_df["match_id"].nunique()
            logger.info("Computing metrics for %d events across %d matches", len(events_df), n_matches)

            player_df = compute_player_metrics(events_df)
            team_df = compute_team_metrics(player_df)

            rows = _persist(session, player_df, team_df)
            run.rows_inserted = rows

            logger.info(
                "Wrote %d player-metric rows, %d team-metric rows across %d matches",
                len(player_df), len(team_df), n_matches,
            )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_pipeline()
