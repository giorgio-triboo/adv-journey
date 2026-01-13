from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from services.sync_orchestrator import SyncOrchestrator
import logging

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()

def nightly_sync_job():
    """
    Job schedulato per le 00:30 che esegue tutti i sync tramite orchestrator.
    """
    orchestrator = SyncOrchestrator()
    orchestrator.run_all()

def start_scheduler():
    # Schedule nightly sync at 00:30 (30 minutes past midnight)
    scheduler.add_job(nightly_sync_job, CronTrigger(hour=0, minute=30))
    
    scheduler.start()
    logger.info("Scheduler started. Nightly sync pipeline scheduled for 00:30 (via orchestrator).")
