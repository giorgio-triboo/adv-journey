#!/usr/bin/env python3
"""
CLI per bootstrap meta_campaigns (core: services.sync.meta_campaigns_sync.run_bootstrap).
Uso: dalla root backend:
  python run_meta_campaigns_bootstrap.py [--from YYYY-MM-DD] [--to YYYY-MM-DD] [--dry-run]
"""
import argparse
import sys
from datetime import date

from services.sync.meta_campaigns_sync import run_bootstrap


def main():
    parser = argparse.ArgumentParser(description="Bootstrap meta_campaigns da impressions (solo campagne attive).")
    parser.add_argument("--from", dest="from_date", default="2026-01-01", help="Data inizio (YYYY-MM-DD)")
    parser.add_argument("--to", dest="to_date", default=None, help="Data fine (YYYY-MM-DD), default oggi")
    parser.add_argument("--dry-run", action="store_true", help="Solo stampa, nessun write")
    args = parser.parse_args()

    start = date.fromisoformat(args.from_date)
    end = date.fromisoformat(args.to_date) if args.to_date else date.today()
    if start > end:
        print("Errore: from > to", file=sys.stderr)
        sys.exit(1)

    stats = run_bootstrap(start_date=start, end_date=end, db=None, dry_run=args.dry_run)
    print("Bootstrap completato:", stats)
    if stats.get("errors", 0) > 0:
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
