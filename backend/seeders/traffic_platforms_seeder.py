"""Seeder per piattaforme traffico di default"""
from database import SessionLocal
from models import TrafficPlatform
import logging

logger = logging.getLogger(__name__)

DEFAULT_PLATFORMS = [
    {"name": "Meta", "slug": "meta", "display_order": 1},
    {"name": "Google Ads", "slug": "google-ads", "display_order": 2},
    {"name": "TikTok", "slug": "tiktok", "display_order": 3},
    {"name": "Organico", "slug": "organico", "display_order": 4},
    {"name": "Altro", "slug": "altro", "display_order": 99},
]


def seed_traffic_platforms():
    """Crea piattaforme di default se non esistono"""
    db = SessionLocal()
    try:
        existing = db.query(TrafficPlatform).count()
        if existing > 0:
            return
        for p in DEFAULT_PLATFORMS:
            platform = TrafficPlatform(**p)
            db.add(platform)
        db.commit()
        logger.info(f"Creati {len(DEFAULT_PLATFORMS)} piattaforme traffico di default")
    except Exception as e:
        logger.exception("Errore seed traffic platforms: %s", e)
        db.rollback()
    finally:
        db.close()
