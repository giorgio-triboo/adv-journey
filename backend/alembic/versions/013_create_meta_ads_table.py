"""create meta_ads table

Revision ID: 013_create_meta_ads
Revises: 012_create_meta_adsets
Create Date: 2026-01-17 10:12:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '013_meta_ads'
down_revision: Union[str, None] = '012_meta_adsets'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
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


def downgrade() -> None:
    op.drop_index(op.f('ix_meta_ads_ad_id'), table_name='meta_ads')
    op.drop_index(op.f('ix_meta_ads_id'), table_name='meta_ads')
    op.drop_table('meta_ads')
