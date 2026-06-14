"""Add confederation to teams; oop_composite_final and oop_confidence to team_metrics

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-13 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("teams", sa.Column("confederation", sa.String(20), nullable=True))
    op.add_column("team_metrics", sa.Column("oop_composite_final", sa.Float(), nullable=True))
    op.add_column("team_metrics", sa.Column("oop_confidence",      sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("team_metrics", "oop_confidence")
    op.drop_column("team_metrics", "oop_composite_final")
    op.drop_column("teams", "confederation")
