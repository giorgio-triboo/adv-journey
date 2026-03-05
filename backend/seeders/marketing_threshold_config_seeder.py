"""Seeder per soglie Marketing (margine, scarto) - default se non esiste"""
from decimal import Decimal
from database import SessionLocal
from models import MarketingThresholdConfig
import logging

logger = logging.getLogger(__name__)


def seed_marketing_threshold_config():
    """Crea/configura la riga di default per le soglie Marketing se non esiste"""
    db = SessionLocal()
    try:
        existing = db.query(MarketingThresholdConfig).first()
        if existing:
            logger.info("Soglie Marketing già presenti")
            return True
        config = MarketingThresholdConfig(
            margine_rosso_fino=Decimal("0"),
            margine_verde_da=Decimal("15"),
            scarto_verde_fino=Decimal("5"),
            scarto_rosso_da=Decimal("20"),
            colori_margine_rosso=True,
            colori_margine_verde=True,
            colori_scarto_verde=True,
            colori_scarto_rosso=True,
        )
        db.add(config)
        db.commit()
        logger.info("Creato config soglie Marketing di default")
        return True
    except Exception as e:
        logger.exception("Errore seed marketing threshold config: %s", e)
        db.rollback()
        return False
    finally:
        db.close()
