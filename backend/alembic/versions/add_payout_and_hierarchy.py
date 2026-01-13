"""Add payout status and campaign hierarchy

Revision ID: add_payout_hierarchy
Revises: add_meta_marketing_models
Create Date: 2026-01-XX

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'add_payout_hierarchy'
down_revision = 'add_meta_marketing'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add payout fields to leads
    op.add_column('leads', sa.Column('payout_status', sa.String(), nullable=True))
    op.add_column('leads', sa.Column('is_paid', sa.Boolean(), nullable=True, server_default='false'))
    
    # Add hierarchy fields to managed_campaigns
    op.add_column('managed_campaigns', sa.Column('cliente_name', sa.String(), nullable=True))
    op.add_column('managed_campaigns', sa.Column('pay_level', sa.String(), nullable=True))
    op.add_column('managed_campaigns', sa.Column('msg_id_pattern', sa.String(), nullable=True))
    
    # Create indexes
    op.create_index(op.f('ix_leads_payout_status'), 'leads', ['payout_status'], unique=False)
    op.create_index(op.f('ix_managed_campaigns_cliente_name'), 'managed_campaigns', ['cliente_name'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_managed_campaigns_cliente_name'), table_name='managed_campaigns')
    op.drop_index(op.f('ix_leads_payout_status'), table_name='leads')
    
    op.drop_column('managed_campaigns', 'msg_id_pattern')
    op.drop_column('managed_campaigns', 'pay_level')
    op.drop_column('managed_campaigns', 'cliente_name')
    
    op.drop_column('leads', 'is_paid')
    op.drop_column('leads', 'payout_status')
