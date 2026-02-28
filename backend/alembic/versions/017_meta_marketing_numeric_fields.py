"""change meta_marketing_data numeric fields to DECIMAL

Revision ID: 017_meta_marketing_numeric
Revises: 016_meta_fetch_jobs
Create Date: 2026-02-23 20:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from decimal import Decimal, InvalidOperation


# revision identifiers, used by Alembic.
revision: str = "017_meta_marketing_numeric"
down_revision: Union[str, None] = "017_sessions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _parse_amount(val) -> Union[Decimal, None]:
    """Parsa stringhe importo sia in formato EU (1.360,71) sia US (1360.71) in Decimal."""
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None
    # Caso: sia '.' che ',' -> assume '.' = migliaia, ',' = decimale  (es. 1.360,71)
    if "." in s and "," in s:
        s = s.replace(".", "").replace(",", ".")
    # Solo virgola -> virgola decimale
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        # In caso di valori sporchi, meglio restituire None che rompere la migrazione
        return None


def upgrade() -> None:
    # Aggiungi nuove colonne DECIMAL temporanee
    op.add_column(
        "meta_marketing_data",
        sa.Column("spend_num", sa.Numeric(18, 4), nullable=True),
    )
    op.add_column(
        "meta_marketing_data",
        sa.Column("ctr_num", sa.Numeric(10, 4), nullable=True),
    )
    op.add_column(
        "meta_marketing_data",
        sa.Column("cpc_num", sa.Numeric(18, 4), nullable=True),
    )
    op.add_column(
        "meta_marketing_data",
        sa.Column("cpm_num", sa.Numeric(18, 4), nullable=True),
    )
    op.add_column(
        "meta_marketing_data",
        sa.Column("cpa_num", sa.Numeric(18, 4), nullable=True),
    )

    conn = op.get_bind()

    meta_marketing_data = sa.table(
        "meta_marketing_data",
        sa.column("id", sa.Integer),
        sa.column("spend", sa.String),
        sa.column("ctr", sa.String),
        sa.column("cpc", sa.String),
        sa.column("cpm", sa.String),
        sa.column("cpa", sa.String),
        sa.column("spend_num", sa.Numeric),
        sa.column("ctr_num", sa.Numeric),
        sa.column("cpc_num", sa.Numeric),
        sa.column("cpm_num", sa.Numeric),
        sa.column("cpa_num", sa.Numeric),
    )

    # Leggi tutte le righe esistenti e convertili
    rows = list(
        conn.execute(
            sa.select(
                meta_marketing_data.c.id,
                meta_marketing_data.c.spend,
                meta_marketing_data.c.ctr,
                meta_marketing_data.c.cpc,
                meta_marketing_data.c.cpm,
                meta_marketing_data.c.cpa,
            )
        )
    )

    for row in rows:
        spend_dec = _parse_amount(row.spend)
        ctr_dec = _parse_amount(row.ctr)
        cpc_dec = _parse_amount(row.cpc)
        cpm_dec = _parse_amount(row.cpm)
        cpa_dec = _parse_amount(row.cpa)

        conn.execute(
            meta_marketing_data.update()
            .where(meta_marketing_data.c.id == row.id)
            .values(
                spend_num=spend_dec,
                ctr_num=ctr_dec,
                cpc_num=cpc_dec,
                cpm_num=cpm_dec,
                cpa_num=cpa_dec,
            )
        )

    # Rimuovi le vecchie colonne stringa
    op.drop_column("meta_marketing_data", "spend")
    op.drop_column("meta_marketing_data", "ctr")
    op.drop_column("meta_marketing_data", "cpc")
    op.drop_column("meta_marketing_data", "cpm")
    op.drop_column("meta_marketing_data", "cpa")

    # Rinomina le colonne numeriche a nomi definitivi
    op.alter_column(
        "meta_marketing_data",
        "spend_num",
        new_column_name="spend",
        existing_type=sa.Numeric(18, 4),
    )
    op.alter_column(
        "meta_marketing_data",
        "ctr_num",
        new_column_name="ctr",
        existing_type=sa.Numeric(10, 4),
    )
    op.alter_column(
        "meta_marketing_data",
        "cpc_num",
        new_column_name="cpc",
        existing_type=sa.Numeric(18, 4),
    )
    op.alter_column(
        "meta_marketing_data",
        "cpm_num",
        new_column_name="cpm",
        existing_type=sa.Numeric(18, 4),
    )
    op.alter_column(
        "meta_marketing_data",
        "cpa_num",
        new_column_name="cpa",
        existing_type=sa.Numeric(18, 4),
    )


def downgrade() -> None:
    # Per il downgrade, ripristina colonne stringa dai DECIMAL
    op.add_column(
        "meta_marketing_data",
        sa.Column("spend_str", sa.String(), nullable=True),
    )
    op.add_column(
        "meta_marketing_data",
        sa.Column("ctr_str", sa.String(), nullable=True),
    )
    op.add_column(
        "meta_marketing_data",
        sa.Column("cpc_str", sa.String(), nullable=True),
    )
    op.add_column(
        "meta_marketing_data",
        sa.Column("cpm_str", sa.String(), nullable=True),
    )
    op.add_column(
        "meta_marketing_data",
        sa.Column("cpa_str", sa.String(), nullable=True),
    )

    conn = op.get_bind()

    meta_marketing_data = sa.table(
        "meta_marketing_data",
        sa.column("id", sa.Integer),
        sa.column("spend", sa.Numeric),
        sa.column("ctr", sa.Numeric),
        sa.column("cpc", sa.Numeric),
        sa.column("cpm", sa.Numeric),
        sa.column("cpa", sa.Numeric),
        sa.column("spend_str", sa.String),
        sa.column("ctr_str", sa.String),
        sa.column("cpc_str", sa.String),
        sa.column("cpm_str", sa.String),
        sa.column("cpa_str", sa.String),
    )

    rows = list(
        conn.execute(
            sa.select(
                meta_marketing_data.c.id,
                meta_marketing_data.c.spend,
                meta_marketing_data.c.ctr,
                meta_marketing_data.c.cpc,
                meta_marketing_data.c.cpm,
                meta_marketing_data.c.cpa,
            )
        )
    )

    for row in rows:
        conn.execute(
            meta_marketing_data.update()
            .where(meta_marketing_data.c.id == row.id)
            .values(
                spend_str=str(row.spend) if row.spend is not None else None,
                ctr_str=str(row.ctr) if row.ctr is not None else None,
                cpc_str=str(row.cpc) if row.cpc is not None else None,
                cpm_str=str(row.cpm) if row.cpm is not None else None,
                cpa_str=str(row.cpa) if row.cpa is not None else None,
            )
        )

    op.drop_column("meta_marketing_data", "spend")
    op.drop_column("meta_marketing_data", "ctr")
    op.drop_column("meta_marketing_data", "cpc")
    op.drop_column("meta_marketing_data", "cpm")
    op.drop_column("meta_marketing_data", "cpa")

    op.alter_column("meta_marketing_data", "spend_str", new_column_name="spend")
    op.alter_column("meta_marketing_data", "ctr_str", new_column_name="ctr")
    op.alter_column("meta_marketing_data", "cpc_str", new_column_name="cpc")
    op.alter_column("meta_marketing_data", "cpm_str", new_column_name="cpm")
    op.alter_column("meta_marketing_data", "cpa_str", new_column_name="cpa")

