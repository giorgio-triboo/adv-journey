"""colori per ogni singolo campo input (4 checkbox)

Revision ID: 025_colori_per_campo
Revises: 024_colori_per_valore
Create Date: 2026-03-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "025_colori_per_campo"
down_revision: Union[str, None] = "024_colori_per_valore"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # Rimuovi le vecchie colonne se esistono
    for col in ("colori_margine_attivi", "colori_scarto_attivi"):
        r = conn.execute(sa.text(
            f"SELECT column_name FROM information_schema.columns "
            f"WHERE table_name='marketing_threshold_config' AND column_name='{col}'"
        ))
        if r.fetchone() is not None:
            op.drop_column("marketing_threshold_config", col)

    # Aggiungi le 4 colonne per ogni singolo input
    for col in ("colori_margine_rosso", "colori_margine_verde", "colori_scarto_verde", "colori_scarto_rosso"):
        r = conn.execute(sa.text(
            f"SELECT column_name FROM information_schema.columns "
            f"WHERE table_name='marketing_threshold_config' AND column_name='{col}'"
        ))
        if r.fetchone() is None:
            op.add_column(
                "marketing_threshold_config",
                sa.Column(col, sa.Boolean(), nullable=False, server_default=sa.true()),
            )


def downgrade() -> None:
    for col in ("colori_scarto_rosso", "colori_scarto_verde", "colori_margine_verde", "colori_margine_rosso"):
        op.drop_column("marketing_threshold_config", col)
