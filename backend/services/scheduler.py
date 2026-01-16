from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from services.sync_orchestrator import SyncOrchestrator
from database import SessionLocal
from models import CronJob
import logging

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()

def nightly_sync_job():
    """
    Job schedulato che esegue tutti i sync tramite orchestrator.
    """
    orchestrator = SyncOrchestrator()
    orchestrator.run_all()

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
    Avvia lo scheduler leggendo le configurazioni dal database.
    Se non ci sono configurazioni, usa i valori di default.
    """
    db = SessionLocal()
    
    try:
        # Leggi configurazioni cron dal database
        cron_jobs = db.query(CronJob).filter(CronJob.enabled == True).all()
        
        if not cron_jobs:
            # Fallback a configurazione di default se non ci sono job nel database
            logger.warning("Nessuna configurazione cron trovata nel database. Uso configurazione di default (00:30).")
            scheduler.add_job(
                nightly_sync_job, 
                CronTrigger(hour=0, minute=30),
                id='nightly_sync',
                name='Nightly Sync Pipeline',
                misfire_grace_time=3600,
                coalesce=True,
                max_instances=1
            )
        else:
            # Aggiungi job per ogni configurazione abilitata
            for cron_job in cron_jobs:
                try:
                    trigger = _build_cron_trigger(cron_job)
                    
                    # Determina la funzione job in base al tipo
                    if cron_job.job_type == 'orchestrator':
                        job_func = nightly_sync_job
                    else:
                        # Per ora supportiamo solo orchestrator
                        logger.warning(f"Tipo job '{cron_job.job_type}' non supportato. Uso orchestrator.")
                        job_func = nightly_sync_job
                    
                    scheduler.add_job(
                        job_func,
                        trigger,
                        id=cron_job.job_name,
                        name=cron_job.description or cron_job.job_name,
                        misfire_grace_time=3600,
                        coalesce=True,
                        max_instances=1
                    )
                    
                    logger.info(f"Scheduled job '{cron_job.job_name}' at {cron_job.hour:02d}:{cron_job.minute:02d} (enabled: {cron_job.enabled})")
                    
                except Exception as e:
                    logger.error(f"Errore aggiunta job '{cron_job.job_name}': {e}", exc_info=True)
        
    except Exception as e:
        logger.error(f"Errore lettura configurazioni cron dal database: {e}", exc_info=True)
        # Fallback a configurazione di default in caso di errore
        scheduler.add_job(
            nightly_sync_job, 
            CronTrigger(hour=0, minute=30),
            id='nightly_sync',
            name='Nightly Sync Pipeline (fallback)',
            misfire_grace_time=3600,
            coalesce=True,
            max_instances=1
        )
    finally:
        db.close()
    
    scheduler.start()
    logger.info("Scheduler started. Jobs loaded from database.")
    logger.info("Scheduler configured: misfire_grace_time=3600s, coalesce=True, max_instances=1")
