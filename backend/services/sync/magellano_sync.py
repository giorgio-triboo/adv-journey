"""
Job autonomo per sincronizzazione Magellano.
Recupera lead del giorno precedente e le salva nel database.
"""
from sqlalchemy.orm import Session
from database import SessionLocal
from services.integrations.magellano import MagellanoService
from services.integrations.lead_correlation import LeadCorrelationService
from services.utils.crypto import hash_email_for_meta, hash_phone_for_meta
from models import Lead, StatusCategory
from datetime import datetime, timedelta
import logging

logger = logging.getLogger('services.sync')

def run(db: Session = None) -> dict:
    """
    Esegue il job di sincronizzazione Magellano.
    
    Returns: dict con statistiche {"new": int, "updated": int, "errors": int}
    """
    if db is None:
        db = SessionLocal()
        close_db = True
    else:
        close_db = False
    
    stats = {"new": 0, "updated": 0, "errors": 0}
    
    try:
        from models import ManagedCampaign
        managed_campaigns = db.query(ManagedCampaign).filter(ManagedCampaign.is_active == True).all()
        
        # Estrai tutti gli ID Magellano dagli array JSON
        campaign_ids = []
        for campaign in managed_campaigns:
            if campaign.magellano_ids:
                for mag_id in campaign.magellano_ids:
                    try:
                        campaign_ids.append(int(mag_id))
                    except (ValueError, TypeError):
                        continue
        
        # Rimuovi duplicati mantenendo l'ordine
        campaign_ids = list(dict.fromkeys(campaign_ids))
        
        if not campaign_ids:
            logger.warning("No active campaigns configured. Skipping Magellano sync.")
            return stats
        
        service = MagellanoService()
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=1)  # Yesterday
        
        logger.info(f"Magellano Sync: Fetching leads for campaigns {campaign_ids} ({start_date} to {end_date})")
        leads_data = service.fetch_leads(start_date, end_date, campaign_ids)
        
        correlation_service = LeadCorrelationService()
        new_leads = []
        
        for data in leads_data:
            magellano_id = data.get('magellano_id')
            existing = db.query(Lead).filter(Lead.magellano_id == magellano_id).first()
            
            if not existing:
                # Recupera dati Magellano
                magellano_status_raw = data.get('magellano_status_raw') or data.get('status_raw')
                magellano_status = data.get('magellano_status')
                magellano_status_category = data.get('magellano_status_category')
                
                # Calcola current_status e status_category (priorità: Ulixe > Magellano)
                # Per nuove lead, usa sempre Magellano (Ulixe non ha ancora sincronizzato)
                current_status = magellano_status_raw if magellano_status_raw else magellano_status
                status_category = magellano_status_category if magellano_status_category else StatusCategory.UNKNOWN
                
                new_lead = Lead(
                    magellano_id=magellano_id,
                    external_user_id=data.get('external_user_id'),
                    email=hash_email_for_meta(data.get('email', '')),
                    phone=hash_phone_for_meta(data.get('phone', '')),
                    brand=data.get('brand'),
                    msg_id=data.get('msg_id'),
                    form_id=data.get('form_id'),
                    source=data.get('source'),
                    campaign_name=data.get('campaign_name'),
                    magellano_campaign_id=data.get('magellano_campaign_id'),
                    # Stato Magellano: originale, normalizzato e categoria
                    magellano_status_raw=magellano_status_raw,
                    magellano_status=magellano_status,
                    magellano_status_category=magellano_status_category,
                    payout_status=data.get('payout_status'),
                    is_paid=data.get('is_paid', False),
                    # Facebook/Meta fields from Magellano
                    facebook_ad_name=data.get('facebook_ad_name'),
                    facebook_ad_set=data.get('facebook_ad_set'),
                    facebook_campaign_name=data.get('facebook_campaign_name'),
                    facebook_id=data.get('facebook_id'),  # ID utente Facebook
                    facebook_piattaforma=data.get('facebook_piattaforma'),
                    # Stato corrente (calcolato: preferisce Ulixe se disponibile, altrimenti Magellano)
                    current_status=current_status,
                    status_category=status_category
                )
                db.add(new_lead)
                new_leads.append(new_lead)
                stats["new"] += 1
            else:
                # Update existing lead - aggiorna anche lo stato Magellano
                magellano_status_raw = data.get('magellano_status_raw') or data.get('status_raw')
                magellano_status = data.get('magellano_status')
                magellano_status_category = data.get('magellano_status_category')
                
                # Aggiorna sempre i campi Magellano
                if magellano_status_raw:
                    existing.magellano_status_raw = magellano_status_raw
                if magellano_status:
                    existing.magellano_status = magellano_status
                if magellano_status_category:
                    existing.magellano_status_category = magellano_status_category
                
                # Calcola current_status e status_category (priorità: Ulixe > Magellano)
                # Se Ulixe ha già sincronizzato, mantieni quello, altrimenti usa Magellano
                if existing.ulixe_status:
                    # Ulixe ha priorità - non sovrascrivere
                    pass  # Mantieni current_status e status_category di Ulixe
                else:
                    # Usa Magellano (Ulixe non ha ancora sincronizzato)
                    current_status = magellano_status_raw if magellano_status_raw else magellano_status
                    status_category = magellano_status_category if magellano_status_category else existing.status_category
                    existing.current_status = current_status
                    existing.status_category = status_category
                
                # Aggiorna sempre payout_status e is_paid (anche se None)
                if 'payout_status' in data:
                    existing.payout_status = data.get('payout_status')
                if 'is_paid' in data:
                    existing.is_paid = data.get('is_paid', False)
                
                # Update altri campi se disponibili
                if data.get('campaign_name'):
                    existing.campaign_name = data.get('campaign_name')
                if data.get('facebook_ad_name'):
                    existing.facebook_ad_name = data.get('facebook_ad_name')
                if data.get('facebook_ad_set'):
                    existing.facebook_ad_set = data.get('facebook_ad_set')
                if data.get('facebook_campaign_name'):
                    existing.facebook_campaign_name = data.get('facebook_campaign_name')
                if data.get('facebook_id'):
                    existing.facebook_id = data.get('facebook_id')
                existing.updated_at = datetime.utcnow()
                stats["updated"] += 1
        
        db.commit()
        
        # Correla nuove lead con Meta Marketing
        if new_leads:
            correlation_stats = correlation_service.correlate_batch(new_leads, db)
            logger.info(f"Lead Correlation: {correlation_stats['correlated']} correlated, {correlation_stats['not_found']} not found")
        
        logger.info(f"Magellano Sync ✅: {stats['new']} new, {stats['updated']} updated")
        
        # Invia alert se configurato
        from services.utils.alert_sender import send_sync_alert_if_needed
        send_sync_alert_if_needed(db, 'magellano', True, stats)
        
    except Exception as e:
        logger.error(f"Magellano Sync ❌: {e}", exc_info=True)
        stats["errors"] += 1
        db.rollback()
        
        # Invia alert errore se configurato
        from services.utils.alert_sender import send_sync_alert_if_needed
        send_sync_alert_if_needed(db, 'magellano', False, stats, str(e))
    finally:
        if close_db:
            db.close()
    
    return stats
