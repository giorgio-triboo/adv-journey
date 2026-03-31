"""meta_graph_leads: Lead Ads da Graph /{ad_id}/leads (flusso separato da insights)

Revision ID: 031_meta_graph_leads
Revises: 030_meta_marketing_placement
Create Date: 2026-03-30 00:00:00.000001

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "031_meta_graph_leads"
down_revision: Union[str, None] = "030_meta_marketing_placement"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "meta_graph_leads",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("graph_lead_id", sa.String(), nullable=False),
        sa.Column("ad_id", sa.Integer(), nullable=False),
        sa.Column("form_id", sa.String(), nullable=True),
        sa.Column("created_time", sa.DateTime(), nullable=True),
        sa.Column("field_data", sa.JSON(), nullable=True),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["ad_id"], ["meta_ads.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("graph_lead_id", name="uq_meta_graph_leads_graph_lead_id"),
    )
    op.create_index(
        op.f("ix_meta_graph_leads_ad_id"),
        "meta_graph_leads",
        ["ad_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_meta_graph_leads_created_time"),
        "meta_graph_leads",
        ["created_time"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_meta_graph_leads_created_time"), table_name="meta_graph_leads")
    op.drop_index(op.f("ix_meta_graph_leads_ad_id"), table_name="meta_graph_leads")
    op.drop_table("meta_graph_leads")
