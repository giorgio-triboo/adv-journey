#!/usr/bin/env python3
"""
Script per testare sync Magellano in locale con browser visibile (headless=False).
Utile per verificare come vengono selezionate le date nell'UI Magellano.

Uso:
  cd backend && python scripts/run_magellano_sync_debug.py
  cd backend && python scripts/run_magellano_sync_debug.py --headless  # senza finestra browser
"""
import os
import sys
from datetime import date

# Aggiungi backend alla path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal
from services.integrations.magellano import MagellanoService
from services.api.ui.sync import run_magellano_sync

CAMPAIGN_ID = 190
START_DATE = date(2026, 3, 1)
END_DATE = date(2026, 3, 3)


def main():
    headless = "--headless" in sys.argv
    print(f"Magellano Sync Debug - Campagna {CAMPAIGN_ID}, date {START_DATE} - {END_DATE}")
    print(f"Browser: {'headless' if headless else 'VISIBILE (puoi monitorare)'}")
    print("-" * 60)

    db = SessionLocal()
    try:
        run_magellano_sync(db, [CAMPAIGN_ID], START_DATE, END_DATE, headless=headless)
        print("\nSync completato. Dati salvati in DB.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
