"""
Script CLI: match lead Meta Lead Ads → Lead Magellano (ID Meta su Lead).

La logica è in services.sync.meta_leads_from_ads_sync.

Uso (da container backend):

    docker compose exec backend python scripts/sync_meta_leads_from_ads.py
"""

import logging
import os
import sys

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from database import SessionLocal  # noqa: E402
from services.sync.meta_leads_from_ads_sync import sync_meta_leads_from_ads  # noqa: E402

logger = logging.getLogger("scripts.sync_meta_leads_from_ads")
logging.basicConfig(level=logging.INFO)


def main():
    db = SessionLocal()
    try:
        logger.info("Avvio sync lead da Meta Lead Ads...")
        stats = sync_meta_leads_from_ads(db, only_missing=True)
        logger.info("Sync completata. Risultato finale: %s", stats)
    finally:
        db.close()


if __name__ == "__main__":
    main()
