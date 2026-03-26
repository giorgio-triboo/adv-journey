"""
Job autonomo per ingestion dati marketing da Meta.
"""
from sqlalchemy.orm import Session
from database import SessionLocal
from services.integrations.meta_marketing import MetaMarketingService
from models import MetaAccount, MetaCampaign, MetaMarketingData, MetaAd, MetaAdSet, now_rome
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


def _normalize_meta_id(raw: object) -> str:
    """
    Normalizza ID Meta in formato stringa semplice.
    """
    if raw is None:
        return ""
    value = str(raw).strip()
    if "/" in value:
        value = value.split("/")[-1]
    for prefix in ("ad_", "adset_", "campaign_", "act_"):
        if value.startswith(prefix):
            value = value.replace(prefix, "", 1)
    return value.strip()


def _group_insights_by_campaign(insights: List[dict]) -> dict[str, List[dict]]:
    grouped: dict[str, List[dict]] = {}
    for insight in insights:
        campaign_id = _normalize_meta_id(insight.get("campaign_id", ""))
        if not campaign_id:
            continue
        grouped.setdefault(campaign_id, []).append(insight)
    return grouped


def _aggregate_insights_by_key(insights: List[dict], key_name: str) -> dict[str, dict]:
    """
    Aggrega metriche base per la chiave indicata (campaign_id/adset_id).
    """
    grouped: dict[str, dict] = {}
    for insight in insights:
        raw_key = _normalize_meta_id(insight.get(key_name, ""))
        if not raw_key:
            continue

        spend = float(insight.get("spend", 0) or 0)
        impressions = int(insight.get("impressions", 0) or 0)
        clicks = int(insight.get("clicks", 0) or 0)
        conversions = int(insight.get("conversions", 0) or 0)

        row = grouped.setdefault(
            raw_key,
            {
                "spend": 0.0,
                "impressions": 0,
                "clicks": 0,
                "conversions": 0,
            },
        )
        row["spend"] += spend
        row["impressions"] += impressions
        row["clicks"] += clicks
        row["conversions"] += conversions

    for _, row in grouped.items():
        impressions = int(row.get("impressions", 0) or 0)
        clicks = int(row.get("clicks", 0) or 0)
        spend = float(row.get("spend", 0) or 0)
        row["ctr"] = (clicks / impressions * 100) if impressions > 0 else 0
        row["cpc"] = (spend / clicks) if clicks > 0 else 0
        row["cpm"] = (spend / impressions * 1000) if impressions > 0 else 0
    return grouped


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
    
    stats = {"accounts_synced": 0, "campaigns_synced": 0, "errors": 0}
    
    try:
        # Auto sync allineata al comportamento manuale:
        # stesso motore di sync con periodo fisso "ieri".
        target_date = now_rome().date() - timedelta(days=1)
        default_metrics = [
            "spend",
            "impressions",
            "clicks",
            "ctr",
            "cpc",
            "cpm",
            "actions",
            "action_values",
            "cost_per_action_type",
        ]

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
                    "target_date": target_date.isoformat(),
                    "skipped": True,
                    "skip_reason": "no_active_accounts_with_sync_enabled",
                },
            )
            return stats
        
        for account in accounts:
            try:
                account_stats = run_manual_sync(
                    db=db,
                    account_id=account.account_id,
                    start_date=target_date,
                    end_date=target_date,
                    metrics=default_metrics,
                )

                stats["campaigns_synced"] += int(account_stats.get("campaigns_synced", 0) or 0)
                account_errors = int(account_stats.get("errors", 0) or 0)
                if account_errors == 0:
                    stats["accounts_synced"] += 1
                else:
                    stats["errors"] += account_errors
                    logger.warning(
                        "Meta Marketing Sync: account %s completed with %s errors",
                        account.account_id,
                        account_errors,
                    )
                
            except Exception as e:
                logger.error(f"Error syncing Meta account {account.account_id}: {e}", exc_info=True)
                stats["errors"] += 1
        
        logger.info(f"Meta Marketing Sync ✅: {stats['accounts_synced']} accounts synced")
        
        # Invia alert se configurato (canale cron job meta_marketing_sync)
        from services.utils.alert_sender import send_sync_alert_if_needed
        send_sync_alert_if_needed(
            db,
            "meta_marketing_sync",
            stats.get("errors", 0) == 0,
            {**stats, "target_date": target_date.isoformat()},
            None if stats.get("errors", 0) == 0 else f"{stats['errors']} errori durante la sync",
        )
        
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
            # Senza filtri non richiamiamo sync_account_campaigns: emetterebbe warning e skip.
            # Usiamo la struttura campagne già presente a DB per la sync marketing.
            logger.info(
                "Meta Marketing Manual Sync: No sync filters found, using existing campaigns in DB for account %s",
                account.account_id,
            )
        
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
        
        # Fetch insights una sola volta per account/range (A)
        logger.info(
            "Meta Marketing Manual Sync: Fetching account-level ad insights once for account %s",
            account.account_id,
        )
        insights = service.get_insights(
            account_id=account.account_id,
            level='ad',
            date_preset=None,  # usa esplicitamente il range richiesto, non last_7d di default
            start_date=start_date,
            end_date=end_date,
            fields=metrics,
        )
        logger.info(
            "Meta Marketing Manual Sync: Retrieved %s ad-level insights for account %s",
            len(insights),
            account.account_id,
        )

        # Aggregazioni da ad-level per validazione tecnica (B)
        campaign_aggregates = _aggregate_insights_by_key(insights, "campaign_id")
        adset_aggregates = _aggregate_insights_by_key(insights, "adset_id")
        logger.info(
            "Meta Marketing Manual Sync: Aggregates built from ad-level insights (campaigns=%s, adsets=%s)",
            len(campaign_aggregates),
            len(adset_aggregates),
        )

        insights_by_campaign = _group_insights_by_campaign(insights)

        # Fetch and save marketing insights for each campaign (using pre-fetched insights)
        for campaign in campaigns:
            try:
                normalized_campaign_id = _normalize_meta_id(campaign.campaign_id)
                campaign_insights = insights_by_campaign.get(normalized_campaign_id, [])
                logger.info(
                    "Meta Marketing Manual Sync: Processing campaign %s with %s pre-fetched insights",
                    campaign.campaign_id,
                    len(campaign_insights),
                )
                
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
                
                for insight in campaign_insights:
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
                        existing.updated_at = now_rome()
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
        if "Meta quota critical" in str(e):
            try:
                from services.utils.alert_sender import send_sync_alert_if_needed
                send_sync_alert_if_needed(
                    db,
                    "meta_marketing_sync",
                    False,
                    {
                        "manual": True,
                        "account_id": account_id,
                        "start_date": start_date.isoformat(),
                        "end_date": end_date.isoformat(),
                        "reason": "meta_quota_critical",
                    },
                    str(e),
                )
            except Exception:
                pass
        logger.error(f"Meta Marketing Manual Sync ❌: {e}", exc_info=True)
        stats["errors"] = 1
    finally:
        if close_db and db:
            try:
                db.close()
            except:
                pass
    
    return stats
