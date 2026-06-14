"""Add possession-adjusted OOP metrics and pressure_final_third_pct

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-13 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # player_metrics — quality of pressing location
    op.add_column("player_metrics", sa.Column("pressure_final_third_pct", sa.Float(), nullable=True))

    # team_metrics — quality signal + possession-adjusted variants
    op.add_column("team_metrics", sa.Column("pressure_final_third_pct",    sa.Float(), nullable=True))
    op.add_column("team_metrics", sa.Column("opponent_possession_phases",   sa.Float(), nullable=True))
    op.add_column("team_metrics", sa.Column("opponent_passing_attempts",    sa.Float(), nullable=True))
    op.add_column("team_metrics", sa.Column("press_intensity_adj",          sa.Float(), nullable=True))
    op.add_column("team_metrics", sa.Column("interceptions_adj",            sa.Float(), nullable=True))
    op.add_column("team_metrics", sa.Column("ball_recoveries_adj",          sa.Float(), nullable=True))
    op.add_column("team_metrics", sa.Column("oop_composite_adj",            sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("team_metrics", "oop_composite_adj")
    op.drop_column("team_metrics", "ball_recoveries_adj")
    op.drop_column("team_metrics", "interceptions_adj")
    op.drop_column("team_metrics", "press_intensity_adj")
    op.drop_column("team_metrics", "opponent_passing_attempts")
    op.drop_column("team_metrics", "opponent_possession_phases")
    op.drop_column("team_metrics", "pressure_final_third_pct")

    op.drop_column("player_metrics", "pressure_final_third_pct")
