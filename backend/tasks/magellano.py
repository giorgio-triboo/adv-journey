"""Celery task per sync Magellano."""
from datetime import datetime
from celery_app import celery_app
from database import SessionLocal
from models import SyncLog, IngestionJob


@celery_app.task(name="tasks.magellano.sync")
def magellano_sync_task(campaigns: list, start_date_str: str, end_date_str: str, job_id: int | None = None):
    """Sync lead da Magellano per le campagne e il periodo indicati."""
    start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
    db = SessionLocal()
    try:
        from services.api.ui.sync import run_magellano_sync

        # Se è stato creato un IngestionJob associato, segna come RUNNING.
        # Se non esiste, creane uno al volo (es. cron interno).
        job = None
        if job_id:
            job = db.query(IngestionJob).filter(IngestionJob.id == job_id).first()
            if job:
                job.status = "RUNNING"
                job.started_at = datetime.utcnow()
                db.commit()
        else:
            job = IngestionJob(
                job_type="magellano",
                status="RUNNING",
                params={
                    "source": "unknown",
                    "campaigns": campaigns,
                    "start_date": start_date_str,
                    "end_date": end_date_str,
                },
            )
            db.add(job)
            db.commit()

        try:
            run_magellano_sync(db, campaigns, start_date, end_date)

            # Registra la sync Magellano avviata dal frontend nel riepilogo ingestion
            sync_log = SyncLog(
                status="SUCCESS",
                details={
                    "magellano": {
                        "type": "frontend_auto",
                        "campaigns": campaigns,
                        "start_date": start_date_str,
                        "end_date": end_date_str,
                        "errors": 0,
                    }
                },
            )
            db.add(sync_log)

            # Aggiorna eventualmente l'IngestionJob associato
            if job:
                job.status = "SUCCESS"
                job.completed_at = datetime.utcnow()
                job.message = "Sync Magellano completata"

            db.commit()
        except Exception as e:
            # In caso di errore, prova a registrare il fallimento e rilancia
            db.rollback()

            # Aggiorna eventualmente l'IngestionJob associato in errore
            if job:
                job.status = "ERROR"
                job.completed_at = datetime.utcnow()
                job.message = str(e)
                db.add(job)
                db.commit()

            try:
                error_details = {
                    "error": str(e),
                    "stats": {
                        "magellano": {
                            "type": "frontend_auto",
                            "campaigns": campaigns,
                            "start_date": start_date_str,
                            "end_date": end_date_str,
                            "errors": 1,
                        }
                    },
                }
                sync_log = SyncLog(status="ERROR", details=error_details)
                db.add(sync_log)
                db.commit()
            except Exception as log_exc:
                import logging
                logger = logging.getLogger("tasks.magellano")
                logger.error(f"Errore salvataggio SyncLog per Magellano Celery: {log_exc}", exc_info=True)

            raise
    finally:
        db.close()
