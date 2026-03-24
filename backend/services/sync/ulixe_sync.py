"""
Job autonomo per sincronizzazione Ulixe.
Controlla stato per lead attive (non rifiutate, non completate).
"""
from sqlalchemy.orm import Session
from database import SessionLocal
from services.integrations.ulixe import UlixeClient
from models import Lead, StatusCategory, LeadHistory
from datetime import datetime, timedelta
import logging
import time

logger = logging.getLogger('services.sync')

def run(db: Session = None) -> dict:
    """
    Esegue il job di sincronizzazione Ulixe.
    
    Logica selezione lead:
    - Include: lead con stato "inviate WS Ulixe" (appena caricate da Magellano)
    - Include: lead con stati Ulixe che NON contengono "RIFIUTATO" o "non interessato"
    - Esclude: lead con status_category = RIFIUTATO
    - Esclude: lead con current_status contenente "RIFIUTATO" o "non interessato"
    - Esclude: lead con current_status = "CRM – ACCETTATO" (esito finale)
    
    Returns: dict con statistiche {"checked": int, "updated": int, "errors": int, "skipped": int}
    """
    if db is None:
        db = SessionLocal()
        close_db = True
    else:
        close_db = False
    
    stats = {"checked": 0, "updated": 0, "errors": 0, "skipped": 0}
    
    try:
        # Verifica che le credenziali Ulixe siano configurate
        from config import settings
        if not settings.ULIXE_USER or not settings.ULIXE_PASSWORD or not settings.ULIXE_WSDL:
            logger.warning("Ulixe Sync: Credenziali non configurate. Sync disabilitata.")
            return stats
        
        # Configurazione gap temporale (predisposta ma non attiva)
        # Quando attivata, evita controlli troppo frequenti (es. 24-48h tra controlli)
        ENABLE_TIME_GAP = False  # Impostare a True per attivare
        TIME_GAP_HOURS = 48  # Gap minimo in ore tra controlli (es. 48h = 2 giorni)
        
        # Query base: escludi lead con status_category = RIFIUTATO
        query = db.query(Lead).filter(
            Lead.status_category != StatusCategory.RIFIUTATO
        )
        
        # Filtro Python per logica più complessa
        all_leads = query.all()
        leads_to_check = []
        
        now = datetime.utcnow()
        
        for lead in all_leads:
            # Skip se non ha external_user_id
            if not lead.external_user_id:
                continue
            
            # Skip se non ha current_status
            if not lead.current_status:
                continue
            
            current_status_upper = lead.current_status.upper()
            
            # Escludi lead con "RIFIUTATO" o "NON INTERESSATO" nel current_status
            if "RIFIUTATO" in current_status_upper or "NON INTERESSATO" in current_status_upper:
                continue
            
            # Escludi lead con esito finale "CRM – ACCETTATO"
            if "CRM – ACCETTATO" in lead.current_status or "CRM-ACCETTATO" in current_status_upper:
                continue
            
            # Include: lead con stato "inviate WS Ulixe" (appena caricate da Magellano)
            if "INVIATE WS ULIXE" in current_status_upper:
                # Controlla gap temporale se attivo
                if ENABLE_TIME_GAP and lead.last_check:
                    time_since_last_check = now - lead.last_check
                    if time_since_last_check < timedelta(hours=TIME_GAP_HOURS):
                        stats["skipped"] += 1
                        continue
                leads_to_check.append(lead)
                continue
            
            # Include: tutte le altre lead (IN_LAVORAZIONE, CRM, CRM - FISSATO, CRM - SVOLTO, etc.)
            # che non sono state già esclusite sopra
            # Controlla gap temporale se attivo
            if ENABLE_TIME_GAP and lead.last_check:
                time_since_last_check = now - lead.last_check
                if time_since_last_check < timedelta(hours=TIME_GAP_HOURS):
                    stats["skipped"] += 1
                    continue
            
            leads_to_check.append(lead)
        
        logger.info(f"Ulixe Sync: Checking status for {len(leads_to_check)} leads (excluded RIFIUTATO, 'non interessato', 'CRM – ACCETTATO')...")
        if ENABLE_TIME_GAP:
            logger.info(f"Ulixe Sync: Time gap check enabled ({TIME_GAP_HOURS}h), skipped {stats['skipped']} leads checked too recently")
        
        client = UlixeClient()
        
        for lead in leads_to_check:
            # Rate limiting: 0.5s tra chiamate
            time.sleep(0.5)
            
            try:
                status_info = client.get_lead_status(lead.external_user_id)
                stats["checked"] += 1
                
                # Aggiorna sempre last_check anche se lo stato non è cambiato
                # (utile per il gap temporale futuro)
                lead.last_check = status_info.checked_at
                
                # Salva sempre stato Ulixe (originale e categoria)
                ulixe_status_category = None
                try:
                    ulixe_status_category = StatusCategory(status_info.category)
                except ValueError:
                    ulixe_status_category = StatusCategory.UNKNOWN
                
                # Aggiorna campi Ulixe
                lead.ulixe_status = status_info.status
                lead.ulixe_status_category = ulixe_status_category
                
                # Check if status changed
                if lead.current_status != status_info.status:
                    old_status = lead.current_status
                    # Aggiorna current_status e status_category (Ulixe ha priorità)
                    lead.current_status = status_info.status
                    lead.status_category = ulixe_status_category
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
                else:
                    # Stato non cambiato, aggiorna solo updated_at per indicare che è stata controllata
                    # Ma aggiorna comunque status_category se necessario
                    if lead.status_category != ulixe_status_category:
                        lead.status_category = ulixe_status_category
                    lead.updated_at = datetime.utcnow()
                
            except Exception as e:
                stats["errors"] += 1
                logger.error(f"Error checking Ulixe for lead {lead.id}: {e}")
        
        db.commit()
        logger.info(f"Ulixe Sync ✅: {stats['checked']} checked, {stats['updated']} updated, {stats['errors']} errors, {stats['skipped']} skipped")
        
        # Invia alert se configurato (canale cron job ulixe_sync)
        from services.utils.alert_sender import send_sync_alert_if_needed
        send_sync_alert_if_needed(db, 'ulixe_sync', True, stats)
        
    except Exception as e:
        logger.error(f"Ulixe Sync ❌: {e}", exc_info=True)
        stats["errors"] += 1
        db.rollback()
        
        # Invia alert errore se configurato
        from services.utils.alert_sender import send_sync_alert_if_needed
        send_sync_alert_if_needed(db, 'ulixe_sync', False, stats, str(e))
    finally:
        if close_db:
            db.close()
    
    return stats
