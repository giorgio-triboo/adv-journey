from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from services.sync_orchestrator import SyncOrchestrator
from services.sync.magellano_sync import run as magellano_sync_job
from services.sync.ulixe_sync import run as ulixe_sync_job
from services.sync.meta_marketing_sync import run as meta_marketing_sync_job
from services.sync.meta_conversion_marker import run as meta_conversion_marker_job
from services.sync.meta_conversion_sync import run as meta_conversion_sync_job
from database import SessionLocal
from models import CronJob
import logging

logger = logging.getLogger('services.scheduler')

scheduler = BackgroundScheduler()

def nightly_sync_job():
    """
    DISABILITATO: Job schedulato disabilitato - non esegue più sincronizzazioni automatiche.
    """
    logger.warning("nightly_sync_job chiamato ma DISABILITATO - nessuna sync verrà eseguita")
    return

def magellano_sync_scheduled():
    """DISABILITATO: Job schedulato per sincronizzazione Magellano disabilitato."""
    logger.warning("magellano_sync_scheduled chiamato ma DISABILITATO - nessuna sync verrà eseguita")
    return

def ulixe_sync_scheduled():
    """DISABILITATO: Job schedulato per sincronizzazione Ulixe disabilitato."""
    logger.warning("ulixe_sync_scheduled chiamato ma DISABILITATO - nessuna sync verrà eseguita")
    return

def meta_marketing_sync_scheduled():
    """DISABILITATO: Job schedulato per sincronizzazione Meta Marketing disabilitato."""
    logger.warning("meta_marketing_sync_scheduled chiamato ma DISABILITATO - nessuna sync verrà eseguita")
    return

def meta_conversion_marker_scheduled():
    """DISABILITATO: Job schedulato per marcatura lead Meta Conversion disabilitato."""
    logger.warning("meta_conversion_marker_scheduled chiamato ma DISABILITATO - nessuna sync verrà eseguita")
    return

def meta_conversion_sync_scheduled():
    """DISABILITATO: Job schedulato per invio eventi Meta Conversion API disabilitato."""
    logger.warning("meta_conversion_sync_scheduled chiamato ma DISABILITATO - nessuna sync verrà eseguita")
    return


def _run_meta_campaigns_incremental():
    """Esegue sync incrementale meta_campaigns (ieri) via Celery."""
    from tasks.meta_marketing import meta_campaigns_incremental_task
    meta_campaigns_incremental_task.delay()


def _run_magellano_sync():
    """Esegue sync Magellano con config da CronJob (quale campagne scaricare)."""
    db = SessionLocal()
    try:
        cron_job = db.query(CronJob).filter(CronJob.job_name == "magellano_sync").first()
        config = (cron_job.config or {}) if cron_job else {}
        campaign_ids = config.get("managed_campaign_ids")  # Lista di ManagedCampaign.id
        magellano_sync_job(db=db, managed_campaign_ids=campaign_ids if campaign_ids else None)
    finally:
        db.close()


# Mappa job_type -> callable (usata quando lo scheduler sarà riattivato per inviare job a Celery)
CRON_JOB_HANDLERS = {
    "meta_campaigns_incremental": _run_meta_campaigns_incremental,
    "magellano": _run_magellano_sync,
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
    DISABILITATO: Tutte le sincronizzazioni automatiche sono state disabilitate.
    Questa funzione non avvia più nessuno scheduler o job automatico.
    """
    logger.warning("=" * 80)
    logger.warning("SCHEDULER DISABILITATO - Nessuna sincronizzazione automatica verrà eseguita")
    logger.warning("=" * 80)
    logger.warning("start_scheduler() chiamato ma disabilitato. Nessun job verrà avviato.")
    # NON avviare lo scheduler - tutte le sync sono disabilitate
    return
