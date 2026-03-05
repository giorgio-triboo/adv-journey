"""create traffic_platforms and campaign_traffic_mapping tables

Revision ID: 021_traffic_platforms
Revises: 020_ulixe_rcrm_temp
Create Date: 2026-03-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "021_traffic_platforms"
down_revision: Union[str, None] = "020_ulixe_rcrm_temp"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "traffic_platforms",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("display_order", sa.Integer(), server_default="0"),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_traffic_platforms_id"), "traffic_platforms", ["id"], unique=False)
    op.create_index(op.f("ix_traffic_platforms_name"), "traffic_platforms", ["name"], unique=True)
    op.create_index(op.f("ix_traffic_platforms_slug"), "traffic_platforms", ["slug"], unique=True)

    op.create_table(
        "campaign_traffic_mapping",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("magellano_campaign_id", sa.String(), nullable=False),
        sa.Column("traffic_platform_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["traffic_platform_id"], ["traffic_platforms.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("magellano_campaign_id", name="uq_campaign_traffic_mapping_mag_id"),
    )
    op.create_index(op.f("ix_campaign_traffic_mapping_id"), "campaign_traffic_mapping", ["id"], unique=False)
    op.create_index(op.f("ix_campaign_traffic_mapping_magellano_campaign_id"), "campaign_traffic_mapping", ["magellano_campaign_id"], unique=False)
    op.create_index(op.f("ix_campaign_traffic_mapping_traffic_platform_id"), "campaign_traffic_mapping", ["traffic_platform_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_campaign_traffic_mapping_traffic_platform_id"), table_name="campaign_traffic_mapping")
    op.drop_index(op.f("ix_campaign_traffic_mapping_magellano_campaign_id"), table_name="campaign_traffic_mapping")
    op.drop_index(op.f("ix_campaign_traffic_mapping_id"), table_name="campaign_traffic_mapping")
    op.drop_table("campaign_traffic_mapping")
    op.drop_index(op.f("ix_traffic_platforms_slug"), table_name="traffic_platforms")
    op.drop_index(op.f("ix_traffic_platforms_name"), table_name="traffic_platforms")
    op.drop_index(op.f("ix_traffic_platforms_id"), table_name="traffic_platforms")
    op.drop_table("traffic_platforms")
