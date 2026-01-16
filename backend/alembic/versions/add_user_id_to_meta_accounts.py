"""Add user_id to meta_accounts for user-specific accounts

Revision ID: add_user_id_meta_accounts
Revises: add_payout_hierarchy
Create Date: 2026-01-13 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_user_id_meta_accounts'
down_revision: Union[str, None] = 'add_payout_hierarchy'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add user_id column to meta_accounts (nullable for backward compatibility)
    # NULL = account condiviso tra tutti gli utenti
    # user_id = account specifico per quell'utente
    op.add_column('meta_accounts', sa.Column('user_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_meta_accounts_user_id'), 'meta_accounts', ['user_id'], unique=False)
    op.create_foreign_key('fk_meta_accounts_user_id', 'meta_accounts', 'users', ['user_id'], ['id'], ondelete='CASCADE')
    
    # Rimuovi unique constraint su account_id per permettere stesso account a più utenti
    op.drop_index('ix_meta_accounts_account_id', table_name='meta_accounts')
    # Aggiungi unique constraint su (account_id, user_id) per permettere stesso account a utenti diversi
    op.create_index('ix_meta_accounts_account_user', 'meta_accounts', ['account_id', 'user_id'], unique=True)


def downgrade() -> None:
    # Rimuovi foreign key e index
    op.drop_constraint('fk_meta_accounts_user_id', 'meta_accounts', type_='foreignkey')
    op.drop_index('ix_meta_accounts_account_user', table_name='meta_accounts')
    op.drop_index(op.f('ix_meta_accounts_user_id'), table_name='meta_accounts')
    
    # Ripristina unique constraint su account_id
    op.create_index('ix_meta_accounts_account_id', 'meta_accounts', ['account_id'], unique=True)
    
    # Rimuovi colonna user_id
    op.drop_column('meta_accounts', 'user_id')
