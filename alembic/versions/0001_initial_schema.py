"""initial schema — 7 tables + pipeline_runs audit

Revision ID: 0001
Revises:
Create Date: 2024-01-01 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')

    op.create_table(
        "teams",
        sa.Column("team_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("fifa_code", sa.String(3)),
        sa.Column("elo_rating", sa.Float()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()")),
        sa.UniqueConstraint("name", name="uq_teams_name"),
    )
    op.create_index("idx_teams_elo", "teams", ["elo_rating"])

    op.create_table(
        "players",
        sa.Column("player_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("team_id", UUID(as_uuid=True), sa.ForeignKey("teams.team_id")),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("position", sa.String(50)),
        sa.Column("nationality", sa.String(100)),
        sa.Column("statsbomb_id", sa.Integer(), unique=True),
    )
    op.create_index("idx_players_team", "players", ["team_id"])

    op.create_table(
        "matches",
        sa.Column("match_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("home_team_id", UUID(as_uuid=True), sa.ForeignKey("teams.team_id")),
        sa.Column("away_team_id", UUID(as_uuid=True), sa.ForeignKey("teams.team_id")),
        sa.Column("match_date", sa.Date(), nullable=False),
        sa.Column("competition", sa.String(100)),
        sa.Column("season", sa.String(20)),
        sa.Column("home_score", sa.Integer()),
        sa.Column("away_score", sa.Integer()),
        sa.Column("statsbomb_id", sa.Integer(), unique=True),
    )
    op.create_index("idx_matches_date", "matches", ["match_date"])
    op.create_index("idx_matches_teams", "matches", ["home_team_id", "away_team_id"])

    op.create_table(
        "events",
        sa.Column("event_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("match_id", UUID(as_uuid=True), sa.ForeignKey("matches.match_id")),
        sa.Column("player_id", UUID(as_uuid=True), sa.ForeignKey("players.player_id"), nullable=True),
        sa.Column("team_id", UUID(as_uuid=True), sa.ForeignKey("teams.team_id")),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("minute", sa.Integer()),
        sa.Column("second", sa.Integer()),
        sa.Column("location", JSONB()),
        sa.Column("outcome", sa.String(50)),
        sa.Column("statsbomb_id", UUID(as_uuid=True), unique=True),
    )
    op.create_index("idx_events_match", "events", ["match_id"])
    op.create_index("idx_events_type", "events", ["event_type"])
    op.create_index("idx_events_player", "events", ["player_id"])

    op.create_table(
        "player_metrics",
        sa.Column("metric_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("player_id", UUID(as_uuid=True), sa.ForeignKey("players.player_id")),
        sa.Column("match_id", UUID(as_uuid=True), sa.ForeignKey("matches.match_id")),
        sa.Column("press_intensity", sa.Float()),
        sa.Column("run_frequency", sa.Float()),
        sa.Column("space_creation_idx", sa.Float()),
        sa.Column("def_line_engagement", sa.Float()),
        sa.Column("computed_at", sa.DateTime(), server_default=sa.text("now()")),
        sa.UniqueConstraint("player_id", "match_id", name="uq_player_match_metric"),
    )

    op.create_table(
        "team_metrics",
        sa.Column("metric_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("team_id", UUID(as_uuid=True), sa.ForeignKey("teams.team_id")),
        sa.Column("match_id", UUID(as_uuid=True), sa.ForeignKey("matches.match_id")),
        sa.Column("avg_press_intensity", sa.Float()),
        sa.Column("avg_space_creation", sa.Float()),
        sa.Column("avg_run_frequency", sa.Float()),
        sa.Column("def_line_engagement", sa.Float()),
        sa.Column("computed_at", sa.DateTime(), server_default=sa.text("now()")),
        sa.UniqueConstraint("team_id", "match_id", name="uq_team_match_metric"),
    )

    op.create_table(
        "predictions",
        sa.Column("pred_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("match_id", UUID(as_uuid=True), sa.ForeignKey("matches.match_id")),
        sa.Column("model_version", sa.String(50), nullable=False),
        sa.Column("home_win_prob", sa.Float(), nullable=False),
        sa.Column("draw_prob", sa.Float(), nullable=False),
        sa.Column("away_win_prob", sa.Float(), nullable=False),
        sa.Column("brier_score", sa.Float()),
        sa.Column("log_loss", sa.Float()),
        sa.Column("predicted_at", sa.DateTime(), server_default=sa.text("now()")),
    )
    op.create_index("idx_predictions_match", "predictions", ["match_id"])
    op.create_index("idx_predictions_model", "predictions", ["model_version"])

    op.create_table(
        "pipeline_runs",
        sa.Column("run_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("pipeline_name", sa.String(100), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("finished_at", sa.DateTime()),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("rows_inserted", sa.Integer(), server_default="0"),
        sa.Column("rows_updated", sa.Integer(), server_default="0"),
        sa.Column("error_message", sa.Text()),
    )
    op.create_index("idx_pipeline_runs_name_status", "pipeline_runs", ["pipeline_name", "status"])


def downgrade() -> None:
    op.drop_table("pipeline_runs")
    op.drop_table("predictions")
    op.drop_table("team_metrics")
    op.drop_table("player_metrics")
    op.drop_table("events")
    op.drop_table("matches")
    op.drop_table("players")
    op.drop_table("teams")
