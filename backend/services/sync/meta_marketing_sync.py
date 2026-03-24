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


def _append_ingestion_debug(existing_raw: dict | None, tag: dict) -> dict:
    """
    Aggiunge informazioni di debug (_ingestion_debug) dentro additional_metrics
    senza sovrascrivere eventuali dati esistenti.
    """
    raw = existing_raw or {}
    debug_list = raw.get("_ingestion_debug")
    if not isinstance(debug_list, list):
        debug_list = []
    debug_list.append(tag)
    raw["_ingestion_debug"] = debug_list
    return raw


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
        # Tag di debug comune per questo job automatico
        job_debug_tag = {
            "ingestion_source": "auto_meta_sync",
            "job_type": "meta_marketing",
        }

        # Get active accounts with sync enabled
        accounts = db.query(MetaAccount).filter(
            MetaAccount.is_active == True,
            MetaAccount.sync_enabled == True
        ).all()
        
        if not accounts:
            logger.info("No active Meta accounts with sync enabled. Skipping Meta Marketing sync.")
            from services.utils.alert_sender import send_sync_alert_if_needed

            send_sync_alert_if_needed(
                db,
                "meta_marketing_sync",
                True,
                {
                    **stats,
                    "skipped": True,
                    "skip_reason": "no_active_accounts_with_sync_enabled",
                },
            )
            return stats
        
        for account in accounts:
            try:
                logger.info(
                    "Meta Marketing Sync: Syncing account %s (%s)...",
                    account.account_id,
                    account.name,
                )

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

                # Decripta il token prima di usarlo
                from services.utils.crypto import decrypt_token
                decrypted_token = decrypt_token(account.access_token)
                service = MetaMarketingService(access_token=decrypted_token)
                
                # Sync campaigns structure:
                # - se ci sono filtri con name_pattern → usali
                # - altrimenti, per coerenza con la sync manuale, sincronizza tutte le campagne
                if filters and filters.get('name_pattern'):
                    service.sync_account_campaigns(account.account_id, db, filters=filters)
                else:
                    logger.info(
                        "Meta Marketing Sync: No filters found for account %s, syncing all campaigns",
                        account.account_id,
                    )
                    service.sync_account_campaigns(account.account_id, db, filters=None)
                
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
                            
                            placement_info = {}

                            if existing:
                                # Update existing
                                logger.info(
                                    "[META_SYNC][AUTO][UPDATE] ad_db_id=%s date=%s spend=%s conv=%s",
                                    ad_record.id,
                                    insight_date,
                                    insight.get('spend'),
                                    insight.get('conversions'),
                                )
                                existing.spend = insight['spend']
                                existing.impressions = insight['impressions']
                                existing.clicks = insight['clicks']
                                existing.conversions = insight['conversions']
                                existing.ctr = insight['ctr']
                                existing.cpc = insight['cpc']
                                existing.cpm = insight['cpm']
                                # Aggiorna info piattaforma/position se presenti
                                # publisher_platform non più aggiornato per ridurre complessità ingestion
                                # Aggiorna additional_metrics con tag di debug
                                existing.additional_metrics = _append_ingestion_debug(
                                    existing.additional_metrics,
                                    {**job_debug_tag, **placement_info},
                                )
                                existing.updated_at = datetime.utcnow()
                            else:
                                # Create new
                                logger.info(
                                    "[META_SYNC][AUTO][INSERT] ad_db_id=%s date=%s spend=%s conv=%s",
                                    ad_record.id,
                                    insight_date,
                                    insight.get('spend'),
                                    insight.get('conversions'),
                                )
                                base_raw = insight.get('raw_data', {})
                                base_raw = _append_ingestion_debug(
                                    base_raw,
                                    {**job_debug_tag, **placement_info},
                                )
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
                                    cpa=insight.get('cpa', 0),
                                    additional_metrics=base_raw,
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
        
        # Invia alert se configurato (canale cron job meta_marketing_sync)
        from services.utils.alert_sender import send_sync_alert_if_needed
        send_sync_alert_if_needed(db, 'meta_marketing_sync', True, stats)
        
    except Exception as e:
        logger.error(f"Meta Marketing Sync ❌: {e}", exc_info=True)
        stats["errors"] += 1
        
        # Invia alert errore se configurato
        from services.utils.alert_sender import send_sync_alert_if_needed
        send_sync_alert_if_needed(db, 'meta_marketing_sync', False, stats, str(e))
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
        # Tag di debug comune per questo job manuale
        job_debug_tag = {
            "ingestion_source": "manual_meta_sync",
            "job_type": "meta_marketing",
            "account_id": account_id,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        }

        # Trova l'account
        account = db.query(MetaAccount).filter(
            MetaAccount.account_id == account_id,
            MetaAccount.is_active == True
        ).first()
        
        if not account:
            logger.error(f"Meta Marketing Manual Sync: Account {account_id} not found or not active")
            stats["errors"] = 1
            return stats
        
        logger.info(
            "Meta Marketing Manual Sync: Syncing account %s (%s)...",
            account.account_id,
            account.name,
        )
        logger.info("Period: %s - %s, Metrics: %s", start_date, end_date, metrics)
        
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

        # Se non esiste nessun MetaAd per l'account, la sync marketing non può produrre dati coerenti
        # e non ha senso segnalarla come completata con 0 record: alziamo un errore esplicito.
        if total_ads == 0:
            raise RuntimeError(
                f"Meta Marketing Manual Sync: no MetaAd records found in DB for account {account.account_id}. "
                f"Run campaigns/adsets/ads sync before marketing sync."
            )
        
        # Fetch and save marketing insights for each campaign
        for campaign in campaigns:
            try:
                logger.info(f"Meta Marketing Manual Sync: Fetching insights for campaign {campaign.campaign_id}")
                
                insights = service.get_insights(
                    account_id=account.account_id,
                    level='ad',
                    date_preset=None,  # usa esplicitamente il range richiesto, non last_7d di default
                    start_date=start_date,
                    end_date=end_date,
                    fields=metrics,
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
                    
                    placement_info = {}

                    if existing:
                        # Update existing
                        logger.info(
                            "[META_SYNC][MANUAL][UPDATE] ad_db_id=%s date=%s spend=%s conv=%s",
                            ad_record.id,
                            insight_date,
                            insight.get('spend'),
                            insight.get('conversions'),
                        )
                        existing.spend = insight.get('spend', existing.spend)
                        existing.impressions = insight.get('impressions', existing.impressions)
                        existing.clicks = insight.get('clicks', existing.clicks)
                        existing.conversions = insight.get('conversions', existing.conversions)
                        existing.ctr = insight.get('ctr', existing.ctr)
                        existing.cpc = insight.get('cpc', existing.cpc)
                        existing.cpm = insight.get('cpm', existing.cpm)
                        # publisher_platform non più aggiornato per ridurre complessità ingestion
                        # Update additional metrics if present + debug tag
                        base_raw = insight.get('raw_data', existing.additional_metrics)
                        existing.additional_metrics = _append_ingestion_debug(
                            base_raw,
                            {**job_debug_tag, **placement_info},
                        )
                        existing.updated_at = datetime.utcnow()
                        records_updated += 1
                    else:
                        # Create new
                        logger.info(
                            "[META_SYNC][MANUAL][INSERT] ad_db_id=%s date=%s spend=%s conv=%s",
                            ad_record.id,
                            insight_date,
                            insight.get('spend'),
                            insight.get('conversions'),
                        )
                        base_raw = insight.get('raw_data', {})
                        base_raw = _append_ingestion_debug(
                            base_raw,
                            {**job_debug_tag, **placement_info},
                        )
                        marketing_data = MetaMarketingData(
                            ad_id=ad_record.id,
                            date=insight_date,
                            spend=insight.get('spend', 0),
                            impressions=insight.get('impressions', 0),
                            clicks=insight.get('clicks', 0),
                            conversions=insight.get('conversions', 0),
                            ctr=insight.get('ctr', 0),
                            cpc=insight.get('cpc', 0),
                            cpm=insight.get('cpm', 0),
                            cpa=insight.get('cpa', 0),
                            additional_metrics=base_raw,
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
