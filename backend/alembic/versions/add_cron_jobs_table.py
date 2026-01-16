"""Add cron_jobs table

Revision ID: add_cron_jobs
Revises: add_smtp_configs
Create Date: 2026-01-13 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'add_cron_jobs'
down_revision: Union[str, None] = 'add_smtp_configs'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create cron_jobs table
    op.create_table('cron_jobs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('job_name', sa.String(), nullable=True),
        sa.Column('job_type', sa.String(), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=True, server_default='true'),
        sa.Column('hour', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('minute', sa.Integer(), nullable=True, server_default='30'),
        sa.Column('day_of_week', sa.String(), nullable=True, server_default='*'),
        sa.Column('day_of_month', sa.String(), nullable=True, server_default='*'),
        sa.Column('month', sa.String(), nullable=True, server_default='*'),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_cron_jobs_job_name'), 'cron_jobs', ['job_name'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_cron_jobs_job_name'), table_name='cron_jobs')
    op.drop_table('cron_jobs')
