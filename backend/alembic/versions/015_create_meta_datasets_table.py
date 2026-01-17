"""create meta_datasets table

Revision ID: 015_create_meta_datasets
Revises: 014_create_meta_marketing_data
Create Date: 2026-01-17 10:14:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '015_meta_datasets'
down_revision: Union[str, None] = '014_meta_marketing'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('meta_datasets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('dataset_id', sa.String(), nullable=True),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('account_id', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['account_id'], ['meta_accounts.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_meta_datasets_id'), 'meta_datasets', ['id'], unique=False)
    op.create_index(op.f('ix_meta_datasets_dataset_id'), 'meta_datasets', ['dataset_id'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_meta_datasets_dataset_id'), table_name='meta_datasets')
    op.drop_index(op.f('ix_meta_datasets_id'), table_name='meta_datasets')
    op.drop_table('meta_datasets')
