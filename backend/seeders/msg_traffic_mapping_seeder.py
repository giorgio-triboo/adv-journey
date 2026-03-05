"""Seeder per mapping msg_id -> piattaforma traffico (canali dashboard).

Mappa tutti gli ID messaggio noti a Meta come default, così la vista canali funziona out-of-the-box.
L'utente può poi personalizzare da Settings > Campagne."""
from database import SessionLocal
from models import TrafficPlatform, MsgTrafficMapping
from seeders.campaigns_seeder import MSG_ID_TO_NAME
import logging

logger = logging.getLogger(__name__)


def seed_msg_traffic_mapping():
    """Crea mapping msg_id -> Meta per tutti gli ID noti se non esistono già"""
    db = SessionLocal()
    try:
        meta = db.query(TrafficPlatform).filter(TrafficPlatform.slug == "meta").first()
        if not meta:
            logger.warning("Piattaforma Meta non trovata - esegui prima seed_traffic_platforms")
            return False
        created = 0
        for msg_id in MSG_ID_TO_NAME.keys():
            existing = db.query(MsgTrafficMapping).filter(MsgTrafficMapping.msg_id == msg_id).first()
            if not existing:
                db.add(MsgTrafficMapping(msg_id=msg_id, traffic_platform_id=meta.id))
                created += 1
        if created > 0:
            db.commit()
            logger.info("Creati %d mapping msg_id -> traffic platform", created)
        else:
            logger.info("Mapping msg_id già presenti")
        return True
    except Exception as e:
        logger.exception("Errore seed msg traffic mapping: %s", e)
        db.rollback()
        return False
    finally:
        db.close()
