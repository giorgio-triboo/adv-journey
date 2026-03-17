"""add platform fields to leads and meta_marketing_data

Revision ID: 029_add_platform_fields
Revises: 028_create_ingestion_jobs_table
Create Date: 2026-03-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "029_add_platform_fields"
down_revision: Union[str, None] = "028_ingestion_jobs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Lead.platform (piattaforma normalizzata: facebook / instagram / unknown)
    op.add_column("leads", sa.Column("platform", sa.String(), nullable=True))
    op.create_index(op.f("ix_leads_platform"), "leads", ["platform"], unique=False)

    # MetaMarketingData.publisher_platform / platform_position
    op.add_column(
        "meta_marketing_data",
        sa.Column("publisher_platform", sa.String(), nullable=True),
    )
    op.add_column(
        "meta_marketing_data",
        sa.Column("platform_position", sa.String(), nullable=True),
    )
    op.create_index(
        op.f("ix_meta_marketing_data_publisher_platform"),
        "meta_marketing_data",
        ["publisher_platform"],
        unique=False,
    )


def downgrade() -> None:
    # MetaMarketingData
    op.drop_index(
        op.f("ix_meta_marketing_data_publisher_platform"),
        table_name="meta_marketing_data",
    )
    op.drop_column("meta_marketing_data", "platform_position")
    op.drop_column("meta_marketing_data", "publisher_platform")

    # Lead
    op.drop_index(op.f("ix_leads_platform"), table_name="leads")
    op.drop_column("leads", "platform")

