"""create marketing_threshold_config table

Revision ID: 019_marketing_threshold_config
Revises: 018_magellano_subscr_date
Create Date: 2026-03-04 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "019_marketing_threshold_config"
down_revision: Union[str, None] = "018_magellano_subscr_date"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "marketing_threshold_config",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("margine_rosso_fino", sa.Numeric(10, 2), nullable=True),
        sa.Column("margine_verde_da", sa.Numeric(10, 2), nullable=True),
        sa.Column("scarto_verde_fino", sa.Numeric(10, 2), nullable=True),
        sa.Column("scarto_rosso_da", sa.Numeric(10, 2), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_marketing_threshold_config_id"), "marketing_threshold_config", ["id"], unique=False)
    op.execute(
        "INSERT INTO marketing_threshold_config (id, margine_rosso_fino, margine_verde_da, scarto_verde_fino, scarto_rosso_da) "
        "VALUES (1, 0, 15, 5, 20)"
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_marketing_threshold_config_id"), table_name="marketing_threshold_config")
    op.drop_table("marketing_threshold_config")
