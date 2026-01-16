"""Add alert_configs table

Revision ID: add_alert_configs
Revises: add_user_id_to_meta_accounts
Create Date: 2026-01-13 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'add_alert_configs'
down_revision: Union[str, None] = 'add_user_id_meta_accounts'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create alert_configs table
    op.create_table('alert_configs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('alert_type', sa.String(), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=True, server_default='true'),
        sa.Column('recipients', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('on_success', sa.Boolean(), nullable=True, server_default='false'),
        sa.Column('on_error', sa.Boolean(), nullable=True, server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_alert_configs_alert_type'), 'alert_configs', ['alert_type'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_alert_configs_alert_type'), table_name='alert_configs')
    op.drop_table('alert_configs')
