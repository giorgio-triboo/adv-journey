"""
Job autonomo per sincronizzazione Magellano.
Recupera lead del giorno precedente e le salva nel database.
"""
from sqlalchemy.orm import Session
from database import SessionLocal
from services.integrations.magellano import MagellanoService
from services.integrations.lead_correlation import LeadCorrelationService
from models import Lead, StatusCategory
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

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
        campaign_ids = [int(c.campaign_id) for c in managed_campaigns if c.campaign_id.isdigit()]
        
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
                new_lead = Lead(
                    magellano_id=magellano_id,
                    external_user_id=data.get('external_user_id'),
                    email=data.get('email'),
                    first_name=data.get('first_name'),
                    last_name=data.get('last_name'),
                    phone=data.get('phone'),
                    province=data.get('province'),
                    city=data.get('city'),
                    region=data.get('region'),
                    brand=data.get('brand'),
                    msg_id=data.get('msg_id'),
                    form_id=data.get('form_id'),
                    source=data.get('source'),
                    campaign_name=data.get('campaign_name'),
                    magellano_campaign_id=data.get('magellano_campaign_id'),
                    # Payout status
                    payout_status=data.get('payout_status'),
                    is_paid=data.get('is_paid', False),
                    # Facebook/Meta fields from Magellano
                    facebook_ad_name=data.get('facebook_ad_name'),
                    facebook_ad_set=data.get('facebook_ad_set'),
                    facebook_campaign_name=data.get('facebook_campaign_name'),
                    facebook_id=data.get('facebook_id'),  # ID utente Facebook
                    facebook_piattaforma=data.get('facebook_piattaforma'),
                    current_status='inviate WS Ulixe',
                    status_category=StatusCategory.IN_LAVORAZIONE
                )
                db.add(new_lead)
                new_leads.append(new_lead)
                stats["new"] += 1
            else:
                # Update existing lead if needed
                existing.campaign_name = data.get('campaign_name') or existing.campaign_name
                # Update Facebook fields if changed
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
        
    except Exception as e:
        logger.error(f"Magellano Sync ❌: {e}", exc_info=True)
        stats["errors"] += 1
        db.rollback()
    finally:
        if close_db:
            db.close()
    
    return stats
