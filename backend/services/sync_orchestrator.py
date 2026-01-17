"""
Orchestrator per gestire l'esecuzione sequenziale di tutti i job di sincronizzazione.
Permette di aggiungere facilmente nuove piattaforme in futuro.
"""
from database import SessionLocal
from models import SyncLog
from services.sync.magellano_sync import run as magellano_sync_job
from services.sync.ulixe_sync import run as ulixe_sync_job
from services.sync.meta_marketing_sync import run as meta_marketing_sync_job
from services.sync.meta_conversion_marker import run as meta_conversion_marker_job
from services.sync.meta_conversion_sync import run as meta_conversion_sync_job
from datetime import datetime
import logging

logger = logging.getLogger('services.sync_orchestrator')

class SyncOrchestrator:
    """
    Orchestrator che gestisce l'esecuzione sequenziale di tutti i sync job.
    """
    
    def __init__(self):
        self.jobs = [
            {
                "name": "magellano",
                "job": magellano_sync_job,
                "description": "Magellano - Recupera e salva dati"
            },
            {
                "name": "ulixe",
                "job": ulixe_sync_job,
                "description": "Ulixe - Sync per lead senza NO CRM"
            },
            {
                "name": "meta_marketing",
                "job": meta_marketing_sync_job,
                "description": "Meta Marketing - Ingestion dati marketing"
            },
            {
                "name": "meta_conversion_marker",
                "job": meta_conversion_marker_job,
                "description": "Meta Conversion Marker - Marca lead da sincronizzare"
            },
            {
                "name": "meta_conversion",
                "job": meta_conversion_sync_job,
                "description": "Meta Conversion API - Invia eventi stati aggiornati"
            }
        ]
    
    def run_all(self) -> dict:
        """
        Esegue tutti i job in sequenza.
        
        Returns: dict con statistiche aggregate di tutti i job
        """
        logger.info("=" * 80)
        logger.info("Starting Sync Orchestrator - Sequential Pipeline")
        logger.info("=" * 80)
        
        db = SessionLocal()
        sync_log = SyncLog(status="RUNNING", details={"started_at": datetime.utcnow().isoformat()})
        db.add(sync_log)
        db.commit()
        
        all_stats = {}
        
        try:
            # Esegui tutti i job in sequenza usando la stessa sessione DB
            for job_config in self.jobs:
                job_name = job_config["name"]
                job_func = job_config["job"]
                job_desc = job_config["description"]
                
                logger.info(f"[{job_name.upper()}] {job_desc}...")
                
                try:
                    # Esegui job con la stessa sessione DB
                    stats = job_func(db=db)
                    all_stats[job_name] = stats
                    logger.info(f"[{job_name.upper()}] ✅ Completed")
                except Exception as e:
                    logger.error(f"[{job_name.upper()}] ❌ Failed: {e}", exc_info=True)
                    all_stats[job_name] = {"errors": 1}
            
            # Update sync log
            sync_log.status = "SUCCESS"
            sync_log.completed_at = datetime.utcnow()
            sync_log.details = all_stats
            db.commit()
            
            logger.info("=" * 80)
            logger.info("✅ Sync Orchestrator completed successfully!")
            self._log_summary(all_stats)
            logger.info("=" * 80)
            
        except Exception as e:
            logger.error(f"❌ Sync Orchestrator failed: {e}", exc_info=True)
            sync_log.status = "ERROR"
            sync_log.completed_at = datetime.utcnow()
            sync_log.details = {"error": str(e), "stats": all_stats}
            db.commit()
        finally:
            db.close()
        
        return all_stats
    
    def _log_summary(self, stats: dict):
        """Log delle statistiche aggregate."""
        if "magellano" in stats:
            m = stats["magellano"]
            logger.info(f"  Magellano: {m.get('new', 0)} new, {m.get('updated', 0)} updated")
        
        if "ulixe" in stats:
            u = stats["ulixe"]
            logger.info(f"  Ulixe: {u.get('checked', 0)} checked, {u.get('updated', 0)} updated")
        
        if "meta_marketing" in stats:
            mm = stats["meta_marketing"]
            logger.info(f"  Meta Marketing: {mm.get('accounts_synced', 0)} accounts synced")
        
        if "meta_conversion_marker" in stats:
            mcm = stats["meta_conversion_marker"]
            logger.info(f"  Meta Conversion Marker: {mcm.get('marked', 0)} marked")
        
        if "meta_conversion" in stats:
            mc = stats["meta_conversion"]
            logger.info(f"  Meta Conversion: {mc.get('events_sent', 0)} events sent, {mc.get('errors', 0)} errors")
    
    def add_job(self, name: str, job_func, description: str):
        """
        Aggiunge un nuovo job all'orchestrator.
        Utile per aggiungere nuove piattaforme in futuro.
        """
        self.jobs.append({
            "name": name,
            "job": job_func,
            "description": description
        })
        logger.info(f"Added new sync job: {name} - {description}")
