#!/usr/bin/env python3
"""
Script 2: controlla se l'export Magellano richiesto in precedenza è pronto,
scarica il file e processa i dati.

Se l'export non è pronto/non viene trovato come "completed" entro il polling
interno, termina con errore (exit code != 0).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import tempfile
from datetime import date, datetime, timedelta

from playwright.sync_api import sync_playwright

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.integrations.magellano_automation import MagellanoAutomation  # noqa: E402


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("magellano_export_step2")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Step 2 Magellano: verifica export, download e processing.",
    )
    parser.add_argument(
        "--campaign",
        type=int,
        required=True,
        help="ID campagna Magellano (deve corrispondere a quello usato nello step 1)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=1,
        help="Giorni da recuperare (default: 1, fine = oggi). Deve corrispondere allo step 1 se usato.",
    )
    parser.add_argument(
        "--start",
        default=None,
        help="Data inizio YYYY-MM-DD (override di --days, deve corrispondere allo step 1).",
    )
    parser.add_argument(
        "--end",
        default=None,
        help="Data fine YYYY-MM-DD (override di --days, deve corrispondere allo step 1).",
    )
    parser.add_argument(
        "--output-csv",
        default=None,
        help="Percorso file CSV di output (default: leads_campagna_<campaign>.csv nella cwd).",
    )
    return parser.parse_args()


def compute_dates(args: argparse.Namespace) -> tuple[date, date]:
    today = date.today()
    if args.start or args.end:
        start = datetime.strptime(args.start, "%Y-%m-%d").date() if args.start else today - timedelta(days=args.days)
        end = datetime.strptime(args.end, "%Y-%m-%d").date() if args.end else today
    else:
        end = today
        start = end - timedelta(days=args.days)
    return start, end


def main() -> None:
    args = parse_args()
    start_date, end_date = compute_dates(args)

    logger.info("=" * 60)
    logger.info("Magellano Export - STEP 2 (fetch + process)")
    logger.info("=" * 60)
    logger.info("Campagna: %s", args.campaign)
    logger.info("Periodo:  %s → %s", start_date, end_date)

    automation = MagellanoAutomation()

    temp_dir = tempfile.mkdtemp()
    try:
        with sync_playwright() as p:
            df = automation.fetch_export_and_process(
                p,
                campaign_number=args.campaign,
                start_date=start_date,
                end_date=end_date,
                download_dir=temp_dir,
            )

        if df is None:
            logger.error(
                "Export non pronto o non trovato per campagna %s nel periodo %s → %s",
                args.campaign,
                start_date,
                end_date,
            )
            # Exit code diverso da 0 per consentire allo scheduler di considerarlo errore
            sys.exit(1)

        output_csv = args.output_csv or f"leads_campagna_{args.campaign}.csv"
        df.to_csv(output_csv, index=False)
        logger.info("Dati salvati in %s", output_csv)
    finally:
        # Pulisce sempre la directory temporanea
        try:
            import shutil

            shutil.rmtree(temp_dir)
        except Exception:
            logger.warning("Impossibile rimuovere la directory temporanea %s", temp_dir, exc_info=True)


if __name__ == "__main__":
    main()

