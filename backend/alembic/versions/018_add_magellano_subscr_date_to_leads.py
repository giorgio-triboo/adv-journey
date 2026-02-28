"""add magellano_subscr_date to leads

Revision ID: 018_magellano_subscr_date
Revises: 017_meta_marketing_numeric
Create Date: 2026-02-24 16:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "018_magellano_subscr_date"
down_revision: Union[str, None] = "017_meta_marketing_numeric"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "leads",
        sa.Column("magellano_subscr_date", sa.Date(), nullable=True),
    )
    # Index per filtrare rapidamente per data Magellano
    op.create_index(
        op.f("ix_leads_magellano_subscr_date"),
        "leads",
        ["magellano_subscr_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_leads_magellano_subscr_date"), table_name="leads")
    op.drop_column("leads", "magellano_subscr_date")

