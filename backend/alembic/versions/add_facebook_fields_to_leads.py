"""Add Facebook fields to leads

Revision ID: add_facebook_fields
Revises: add_meta_marketing
Create Date: 2026-01-13 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'add_facebook_fields'
down_revision: Union[str, None] = 'add_meta_marketing'  # After meta_marketing migration
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add Facebook/Meta fields from Magellano (solo se non esistono già)
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_columns = [col['name'] for col in inspector.get_columns('leads')]
    
    if 'facebook_ad_name' not in existing_columns:
        op.add_column('leads', sa.Column('facebook_ad_name', sa.String(), nullable=True))
    if 'facebook_ad_set' not in existing_columns:
        op.add_column('leads', sa.Column('facebook_ad_set', sa.String(), nullable=True))
    if 'facebook_campaign_name' not in existing_columns:
        op.add_column('leads', sa.Column('facebook_campaign_name', sa.String(), nullable=True))
    if 'facebook_id' not in existing_columns:
        op.add_column('leads', sa.Column('facebook_id', sa.String(), nullable=True))
    if 'facebook_piattaforma' not in existing_columns:
        op.add_column('leads', sa.Column('facebook_piattaforma', sa.String(), nullable=True))
    
    # Add index on msg_id for faster queries (solo se non esiste già)
    existing_indexes = [idx['name'] for idx in inspector.get_indexes('leads')]
    if 'ix_leads_msg_id' not in existing_indexes:
        op.create_index(op.f('ix_leads_msg_id'), 'leads', ['msg_id'], unique=False)
    if 'ix_leads_facebook_ad_name' not in existing_indexes:
        op.create_index(op.f('ix_leads_facebook_ad_name'), 'leads', ['facebook_ad_name'], unique=False)
    if 'ix_leads_facebook_ad_set' not in existing_indexes:
        op.create_index(op.f('ix_leads_facebook_ad_set'), 'leads', ['facebook_ad_set'], unique=False)
    if 'ix_leads_facebook_campaign_name' not in existing_indexes:
        op.create_index(op.f('ix_leads_facebook_campaign_name'), 'leads', ['facebook_campaign_name'], unique=False)
    if 'ix_leads_facebook_id' not in existing_indexes:
        op.create_index(op.f('ix_leads_facebook_id'), 'leads', ['facebook_id'], unique=False)


def downgrade() -> None:
    # Remove indexes
    op.drop_index(op.f('ix_leads_facebook_id'), table_name='leads')
    op.drop_index(op.f('ix_leads_facebook_campaign_name'), table_name='leads')
    op.drop_index(op.f('ix_leads_facebook_ad_set'), table_name='leads')
    op.drop_index(op.f('ix_leads_facebook_ad_name'), table_name='leads')
    op.drop_index(op.f('ix_leads_msg_id'), table_name='leads')
    
    # Remove columns
    op.drop_column('leads', 'facebook_piattaforma')
    op.drop_column('leads', 'facebook_id')
    op.drop_column('leads', 'facebook_campaign_name')
    op.drop_column('leads', 'facebook_ad_set')
    op.drop_column('leads', 'facebook_ad_name')
