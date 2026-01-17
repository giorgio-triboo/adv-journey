"""create status_category enum

Revision ID: 001_status_category_enum
Revises: 
Create Date: 2026-01-17 10:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001_status_enum'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create StatusCategory enum
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE statuscategory AS ENUM (
                'IN_LAVORAZIONE',
                'RIFIUTATO',
                'CRM',
                'FINALE',
                'UNKNOWN'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)


def downgrade() -> None:
    # Drop StatusCategory enum
    op.execute("DROP TYPE IF EXISTS statuscategory")
