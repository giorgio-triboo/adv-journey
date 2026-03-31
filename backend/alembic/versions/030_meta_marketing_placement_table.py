"""meta_marketing_placement: layer B breakdown publisher_platform x platform_position

Revision ID: 030_meta_marketing_placement
Revises: 029_add_platform_fields
Create Date: 2026-03-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "030_meta_marketing_placement"
down_revision: Union[str, None] = "029_add_platform_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "meta_marketing_placement",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ad_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.DateTime(), nullable=False),
        sa.Column("publisher_platform", sa.String(), nullable=False, server_default=""),
        sa.Column("platform_position", sa.String(), nullable=False, server_default=""),
        sa.Column("spend", sa.Numeric(18, 4), nullable=True),
        sa.Column("impressions", sa.Integer(), nullable=True),
        sa.Column("clicks", sa.Integer(), nullable=True),
        sa.Column("conversions", sa.Integer(), nullable=True),
        sa.Column("ctr", sa.Numeric(10, 4), nullable=True),
        sa.Column("cpc", sa.Numeric(18, 4), nullable=True),
        sa.Column("cpm", sa.Numeric(18, 4), nullable=True),
        sa.Column("cpa", sa.Numeric(18, 4), nullable=True),
        sa.Column("additional_metrics", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["ad_id"], ["meta_ads.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "ad_id",
            "date",
            "publisher_platform",
            "platform_position",
            name="uq_meta_marketing_placement_ad_date_pub_pos",
        ),
    )
    op.create_index(
        op.f("ix_meta_marketing_placement_ad_id"),
        "meta_marketing_placement",
        ["ad_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_meta_marketing_placement_date"),
        "meta_marketing_placement",
        ["date"],
        unique=False,
    )
    op.create_index(
        op.f("ix_meta_marketing_placement_publisher_platform"),
        "meta_marketing_placement",
        ["publisher_platform"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_meta_marketing_placement_publisher_platform"),
        table_name="meta_marketing_placement",
    )
    op.drop_index(op.f("ix_meta_marketing_placement_date"), table_name="meta_marketing_placement")
    op.drop_index(op.f("ix_meta_marketing_placement_ad_id"), table_name="meta_marketing_placement")
    op.drop_table("meta_marketing_placement")
