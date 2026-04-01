"""Celery task per sync completo (orchestrator)."""
from celery_app import celery_app
from database import SessionLocal
from models import IngestionJob, now_rome
from services.sync_orchestrator import SyncOrchestrator, pipeline_outcome


@celery_app.task(name="tasks.sync.full_pipeline")
def run_full_sync_task(job_id: int | None = None):
    """Esegue l'intera pipeline di sync (Magellano, Ulixe, Meta marketing, conversion marker, conversion sync)."""
    db = SessionLocal()
    job = None
    try:
        # Se non esiste ancora un IngestionJob, creane uno al volo
        if job_id:
            job = db.query(IngestionJob).filter(IngestionJob.id == job_id).first()
            if job:
                job.status = "RUNNING"
                job.started_at = now_rome()
                db.commit()
        else:
            job = IngestionJob(
                job_type="full_pipeline",
                status="RUNNING",
                params={"source": "unknown"},
            )
            db.add(job)
            db.commit()

        orchestrator = SyncOrchestrator()
        result = orchestrator.run_all()

        if job:
            ordered = [j["name"] for j in orchestrator.jobs]
            st, msg = pipeline_outcome(result, ordered)
            job.status = st
            job.completed_at = now_rome()
            job.message = msg
            db.commit()

        return result
    except Exception as e:
        if job:
            job.status = "ERROR"
            job.completed_at = now_rome()
            job.message = str(e)
            db.commit()
        raise
    finally:
        db.close()
