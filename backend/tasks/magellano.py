"""Celery task per sync Magellano."""
from datetime import datetime
from celery_app import celery_app
from database import SessionLocal


@celery_app.task(name="tasks.magellano.sync")
def magellano_sync_task(campaigns: list, start_date_str: str, end_date_str: str):
    """Sync lead da Magellano per le campagne e il periodo indicati."""
    start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
    db = SessionLocal()
    try:
        from services.api.ui.sync import run_magellano_sync
        run_magellano_sync(db, campaigns, start_date, end_date)
    finally:
        db.close()
