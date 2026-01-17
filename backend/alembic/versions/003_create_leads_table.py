"""create leads table

Revision ID: 003_create_leads
Revises: 002_create_users
Create Date: 2026-01-17 10:02:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '003_leads'
down_revision: Union[str, None] = '002_users'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('leads',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('magellano_id', sa.String(), nullable=True),
        sa.Column('external_user_id', sa.String(), nullable=True),
        sa.Column('email', sa.String(), nullable=True),
        sa.Column('phone', sa.String(), nullable=True),
        sa.Column('brand', sa.String(), nullable=True),
        sa.Column('msg_id', sa.String(), nullable=True),
        sa.Column('form_id', sa.String(), nullable=True),
        sa.Column('source', sa.String(), nullable=True),
        sa.Column('campaign_name', sa.String(), nullable=True),
        sa.Column('magellano_campaign_id', sa.String(), nullable=True),
        sa.Column('payout_status', sa.String(), nullable=True),
        sa.Column('is_paid', sa.Boolean(), nullable=True),
        sa.Column('magellano_status', sa.String(), nullable=True),
        sa.Column('magellano_status_raw', sa.String(), nullable=True),
        sa.Column('magellano_status_category', postgresql.ENUM('IN_LAVORAZIONE', 'RIFIUTATO', 'CRM', 'FINALE', 'UNKNOWN', name='statuscategory', create_type=False), nullable=True),
        sa.Column('ulixe_status', sa.String(), nullable=True),
        sa.Column('ulixe_status_category', postgresql.ENUM('IN_LAVORAZIONE', 'RIFIUTATO', 'CRM', 'FINALE', 'UNKNOWN', name='statuscategory', create_type=False), nullable=True),
        sa.Column('facebook_ad_name', sa.String(), nullable=True),
        sa.Column('facebook_ad_set', sa.String(), nullable=True),
        sa.Column('facebook_campaign_name', sa.String(), nullable=True),
        sa.Column('facebook_id', sa.String(), nullable=True),
        sa.Column('facebook_piattaforma', sa.String(), nullable=True),
        sa.Column('meta_campaign_id', sa.String(), nullable=True),
        sa.Column('meta_adset_id', sa.String(), nullable=True),
        sa.Column('meta_ad_id', sa.String(), nullable=True),
        sa.Column('current_status', sa.String(), nullable=True),
        sa.Column('status_category', postgresql.ENUM('IN_LAVORAZIONE', 'RIFIUTATO', 'CRM', 'FINALE', 'UNKNOWN', name='statuscategory', create_type=False), nullable=True),
        sa.Column('last_check', sa.DateTime(), nullable=True),
        sa.Column('to_sync_meta', sa.Boolean(), nullable=True),
        sa.Column('last_meta_event_status', sa.String(), nullable=True),
        sa.Column('meta_correlation_status', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_leads_id'), 'leads', ['id'], unique=False)
    op.create_index(op.f('ix_leads_magellano_id'), 'leads', ['magellano_id'], unique=True)
    op.create_index(op.f('ix_leads_external_user_id'), 'leads', ['external_user_id'], unique=False)
    op.create_index(op.f('ix_leads_msg_id'), 'leads', ['msg_id'], unique=False)
    op.create_index(op.f('ix_leads_magellano_campaign_id'), 'leads', ['magellano_campaign_id'], unique=False)
    op.create_index(op.f('ix_leads_magellano_status'), 'leads', ['magellano_status'], unique=False)
    op.create_index(op.f('ix_leads_facebook_ad_name'), 'leads', ['facebook_ad_name'], unique=False)
    op.create_index(op.f('ix_leads_facebook_ad_set'), 'leads', ['facebook_ad_set'], unique=False)
    op.create_index(op.f('ix_leads_facebook_campaign_name'), 'leads', ['facebook_campaign_name'], unique=False)
    op.create_index(op.f('ix_leads_facebook_id'), 'leads', ['facebook_id'], unique=False)
    op.create_index(op.f('ix_leads_meta_campaign_id'), 'leads', ['meta_campaign_id'], unique=False)
    op.create_index(op.f('ix_leads_meta_adset_id'), 'leads', ['meta_adset_id'], unique=False)
    op.create_index(op.f('ix_leads_meta_ad_id'), 'leads', ['meta_ad_id'], unique=False)
    op.create_index(op.f('ix_leads_to_sync_meta'), 'leads', ['to_sync_meta'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_leads_to_sync_meta'), table_name='leads')
    op.drop_index(op.f('ix_leads_meta_ad_id'), table_name='leads')
    op.drop_index(op.f('ix_leads_meta_adset_id'), table_name='leads')
    op.drop_index(op.f('ix_leads_meta_campaign_id'), table_name='leads')
    op.drop_index(op.f('ix_leads_facebook_id'), table_name='leads')
    op.drop_index(op.f('ix_leads_facebook_campaign_name'), table_name='leads')
    op.drop_index(op.f('ix_leads_facebook_ad_set'), table_name='leads')
    op.drop_index(op.f('ix_leads_facebook_ad_name'), table_name='leads')
    op.drop_index(op.f('ix_leads_magellano_status'), table_name='leads')
    op.drop_index(op.f('ix_leads_magellano_campaign_id'), table_name='leads')
    op.drop_index(op.f('ix_leads_msg_id'), table_name='leads')
    op.drop_index(op.f('ix_leads_external_user_id'), table_name='leads')
    op.drop_index(op.f('ix_leads_magellano_id'), table_name='leads')
    op.drop_index(op.f('ix_leads_id'), table_name='leads')
    op.drop_table('leads')
