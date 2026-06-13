"""Phase 2 — Feature engineering: compute off-ball metrics from event data.

Per-90-minute metrics derived from StatsBomb event types:

  Player-level
  ────────────
  press_intensity      — Pressure events per 90 min
  run_frequency        — Carry events per 90 min          [IN-POSSESSION ONLY]
  space_creation_idx   — (Carry + completed Dribble) / 90 [IN-POSSESSION ONLY]
  def_line_engagement  — (Clearance + Interception + Ball Recovery) / 90
                         Kept for backwards compatibility; composite of the three below.
  clearances_per90     — Clearance events per 90 min
  interceptions_per90  — Interception events per 90 min
  ball_recoveries_per90— Ball Recovery events per 90 min

  Team-level (aggregated from players, plus pressure sequence analysis)
  ─────────────────────────────────────────────────────────────────────
  avg_press_intensity   — team mean of press_intensity
  avg_space_creation    — team mean of space_creation_idx [IN-POSSESSION ONLY]
  avg_run_frequency     — team mean of run_frequency      [IN-POSSESSION ONLY]
  def_line_engagement   — team mean of def_line_engagement (composite, backwards compat)
  clearances_per90      — team mean of clearances_per90
  interceptions_per90   — team mean of interceptions_per90
  ball_recoveries_per90 — team mean of ball_recoveries_per90
  pressure_success_rate — fraction of Pressure events followed by a team Ball Recovery
                          or Interception within 5 seconds; best OOP quality signal
  oop_composite         — weighted OOP signal:
                            press_intensity       × 0.35
                          + pressure_success_rate × 0.30
                          + interceptions_per90   × 0.20
                          + ball_recoveries_per90 × 0.15

Rolling window (rolling_oop_composite)
───────────────────────────────────────
  Uses the last 10 available StatsBomb matches for a team strictly before the
  target date — no future data leakage.

Pipeline is idempotent: re-running skips already-processed matches unless
explicit match_ids are supplied (forces recompute).
"""
import logging
import uuid
from datetime import date
from typing import Sequence

import pandas as pd
from sqlalchemy.orm import Session

from src.db.models import Event, PlayerMetric, Team
from src.db.session import get_session
from src.etl.loaders import upsert_player_metrics, upsert_team_metrics
from src.etl.pipeline_logger import pipeline_run

logger = logging.getLogger(__name__)

_PRESSURE = "Pressure"
_CARRY = "Carry"
_DRIBBLE = "Dribble"
_DRIBBLE_COMPLETE = "Complete"
_CLEARANCE = "Clearance"
_INTERCEPTION = "Interception"
_BALL_RECOVERY = "Ball Recovery"
_DEFENSIVE_TYPES = frozenset({_CLEARANCE, _INTERCEPTION, _BALL_RECOVERY})
_REGAIN_TYPES = frozenset({_BALL_RECOVERY, _INTERCEPTION})

_OOP_W_PRESS = 0.35
_OOP_W_PSR = 0.30
_OOP_W_INTERCEPT = 0.20
_OOP_W_RECOVERY = 0.15


# ---------------------------------------------------------------------------
# Pure computation — no DB access
# ---------------------------------------------------------------------------

def compute_player_metrics(events_df: pd.DataFrame) -> pd.DataFrame:
    """Map raw events to per-player per-match metrics.

    Input columns : match_id, player_id, team_id, event_type, outcome, minute
    Output columns: match_id, player_id, team_id,
                    press_intensity,
                    run_frequency,          (IN-POSSESSION ONLY)
                    space_creation_idx,     (IN-POSSESSION ONLY)
                    def_line_engagement,    (composite, backwards compat)
                    clearances_per90,
                    interceptions_per90,
                    ball_recoveries_per90
    """
    _EMPTY_COLS = [
        "match_id", "player_id", "team_id",
        "press_intensity", "run_frequency", "space_creation_idx", "def_line_engagement",
        "clearances_per90", "interceptions_per90", "ball_recoveries_per90",
    ]
    if events_df.empty:
        return pd.DataFrame(columns=_EMPTY_COLS)

    df = events_df.copy()
    df["is_pressure"] = df["event_type"] == _PRESSURE
    df["is_carry"] = df["event_type"] == _CARRY
    df["is_dribble_complete"] = (df["event_type"] == _DRIBBLE) & (df["outcome"] == _DRIBBLE_COMPLETE)
    df["is_defensive"] = df["event_type"].isin(_DEFENSIVE_TYPES)
    df["is_clearance"] = df["event_type"] == _CLEARANCE
    df["is_interception"] = df["event_type"] == _INTERCEPTION
    df["is_ball_recovery"] = df["event_type"] == _BALL_RECOVERY

    agg = (
        df.groupby(["match_id", "player_id", "team_id"], sort=False)
        .agg(
            pressure_count=("is_pressure", "sum"),
            carry_count=("is_carry", "sum"),
            dribble_complete_count=("is_dribble_complete", "sum"),
            defensive_count=("is_defensive", "sum"),
            clearance_count=("is_clearance", "sum"),
            interception_count=("is_interception", "sum"),
            ball_recovery_count=("is_ball_recovery", "sum"),
            max_minute=("minute", "max"),
        )
        .reset_index()
    )

    minutes = agg["max_minute"].clip(lower=1)
    agg["press_intensity"] = (agg["pressure_count"] / minutes * 90).round(4)
    agg["run_frequency"] = (agg["carry_count"] / minutes * 90).round(4)
    agg["space_creation_idx"] = (
        (agg["carry_count"] + agg["dribble_complete_count"]) / minutes * 90
    ).round(4)
    agg["def_line_engagement"] = (agg["defensive_count"] / minutes * 90).round(4)
    agg["clearances_per90"] = (agg["clearance_count"] / minutes * 90).round(4)
    agg["interceptions_per90"] = (agg["interception_count"] / minutes * 90).round(4)
    agg["ball_recoveries_per90"] = (agg["ball_recovery_count"] / minutes * 90).round(4)

    return agg[_EMPTY_COLS]


def compute_team_metrics(
    player_metrics_df: pd.DataFrame,
    raw_events_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Aggregate player metrics to team level and compute OOP composite.

    Args:
        player_metrics_df: Output of compute_player_metrics.
        raw_events_df:     All events for the same matches (including those without
                           player_id) with columns: match_id, team_id, event_type,
                           minute, second.  Required for pressure_success_rate;
                           defaults to 0.0 if not supplied.

    Output columns: match_id, team_id,
                    avg_press_intensity,
                    avg_space_creation,     (IN-POSSESSION ONLY)
                    avg_run_frequency,      (IN-POSSESSION ONLY)
                    def_line_engagement,    (composite, backwards compat)
                    clearances_per90,
                    interceptions_per90,
                    ball_recoveries_per90,
                    pressure_success_rate,
                    oop_composite
    """
    _EMPTY_COLS = [
        "match_id", "team_id",
        "avg_press_intensity", "avg_space_creation", "avg_run_frequency", "def_line_engagement",
        "clearances_per90", "interceptions_per90", "ball_recoveries_per90",
        "pressure_success_rate", "oop_composite",
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
            clearances_per90=("clearances_per90", "mean"),
            interceptions_per90=("interceptions_per90", "mean"),
            ball_recoveries_per90=("ball_recoveries_per90", "mean"),
        )
        .round(4)
        .reset_index()
    )

    if raw_events_df is not None and not raw_events_df.empty:
        psr = _compute_pressure_success_rate(raw_events_df)
        team = team.merge(psr, on=["match_id", "team_id"], how="left")
        team["pressure_success_rate"] = team["pressure_success_rate"].fillna(0.0).round(4)
    else:
        team["pressure_success_rate"] = 0.0

    team["oop_composite"] = (
        team["avg_press_intensity"] * _OOP_W_PRESS
        + team["pressure_success_rate"] * _OOP_W_PSR
        + team["interceptions_per90"] * _OOP_W_INTERCEPT
        + team["ball_recoveries_per90"] * _OOP_W_RECOVERY
    ).round(4)

    return team[_EMPTY_COLS]


def rolling_oop_composite(
    team_metrics_df: pd.DataFrame,
    team_id: uuid.UUID,
    before_date: date,
    n: int = 10,
) -> float | None:
    """Rolling OOP composite for a team from the last n matches before a date.

    Args:
        team_metrics_df: DataFrame with columns: team_id, match_date, oop_composite.
        team_id:         Target team.
        before_date:     Cutoff — only matches strictly before this date are used.
        n:               Rolling window size (default 10).

    Returns None if the team has no history before before_date.
    No future data leakage: uses only matches strictly before before_date.
    """
    mask = (
        (team_metrics_df["team_id"] == team_id)
        & (team_metrics_df["match_date"] < before_date)
        & team_metrics_df["oop_composite"].notna()
    )
    history = team_metrics_df.loc[mask].sort_values("match_date", ascending=False).head(n)
    if history.empty:
        return None
    return round(float(history["oop_composite"].mean()), 4)


# ---------------------------------------------------------------------------
# Pressure success rate — team-level, requires temporal event sequence
# ---------------------------------------------------------------------------

def _compute_pressure_success_rate(raw_events_df: pd.DataFrame) -> pd.DataFrame:
    """Fraction of Pressure events where the pressing team regained possession within 5 s.

    A regain is a Ball Recovery or Interception by the same team in [t, t+5] seconds
    in the same match.

    Input columns : match_id, team_id, event_type, minute, second
    Output columns: match_id, team_id, pressure_success_rate
    """
    df = raw_events_df.copy()
    df["t"] = df["minute"] * 60 + df["second"].fillna(0).astype(int)

    pressures = (
        df[df["event_type"] == _PRESSURE][["match_id", "team_id", "t"]]
        .reset_index(drop=True)
    )
    pressures["press_idx"] = pressures.index

    empty = pd.DataFrame(columns=["match_id", "team_id", "pressure_success_rate"])
    if pressures.empty:
        return empty

    regains = df[df["event_type"].isin(_REGAIN_TYPES)][["match_id", "team_id", "t"]].copy()

    if regains.empty:
        totals = pressures.groupby(["match_id", "team_id"]).size().reset_index(name="_n")
        totals["pressure_success_rate"] = 0.0
        return totals[["match_id", "team_id", "pressure_success_rate"]]

    # Cross-join pressures × regains within same (match, team), then filter by 5s window
    merged = pressures.merge(
        regains.rename(columns={"t": "regain_t"}),
        on=["match_id", "team_id"],
        how="left",
    )
    merged["is_success"] = (
        merged["regain_t"].notna()
        & (merged["regain_t"] >= merged["t"])
        & (merged["regain_t"] <= merged["t"] + 5)
    )

    per_press = (
        merged.groupby(["press_idx", "match_id", "team_id"])["is_success"]
        .any()
        .reset_index()
    )

    team_psr = (
        per_press.groupby(["match_id", "team_id"])
        .agg(success=("is_success", "sum"), total=("is_success", "count"))
        .reset_index()
    )
    team_psr["pressure_success_rate"] = (team_psr["success"] / team_psr["total"]).round(4)

    return team_psr[["match_id", "team_id", "pressure_success_rate"]]


# ---------------------------------------------------------------------------
# DB I/O
# ---------------------------------------------------------------------------

def _fetch_events(
    session: Session,
    match_ids: Sequence[uuid.UUID] | None = None,
) -> pd.DataFrame:
    """Events with player_id for player-level metric computation.

    If match_ids is None, fetches only matches without existing player_metrics.
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


def _fetch_raw_events(
    session: Session,
    match_ids: Sequence[uuid.UUID],
) -> pd.DataFrame:
    """All events for the given matches (no player filter) for PSR computation."""
    if not match_ids:
        return pd.DataFrame(columns=["match_id", "team_id", "event_type", "minute", "second"])

    rows = (
        session.query(
            Event.match_id,
            Event.team_id,
            Event.event_type,
            Event.minute,
            Event.second,
        )
        .filter(Event.match_id.in_(match_ids))
        .all()
    )
    if not rows:
        return pd.DataFrame(columns=["match_id", "team_id", "event_type", "minute", "second"])
    return pd.DataFrame(rows, columns=["match_id", "team_id", "event_type", "minute", "second"])


def _persist(session: Session, player_df: pd.DataFrame, team_df: pd.DataFrame) -> int:
    for _, row in player_df.iterrows():
        upsert_player_metrics(
            session,
            player_id=row["player_id"],
            match_id=row["match_id"],
            press_intensity=float(row["press_intensity"]),
            run_frequency=float(row["run_frequency"]),
            space_creation_idx=float(row["space_creation_idx"]),
            def_line_engagement=float(row["def_line_engagement"]),
            clearances_per90=float(row["clearances_per90"]),
            interceptions_per90=float(row["interceptions_per90"]),
            ball_recoveries_per90=float(row["ball_recoveries_per90"]),
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
            clearances_per90=float(row["clearances_per90"]),
            interceptions_per90=float(row["interceptions_per90"]),
            ball_recoveries_per90=float(row["ball_recoveries_per90"]),
            pressure_success_rate=float(row["pressure_success_rate"]),
            oop_composite=float(row["oop_composite"]),
        )

    return len(player_df)


def _print_oop_ranking(session: Session, team_df: pd.DataFrame) -> None:
    """Print top 10 / bottom 10 teams by mean oop_composite across processed matches."""
    if team_df.empty or "oop_composite" not in team_df.columns:
        return

    summary = (
        team_df.groupby("team_id")["oop_composite"]
        .mean()
        .reset_index()
        .rename(columns={"oop_composite": "avg_oop"})
        .sort_values("avg_oop", ascending=False)
        .reset_index(drop=True)
    )

    team_ids = summary["team_id"].tolist()
    name_rows = session.query(Team.team_id, Team.name).filter(Team.team_id.in_(team_ids)).all()
    id_to_name = {row.team_id: row.name for row in name_rows}
    summary["team"] = summary["team_id"].map(id_to_name).fillna("Unknown")

    print("\n=== Top 10 teams by oop_composite ===")
    for _, r in summary.head(10).iterrows():
        print(f"  {r['team']:<35} {r['avg_oop']:.4f}")

    print("\n=== Bottom 10 teams by oop_composite ===")
    for _, r in summary.tail(10).iterrows():
        print(f"  {r['team']:<35} {r['avg_oop']:.4f}")
    print()


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

            processed_match_ids = events_df["match_id"].unique().tolist()
            raw_events_df = _fetch_raw_events(session, processed_match_ids)

            player_df = compute_player_metrics(events_df)
            team_df = compute_team_metrics(player_df, raw_events_df)

            rows = _persist(session, player_df, team_df)
            run.rows_inserted = rows

            logger.info(
                "Wrote %d player-metric rows, %d team-metric rows across %d matches",
                len(player_df), len(team_df), n_matches,
            )

            _print_oop_ranking(session, team_df)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_pipeline()
