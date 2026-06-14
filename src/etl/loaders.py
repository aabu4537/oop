"""Generic upsert helpers used by all ETL scripts.

All functions are idempotent — safe to call repeatedly without producing
duplicate rows.  They rely on PostgreSQL's ON CONFLICT DO UPDATE / DO NOTHING.
"""
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.db.models import Match, Player, PlayerMetric, Prediction, Team, TeamMetric


def upsert_team(session: Session, name: str, fifa_code: str | None = None, elo_rating: float | None = None) -> uuid.UUID:
    values: dict[str, Any] = {"name": name}
    if fifa_code is not None:
        values["fifa_code"] = fifa_code
    if elo_rating is not None:
        values["elo_rating"] = elo_rating
        values["updated_at"] = datetime.now(timezone.utc)

    stmt = (
        insert(Team)
        .values(**values)
        .on_conflict_do_update(
            index_elements=["name"],
            set_={k: v for k, v in values.items() if k != "name"},
        )
        .returning(Team.team_id)
    )
    result = session.execute(stmt).fetchone()
    return result[0] if result else session.query(Team.team_id).filter_by(name=name).scalar()


def upsert_player(
    session: Session,
    name: str,
    statsbomb_id: int,
    team_id: uuid.UUID | None = None,
    position: str | None = None,
    nationality: str | None = None,
) -> uuid.UUID:
    values: dict[str, Any] = {"name": name, "statsbomb_id": statsbomb_id}
    if team_id is not None:
        values["team_id"] = team_id
    if position is not None:
        values["position"] = position
    if nationality is not None:
        values["nationality"] = nationality

    stmt = (
        insert(Player)
        .values(**values)
        .on_conflict_do_update(
            index_elements=["statsbomb_id"],
            set_={k: v for k, v in values.items() if k != "statsbomb_id"},
        )
        .returning(Player.player_id)
    )
    result = session.execute(stmt).fetchone()
    return result[0]


def upsert_player_metrics(
    session: Session,
    player_id: uuid.UUID,
    match_id: uuid.UUID,
    press_intensity: float | None = None,
    run_frequency: float | None = None,
    space_creation_idx: float | None = None,
    def_line_engagement: float | None = None,
    clearances_per90: float | None = None,
    interceptions_per90: float | None = None,
    ball_recoveries_per90: float | None = None,
    pressure_final_third_pct: float | None = None,
) -> None:
    values = {
        "player_id": player_id,
        "match_id": match_id,
        "press_intensity": press_intensity,
        "run_frequency": run_frequency,
        "space_creation_idx": space_creation_idx,
        "def_line_engagement": def_line_engagement,
        "clearances_per90": clearances_per90,
        "interceptions_per90": interceptions_per90,
        "ball_recoveries_per90": ball_recoveries_per90,
        "pressure_final_third_pct": pressure_final_third_pct,
        "computed_at": datetime.now(timezone.utc),
    }
    stmt = (
        insert(PlayerMetric)
        .values(**values)
        .on_conflict_do_update(
            constraint="uq_player_match_metric",
            set_={k: v for k, v in values.items() if k not in ("player_id", "match_id")},
        )
    )
    session.execute(stmt)


def upsert_team_metrics(
    session: Session,
    team_id: uuid.UUID,
    match_id: uuid.UUID,
    avg_press_intensity: float | None = None,
    avg_space_creation: float | None = None,
    avg_run_frequency: float | None = None,
    def_line_engagement: float | None = None,
    clearances_per90: float | None = None,
    interceptions_per90: float | None = None,
    ball_recoveries_per90: float | None = None,
    pressure_success_rate: float | None = None,
    pressure_final_third_pct: float | None = None,
    oop_composite: float | None = None,
    opponent_possession_phases: float | None = None,
    opponent_passing_attempts: float | None = None,
    press_intensity_adj: float | None = None,
    interceptions_adj: float | None = None,
    ball_recoveries_adj: float | None = None,
    oop_composite_adj: float | None = None,
) -> None:
    values = {
        "team_id": team_id,
        "match_id": match_id,
        "avg_press_intensity": avg_press_intensity,
        "avg_space_creation": avg_space_creation,
        "avg_run_frequency": avg_run_frequency,
        "def_line_engagement": def_line_engagement,
        "clearances_per90": clearances_per90,
        "interceptions_per90": interceptions_per90,
        "ball_recoveries_per90": ball_recoveries_per90,
        "pressure_success_rate": pressure_success_rate,
        "pressure_final_third_pct": pressure_final_third_pct,
        "oop_composite": oop_composite,
        "opponent_possession_phases": opponent_possession_phases,
        "opponent_passing_attempts": opponent_passing_attempts,
        "press_intensity_adj": press_intensity_adj,
        "interceptions_adj": interceptions_adj,
        "ball_recoveries_adj": ball_recoveries_adj,
        "oop_composite_adj": oop_composite_adj,
        "computed_at": datetime.now(timezone.utc),
    }
    stmt = (
        insert(TeamMetric)
        .values(**values)
        .on_conflict_do_update(
            constraint="uq_team_match_metric",
            set_={k: v for k, v in values.items() if k not in ("team_id", "match_id")},
        )
    )
    session.execute(stmt)


def upsert_prediction(
    session: Session,
    match_id: uuid.UUID,
    model_version: str,
    home_win_prob: float,
    draw_prob: float,
    away_win_prob: float,
    brier_score: float | None = None,
    log_loss: float | None = None,
) -> uuid.UUID:
    values = {
        "match_id": match_id,
        "model_version": model_version,
        "home_win_prob": home_win_prob,
        "draw_prob": draw_prob,
        "away_win_prob": away_win_prob,
        "brier_score": brier_score,
        "log_loss": log_loss,
        "predicted_at": datetime.now(timezone.utc),
    }
    stmt = (
        insert(Prediction)
        .values(**values)
        .on_conflict_do_nothing()
        .returning(Prediction.pred_id)
    )
    result = session.execute(stmt).fetchone()
    if result:
        return result[0]
    return (
        session.query(Prediction.pred_id)
        .filter_by(match_id=match_id, model_version=model_version)
        .scalar()
    )
