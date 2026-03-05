"""add config column to cron_jobs

Revision ID: 027_cron_job_config
Revises: 026_index_status_category
Create Date: 2026-03-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "027_cron_job_config"
down_revision: Union[str, None] = "026_index_status_category"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("cron_jobs", sa.Column("config", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("cron_jobs", "config")
