import os
import sys
import logging

# Ensure project root (/app) is on sys.path when running as a script
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from database import SessionLocal  # type: ignore
from models import Lead  # type: ignore
from services.integrations.lead_correlation import LeadCorrelationService  # type: ignore


def main():
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("scripts.correlate_leads_with_meta")

    db = SessionLocal()
    try:
        logger.info("Starting retroactive Lead ↔ Meta Marketing correlation...")

        # Seleziona tutte le lead che hanno informazioni di campagna Facebook
        leads = db.query(Lead).filter(Lead.facebook_campaign_name.isnot(None)).all()
        logger.info(f"Loaded {len(leads)} leads with facebook_campaign_name for correlation")

        if not leads:
            logger.info("No leads found for correlation. Nothing to do.")
            return

        service = LeadCorrelationService()
        stats = service.correlate_batch(leads, db)

        logger.info(
            "Retroactive correlation completed: "
            f"{stats['correlated']} correlated, {stats['not_found']} not found"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()

