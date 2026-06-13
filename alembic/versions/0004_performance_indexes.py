"""add performance indexes for OOP and team metric queries

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-13 00:00:00.000000

Index design notes
──────────────────
Only the indexes not already present in 0001_initial_schema.py are added here.
Existing indexes from 0001: idx_events_match, idx_events_type, idx_events_player,
idx_matches_date, idx_matches_teams, idx_teams_elo, idx_players_team,
idx_predictions_match, idx_predictions_model, idx_pipeline_runs_name_status.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Optimises _compute_pressure_success_rate and any query that filters
    # events by (team, event_type) — e.g. fetching all Pressure or Ball Recovery
    # events for a specific team across matches.
    op.create_index(
        "idx_events_team_type",
        "events",
        ["team_id", "event_type"],
    )

    # Optimises rolling_oop_composite() which needs all team_metric rows for
    # a given team, sorted by match date (resolved via JOIN to matches).
    # Also speeds up the feature matrix build in src/models/features.py.
    op.create_index(
        "idx_team_metrics_team",
        "team_metrics",
        ["team_id"],
    )

    # Optimises the has_oop_data check in POST /simulate/async — joins
    # teams + team_metrics filtered by team name and non-null oop_composite.
    op.create_index(
        "idx_team_metrics_oop",
        "team_metrics",
        ["oop_composite"],
        postgresql_where=sa.text("oop_composite IS NOT NULL"),
    )

    # Optimises the player metric fetch in _fetch_events() which joins
    # events with player_metrics; composite (player_id, event_type) covers
    # both player-filter and event-type-filter in a single index scan.
    op.create_index(
        "idx_events_player_type",
        "events",
        ["player_id", "event_type"],
        postgresql_where=sa.text("player_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_events_player_type", table_name="events")
    op.drop_index("idx_team_metrics_oop", table_name="team_metrics")
    op.drop_index("idx_team_metrics_team", table_name="team_metrics")
    op.drop_index("idx_events_team_type", table_name="events")
