"""
Job autonomo per sincronizzazione Ulixe.
Controlla stato per tutte le lead che NON hanno "NO CRM" nel feedback.
"""
from sqlalchemy.orm import Session
from database import SessionLocal
from services.integrations.ulixe import UlixeClient
from models import Lead, StatusCategory, LeadHistory
from datetime import datetime
import logging
import time

logger = logging.getLogger(__name__)

def run(db: Session = None) -> dict:
    """
    Esegue il job di sincronizzazione Ulixe.
    
    Returns: dict con statistiche {"checked": int, "updated": int, "errors": int}
    """
    if db is None:
        db = SessionLocal()
        close_db = True
    else:
        close_db = False
    
    stats = {"checked": 0, "updated": 0, "errors": 0}
    
    try:
        # Get leads that do NOT have "NO CRM" in their status
        leads_to_check = db.query(Lead).filter(
            Lead.status_category != StatusCategory.RIFIUTATO
        ).all()
        
        # Additional filter: exclude leads with "NO CRM" in current_status
        leads_to_check = [l for l in leads_to_check if l.current_status and "NO CRM" not in l.current_status.upper()]
        
        logger.info(f"Ulixe Sync: Checking status for {len(leads_to_check)} leads (excluding NO CRM)...")
        client = UlixeClient()
        
        for lead in leads_to_check:
            if not lead.external_user_id:
                logger.warning(f"Lead {lead.id} has no external_user_id, skipping")
                continue
            
            # Rate limiting: 0.5s tra chiamate
            time.sleep(0.5)
            
            try:
                status_info = client.get_lead_status(lead.external_user_id)
                stats["checked"] += 1
                
                # Check if status changed
                if lead.current_status != status_info.status:
                    old_status = lead.current_status
                    lead.current_status = status_info.status
                    try:
                        lead.status_category = StatusCategory(status_info.category)
                    except ValueError:
                        lead.status_category = StatusCategory.UNKNOWN
                    lead.last_check = status_info.checked_at
                    lead.updated_at = datetime.utcnow()
                    
                    # Save history
                    history = LeadHistory(
                        lead_id=lead.id,
                        status=status_info.status,
                        status_category=lead.status_category,
                        raw_response={"raw": status_info.raw_response},
                        checked_at=status_info.checked_at
                    )
                    db.add(history)
                    stats["updated"] += 1
                    logger.debug(f"Lead {lead.id}: {old_status} -> {status_info.status}")
                
            except Exception as e:
                stats["errors"] += 1
                logger.error(f"Error checking Ulixe for lead {lead.id}: {e}")
        
        db.commit()
        logger.info(f"Ulixe Sync ✅: {stats['checked']} checked, {stats['updated']} updated, {stats['errors']} errors")
        
    except Exception as e:
        logger.error(f"Ulixe Sync ❌: {e}", exc_info=True)
        stats["errors"] += 1
        db.rollback()
    finally:
        if close_db:
            db.close()
    
    return stats
