"""
Job autonomo per invio eventi Meta Conversion API.
Invia eventi per lead con stati aggiornati.
"""
from sqlalchemy.orm import Session
from database import SessionLocal
from services.integrations.meta import MetaService
from models import Lead, StatusCategory
from datetime import datetime, timedelta
import logging
import time

logger = logging.getLogger(__name__)

def run(db: Session = None) -> dict:
    """
    Esegue il job di invio eventi Meta Conversion API.
    
    Returns: dict con statistiche {"events_sent": int, "errors": int}
    """
    if db is None:
        db = SessionLocal()
        close_db = True
    else:
        close_db = False
    
    stats = {"events_sent": 0, "errors": 0}
    
    try:
        meta_service = MetaService()
        if not meta_service.access_token or not meta_service.pixel_id:
            logger.warning("Meta Conversion API credentials not configured. Skipping events.")
            return stats
        
        # Get leads updated in the last hour (to catch updates from this sync)
        recent_cutoff = datetime.utcnow() - timedelta(hours=1)
        leads_for_events = db.query(Lead).filter(
            Lead.updated_at >= recent_cutoff,
            Lead.email.isnot(None)
        ).limit(100).all()  # Limit to avoid too many API calls
        
        logger.info(f"Meta Conversion Sync: Sending events for {len(leads_for_events)} recently updated leads...")
        
        for lead in leads_for_events:
            try:
                # Map status category to event name
                event_name_map = {
                    StatusCategory.IN_LAVORAZIONE: "LeadStatus_InLavorazione",
                    StatusCategory.CRM: "LeadStatus_CRM",
                    StatusCategory.FINALE: "LeadStatus_Converted",
                    StatusCategory.RIFIUTATO: "LeadStatus_Rejected"
                }
                
                event_name = event_name_map.get(lead.status_category, "LeadStatus_Update")
                
                # Send event
                meta_service.send_custom_event(
                    event_name=event_name,
                    lead_data={
                        "email": lead.email,
                        "phone": lead.phone,
                        "first_name": lead.first_name,
                        "last_name": lead.last_name,
                        "province": lead.province
                    },
                    additional_data={
                        "status": lead.current_status,
                        "status_category": lead.status_category.value if hasattr(lead.status_category, 'value') else str(lead.status_category),
                        "lead_id": lead.id,
                        "magellano_id": lead.magellano_id
                    }
                )
                stats["events_sent"] += 1
                
                # Small delay to respect rate limits
                time.sleep(0.1)
                
            except Exception as e:
                stats["errors"] += 1
                logger.error(f"Error sending Meta event for lead {lead.id}: {e}")
        
        logger.info(f"Meta Conversion Sync ✅: {stats['events_sent']} events sent, {stats['errors']} errors")
        
    except Exception as e:
        logger.error(f"Meta Conversion Sync ❌: {e}", exc_info=True)
        stats["errors"] += 1
    finally:
        if close_db:
            db.close()
    
    return stats
