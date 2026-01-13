"""merge heads

Revision ID: 68b5b7e3af9e
Revises: add_facebook_fields, add_payout_hierarchy
Create Date: 2026-01-13 13:29:06.689760

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '68b5b7e3af9e'
down_revision: Union[str, None] = ('add_facebook_fields', 'add_payout_hierarchy')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
