"""add colori_margine_attivi and colori_scarto_attivi to marketing_threshold_config

Revision ID: 023_colori_attivi
Revises: 022_msg_traffic_mapping
Create Date: 2026-03-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "023_colori_attivi"
down_revision: Union[str, None] = "022_msg_traffic_mapping"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "marketing_threshold_config",
        sa.Column("colori_margine_attivi", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "marketing_threshold_config",
        sa.Column("colori_scarto_attivi", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("marketing_threshold_config", "colori_scarto_attivi")
    op.drop_column("marketing_threshold_config", "colori_margine_attivi")
