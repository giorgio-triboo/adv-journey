"""
Job autonomo per ingestion dati marketing da Meta.
"""
from sqlalchemy.orm import Session
from database import SessionLocal
from services.integrations.meta_marketing import MetaMarketingService
from models import MetaAccount, MetaCampaign, MetaMarketingData, MetaAd, MetaAdSet
from datetime import datetime, timedelta, date
from typing import List, Optional
import logging

logger = logging.getLogger('services.sync')

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
                            insight_date_only = insight_date.date()
                            
                            # Filter: salva solo dati nel range richiesto (last 7 days fino a oggi-1)
                            if insight_date_only < start_date or insight_date_only > end_date:
                                logger.debug(f"Meta Marketing Sync: Skipping insight with date {insight_date_only} (outside range {start_date} - {end_date})")
                                continue
                            
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

def run_manual_sync(db: Session, account_id: str, start_date: date, end_date: date, metrics: List[str]) -> dict:
    """
    Esegue sync manuale per un account specifico con date e metriche personalizzate.
    
    Args:
        db: Database session
        account_id: ID dell'account Meta da sincronizzare
        start_date: Data inizio periodo
        end_date: Data fine periodo
        metrics: Lista di metriche da recuperare
    
    Returns: dict con statistiche {"campaigns_synced": int, "errors": int}
    """
    close_db = False
    stats = {"campaigns_synced": 0, "errors": 0}
    
    try:
        # Trova l'account
        account = db.query(MetaAccount).filter(
            MetaAccount.account_id == account_id,
            MetaAccount.is_active == True
        ).first()
        
        if not account:
            logger.error(f"Meta Marketing Manual Sync: Account {account_id} not found or not active")
            stats["errors"] = 1
            return stats
        
        logger.info(f"Meta Marketing Manual Sync: Syncing account {account.account_id} ({account.name})...")
        logger.info(f"Period: {start_date} - {end_date}, Metrics: {metrics}")
        
        # Decripta il token prima di usarlo
        from services.utils.crypto import decrypt_token
        decrypted_token = decrypt_token(account.access_token)
        service = MetaMarketingService(access_token=decrypted_token)
        
        # Prova a recuperare i filtri da una campagna esistente dell'account
        filters = None
        existing_campaign = db.query(MetaCampaign).filter(
            MetaCampaign.account_id == account.id
        ).first()
        
        if existing_campaign and existing_campaign.sync_filters:
            filters = existing_campaign.sync_filters.copy()
            # Se c'è solo un tag filter, non è sufficiente - serve name_pattern
            if not filters.get('name_pattern'):
                filters = None
        
        # Sync campaigns structure con filtri (se disponibili)
        if filters and filters.get('name_pattern'):
            service.sync_account_campaigns(account.account_id, db, filters=filters)
        else:
            # Se non ci sono filtri, sincronizza tutte le campagne
            logger.info(f"Meta Marketing Manual Sync: No filters found, syncing all campaigns for account {account.account_id}")
            service.sync_account_campaigns(account.account_id, db, filters=None)
        
        # Get campaigns (for manual sync, we use all campaigns, not just is_synced=True)
        # because manual sync should work even without filters
        campaigns = db.query(MetaCampaign).join(MetaAccount).filter(
            MetaAccount.id == account.id
        ).all()
        
        if not campaigns:
            logger.warning(f"Meta Marketing Manual Sync: No campaigns found for account {account.account_id}")
            return stats
        
        logger.info(f"Meta Marketing Manual Sync: Found {len(campaigns)} campaigns for account {account.account_id}")
        
        # Check how many ads exist for these campaigns
        total_ads = db.query(MetaAd).join(MetaAdSet).join(MetaCampaign).join(MetaAccount).filter(
            MetaAccount.id == account.id
        ).count()
        logger.info(f"Meta Marketing Manual Sync: Found {total_ads} total ads for account {account.account_id}")
        
        # Fetch and save marketing insights for each campaign
        for campaign in campaigns:
            try:
                logger.info(f"Meta Marketing Manual Sync: Fetching insights for campaign {campaign.campaign_id}")
                
                insights = service.get_insights(
                    account_id=account.account_id,
                    level='ad',
                    start_date=start_date,
                    end_date=end_date,
                    fields=metrics
                )
                
                logger.info(f"Meta Marketing Manual Sync: Retrieved {len(insights)} insights for campaign {campaign.campaign_id}")
                
                # Get all ad_ids for this campaign to help debug matching issues
                campaign_ad_ids = db.query(MetaAd.ad_id).join(MetaAdSet).filter(
                    MetaAdSet.campaign_id == campaign.id
                ).all()
                campaign_ad_ids_set = {str(ad_id[0]) for ad_id in campaign_ad_ids}
                logger.debug(f"Meta Marketing Manual Sync: Campaign {campaign.campaign_id} has {len(campaign_ad_ids_set)} ads in DB: {list(campaign_ad_ids_set)[:5]}...")
                
                # Save insights to database
                records_created = 0
                records_updated = 0
                records_skipped_no_ad_id = 0
                records_skipped_no_ad_record = 0
                insight_ad_ids = set()
                
                for insight in insights:
                    ad_id_str = insight.get('ad_id', '')
                    if not ad_id_str:
                        records_skipped_no_ad_id += 1
                        continue
                    
                    insight_ad_ids.add(ad_id_str)
                    
                    # Find ad record
                    ad_record = db.query(MetaAd).filter(MetaAd.ad_id == ad_id_str).first()
                    if not ad_record:
                        records_skipped_no_ad_record += 1
                        if records_skipped_no_ad_record <= 3:  # Log first 3 missing ads for debugging
                            logger.warning(f"Meta Marketing Manual Sync: Ad record not found for ad_id {ad_id_str} in campaign {campaign.campaign_id}")
                        continue
                    
                    # Parse date
                    insight_date = datetime.strptime(insight['date'], '%Y-%m-%d')
                    insight_date_only = insight_date.date()
                    
                    # Filter: salva solo dati nel range richiesto
                    if insight_date_only < start_date or insight_date_only > end_date:
                        logger.debug(f"Meta Marketing Manual Sync: Skipping insight with date {insight_date_only} (outside range {start_date} - {end_date})")
                        continue
                    
                    # Check if record exists
                    existing = db.query(MetaMarketingData).filter(
                        MetaMarketingData.ad_id == ad_record.id,
                        MetaMarketingData.date == insight_date
                    ).first()
                    
                    if existing:
                        # Update existing
                        existing.spend = insight.get('spend', existing.spend)
                        existing.impressions = insight.get('impressions', existing.impressions)
                        existing.clicks = insight.get('clicks', existing.clicks)
                        existing.conversions = insight.get('conversions', existing.conversions)
                        existing.ctr = insight.get('ctr', existing.ctr)
                        existing.cpc = insight.get('cpc', existing.cpc)
                        existing.cpm = insight.get('cpm', existing.cpm)
                        existing.updated_at = datetime.utcnow()
                        
                        # Update additional metrics if present
                        if 'raw_data' in insight:
                            existing.additional_metrics = insight.get('raw_data', {})
                        records_updated += 1
                    else:
                        # Create new
                        marketing_data = MetaMarketingData(
                            ad_id=ad_record.id,
                            date=insight_date,
                            spend=insight.get('spend', '0,00'),
                            impressions=insight.get('impressions', 0),
                            clicks=insight.get('clicks', 0),
                            conversions=insight.get('conversions', 0),
                            ctr=insight.get('ctr', '0,00'),
                            cpc=insight.get('cpc', '0,00'),
                            cpm=insight.get('cpm', '0,00'),
                            cpa=insight.get('cpa', '0,00'),
                            additional_metrics=insight.get('raw_data', {})
                        )
                        db.add(marketing_data)
                        records_created += 1
                
                db.commit()
                stats["campaigns_synced"] += 1
                
                # Log matching statistics
                matched_ad_ids = insight_ad_ids & campaign_ad_ids_set
                unmatched_ad_ids = insight_ad_ids - campaign_ad_ids_set
                
                logger.info(
                    f"Meta Marketing Manual Sync: Campaign {campaign.campaign_id} completed - "
                    f"Created: {records_created}, Updated: {records_updated}, "
                    f"Skipped (no ad_id): {records_skipped_no_ad_id}, "
                    f"Skipped (no ad_record): {records_skipped_no_ad_record}, "
                    f"Ad ID matching: {len(matched_ad_ids)} matched, {len(unmatched_ad_ids)} unmatched"
                )
                
                if unmatched_ad_ids and len(unmatched_ad_ids) <= 5:
                    logger.warning(f"Meta Marketing Manual Sync: Unmatched ad_ids in insights: {list(unmatched_ad_ids)}")
                
            except Exception as e:
                logger.error(f"Meta Marketing Manual Sync: Error syncing insights for campaign {campaign.campaign_id}: {e}", exc_info=True)
                db.rollback()
                stats["errors"] += 1
        
        logger.info(f"Meta Marketing Manual Sync ✅: {stats['campaigns_synced']} campaigns synced for account {account.account_id}")
        
    except Exception as e:
        logger.error(f"Meta Marketing Manual Sync ❌: {e}", exc_info=True)
        stats["errors"] = 1
    finally:
        if close_db and db:
            try:
                db.close()
            except:
                pass
    
    return stats
