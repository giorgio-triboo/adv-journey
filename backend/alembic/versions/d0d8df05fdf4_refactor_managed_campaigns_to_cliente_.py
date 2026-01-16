"""refactor_managed_campaigns_to_cliente_based

Revision ID: d0d8df05fdf4
Revises: add_user_id_meta_accounts
Create Date: 2026-01-13 15:04:39.979391

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd0d8df05fdf4'
down_revision: Union[str, None] = '2a655e6c0607'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Rimuovi il constraint composito vecchio se esiste
    try:
        op.drop_constraint('uq_campaign_msg_id', 'managed_campaigns', type_='unique')
    except Exception:
        pass
    
    # Rimuovi gli index vecchi se esistono
    try:
        op.drop_index('ix_managed_campaigns_campaign_id', table_name='managed_campaigns')
    except Exception:
        pass
    
    try:
        op.drop_index('ix_managed_campaigns_msg_id_pattern', table_name='managed_campaigns')
    except Exception:
        pass
    
    # Aggiungi i nuovi campi JSON se non esistono già
    try:
        op.add_column('managed_campaigns', sa.Column('magellano_ids', sa.JSON(), nullable=True))
    except Exception:
        pass
    
    try:
        op.add_column('managed_campaigns', sa.Column('msg_ids', sa.JSON(), nullable=True))
    except Exception:
        pass
    
    # Pulisci i dati vecchi: elimina record con cliente_name NULL o duplicati
    op.execute("""
        DELETE FROM managed_campaigns 
        WHERE cliente_name IS NULL 
        OR cliente_name = ''
        OR id NOT IN (
            SELECT MIN(id) 
            FROM managed_campaigns 
            WHERE cliente_name IS NOT NULL 
            AND cliente_name != ''
            GROUP BY cliente_name
        )
    """)
    
    # Modifica cliente_name: da nullable a NOT NULL
    op.alter_column('managed_campaigns', 'cliente_name',
                    nullable=False,
                    existing_nullable=True,
                    existing_type=sa.String())
    
    # Crea unique constraint su cliente_name se non esiste
    try:
        op.create_unique_constraint('uq_managed_campaigns_cliente_name', 'managed_campaigns', ['cliente_name'])
    except Exception:
        pass
    
    # Rimuovi i campi vecchi se esistono
    try:
        op.drop_column('managed_campaigns', 'campaign_id')
    except Exception:
        pass
    
    try:
        op.drop_column('managed_campaigns', 'msg_id_pattern')
    except Exception:
        pass


def downgrade() -> None:
    # Ripristina i campi vecchi
    op.add_column('managed_campaigns', sa.Column('campaign_id', sa.String(), nullable=True))
    op.add_column('managed_campaigns', sa.Column('msg_id_pattern', sa.String(), nullable=True))
    
    # Rimuovi unique constraint su cliente_name
    op.drop_constraint('uq_managed_campaigns_cliente_name', 'managed_campaigns', type_='unique')
    
    # Ripristina nullable su cliente_name
    op.alter_column('managed_campaigns', 'cliente_name',
                    nullable=True,
                    existing_nullable=False)
    
    # Rimuovi i nuovi campi JSON
    op.drop_column('managed_campaigns', 'msg_ids')
    op.drop_column('managed_campaigns', 'magellano_ids')
    
    # Ripristina index e constraint vecchi
    op.create_index('ix_managed_campaigns_campaign_id', 'managed_campaigns', ['campaign_id'], unique=False)
    op.create_index('ix_managed_campaigns_msg_id_pattern', 'managed_campaigns', ['msg_id_pattern'], unique=False)
    op.create_unique_constraint('uq_campaign_msg_id', 'managed_campaigns', ['campaign_id', 'msg_id_pattern'])
