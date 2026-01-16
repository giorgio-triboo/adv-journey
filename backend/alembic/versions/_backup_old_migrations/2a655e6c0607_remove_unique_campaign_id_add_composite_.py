"""remove_unique_campaign_id_add_composite_unique

Revision ID: 2a655e6c0607
Revises: 68b5b7e3af9e
Create Date: 2026-01-13 14:55:19.468709

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2a655e6c0607'
down_revision: Union[str, None] = '68b5b7e3af9e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Questa migration è stata sostituita da d0d8df05fdf4 che refactora managed_campaigns
    # Le colonne campaign_id e msg_id_pattern sono state rimosse da d0d8df05fdf4
    # Questa migration è quindi obsoleta e non fa nulla
    # (Mantenuta solo per la catena di migration)
    pass


def downgrade() -> None:
    # Rimuovi il unique constraint composito
    op.drop_constraint('uq_campaign_msg_id', 'managed_campaigns', type_='unique')
    
    # Ripristina il vincolo unique su campaign_id
    op.drop_index('ix_managed_campaigns_campaign_id', table_name='managed_campaigns')
    op.create_index('ix_managed_campaigns_campaign_id', 'managed_campaigns', ['campaign_id'], unique=True)
