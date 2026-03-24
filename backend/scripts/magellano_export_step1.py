#!/usr/bin/env python3
"""
Script 1: richiede solo la generazione dell'export Magellano per una campagna
in un intervallo di date, poi termina.

Non attende il completamento dell'export né scarica il file.
Pensato per essere seguito, dopo ~5 minuti, da magellano_export_step2.py.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, datetime, timedelta

from playwright.sync_api import sync_playwright

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.integrations.magellano_automation import MagellanoAutomation  # noqa: E402


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("magellano_export_step1")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Step 1 Magellano: richiesta export (senza download).",
    )
    parser.add_argument(
        "--campaign",
        type=int,
        required=True,
        help="ID campagna Magellano",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=1,
        help="Giorni da recuperare (default: 1, fine = oggi)",
    )
    parser.add_argument(
        "--start",
        default=None,
        help="Data inizio YYYY-MM-DD (override di --days)",
    )
    parser.add_argument(
        "--end",
        default=None,
        help="Data fine YYYY-MM-DD (override di --days)",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Apri il browser visibile (Playwright non headless) per debug",
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
    logger.info("Magellano Export - STEP 1 (enqueue only)")
    logger.info("=" * 60)
    logger.info("Campagna: %s", args.campaign)
    logger.info("Periodo:  %s → %s", start_date, end_date)

    automation = MagellanoAutomation(headless=not args.headed)

    with sync_playwright() as p:
        export_filename_xls = automation.enqueue_export_only(
            p,
            campaign_number=args.campaign,
            start_date=start_date,
            end_date=end_date,
        )

    logger.info("Export richiesto con filename atteso: %s", export_filename_xls)
    logger.info("STEP 1 completato. Eseguire STEP 2 dopo alcuni minuti per il download.")


if __name__ == "__main__":
    main()

