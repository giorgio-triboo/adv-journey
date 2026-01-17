"""create smtp_configs table

Revision ID: 007_create_smtp_configs
Revises: 006_create_alert_configs
Create Date: 2026-01-17 10:06:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '007_smtp_configs'
down_revision: Union[str, None] = '006_alert_configs'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('smtp_configs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('host', sa.String(), nullable=True),
        sa.Column('port', sa.Integer(), nullable=True),
        sa.Column('user', sa.String(), nullable=True),
        sa.Column('password', sa.String(), nullable=True),
        sa.Column('from_email', sa.String(), nullable=True),
        sa.Column('use_tls', sa.Boolean(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_smtp_configs_id'), 'smtp_configs', ['id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_smtp_configs_id'), table_name='smtp_configs')
    op.drop_table('smtp_configs')
