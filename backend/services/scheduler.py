from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from services.sync_orchestrator import SyncOrchestrator
from services.sync.magellano_sync import run as magellano_sync_job
from services.sync.ulixe_sync import run as ulixe_sync_job
from services.sync.meta_marketing_sync import run as meta_marketing_sync_job
from services.sync.meta_conversion_marker import run as meta_conversion_marker_job
from services.sync.meta_conversion_sync import run as meta_conversion_sync_job
from database import SessionLocal
from models import CronJob, IngestionJob, now_rome
import os
import logging

logger = logging.getLogger('services.scheduler')

scheduler = BackgroundScheduler()

def nightly_sync_job():
    """Esegue l'orchestrator completo di sincronizzazione notturna."""
    logger.info("Esecuzione nightly_sync_job (orchestrator completo)...")
    db = SessionLocal()
    job = None
    try:
        job = IngestionJob(
            job_type="orchestrator",
            status="RUNNING",
            params={"source": "scheduler"},
            started_at=now_rome(),
        )
        db.add(job)
        db.commit()

        orchestrator = SyncOrchestrator()
        orchestrator.run_all()

        job.status = "SUCCESS"
        job.completed_at = now_rome()
        job.message = "Nightly orchestrator completed"
        db.commit()
    except Exception as e:
        logger.error("Errore in nightly_sync_job: %s", e, exc_info=True)
        if job:
            job.status = "ERROR"
            job.completed_at = now_rome()
            job.message = str(e)
            db.commit()
        raise
    finally:
        db.close()

def magellano_sync_scheduled():
    """Job schedulato per sincronizzazione Magellano (usa config da CronJob)."""
    logger.info("Esecuzione magellano_sync_scheduled...")
    db = SessionLocal()
    job = None
    try:
        job = IngestionJob(
            job_type="magellano",
            status="RUNNING",
            params={"source": "scheduler"},
            started_at=now_rome(),
        )
        db.add(job)
        db.commit()

        _run_magellano_sync()

        job.status = "SUCCESS"
        job.completed_at = now_rome()
        job.message = "Magellano sync completed"
        db.commit()
    except Exception as e:
        logger.error("Errore in magellano_sync_scheduled: %s", e, exc_info=True)
        if job:
            job.status = "ERROR"
            job.completed_at = now_rome()
            job.message = str(e)
            db.commit()
        raise
    finally:
        db.close()

def ulixe_sync_scheduled():
    """Job schedulato per sincronizzazione Ulixe."""
    logger.info("Esecuzione ulixe_sync_scheduled...")
    db = SessionLocal()
    job = None
    try:
        job = IngestionJob(
            job_type="ulixe",
            status="RUNNING",
            params={"source": "scheduler"},
            started_at=now_rome(),
        )
        db.add(job)
        db.commit()

        ulixe_sync_job()

        job.status = "SUCCESS"
        job.completed_at = now_rome()
        job.message = "Ulixe sync completed"
        db.commit()
    except Exception as e:
        logger.error("Errore in ulixe_sync_scheduled: %s", e, exc_info=True)
        if job:
            job.status = "ERROR"
            job.completed_at = now_rome()
            job.message = str(e)
            db.commit()
        raise
    finally:
        db.close()

def meta_marketing_sync_scheduled():
    """Job schedulato per sincronizzazione Meta Marketing."""
    logger.info("Esecuzione meta_marketing_sync_scheduled...")
    db = SessionLocal()
    job = None
    try:
        job = IngestionJob(
            job_type="meta_marketing",
            status="RUNNING",
            params={"source": "scheduler"},
            started_at=now_rome(),
        )
        db.add(job)
        db.commit()

        meta_marketing_sync_job()

        job.status = "SUCCESS"
        job.completed_at = now_rome()
        job.message = "Meta marketing sync completed"
        db.commit()
    except Exception as e:
        logger.error("Errore in meta_marketing_sync_scheduled: %s", e, exc_info=True)
        if job:
            job.status = "ERROR"
            job.completed_at = now_rome()
            job.message = str(e)
            db.commit()
        raise
    finally:
        db.close()

def meta_conversion_marker_scheduled():
    """Job schedulato per marcatura lead Meta Conversion."""
    logger.info("Esecuzione meta_conversion_marker_scheduled...")
    db = SessionLocal()
    job = None
    try:
        job = IngestionJob(
            job_type="meta_conversion_marker",
            status="RUNNING",
            params={"source": "scheduler"},
            started_at=now_rome(),
        )
        db.add(job)
        db.commit()

        meta_conversion_marker_job()

        job.status = "SUCCESS"
        job.completed_at = now_rome()
        job.message = "Meta conversion marker completed"
        db.commit()
    except Exception as e:
        logger.error("Errore in meta_conversion_marker_scheduled: %s", e, exc_info=True)
        if job:
            job.status = "ERROR"
            job.completed_at = now_rome()
            job.message = str(e)
            db.commit()
        raise
    finally:
        db.close()

def meta_conversion_sync_scheduled():
    """Job schedulato per invio eventi Meta Conversion API."""
    logger.info("Esecuzione meta_conversion_sync_scheduled...")
    db = SessionLocal()
    job = None
    try:
        job = IngestionJob(
            job_type="meta_conversion",
            status="RUNNING",
            params={"source": "scheduler"},
            started_at=now_rome(),
        )
        db.add(job)
        db.commit()

        meta_conversion_sync_job()

        job.status = "SUCCESS"
        job.completed_at = now_rome()
        job.message = "Meta conversion sync completed"
        db.commit()
    except Exception as e:
        logger.error("Errore in meta_conversion_sync_scheduled: %s", e, exc_info=True)
        if job:
            job.status = "ERROR"
            job.completed_at = now_rome()
            job.message = str(e)
            db.commit()
        raise
    finally:
        db.close()


def _run_meta_campaigns_incremental():
    """Esegue sync incrementale meta_campaigns (ieri) via Celery."""
    from tasks.meta_marketing import meta_campaigns_incremental_task

    db = SessionLocal()
    job = None
    try:
        # Crea esplicitamente un IngestionJob con source="scheduler" così da distinguerlo da run manuali.
        job = IngestionJob(
            job_type="meta_campaigns_incremental",
            status="PENDING",
            params={"source": "scheduler"},
        )
        db.add(job)
        db.commit()

        meta_campaigns_incremental_task.delay(job_id=job.id)
        logger.info("meta_campaigns_incremental schedulato via Celery con job_id=%s (source=scheduler)", job.id)
    except Exception as e:
        logger.error("Errore nel pianificare meta_campaigns_incremental: %s", e, exc_info=True)
        if job:
            job.status = "ERROR"
            job.completed_at = now_rome()
            job.message = f"Scheduling failed: {e}"
            db.commit()
        raise
    finally:
        db.close()


def _run_magellano_sync():
    """Esegue sync Magellano con config da CronJob (quali ID campagna Magellano scaricare)."""
    db = SessionLocal()
    try:
        cron_job = db.query(CronJob).filter(CronJob.job_name == "magellano_sync").first()
        config = (cron_job.config or {}) if cron_job else {}

        # Nuova chiave: lista di ID campagna Magellano (es. [190, 199, 423])
        magellano_ids = config.get("magellano_campaign_ids")

        # Backward compatibility: se esistono solo managed_campaign_ids, traducili in ID Magellano.
        if not magellano_ids:
            managed_campaign_ids = config.get("managed_campaign_ids") or []
            if managed_campaign_ids:
                from models import ManagedCampaign

                managed = (
                    db.query(ManagedCampaign)
                    .filter(ManagedCampaign.id.in_(managed_campaign_ids))
                    .all()
                )
                mags: list[int] = []
                for mc in managed:
                    if mc.magellano_ids:
                        for mid in mc.magellano_ids:
                            try:
                                mags.append(int(mid))
                            except (ValueError, TypeError):
                                continue
                # Deduplica mantenendo l'ordine
                seen: set[int] = set()
                magellano_ids = []
                for mid in mags:
                    if mid in seen:
                        continue
                    seen.add(mid)
                    magellano_ids.append(mid)

        magellano_sync_job(
            db=db,
            magellano_campaign_ids=magellano_ids if magellano_ids else None,
        )
    finally:
        db.close()


# Mappa job_type -> callable
CRON_JOB_HANDLERS = {
    "orchestrator": nightly_sync_job,
    "magellano": magellano_sync_scheduled,
    "ulixe": ulixe_sync_scheduled,
    "meta_marketing": meta_marketing_sync_scheduled,
    "meta_conversion_marker": meta_conversion_marker_scheduled,
    "meta_conversion": meta_conversion_sync_scheduled,
    "meta_campaigns_incremental": _run_meta_campaigns_incremental,
}


def _parse_cron_field(field: str, default: str = '*') -> str:
    """Converte campo cron da formato database a formato cron standard."""
    if not field or field == '*':
        return '*'
    
    # Gestione range (es: "0-4" -> "0-4")
    if '-' in field:
        return field
    
    # Gestione giorni della settimana (0=Lunedì in APScheduler)
    # Il database usa 0=Lunedì, che corrisponde al formato APScheduler
    return field

def _build_cron_trigger(cron_job: CronJob) -> CronTrigger:
    """Costruisce un CronTrigger da una configurazione CronJob."""
    day_of_week = _parse_cron_field(cron_job.day_of_week, '*')
    day_of_month = _parse_cron_field(cron_job.day_of_month, '*')
    month = _parse_cron_field(cron_job.month, '*')
    
    # Converti day_of_week se è un range (es: "0-4" -> "mon-fri")
    if day_of_week == '0-4':
        day_of_week = 'mon-fri'
    elif day_of_week == '1-5':
        day_of_week = 'tue-sat'
    elif day_of_week and day_of_week != '*':
        try:
            # Converti numero a giorno (0=Lunedì in APScheduler)
            day_num = int(day_of_week)
            days = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
            if 0 <= day_num <= 6:
                day_of_week = days[day_num]
        except ValueError:
            pass  # Mantieni il valore originale se non è un numero
    
    return CronTrigger(
        hour=cron_job.hour,
        minute=cron_job.minute,
        day_of_week=day_of_week if day_of_week != '*' else None,
        day=day_of_month if day_of_month != '*' else None,
        month=month if month != '*' else None
    )

def start_scheduler():
    """
    Avvia APScheduler e registra tutti i CronJob abilitati presenti a database.
    Usa la tabella cron_jobs per determinare quali job eseguire e con quale schedule.
    """
    logger.info("=" * 80)
    logger.info(
        "Inizializzazione scheduler sincronizzazioni automatiche (pid=%s, hostname=%s)...",
        os.getpid(),
        os.getenv("HOSTNAME", "-"),
    )

    db = SessionLocal()
    try:
        cron_jobs = db.query(CronJob).filter(CronJob.enabled == True).all()  # type: ignore[comparison-overlap]

        if not cron_jobs:
            logger.warning("Nessun CronJob abilitato trovato. Scheduler non registrerà alcun job.")
            return

        # Pulisci eventuali job già registrati per evitare duplicazioni su riavvii
        if scheduler.get_jobs():
            logger.info("Rimozione dei job schedulati esistenti prima di registrare i nuovi...")
            scheduler.remove_all_jobs()

        for cron_job in cron_jobs:
            handler = CRON_JOB_HANDLERS.get(cron_job.job_type)
            if not handler:
                logger.warning(
                    "Nessun handler registrato per job_type='%s' (job_name='%s'). Job ignorato.",
                    cron_job.job_type,
                    cron_job.job_name,
                )
                continue

            trigger = _build_cron_trigger(cron_job)

            try:
                scheduler.add_job(
                    handler,
                    trigger=trigger,
                    id=cron_job.job_name,
                    name=cron_job.description or cron_job.job_name,
                    replace_existing=True,
                )
                logger.info(
                    "Registrato cron job '%s' (type=%s) alle %02d:%02d (dow=%s dom=%s month=%s)",
                    cron_job.job_name,
                    cron_job.job_type,
                    cron_job.hour,
                    cron_job.minute,
                    cron_job.day_of_week,
                    cron_job.day_of_month,
                    cron_job.month,
                )
            except Exception as e:
                logger.error(
                    "Errore registrando il cron job '%s': %s",
                    cron_job.job_name,
                    e,
                    exc_info=True,
                )

        if not scheduler.running:
            scheduler.start()
            logger.info("Scheduler avviato con %d job attivi.", len(scheduler.get_jobs()))
        else:
            logger.info("Scheduler già in esecuzione; job aggiornati.")

        logger.info("=" * 80)
        logger.info("Scheduler pronto. Le sincronizzazioni automatiche sono ATTIVE in base ai CronJob abilitati.")
        logger.info("=" * 80)
    except Exception as e:
        logger.error("Errore durante l'avvio dello scheduler: %s", e, exc_info=True)
    finally:
        db.close()
