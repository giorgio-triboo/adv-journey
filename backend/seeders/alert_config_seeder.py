"""Seeder per configurazioni alert email - default per magellano, ulixe, meta"""
from database import SessionLocal
from models import AlertConfig
import logging

logger = logging.getLogger(__name__)

DEFAULT_ALERTS = [
    {"alert_type": "magellano", "enabled": True, "recipients": [], "on_success": False, "on_error": True},
    {"alert_type": "ulixe", "enabled": True, "recipients": [], "on_success": False, "on_error": True},
    {"alert_type": "ulixe_rcrm_google_sync", "enabled": True, "recipients": [], "on_success": True, "on_error": True},
    {"alert_type": "meta_marketing", "enabled": True, "recipients": [], "on_success": False, "on_error": True},
    {"alert_type": "meta_conversion", "enabled": True, "recipients": [], "on_success": False, "on_error": True},
]


def seed_alert_configs():
    """Crea configurazioni alert di default se non esistono"""
    db = SessionLocal()
    try:
        created = 0
        for data in DEFAULT_ALERTS:
            existing = db.query(AlertConfig).filter(AlertConfig.alert_type == data["alert_type"]).first()
            if not existing:
                config = AlertConfig(**data)
                db.add(config)
                created += 1
        if created > 0:
            db.commit()
            logger.info("Creati %d alert config di default", created)
        else:
            logger.info("Alert config già presenti")
        return True
    except Exception as e:
        logger.exception("Errore seed alert config: %s", e)
        db.rollback()
        return False
    finally:
        db.close()
