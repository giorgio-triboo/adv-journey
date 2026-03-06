"""Celery task per sync Magellano."""
from datetime import datetime
from celery_app import celery_app
from database import SessionLocal
from models import SyncLog, IngestionJob, now_rome


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
                job.started_at = now_rome()
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
            # Passa sempre l'ID del job a run_magellano_sync per generare
            # nomi file export univoci per job (evita collisioni con export manuali).
            stats = run_magellano_sync(
                db,
                campaigns,
                start_date,
                end_date,
                job_id=job.id if job else None,
            )

            failed_campaigns = (stats or {}).get("failed_campaigns") or []
            total_errors = int((stats or {}).get("total_errors") or 0)
            has_errors = bool(failed_campaigns or total_errors)
            status_str = "ERROR" if has_errors else "SUCCESS"

            # Registra la sync Magellano avviata dal frontend nel riepilogo ingestion
            sync_log = SyncLog(
                status=status_str,
                details={
                    "magellano": {
                        "type": "frontend_auto",
                        "campaigns": campaigns,
                        "start_date": start_date_str,
                        "end_date": end_date_str,
                        "errors": total_errors,
                        "failed_campaigns": failed_campaigns,
                    }
                },
            )
            db.add(sync_log)

            # Aggiorna eventualmente l'IngestionJob associato
            if job:
                params = job.params or {}
                if stats is not None:
                    params["stats"] = stats
                job.params = params
                job.status = status_str
                job.completed_at = now_rome()
                if has_errors:
                    if failed_campaigns:
                        job.message = (
                            "Sync Magellano completata con errori "
                            f"(campagne fallite: {', '.join(failed_campaigns)})"
                        )
                    else:
                        job.message = "Sync Magellano completata con errori"
                else:
                    if stats and "total_new" in stats and "total_updated" in stats:
                        job.message = (
                            f"Sync Magellano completata "
                            f"({stats['total_new']} nuove, {stats['total_updated']} aggiornate)"
                        )
                    else:
                        job.message = "Sync Magellano completata"

            db.commit()
        except Exception as e:
            # In caso di errore, prova a registrare il fallimento e rilancia
            db.rollback()

            # Aggiorna eventualmente l'IngestionJob associato in errore
            if job:
                job.status = "ERROR"
                job.completed_at = now_rome()
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
