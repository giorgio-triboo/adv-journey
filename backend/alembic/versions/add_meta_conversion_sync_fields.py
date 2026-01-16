"""Add Meta Conversion Sync fields

Revision ID: add_meta_conversion_sync
Revises: 2a655e6c0607
Create Date: 2026-01-13 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_meta_conversion_sync'
down_revision: Union[str, None] = '2a655e6c0607'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add Meta Conversion sync fields to leads
    op.add_column('leads', sa.Column('to_sync_meta', sa.Boolean(), nullable=True, server_default='false'))
    op.add_column('leads', sa.Column('last_meta_event_status', sa.String(), nullable=True))
    op.add_column('leads', sa.Column('meta_correlation_status', sa.String(), nullable=True))
    op.create_index(op.f('ix_leads_to_sync_meta'), 'leads', ['to_sync_meta'], unique=False)
    
    # Add meta_dataset_id to managed_campaigns for mapping
    op.add_column('managed_campaigns', sa.Column('meta_dataset_id', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('managed_campaigns', 'meta_dataset_id')
    op.drop_index(op.f('ix_leads_to_sync_meta'), table_name='leads')
    op.drop_column('leads', 'meta_correlation_status')
    op.drop_column('leads', 'last_meta_event_status')
    op.drop_column('leads', 'to_sync_meta')
