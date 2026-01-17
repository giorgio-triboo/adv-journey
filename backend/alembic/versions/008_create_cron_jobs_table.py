"""create cron_jobs table

Revision ID: 008_create_cron_jobs
Revises: 007_create_smtp_configs
Create Date: 2026-01-17 10:07:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '008_cron_jobs'
down_revision: Union[str, None] = '007_smtp_configs'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('cron_jobs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('job_name', sa.String(), nullable=True),
        sa.Column('job_type', sa.String(), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=True),
        sa.Column('hour', sa.Integer(), nullable=True),
        sa.Column('minute', sa.Integer(), nullable=True),
        sa.Column('day_of_week', sa.String(), nullable=True),
        sa.Column('day_of_month', sa.String(), nullable=True),
        sa.Column('month', sa.String(), nullable=True),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_cron_jobs_id'), 'cron_jobs', ['id'], unique=False)
    op.create_index(op.f('ix_cron_jobs_job_name'), 'cron_jobs', ['job_name'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_cron_jobs_job_name'), table_name='cron_jobs')
    op.drop_index(op.f('ix_cron_jobs_id'), table_name='cron_jobs')
    op.drop_table('cron_jobs')
