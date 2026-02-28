"""Celery task per recupero dataset Meta."""
from celery_app import celery_app


@celery_app.task(name="tasks.meta_datasets.fetch")
def fetch_datasets_task(job_id: int, account_ids: list, user_id: int):
    """Recupera dataset dagli account Meta selezionati (aggiorna MetaDatasetFetchJob)."""
    # Import inside task to avoid circular import (campaigns.py imports this module)
    from services.api.ui.settings.campaigns import fetch_datasets_background_task
    fetch_datasets_background_task(job_id, account_ids, user_id)
