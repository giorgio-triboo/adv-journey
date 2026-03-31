"""Rimuove publisher_platform e platform_position da leads

Revision ID: 033_drop_lead_placement
Revises: 032_lead_placement
Create Date: 2026-03-31

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "033_drop_lead_placement"
down_revision: Union[str, None] = "032_lead_placement"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index(op.f("ix_leads_publisher_platform"), table_name="leads")
    op.drop_column("leads", "platform_position")
    op.drop_column("leads", "publisher_platform")


def downgrade() -> None:
    op.add_column(
        "leads",
        sa.Column("publisher_platform", sa.String(), nullable=True),
    )
    op.add_column(
        "leads",
        sa.Column("platform_position", sa.String(), nullable=True),
    )
    op.create_index(
        op.f("ix_leads_publisher_platform"),
        "leads",
        ["publisher_platform"],
        unique=False,
    )
