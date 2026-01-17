"""create meta_marketing_data table

Revision ID: 014_create_meta_marketing_data
Revises: 013_create_meta_ads
Create Date: 2026-01-17 10:13:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '014_meta_marketing'
down_revision: Union[str, None] = '013_meta_ads'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
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
        sa.Column('additional_metrics', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['ad_id'], ['meta_ads.id'], ),
        sa.ForeignKeyConstraint(['lead_id'], ['leads.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_meta_marketing_data_id'), 'meta_marketing_data', ['id'], unique=False)
    op.create_index(op.f('ix_meta_marketing_data_date'), 'meta_marketing_data', ['date'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_meta_marketing_data_date'), table_name='meta_marketing_data')
    op.drop_index(op.f('ix_meta_marketing_data_id'), table_name='meta_marketing_data')
    op.drop_table('meta_marketing_data')
