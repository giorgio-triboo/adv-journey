"""index leads status_category per query più veloci

Revision ID: 026_index_status_category
Revises: 025_colori_per_campo
Create Date: 2026-03-05

"""
from typing import Sequence, Union

from alembic import op


revision: str = "026_index_status_category"
down_revision: Union[str, None] = "025_colori_per_campo"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        op.f("ix_leads_status_category"),
        "leads",
        ["status_category"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_leads_status_category"), table_name="leads")
