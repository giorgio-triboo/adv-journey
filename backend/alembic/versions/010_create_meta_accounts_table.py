"""create meta_accounts table

Revision ID: 010_create_meta_accounts
Revises: 009_create_managed_campaigns
Create Date: 2026-01-17 10:09:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '010_meta_accounts'
down_revision: Union[str, None] = '009_managed_campaigns'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('meta_accounts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.String(), nullable=True),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('access_token', sa.String(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('sync_enabled', sa.Boolean(), nullable=True),
        sa.Column('sync_frequency', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('account_id', 'user_id', name='uq_meta_account_user')
    )
    op.create_index(op.f('ix_meta_accounts_id'), 'meta_accounts', ['id'], unique=False)
    op.create_index(op.f('ix_meta_accounts_account_id'), 'meta_accounts', ['account_id'], unique=False)
    op.create_index(op.f('ix_meta_accounts_user_id'), 'meta_accounts', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_meta_accounts_user_id'), table_name='meta_accounts')
    op.drop_index(op.f('ix_meta_accounts_account_id'), table_name='meta_accounts')
    op.drop_index(op.f('ix_meta_accounts_id'), table_name='meta_accounts')
    op.drop_table('meta_accounts')
