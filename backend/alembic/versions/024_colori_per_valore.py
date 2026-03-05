"""migrate colori_attivi to colori_margine_attivi + colori_scarto_attivi

Per chi ha eseguito la vecchia 023 con colori_attivi singolo.
Revision ID: 024_colori_per_valore
Revises: 023_colori_attivi
Create Date: 2026-03-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "024_colori_per_valore"
down_revision: Union[str, None] = "023_colori_attivi"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    # Se esiste colori_attivi (vecchia 023), rimuovilo
    r = conn.execute(sa.text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='marketing_threshold_config' AND column_name='colori_attivi'"
    ))
    if r.fetchone() is not None:
        op.drop_column("marketing_threshold_config", "colori_attivi")

    # Aggiungi le due colonne se non esistono (per chi aveva vecchia 023)
    r = conn.execute(sa.text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='marketing_threshold_config' AND column_name='colori_margine_attivi'"
    ))
    if r.fetchone() is None:
        op.add_column(
            "marketing_threshold_config",
            sa.Column("colori_margine_attivi", sa.Boolean(), nullable=False, server_default=sa.true()),
        )
    r = conn.execute(sa.text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='marketing_threshold_config' AND column_name='colori_scarto_attivi'"
    ))
    if r.fetchone() is None:
        op.add_column(
            "marketing_threshold_config",
            sa.Column("colori_scarto_attivi", sa.Boolean(), nullable=False, server_default=sa.true()),
        )


def downgrade() -> None:
    # Non reversibile: la migrazione da colori_attivi a colori_margine/scarto_attivi
    pass
