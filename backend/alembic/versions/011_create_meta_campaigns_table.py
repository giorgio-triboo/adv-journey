"""create meta_campaigns table

Revision ID: 011_create_meta_campaigns
Revises: 010_create_meta_accounts
Create Date: 2026-01-17 10:10:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '011_meta_campaigns'
down_revision: Union[str, None] = '010_meta_accounts'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('meta_campaigns',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=True),
        sa.Column('campaign_id', sa.String(), nullable=True),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=True),
        sa.Column('objective', sa.String(), nullable=True),
        sa.Column('daily_budget', sa.String(), nullable=True),
        sa.Column('lifetime_budget', sa.String(), nullable=True),
        sa.Column('tags', sa.JSON(), nullable=True),
        sa.Column('is_synced', sa.Boolean(), nullable=True),
        sa.Column('sync_filters', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['account_id'], ['meta_accounts.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_meta_campaigns_id'), 'meta_campaigns', ['id'], unique=False)
    op.create_index(op.f('ix_meta_campaigns_campaign_id'), 'meta_campaigns', ['campaign_id'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_meta_campaigns_campaign_id'), table_name='meta_campaigns')
    op.drop_index(op.f('ix_meta_campaigns_id'), table_name='meta_campaigns')
    op.drop_table('meta_campaigns')
