"""
Job autonomo per ingestion dati marketing da Meta.
"""
from sqlalchemy.orm import Session
from database import SessionLocal
from services.integrations.meta_marketing import MetaMarketingService
from models import MetaAccount, MetaCampaign, MetaMarketingData, MetaAd
from datetime import datetime, timedelta, date
from typing import List, Optional
import logging

logger = logging.getLogger(__name__)

def run(db: Session = None) -> dict:
    """
    Esegue il job di ingestion dati marketing Meta.
    
    Returns: dict con statistiche {"accounts_synced": int, "errors": int}
    """
    if db is None:
        db = SessionLocal()
        close_db = True
    else:
        close_db = False
    
    stats = {"accounts_synced": 0, "errors": 0}
    
    try:
        # Get active accounts with sync enabled
        accounts = db.query(MetaAccount).filter(
            MetaAccount.is_active == True,
            MetaAccount.sync_enabled == True
        ).all()
        
        if not accounts:
            logger.info("No active Meta accounts with sync enabled. Skipping Meta Marketing sync.")
            return stats
        
        for account in accounts:
            try:
                logger.info(f"Meta Marketing Sync: Syncing account {account.account_id} ({account.name})...")
                
                # Verifica se ci sono filtri configurati per questo account
                # I filtri possono essere salvati in un campo sync_filters dell'account o recuperati da campagne esistenti
                filters = None
                
                # Prova a recuperare i filtri da una campagna esistente dell'account
                existing_campaign = db.query(MetaCampaign).filter(
                    MetaCampaign.account_id == account.id
                ).first()
                
                if existing_campaign and existing_campaign.sync_filters:
                    filters = existing_campaign.sync_filters.copy()
                    # Se c'è solo un tag filter, non è sufficiente - serve name_pattern
                    if not filters.get('name_pattern'):
                        filters = None
                
                # Se non ci sono filtri disponibili, salta l'account con un warning
                if not filters or not filters.get('name_pattern'):
                    logger.warning(
                        f"Meta Marketing Sync: Skipping account {account.account_id} ({account.name}) - "
                        f"no sync filters configured (name_pattern required). "
                        f"Please configure filters via UI before enabling automatic sync."
                    )
                    continue
                
                # Decripta il token prima di usarlo
                from services.utils.crypto import decrypt_token
                decrypted_token = decrypt_token(account.access_token)
                service = MetaMarketingService(access_token=decrypted_token)
                
                # Sync campaigns structure con filtri
                service.sync_account_campaigns(account.account_id, db, filters=filters)
                
                # Get synced campaigns
                campaigns = db.query(MetaCampaign).join(MetaAccount).filter(
                    MetaAccount.id == account.id,
                    MetaCampaign.is_synced == True
                ).all()
                
                # Fetch and save marketing insights for each campaign
                for campaign in campaigns:
                    try:
                        # Get insights for last 7 days (fino a oggi-1)
                        end_date = date.today() - timedelta(days=1)  # oggi-1 come da richiesta
                        start_date = end_date - timedelta(days=7)
                        
                        # Default metrics per sync automatica: tutte le metriche principali
                        default_metrics = [
                            'spend', 'impressions', 'clicks', 'ctr', 'cpc', 'cpm',
                            'actions', 'action_values', 'cost_per_action_type'
                        ]
                        
                        insights = service.get_insights(
                            account_id=account.account_id,
                            level='ad',
                            start_date=start_date,
                            end_date=end_date,
                            fields=default_metrics
                        )
                        
                        # Save insights to database
                        for insight in insights:
                            ad_id_str = insight.get('ad_id', '')
                            if not ad_id_str:
                                continue
                            
                            # Find ad record
                            ad_record = db.query(MetaAd).filter(MetaAd.ad_id == ad_id_str).first()
                            if not ad_record:
                                continue
                            
                            # Parse date
                            insight_date = datetime.strptime(insight['date'], '%Y-%m-%d')
                            
                            # Check if record exists
                            existing = db.query(MetaMarketingData).filter(
                                MetaMarketingData.ad_id == ad_record.id,
                                MetaMarketingData.date == insight_date
                            ).first()
                            
                            if existing:
                                # Update existing
                                existing.spend = insight['spend']
                                existing.impressions = insight['impressions']
                                existing.clicks = insight['clicks']
                                existing.conversions = insight['conversions']
                                existing.ctr = insight['ctr']
                                existing.cpc = insight['cpc']
                                existing.cpm = insight['cpm']
                                existing.updated_at = datetime.utcnow()
                            else:
                                # Create new
                                marketing_data = MetaMarketingData(
                                    ad_id=ad_record.id,
                                    date=insight_date,
                                    spend=insight['spend'],
                                    impressions=insight['impressions'],
                                    clicks=insight['clicks'],
                                    conversions=insight['conversions'],
                                    ctr=insight['ctr'],
                                    cpc=insight['cpc'],
                                    cpm=insight['cpm'],
                                    cpa=insight.get('cpa', '0,00'),
                                    additional_metrics=insight.get('raw_data', {})
                                )
                                db.add(marketing_data)
                        
                        db.commit()
                        logger.info(f"Synced insights for campaign {campaign.campaign_id}")
                        
                    except Exception as e:
                        logger.error(f"Error syncing insights for campaign {campaign.campaign_id}: {e}", exc_info=True)
                        db.rollback()
                
                stats["accounts_synced"] += 1
                logger.info(f"Meta account {account.account_id} sync completed.")
                
            except Exception as e:
                logger.error(f"Error syncing Meta account {account.account_id}: {e}", exc_info=True)
                stats["errors"] += 1
        
        logger.info(f"Meta Marketing Sync ✅: {stats['accounts_synced']} accounts synced")
        
        # Invia alert se configurato
        from services.utils.alert_sender import send_sync_alert_if_needed
        send_sync_alert_if_needed(db, 'meta_marketing', True, stats)
        
    except Exception as e:
        logger.error(f"Meta Marketing Sync ❌: {e}", exc_info=True)
        stats["errors"] += 1
        
        # Invia alert errore se configurato
        from services.utils.alert_sender import send_sync_alert_if_needed
        send_sync_alert_if_needed(db, 'meta_marketing', False, stats, str(e))
    finally:
        if close_db:
            db.close()
    
    return stats
