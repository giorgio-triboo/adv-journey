"""create meta_dataset_fetch_jobs table

Revision ID: 016_create_meta_dataset_fetch_jobs
Revises: 015_create_meta_datasets
Create Date: 2026-01-17 10:15:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '016_meta_fetch_jobs'
down_revision: Union[str, None] = '015_meta_datasets'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('meta_dataset_fetch_jobs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(), nullable=True),
        sa.Column('datasets', sa.JSON(), nullable=True),
        sa.Column('account_map', sa.JSON(), nullable=True),
        sa.Column('error_message', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_meta_dataset_fetch_jobs_id'), 'meta_dataset_fetch_jobs', ['id'], unique=False)
    op.create_index(op.f('ix_meta_dataset_fetch_jobs_user_id'), 'meta_dataset_fetch_jobs', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_meta_dataset_fetch_jobs_user_id'), table_name='meta_dataset_fetch_jobs')
    op.drop_index(op.f('ix_meta_dataset_fetch_jobs_id'), table_name='meta_dataset_fetch_jobs')
    op.drop_table('meta_dataset_fetch_jobs')
