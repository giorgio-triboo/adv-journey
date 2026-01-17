"""create meta_adsets table

Revision ID: 012_create_meta_adsets
Revises: 011_create_meta_campaigns
Create Date: 2026-01-17 10:11:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '012_meta_adsets'
down_revision: Union[str, None] = '011_meta_campaigns'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('meta_adsets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('campaign_id', sa.Integer(), nullable=True),
        sa.Column('adset_id', sa.String(), nullable=True),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=True),
        sa.Column('optimization_goal', sa.String(), nullable=True),
        sa.Column('targeting', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['campaign_id'], ['meta_campaigns.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_meta_adsets_id'), 'meta_adsets', ['id'], unique=False)
    op.create_index(op.f('ix_meta_adsets_adset_id'), 'meta_adsets', ['adset_id'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_meta_adsets_adset_id'), table_name='meta_adsets')
    op.drop_index(op.f('ix_meta_adsets_id'), table_name='meta_adsets')
    op.drop_table('meta_adsets')
