"""create managed_campaigns table

Revision ID: 009_create_managed_campaigns
Revises: 008_create_cron_jobs
Create Date: 2026-01-17 10:08:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '009_managed_campaigns'
down_revision: Union[str, None] = '008_cron_jobs'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('managed_campaigns',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('cliente_name', sa.String(), nullable=True),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('magellano_ids', sa.JSON(), nullable=True),
        sa.Column('msg_ids', sa.JSON(), nullable=True),
        sa.Column('pay_level', sa.String(), nullable=True),
        sa.Column('ulixe_ids', sa.JSON(), nullable=True),
        sa.Column('meta_dataset_id', sa.String(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_managed_campaigns_id'), 'managed_campaigns', ['id'], unique=False)
    op.create_index(op.f('ix_managed_campaigns_cliente_name'), 'managed_campaigns', ['cliente_name'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_managed_campaigns_cliente_name'), table_name='managed_campaigns')
    op.drop_index(op.f('ix_managed_campaigns_id'), table_name='managed_campaigns')
    op.drop_table('managed_campaigns')
