"""create alert_configs table

Revision ID: 006_create_alert_configs
Revises: 005_create_sync_logs
Create Date: 2026-01-17 10:05:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '006_alert_configs'
down_revision: Union[str, None] = '005_sync_logs'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('alert_configs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('alert_type', sa.String(), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=True),
        sa.Column('recipients', sa.JSON(), nullable=True),
        sa.Column('on_success', sa.Boolean(), nullable=True),
        sa.Column('on_error', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_alert_configs_id'), 'alert_configs', ['id'], unique=False)
    op.create_index(op.f('ix_alert_configs_alert_type'), 'alert_configs', ['alert_type'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_alert_configs_alert_type'), table_name='alert_configs')
    op.drop_index(op.f('ix_alert_configs_id'), table_name='alert_configs')
    op.drop_table('alert_configs')
