"""merge_heads

Revision ID: 891078d8154d
Revises: add_alert_configs, add_meta_conversion_sync, d0d8df05fdf4
Create Date: 2026-01-16 10:57:07.365960

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '891078d8154d'
down_revision: Union[str, None] = ('add_alert_configs', 'add_meta_conversion_sync', 'd0d8df05fdf4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
