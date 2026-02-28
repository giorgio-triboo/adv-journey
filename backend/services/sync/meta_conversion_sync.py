"""
Job autonomo per invio eventi Meta Conversion API.
Invia eventi per lead marcate con to_sync_meta = True.
Recupera token dall'account Meta corretto e adset dal mapping campagna Magellano.
"""
from sqlalchemy.orm import Session
from database import SessionLocal
from services.integrations.meta import MetaService
from services.utils.crypto import decrypt_token
from models import Lead, StatusCategory, MetaAccount, MetaCampaign, MetaAdSet, ManagedCampaign
from config import settings
import logging
import time

logger = logging.getLogger('services.sync')

def _get_meta_account_for_lead(lead: Lead, db: Session) -> tuple:
    """
    Recupera l'account Meta e il token per una lead.
    
    Returns: (MetaAccount, decrypted_token, pixel_id) o (None, None, None) se non trovato
    """
    try:
        # Cerca account Meta tramite correlazione lead -> campaign -> account
        if lead.meta_campaign_id:
            meta_campaign = db.query(MetaCampaign).filter(
                MetaCampaign.campaign_id == lead.meta_campaign_id
            ).first()
            
            if meta_campaign and meta_campaign.account:
                account = meta_campaign.account
                if account.is_active and account.access_token:
                    decrypted_token = decrypt_token(account.access_token)
                    pixel_id = settings.META_PIXEL_ID  # Usa pixel globale per ora
                    return (account, decrypted_token, pixel_id)
        
        # Se non c'è correlazione, usa account condiviso (user_id = NULL) o token di default
        shared_account = db.query(MetaAccount).filter(
            MetaAccount.is_active == True,
            MetaAccount.user_id.is_(None)
        ).first()
        
        if shared_account and shared_account.access_token:
            decrypted_token = decrypt_token(shared_account.access_token)
            pixel_id = settings.META_PIXEL_ID
            return (shared_account, decrypted_token, pixel_id)
        
        # Fallback: token di default da settings
        if settings.META_ACCESS_TOKEN:
            return (None, settings.META_ACCESS_TOKEN, settings.META_PIXEL_ID)
        
        return (None, None, None)
        
    except Exception as e:
        logger.error(f"Error getting Meta account for lead {lead.id}: {e}")
        return (None, None, None)

def _get_dataset_for_lead(lead: Lead, db: Session) -> str:
    """
    Recupera il dataset_id per una lead tramite mapping campagna Magellano -> Dataset Meta.
    Il dataset è separato dal circuito campagna-adset-creatività (che sono per metriche marketing).
    
    Returns: dataset_id o None
    """
    try:
        # Cerca mapping tramite campagna Magellano
        # Nota: magellano_ids è un array JSON, quindi dobbiamo iterare per cercare
        if lead.magellano_campaign_id:
            managed_campaigns = db.query(ManagedCampaign).filter(
                ManagedCampaign.is_active == True
            ).all()
            
            for managed_campaign in managed_campaigns:
                if managed_campaign.magellano_ids:
                    # Verifica se il magellano_campaign_id della lead è nell'array
                    if str(lead.magellano_campaign_id) in [str(mid) for mid in managed_campaign.magellano_ids]:
                        if managed_campaign.meta_dataset_id:
                            return managed_campaign.meta_dataset_id
        
        return None
        
    except Exception as e:
        logger.error(f"Error getting dataset for lead {lead.id}: {e}")
        return None

def run(db: Session = None) -> dict:
    """
    Esegue il job di invio eventi Meta Conversion API.
    Cerca solo lead con to_sync_meta = True.
    
    Returns: dict con statistiche {"events_sent": int, "errors": int, "skipped": int}
    """
    if db is None:
        db = SessionLocal()
        close_db = True
    else:
        close_db = False
    
    stats = {"events_sent": 0, "errors": 0, "skipped": 0}
    
    try:
        # Get leads marcate per sync
        leads_for_events = db.query(Lead).filter(
            Lead.to_sync_meta == True,
            Lead.email.isnot(None)
        ).limit(500).all()  # Limit per evitare troppe chiamate API
        
        logger.info(f"Meta Conversion Sync: Processing {len(leads_for_events)} leads marked for sync...")
        
        for lead in leads_for_events:
            try:
                # Event name unico e stabile per tutti gli aggiornamenti di stato lead
                event_name = "LeadStatus_Update"
                
                # Calcola codici aggregati per Magellano (ingresso) e Ulixe/WS (uscita)
                mag_cat = lead.magellano_status_category
                if mag_cat == StatusCategory.IN_LAVORAZIONE:
                    mag_code = "magellano_approved"
                elif mag_cat == StatusCategory.RIFIUTATO:
                    mag_code = "magellano_refused"
                else:
                    mag_code = "magellano_unknown"
                
                ulixe_cat = lead.ulixe_status_category
                if ulixe_cat == StatusCategory.IN_LAVORAZIONE:
                    ulixe_code = "ulixe_in_lavorazione"
                elif ulixe_cat == StatusCategory.RIFIUTATO:
                    ulixe_code = "ulixe_rifiutato"
                elif ulixe_cat == StatusCategory.CRM:
                    ulixe_code = "ulixe_crm"
                elif ulixe_cat == StatusCategory.FINALE:
                    ulixe_code = "ulixe_finale"
                elif ulixe_cat == StatusCategory.UNKNOWN:
                    ulixe_code = "ulixe_unknown"
                else:
                    ulixe_code = None
                
                # Stato WS aggregato: approved/refused/unknown in base alla categoria Ulixe
                if ulixe_cat in (StatusCategory.IN_LAVORAZIONE, StatusCategory.CRM, StatusCategory.FINALE):
                    ws_status_code = "ws_approved"
                elif ulixe_cat == StatusCategory.RIFIUTATO:
                    ws_status_code = "ws_refused"
                else:
                    ws_status_code = "ws_unknown"
                
                # Sorgente principale dello stato corrente: Ulixe se presente, altrimenti Magellano
                if ulixe_cat is not None:
                    status_source = "ulixe"
                    status_stage = "uscita_ws"
                    status_code = ws_status_code
                else:
                    status_source = "magellano"
                    status_stage = "ingresso_magellano"
                    status_code = mag_code
                
                # Recupera account Meta e token
                account, access_token, pixel_id = _get_meta_account_for_lead(lead, db)
                
                if not access_token:
                    logger.warning(f"Lead {lead.id}: No Meta access token available, skipping")
                    lead.meta_correlation_status = "no_credentials"
                    lead.to_sync_meta = False
                    stats["skipped"] += 1
                    continue
                
                # Recupera dataset_id dal mapping campagna Magellano -> Dataset
                dataset_id = _get_dataset_for_lead(lead, db)
                
                # Se non c'è dataset specifico, usa pixel_id come fallback
                target_id = dataset_id or pixel_id
                
                if not target_id:
                    logger.warning(f"Lead {lead.id}: No dataset_id or pixel_id available, skipping")
                    lead.meta_correlation_status = "no_dataset"
                    lead.to_sync_meta = False
                    stats["skipped"] += 1
                    continue
                
                # Crea servizio Meta con token e dataset_id (o pixel_id come fallback)
                meta_service = MetaService(access_token=access_token, pixel_id=pixel_id, dataset_id=dataset_id)
                
                # Prepara dati aggiuntivi per custom_data
                additional_data = {
                    # Stato canonico (Magellano/Ulixe combinati)
                    "status": lead.current_status,
                    "status_category": lead.status_category.value if hasattr(lead.status_category, 'value') else str(lead.status_category),
                    "status_source": status_source,
                    "status_stage": status_stage,
                    "status_code": status_code,
                    # Ingresso Magellano
                    "magellano_status_code": mag_code,
                    "magellano_status_raw": lead.magellano_status_raw,
                    "magellano_status_category": mag_cat.value if hasattr(mag_cat, 'value') else (str(mag_cat) if mag_cat is not None else None),
                    # Uscita Magellano / WS (Ulixe)
                    "ws_status_code": ws_status_code,
                    "ulixe_status_code": ulixe_code,
                    "ulixe_status_raw": lead.ulixe_status,
                    "ulixe_status_category": ulixe_cat.value if hasattr(ulixe_cat, 'value') else (str(ulixe_cat) if ulixe_cat is not None else None),
                    # Identificativi di correlazione
                    "lead_id": lead.id,
                    "magellano_id": lead.magellano_id,
                    "external_user_id": lead.external_user_id,
                    "meta_campaign_id": lead.meta_campaign_id,
                    "meta_adset_id": lead.meta_adset_id,
                    "meta_ad_id": lead.meta_ad_id,
                    "brand": lead.brand,
                    "campaign_name": lead.campaign_name
                }
                
                # Send event al dataset (adset_id, campaign_id, ad_id sono opzionali per attribuzione metriche)
                result = meta_service.send_custom_event(
                    event_name=event_name,
                    lead_data={
                        "email": lead.email,  # Già hash
                        "phone": lead.phone,  # Già hash
                        "province": lead.province
                    },
                    additional_data=additional_data,
                    adset_id=lead.meta_adset_id,  # Opzionale, per attribuzione metriche marketing
                    campaign_id=lead.meta_campaign_id,  # Opzionale, per attribuzione metriche marketing
                    ad_id=lead.meta_ad_id  # Opzionale, per attribuzione metriche marketing
                )
                
                if result:
                    # Evento inviato con successo
                    stats["events_sent"] += 1
                    lead.to_sync_meta = False
                    lead.last_meta_event_status = lead.status_category.value if hasattr(lead.status_category, 'value') else str(lead.status_category)
                    lead.meta_correlation_status = "found" if dataset_id else "sent_no_dataset"
                    logger.debug(f"Lead {lead.id}: Event {event_name} sent successfully to dataset {dataset_id or 'pixel fallback'}")
                else:
                    # Errore nell'invio
                    stats["errors"] += 1
                    lead.meta_correlation_status = "error"
                    logger.warning(f"Lead {lead.id}: Failed to send event {event_name}")
                
                # Small delay to respect rate limits (best practice Meta: ~1 secondo tra chiamate)
                time.sleep(1.0)
                
            except Exception as e:
                stats["errors"] += 1
                lead.meta_correlation_status = "error"
                logger.error(f"Error sending Meta event for lead {lead.id}: {e}", exc_info=True)
        
        db.commit()
        logger.info(f"Meta Conversion Sync ✅: {stats['events_sent']} events sent, {stats['errors']} errors, {stats['skipped']} skipped")
        
        # Invia alert se configurato
        from services.utils.alert_sender import send_sync_alert_if_needed
        send_sync_alert_if_needed(db, 'meta_conversion', True, stats)
        
    except Exception as e:
        logger.error(f"Meta Conversion Sync ❌: {e}", exc_info=True)
        stats["errors"] += 1
        
        # Invia alert errore se configurato
        from services.utils.alert_sender import send_sync_alert_if_needed
        send_sync_alert_if_needed(db, 'meta_conversion', False, stats, str(e))
    finally:
        if close_db:
            db.close()
    
    return stats
