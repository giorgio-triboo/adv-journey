"""create ulixe_rcrm_temp table (provvisoria per RCRM da export Ulixe)

Revision ID: 020_ulixe_rcrm_temp
Revises: 019_marketing_threshold_config
Create Date: 2026-03-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "020_ulixe_rcrm_temp"
down_revision: Union[str, None] = "019_marketing_threshold_config"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ulixe_rcrm_temp",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("msg_id", sa.String(), nullable=False),
        sa.Column("period", sa.String(), nullable=False),
        sa.Column("rcrm_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_file", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("msg_id", "period", name="uq_ulixe_rcrm_temp_msg_period"),
    )
    op.create_index(op.f("ix_ulixe_rcrm_temp_id"), "ulixe_rcrm_temp", ["id"], unique=False)
    op.create_index(op.f("ix_ulixe_rcrm_temp_msg_id"), "ulixe_rcrm_temp", ["msg_id"], unique=False)
    op.create_index(op.f("ix_ulixe_rcrm_temp_period"), "ulixe_rcrm_temp", ["period"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_ulixe_rcrm_temp_period"), table_name="ulixe_rcrm_temp")
    op.drop_index(op.f("ix_ulixe_rcrm_temp_msg_id"), table_name="ulixe_rcrm_temp")
    op.drop_index(op.f("ix_ulixe_rcrm_temp_id"), table_name="ulixe_rcrm_temp")
    op.drop_table("ulixe_rcrm_temp")
