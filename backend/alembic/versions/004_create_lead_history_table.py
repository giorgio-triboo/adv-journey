"""create lead_history table

Revision ID: 004_create_lead_history
Revises: 003_create_leads
Create Date: 2026-01-17 10:03:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '004_lead_history'
down_revision: Union[str, None] = '003_leads'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('lead_history',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('lead_id', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(), nullable=True),
        sa.Column('status_category', postgresql.ENUM('IN_LAVORAZIONE', 'RIFIUTATO', 'CRM', 'FINALE', 'UNKNOWN', name='statuscategory', create_type=False), nullable=True),
        sa.Column('raw_response', sa.JSON(), nullable=True),
        sa.Column('checked_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['lead_id'], ['leads.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_lead_history_id'), 'lead_history', ['id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_lead_history_id'), table_name='lead_history')
    op.drop_table('lead_history')
