"""Add smtp_configs table

Revision ID: add_smtp_configs
Revises: 891078d8154d
Create Date: 2026-01-13 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'add_smtp_configs'
down_revision: Union[str, None] = '891078d8154d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create smtp_configs table
    op.create_table('smtp_configs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('host', sa.String(), nullable=True),
        sa.Column('port', sa.Integer(), nullable=True, server_default='587'),
        sa.Column('user', sa.String(), nullable=True),
        sa.Column('password', sa.String(), nullable=True),
        sa.Column('from_email', sa.String(), nullable=True),
        sa.Column('use_tls', sa.Boolean(), nullable=True, server_default='true'),
        sa.Column('is_active', sa.Boolean(), nullable=True, server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('smtp_configs')
