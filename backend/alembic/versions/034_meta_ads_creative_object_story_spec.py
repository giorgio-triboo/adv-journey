"""Aggiunge creative_object_story_spec a meta_ads (copy creatività Meta)

Revision ID: 034_meta_ads_oss
Revises: 033_drop_lead_placement
Create Date: 2026-04-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "034_meta_ads_oss"
down_revision: Union[str, None] = "033_drop_lead_placement"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "meta_ads",
        sa.Column("creative_object_story_spec", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("meta_ads", "creative_object_story_spec")
