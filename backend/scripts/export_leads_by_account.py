#!/usr/bin/env python3
"""
Script standalone: esporta tutte le lead di un account pubblicitario Meta in CSV.
Uso: python scripts/export_leads_by_account.py <account_id> [--output file.csv] [--date-from YYYY-MM-DD] [--date-to YYYY-MM-DD]

L'account_id è l'ID dell'account Meta (es. 123456789 o act_123456789).
Le lead vengono filtrate per meta_campaign_id appartenente alle campagne di quell'account.
Opzionale: --date-from / --date-to filtrano per created_at (formato YYYY-MM-DD).
"""
import argparse
import csv
import os
import sys
import logging
from datetime import datetime, time

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from database import SessionLocal
from models import Lead, MetaAccount, MetaCampaign


logger = logging.getLogger("scripts.export_leads_by_account")


# Colonne Lead in ordine (tutti i campi possibili)
LEAD_COLUMNS = [
    "id",
    "magellano_id",
    "external_user_id",
    "email",
    "phone",
    "brand",
    "msg_id",
    "form_id",
    "source",
    "campaign_name",
    "magellano_campaign_id",
    "payout_status",
    "is_paid",
    "magellano_status",
    "magellano_status_raw",
    "magellano_status_category",
    "ulixe_status",
    "ulixe_status_category",
    "facebook_ad_name",
    "facebook_ad_set",
    "facebook_campaign_name",
    "facebook_id",
    "facebook_piattaforma",
    "meta_campaign_id",
    "meta_adset_id",
    "meta_ad_id",
    "magellano_subscr_date",
    "current_status",
    "status_category",
    "last_check",
    "to_sync_meta",
    "last_meta_event_status",
    "meta_correlation_status",
    "created_at",
    "updated_at",
]


def _cell(value):
    """Converte un valore per la scrittura CSV (enum -> value, None -> '', date/datetime -> iso)."""
    if value is None:
        return ""
    if hasattr(value, "value"):  # Enum
        return str(value.value)
    if hasattr(value, "isoformat"):  # date, datetime
        return value.isoformat()
    return str(value)


def main():
    parser = argparse.ArgumentParser(
        description="Esporta tutte le lead di un account pubblicitario Meta in CSV."
    )
    parser.add_argument(
        "account_id",
        help="ID account Meta (es. 123456789 o act_123456789)",
    )
    parser.add_argument(
        "-o", "--output",
        default=None,
        help="File CSV di output (default: leads_<account_id>_<timestamp>.csv)",
    )
    parser.add_argument(
        "--no-header",
        action="store_true",
        help="Non scrivere la riga di intestazione",
    )
    parser.add_argument(
        "--date-from",
        default=None,
        metavar="YYYY-MM-DD",
        help="Data inizio periodo (created_at >= questa data)",
    )
    parser.add_argument(
        "--date-to",
        default=None,
        metavar="YYYY-MM-DD",
        help="Data fine periodo (created_at <= questa data)",
    )
    args = parser.parse_args()

    # Configurazione logging basilare (solo se non già configurato)
    if not logger.handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    logger.info("=== Export leads by account iniziato ===")

    raw_id = args.account_id.strip().lower()
    if raw_id.startswith("act_"):
        account_id = raw_id.replace("act_", "")
    else:
        account_id = raw_id

    logger.info("Arg account_id=%s, normalizzato=%s", args.account_id, account_id)

    db = SessionLocal()
    try:
        # Trova l'account (per account_id Meta)
        account = db.query(MetaAccount).filter(
            MetaAccount.account_id == account_id,
            MetaAccount.is_active == True,
        ).first()

        if not account:
            # Prova con act_ prefix nel DB
            account = db.query(MetaAccount).filter(
                MetaAccount.account_id == f"act_{account_id}",
                MetaAccount.is_active == True,
            ).first()

        if not account:
            print(f"Errore: account '{args.account_id}' non trovato o non attivo.", file=sys.stderr)
            logger.error("Account %s non trovato o non attivo", args.account_id)
            sys.exit(1)

        logger.info("Account DB trovato: id=%s, account_id=%s, name=%s", account.id, account.account_id, account.name)

        # Tutti gli id MetaAccount con lo stesso account_id (stesso account può essere associato a più user)
        account_ids = [
            a.id for a in db.query(MetaAccount).filter(
                MetaAccount.account_id == account.account_id,
                MetaAccount.is_active == True,
            ).all()
        ]
        logger.info("Trovati %d record MetaAccount per lo stesso account_id", len(account_ids))

        # Campagne di questo account
        campaign_ids = [
            row.campaign_id
            for row in db.query(MetaCampaign.campaign_id).filter(
                MetaCampaign.account_id.in_(account_ids)
            ).all()
        ]

        if not campaign_ids:
            print(
                f"Attenzione: nessuna campagna trovata per l'account {account.name} ({account_id}).",
                file=sys.stderr,
            )
            print("Export vuoto.", file=sys.stderr)
            logger.warning("Nessuna campagna trovata per account_id=%s, export vuoto", account.account_id)

        # Parse date filter (YYYY-MM-DD)
        date_from = None
        date_to = None
        for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
            try:
                if args.date_from:
                    date_from = datetime.strptime(args.date_from.strip(), fmt).date()
                    date_from = datetime.combine(date_from, time.min)
                    break
            except ValueError:
                continue
        if args.date_from and date_from is None:
            print(f"Errore: --date-from non valido '{args.date_from}'. Usa YYYY-MM-DD o DD/MM/YYYY.", file=sys.stderr)
            logger.error("Valore --date-from non valido: %s", args.date_from)
            sys.exit(1)
        for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
            try:
                if args.date_to:
                    date_to = datetime.strptime(args.date_to.strip(), fmt).date()
                    date_to = datetime.combine(date_to, time.max)
                    break
            except ValueError:
                continue
        if args.date_to and date_to is None:
            print(f"Errore: --date-to non valido '{args.date_to}'. Usa YYYY-MM-DD o DD/MM/YYYY.", file=sys.stderr)
            sys.exit(1)

        logger.info("Filtri data: date_from=%s, date_to=%s", date_from, date_to)

        # Lead con meta_campaign_id in una delle campagne dell'account (+ filtro date)
        q = db.query(Lead).filter(Lead.meta_campaign_id.in_(campaign_ids))
        if date_from is not None:
            q = q.filter(Lead.created_at >= date_from)
        if date_to is not None:
            q = q.filter(Lead.created_at <= date_to)
        leads = q.order_by(Lead.created_at.desc()).all()
        logger.info("Lead trovate dopo filtri: %d", len(leads))

        out_path = args.output
        if not out_path:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            out_path = os.path.join(PROJECT_ROOT, f"leads_{account_id}_{ts}.csv")

        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, delimiter=",", quoting=csv.QUOTE_MINIMAL)
            if not args.no_header:
                writer.writerow(LEAD_COLUMNS)
            for lead in leads:
                row = [_cell(getattr(lead, col, None)) for col in LEAD_COLUMNS]
                writer.writerow(row)

        print(f"Esportate {len(leads)} lead in {out_path}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
