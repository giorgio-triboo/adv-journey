"""
Script autonomo per marcare lead da sincronizzare con Meta Conversion API.
Verifica lead con status_category cambiato e imposta to_sync_meta = True.
Questo script può girare durante il giorno (08-18) per preparare le lead per la sync notturna.
"""
from sqlalchemy.orm import Session
from sqlalchemy import cast, String
from database import SessionLocal
from models import Lead, StatusCategory
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

def run(db: Session = None) -> dict:
    """
    Marca lead da sincronizzare con Meta CAPI.
    Verifica se status_category è diverso da last_meta_event_status.
    
    Returns: dict con statistiche {"marked": int, "skipped": int}
    """
    if db is None:
        db = SessionLocal()
        close_db = True
    else:
        close_db = False
    
    stats = {"marked": 0, "skipped": 0}
    
    try:
        # Trova lead dove last_meta_event_status è NULL (prima volta) o diverso da status_category
        # Usa cast per convertire status_category Enum in String per il confronto SQL
        leads_to_check = db.query(Lead).filter(
            (cast(Lead.status_category, String) != Lead.last_meta_event_status) |
            (Lead.last_meta_event_status.is_(None))
        ).filter(
            Lead.email.isnot(None)  # Solo lead con email per matching
        ).all()
        
        logger.info(f"Meta Conversion Marker: Checking {len(leads_to_check)} leads...")
        
        for lead in leads_to_check:
            try:
                # Verifica se lo status è effettivamente cambiato (doppio controllo in Python)
                current_status = lead.status_category.value if hasattr(lead.status_category, 'value') else str(lead.status_category)
                last_status = lead.last_meta_event_status or ""
                
                if current_status != last_status:
                    # Marca per sync
                    lead.to_sync_meta = True
                    stats["marked"] += 1
                    logger.debug(f"Lead {lead.id}: Marked for sync (status: {last_status} -> {current_status})")
                else:
                    stats["skipped"] += 1
                    
            except Exception as e:
                logger.error(f"Error processing lead {lead.id}: {e}")
                stats["skipped"] += 1
        
        db.commit()
        logger.info(f"Meta Conversion Marker ✅: {stats['marked']} marked, {stats['skipped']} skipped")
        
    except Exception as e:
        logger.error(f"Meta Conversion Marker ❌: {e}", exc_info=True)
        if close_db:
            db.rollback()
    finally:
        if close_db:
            db.close()
    
    return stats
