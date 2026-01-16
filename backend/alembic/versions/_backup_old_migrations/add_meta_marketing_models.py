"""Add Meta Marketing models

Revision ID: add_meta_marketing
Revises: 01538fb04cf3
Create Date: 2026-01-13 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'add_meta_marketing'
down_revision: Union[str, None] = '1d723402bf5e'  # After form_id migration
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add Meta Marketing correlation fields to leads
    op.add_column('leads', sa.Column('meta_campaign_id', sa.String(), nullable=True))
    op.add_column('leads', sa.Column('meta_adset_id', sa.String(), nullable=True))
    op.add_column('leads', sa.Column('meta_ad_id', sa.String(), nullable=True))
    op.create_index(op.f('ix_leads_meta_campaign_id'), 'leads', ['meta_campaign_id'], unique=False)
    op.create_index(op.f('ix_leads_meta_adset_id'), 'leads', ['meta_adset_id'], unique=False)
    op.create_index(op.f('ix_leads_meta_ad_id'), 'leads', ['meta_ad_id'], unique=False)
    
    # Create meta_accounts table
    op.create_table('meta_accounts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.String(), nullable=True),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('access_token', sa.String(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('sync_enabled', sa.Boolean(), nullable=True),
        sa.Column('sync_frequency', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_meta_accounts_id'), 'meta_accounts', ['id'], unique=False)
    op.create_index(op.f('ix_meta_accounts_account_id'), 'meta_accounts', ['account_id'], unique=True)
    
    # Create meta_campaigns table
    op.create_table('meta_campaigns',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=True),
        sa.Column('campaign_id', sa.String(), nullable=True),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=True),
        sa.Column('objective', sa.String(), nullable=True),
        sa.Column('daily_budget', sa.String(), nullable=True),
        sa.Column('lifetime_budget', sa.String(), nullable=True),
        sa.Column('tags', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('is_synced', sa.Boolean(), nullable=True),
        sa.Column('sync_filters', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['account_id'], ['meta_accounts.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_meta_campaigns_id'), 'meta_campaigns', ['id'], unique=False)
    op.create_index(op.f('ix_meta_campaigns_campaign_id'), 'meta_campaigns', ['campaign_id'], unique=True)
    
    # Create meta_adsets table
    op.create_table('meta_adsets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('campaign_id', sa.Integer(), nullable=True),
        sa.Column('adset_id', sa.String(), nullable=True),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=True),
        sa.Column('optimization_goal', sa.String(), nullable=True),
        sa.Column('targeting', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['campaign_id'], ['meta_campaigns.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_meta_adsets_id'), 'meta_adsets', ['id'], unique=False)
    op.create_index(op.f('ix_meta_adsets_adset_id'), 'meta_adsets', ['adset_id'], unique=True)
    
    # Create meta_ads table
    op.create_table('meta_ads',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('adset_id', sa.Integer(), nullable=True),
        sa.Column('ad_id', sa.String(), nullable=True),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=True),
        sa.Column('creative_id', sa.String(), nullable=True),
        sa.Column('creative_thumbnail_url', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['adset_id'], ['meta_adsets.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_meta_ads_id'), 'meta_ads', ['id'], unique=False)
    op.create_index(op.f('ix_meta_ads_ad_id'), 'meta_ads', ['ad_id'], unique=True)
    
    # Create meta_marketing_data table
    op.create_table('meta_marketing_data',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('lead_id', sa.Integer(), nullable=True),
        sa.Column('ad_id', sa.Integer(), nullable=True),
        sa.Column('date', sa.DateTime(), nullable=True),
        sa.Column('spend', sa.String(), nullable=True),
        sa.Column('impressions', sa.Integer(), nullable=True),
        sa.Column('clicks', sa.Integer(), nullable=True),
        sa.Column('conversions', sa.Integer(), nullable=True),
        sa.Column('ctr', sa.String(), nullable=True),
        sa.Column('cpc', sa.String(), nullable=True),
        sa.Column('cpm', sa.String(), nullable=True),
        sa.Column('cpa', sa.String(), nullable=True),
        sa.Column('additional_metrics', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['lead_id'], ['leads.id'], ),
        sa.ForeignKeyConstraint(['ad_id'], ['meta_ads.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_meta_marketing_data_id'), 'meta_marketing_data', ['id'], unique=False)
    op.create_index(op.f('ix_meta_marketing_data_date'), 'meta_marketing_data', ['date'], unique=False)


def downgrade() -> None:
    # Drop meta_marketing_data table
    op.drop_index(op.f('ix_meta_marketing_data_date'), table_name='meta_marketing_data')
    op.drop_index(op.f('ix_meta_marketing_data_id'), table_name='meta_marketing_data')
    op.drop_table('meta_marketing_data')
    
    # Drop meta_ads table
    op.drop_index(op.f('ix_meta_ads_ad_id'), table_name='meta_ads')
    op.drop_index(op.f('ix_meta_ads_id'), table_name='meta_ads')
    op.drop_table('meta_ads')
    
    # Drop meta_adsets table
    op.drop_index(op.f('ix_meta_adsets_adset_id'), table_name='meta_adsets')
    op.drop_index(op.f('ix_meta_adsets_id'), table_name='meta_adsets')
    op.drop_table('meta_adsets')
    
    # Drop meta_campaigns table
    op.drop_index(op.f('ix_meta_campaigns_campaign_id'), table_name='meta_campaigns')
    op.drop_index(op.f('ix_meta_campaigns_id'), table_name='meta_campaigns')
    op.drop_table('meta_campaigns')
    
    # Drop meta_accounts table
    op.drop_index(op.f('ix_meta_accounts_account_id'), table_name='meta_accounts')
    op.drop_index(op.f('ix_meta_accounts_id'), table_name='meta_accounts')
    op.drop_table('meta_accounts')
    
    # Remove Meta Marketing fields from leads
    op.drop_index(op.f('ix_leads_meta_ad_id'), table_name='leads')
    op.drop_index(op.f('ix_leads_meta_adset_id'), table_name='leads')
    op.drop_index(op.f('ix_leads_meta_campaign_id'), table_name='leads')
    op.drop_column('leads', 'meta_ad_id')
    op.drop_column('leads', 'meta_adset_id')
    op.drop_column('leads', 'meta_campaign_id')
