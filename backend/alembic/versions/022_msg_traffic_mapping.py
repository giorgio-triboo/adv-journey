"""Replace campaign_traffic_mapping with msg_traffic_mapping (msg_id level)

Revision ID: 022_msg_traffic_mapping
Revises: 021_traffic_platforms
Create Date: 2026-03-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "022_msg_traffic_mapping"
down_revision: Union[str, None] = "021_traffic_platforms"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create new msg_traffic_mapping
    op.create_table(
        "msg_traffic_mapping",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("msg_id", sa.String(), nullable=False),
        sa.Column("traffic_platform_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["traffic_platform_id"], ["traffic_platforms.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("msg_id", name="uq_msg_traffic_mapping_msg_id"),
    )
    op.create_index(op.f("ix_msg_traffic_mapping_id"), "msg_traffic_mapping", ["id"], unique=False)
    op.create_index(op.f("ix_msg_traffic_mapping_msg_id"), "msg_traffic_mapping", ["msg_id"], unique=False)
    op.create_index(op.f("ix_msg_traffic_mapping_traffic_platform_id"), "msg_traffic_mapping", ["traffic_platform_id"], unique=False)

    # Drop old campaign_traffic_mapping
    op.drop_index(op.f("ix_campaign_traffic_mapping_traffic_platform_id"), table_name="campaign_traffic_mapping")
    op.drop_index(op.f("ix_campaign_traffic_mapping_magellano_campaign_id"), table_name="campaign_traffic_mapping")
    op.drop_index(op.f("ix_campaign_traffic_mapping_id"), table_name="campaign_traffic_mapping")
    op.drop_table("campaign_traffic_mapping")


def downgrade() -> None:
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

    op.drop_index(op.f("ix_msg_traffic_mapping_traffic_platform_id"), table_name="msg_traffic_mapping")
    op.drop_index(op.f("ix_msg_traffic_mapping_msg_id"), table_name="msg_traffic_mapping")
    op.drop_index(op.f("ix_msg_traffic_mapping_id"), table_name="msg_traffic_mapping")
    op.drop_table("msg_traffic_mapping")
