"""Celery task per sync completo (orchestrator)."""
from celery_app import celery_app
from services.sync_orchestrator import SyncOrchestrator


@celery_app.task(name="tasks.sync.full_pipeline")
def run_full_sync_task():
    """Esegue l'intera pipeline di sync (Magellano, Ulixe, Meta marketing, conversion marker, conversion sync)."""
    orchestrator = SyncOrchestrator()
    return orchestrator.run_all()
