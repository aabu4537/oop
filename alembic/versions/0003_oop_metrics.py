"""add OOP split metrics and oop_composite to player_metrics and team_metrics

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-13 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # player_metrics — split def_line_engagement into three components
    op.add_column("player_metrics", sa.Column("clearances_per90",     sa.Float(), nullable=True))
    op.add_column("player_metrics", sa.Column("interceptions_per90",  sa.Float(), nullable=True))
    op.add_column("player_metrics", sa.Column("ball_recoveries_per90", sa.Float(), nullable=True))

    # team_metrics — split columns + PSR + OOP composite
    op.add_column("team_metrics", sa.Column("clearances_per90",      sa.Float(), nullable=True))
    op.add_column("team_metrics", sa.Column("interceptions_per90",   sa.Float(), nullable=True))
    op.add_column("team_metrics", sa.Column("ball_recoveries_per90", sa.Float(), nullable=True))
    op.add_column("team_metrics", sa.Column("pressure_success_rate", sa.Float(), nullable=True))
    op.add_column("team_metrics", sa.Column("oop_composite",         sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("team_metrics", "oop_composite")
    op.drop_column("team_metrics", "pressure_success_rate")
    op.drop_column("team_metrics", "ball_recoveries_per90")
    op.drop_column("team_metrics", "interceptions_per90")
    op.drop_column("team_metrics", "clearances_per90")

    op.drop_column("player_metrics", "ball_recoveries_per90")
    op.drop_column("player_metrics", "interceptions_per90")
    op.drop_column("player_metrics", "clearances_per90")
