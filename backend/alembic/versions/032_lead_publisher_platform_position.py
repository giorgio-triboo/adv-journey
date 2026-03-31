"""leads: publisher_platform e platform_position (da MetaMarketingPlacement)

Revision ID: 032_lead_placement
Revises: 031_meta_graph_leads
Create Date: 2026-03-30 00:00:00.000002

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "032_lead_placement"
down_revision: Union[str, None] = "031_meta_graph_leads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
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


def downgrade() -> None:
    op.drop_index(op.f("ix_leads_publisher_platform"), table_name="leads")
    op.drop_column("leads", "platform_position")
    op.drop_column("leads", "publisher_platform")
