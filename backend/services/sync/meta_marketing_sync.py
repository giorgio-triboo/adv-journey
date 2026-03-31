"""
Job autonomo per ingestion dati marketing da Meta.
"""
from sqlalchemy.orm import Session
from database import SessionLocal
from services.integrations.meta_marketing import MetaMarketingService, META_INSIGHTS_PAGE_LIMIT
from models import (
    MetaAccount,
    MetaCampaign,
    MetaMarketingData,
    MetaMarketingPlacement,
    MetaAd,
    MetaAdSet,
    now_rome,
)
from datetime import datetime, timedelta, date
from typing import List, Optional, Set
import logging

logger = logging.getLogger('services.sync')


def _meta_ad_for_account(
    db: Session,
    account: MetaAccount,
    ad_id_str: str,
) -> Optional[MetaAd]:
    """Risolve MetaAd per stringa ad_id limitato all'account (join campagna)."""
    if not ad_id_str or not str(ad_id_str).strip():
        return None
    aid = str(ad_id_str).strip()
    return (
        db.query(MetaAd)
        .join(MetaAdSet, MetaAd.adset_id == MetaAdSet.id)
        .join(MetaCampaign, MetaAdSet.campaign_id == MetaCampaign.id)
        .filter(MetaCampaign.account_id == account.id)
        .filter(MetaAd.ad_id == aid)
        .first()
    )


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


def _aggregate_insights_merge_into(
    grouped: dict[str, dict],
    insights: List[dict],
    key_name: str,
) -> None:
    """Aggiorna grouped con le righe insights (senza ricalcolare ctr/cpc/cpm)."""
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


def _aggregate_insights_finalize_derived_metrics(grouped: dict[str, dict]) -> None:
    for _, row in grouped.items():
        impressions = int(row.get("impressions", 0) or 0)
        clicks = int(row.get("clicks", 0) or 0)
        spend = float(row.get("spend", 0) or 0)
        row["ctr"] = (clicks / impressions * 100) if impressions > 0 else 0
        row["cpc"] = (spend / clicks) if clicks > 0 else 0
        row["cpm"] = (spend / impressions * 1000) if impressions > 0 else 0


def _aggregate_insights_by_key(insights: List[dict], key_name: str) -> dict[str, dict]:
    """
    Aggrega metriche base per la chiave indicata (campaign_id/adset_id).
    """
    grouped: dict[str, dict] = {}
    _aggregate_insights_merge_into(grouped, insights, key_name)
    _aggregate_insights_finalize_derived_metrics(grouped)
    return grouped


def _merge_insight_rows_into_groups(groups: dict[tuple[str, str], dict], rows: List[dict]) -> None:
    """Somma metriche per (ad_id, date) dentro groups (merge incrementale per pagina)."""
    for r in rows:
        aid = (r.get("ad_id") or "").strip()
        d = (r.get("date") or "").strip()
        if not aid or not d:
            continue
        key = (aid, d)
        if key not in groups:
            groups[key] = {
                "ad_id": aid,
                "date": d,
                "campaign_id": r.get("campaign_id", ""),
                "adset_id": r.get("adset_id", ""),
                "spend": 0.0,
                "impressions": 0,
                "clicks": 0,
                "conversions": 0,
                "_parts": 0,
            }
        g = groups[key]
        g["_parts"] += 1
        try:
            g["spend"] += float(str(r.get("spend", 0) or 0))
        except (TypeError, ValueError):
            pass
        g["impressions"] += int(r.get("impressions", 0) or 0)
        g["clicks"] += int(r.get("clicks", 0) or 0)
        g["conversions"] += int(r.get("conversions", 0) or 0)


def _finalize_ad_day_merge_groups(groups: dict[tuple[str, str], dict]) -> List[dict]:
    """Converte groups in lista con ctr/cpc/cpm dai totali."""
    out: List[dict] = []
    for g in groups.values():
        spend = float(g["spend"])
        im = int(g["impressions"])
        cl = int(g["clicks"])
        ctr = (cl / im * 100) if im > 0 else 0.0
        cpc = (spend / cl) if cl > 0 else 0.0
        cpm = (spend / im * 1000) if im > 0 else 0.0
        out.append(
            {
                "date": g["date"],
                "campaign_id": g["campaign_id"],
                "adset_id": g["adset_id"],
                "ad_id": g["ad_id"],
                "impressions": im,
                "clicks": cl,
                "conversions": g["conversions"],
                "ctr": f"{ctr:.2f}",
                "spend": f"{spend:.2f}",
                "cpc": f"{cpc:.2f}",
                "cpm": f"{cpm:.2f}",
                "cpa": "0.00",
                "publisher_platform": "",
                "platform_position": "",
                "raw_data": {
                    "_aggregated_from_breakdown": True,
                    "breakdown_row_count": g["_parts"],
                },
            }
        )
    return out


def _merge_insight_rows_by_ad_day(rows: List[dict]) -> List[dict]:
    """
    Somma metriche per (ad_id, date) — usato quando la risposta Insights include più righe
    (breakdown per placement). Ricava ctr/cpc/cpm dai totali come in get_insights.
    """
    groups: dict[tuple[str, str], dict] = {}
    _merge_insight_rows_into_groups(groups, rows)
    return _finalize_ad_day_merge_groups(groups)


def _upsert_placement_row(
    db: Session,
    insight: dict,
    ad_record: MetaAd,
    insight_date: datetime,
    start_date: date,
    end_date: date,
    job_debug_tag: dict,
) -> str:
    """Persiste una riga breakdown su meta_marketing_placement. Ritorna 'created'|'updated'|''."""
    insight_date_only = insight_date.date()
    if insight_date_only < start_date or insight_date_only > end_date:
        return ""

    pub = (insight.get("publisher_platform") or "").strip().lower()
    pos = (insight.get("platform_position") or "").strip()

    existing = (
        db.query(MetaMarketingPlacement)
        .filter(
            MetaMarketingPlacement.ad_id == ad_record.id,
            MetaMarketingPlacement.date == insight_date,
            MetaMarketingPlacement.publisher_platform == pub,
            MetaMarketingPlacement.platform_position == pos,
        )
        .first()
    )

    base_raw = insight.get("raw_data", {})
    base_raw = _append_ingestion_debug(
        base_raw,
        {**job_debug_tag, "layer": "placement_breakdown"},
    )

    if existing:
        existing.spend = insight.get("spend", existing.spend)
        existing.impressions = insight.get("impressions", existing.impressions)
        existing.clicks = insight.get("clicks", existing.clicks)
        existing.conversions = insight.get("conversions", existing.conversions)
        existing.ctr = insight.get("ctr", existing.ctr)
        existing.cpc = insight.get("cpc", existing.cpc)
        existing.cpm = insight.get("cpm", existing.cpm)
        existing.cpa = insight.get("cpa", existing.cpa)
        existing.additional_metrics = base_raw
        existing.updated_at = now_rome()
        return "updated"

    row = MetaMarketingPlacement(
        ad_id=ad_record.id,
        date=insight_date,
        publisher_platform=pub,
        platform_position=pos,
        spend=insight.get("spend", 0),
        impressions=insight.get("impressions", 0),
        clicks=insight.get("clicks", 0),
        conversions=insight.get("conversions", 0),
        ctr=insight.get("ctr", 0),
        cpc=insight.get("cpc", 0),
        cpm=insight.get("cpm", 0),
        cpa=insight.get("cpa", 0),
        additional_metrics=base_raw,
    )
    db.add(row)
    return "created"


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

def run_manual_sync(
    db: Session,
    account_id: str,
    start_date: date,
    end_date: date,
    metrics: List[str],
) -> dict:
    """
    Sync manuale Insights → meta_marketing_data / meta_marketing_placement.
    Lead Ads Graph (`meta_graph_leads`) è solo il task/endpoint dedicati, non questo modulo.
    
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
            # Struttura da Meta: serve name_pattern (match sul nome) OPPURE campaign_ids (lista ID espliciti).
            has_name = bool((filters.get("name_pattern") or "").strip())
            has_ids = bool(filters.get("campaign_ids"))
            if not has_name and not has_ids:
                filters = None
        
        # Sync campaigns structure con filtri (se disponibili)
        if filters and (
            (filters.get("name_pattern") or "").strip() or filters.get("campaign_ids")
        ):
            service.sync_account_campaigns(account.account_id, db, filters=filters)
        else:
            # Senza filtri usabili non richiamiamo sync_account_campaigns (evita sync “vuota”).
            # La sync marketing usa comunque ads/campagne già in DB.
            logger.info(
                "Meta Marketing Manual Sync: No sync filters (name_pattern or campaign_ids) on sample campaign; "
                "using existing structure in DB for account %s",
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
        
        # Sempre breakdown placement + totali aggregati (Insights paginati, limit=50 per richiesta).
        breakdowns = ["publisher_platform", "platform_position"]
        logger.info(
            "Meta Marketing Manual Sync: fetching ad insights for account %s (breakdowns=%s, page_limit=%s)",
            account.account_id,
            breakdowns,
            META_INSIGHTS_PAGE_LIMIT,
        )

        stats["placement_created"] = 0
        stats["placement_updated"] = 0

        # Merge incrementale (ad_id, date): non teniamo in RAM l'intera lista breakdown.
        merge_groups: dict[tuple[str, str], dict] = {}
        campaign_agg: dict[str, dict] = {}
        adset_agg: dict[str, dict] = {}
        api_campaign_ids: Set[str] = set()
        total_insight_rows = 0
        insight_page_idx = 0

        records_created = 0
        records_updated = 0
        records_skipped_no_ad_id = 0
        records_skipped_no_ad_record = 0
        campaigns_touched: Set[str] = set()

        try:
            logger.info(
                "Meta Marketing Manual Sync: start insights pagination account=%s (%s) period=%s..%s "
                "(each API page is logged under services.integrations.meta_marketing)",
                account.account_id,
                account.name,
                start_date,
                end_date,
            )
            for page in service.iter_insight_pages(
                account_id=account.account_id,
                level="ad",
                date_preset=None,
                start_date=start_date,
                end_date=end_date,
                fields=metrics,
                breakdowns=breakdowns,
                page_limit=META_INSIGHTS_PAGE_LIMIT,
            ):
                insight_page_idx += 1
                total_insight_rows += len(page)
                _merge_insight_rows_into_groups(merge_groups, page)
                _aggregate_insights_merge_into(campaign_agg, page, "campaign_id")
                _aggregate_insights_merge_into(adset_agg, page, "adset_id")
                for i in page:
                    if i.get("campaign_id"):
                        api_campaign_ids.add(_normalize_meta_id(i["campaign_id"]))

                # Placement: persisti e commit per pagina (riduce RAM sessione / rischio OOM).
                for raw in page:
                    ad_id_str = raw.get("ad_id", "")
                    if not ad_id_str:
                        continue
                    ad_record = _meta_ad_for_account(db, account, ad_id_str)
                    if not ad_record:
                        continue
                    try:
                        insight_date = datetime.strptime(raw["date"], "%Y-%m-%d")
                    except (ValueError, KeyError):
                        continue
                    pr = _upsert_placement_row(
                        db,
                        raw,
                        ad_record,
                        insight_date,
                        start_date,
                        end_date,
                        job_debug_tag,
                    )
                    if pr == "created":
                        stats["placement_created"] += 1
                    elif pr == "updated":
                        stats["placement_updated"] += 1

                db.commit()
                logger.info(
                    "Meta Marketing Manual Sync: DB commit after insights page %s — placements "
                    "created_total=%s updated_total=%s | page_rows=%s cum_insight_rows=%s ad_day_keys=%s",
                    insight_page_idx,
                    stats.get("placement_created", 0),
                    stats.get("placement_updated", 0),
                    len(page),
                    total_insight_rows,
                    len(merge_groups),
                )

            if insight_page_idx == 0:
                logger.warning(
                    "Meta Marketing Manual Sync: no insight pages returned for account %s (check token / range)",
                    account.account_id,
                )

            logger.info(
                "Meta Marketing Manual Sync: insights fetch finished — %s ad-level rows, %s API pages, account %s",
                total_insight_rows,
                insight_page_idx,
                account.account_id,
            )

            _aggregate_insights_finalize_derived_metrics(campaign_agg)
            _aggregate_insights_finalize_derived_metrics(adset_agg)
            logger.info(
                "Meta Marketing Manual Sync: Aggregates built from ad-level insights (campaigns=%s, adsets=%s)",
                len(campaign_agg),
                len(adset_agg),
            )

            db_campaign_ids: Set[str] = {
                _normalize_meta_id(c.campaign_id) for c in campaigns
            }
            orphan_campaigns = api_campaign_ids - db_campaign_ids
            if orphan_campaigns:
                logger.warning(
                    "Meta Marketing Manual Sync: %s campaign_id nelle risposta Insights non sono in meta_campaigns "
                    "per questo account (es. %s). Si elabora comunque per ad_id sull'account; "
                    "sincronizza la struttura campagne da Meta se mancano oggetti.",
                    len(orphan_campaigns),
                    list(orphan_campaigns)[:5],
                )

            merged_for_totals = _finalize_ad_day_merge_groups(merge_groups)
            n_layer_a = len(merged_for_totals)
            logger.info(
                "Meta Marketing Manual Sync: persisting MetaMarketingData (layer A totals) — %s ad-day rows, account %s",
                n_layer_a,
                account.account_id,
            )

            for md_i, insight in enumerate(merged_for_totals, start=1):
                ad_id_str = insight.get("ad_id", "")
                if not ad_id_str:
                    records_skipped_no_ad_id += 1
                    continue

                ad_record = _meta_ad_for_account(db, account, ad_id_str)
                if not ad_record:
                    records_skipped_no_ad_record += 1
                    if records_skipped_no_ad_record <= 5:
                        logger.warning(
                            "Meta Marketing Manual Sync: nessun MetaAd in DB per ad_id=%s "
                            "(account %s); sincronizza ads/campagne o verifica ID.",
                            ad_id_str,
                            account.account_id,
                        )
                    continue

                cid = _normalize_meta_id(insight.get("campaign_id", ""))
                if cid:
                    campaigns_touched.add(cid)

                insight_date = datetime.strptime(insight["date"], "%Y-%m-%d")
                insight_date_only = insight_date.date()
                if insight_date_only < start_date or insight_date_only > end_date:
                    logger.debug(
                        "Meta Marketing Manual Sync: Skipping insight date %s outside range",
                        insight_date_only,
                    )
                    continue

                existing = (
                    db.query(MetaMarketingData)
                    .filter(
                        MetaMarketingData.ad_id == ad_record.id,
                        MetaMarketingData.date == insight_date,
                    )
                    .first()
                )

                placement_info = {}

                if existing:
                    logger.debug(
                        "[META_SYNC][MANUAL][UPDATE] ad_db_id=%s date=%s spend=%s conv=%s",
                        ad_record.id,
                        insight_date,
                        insight.get("spend"),
                        insight.get("conversions"),
                    )
                    existing.spend = insight.get("spend", existing.spend)
                    existing.impressions = insight.get("impressions", existing.impressions)
                    existing.clicks = insight.get("clicks", existing.clicks)
                    existing.conversions = insight.get("conversions", existing.conversions)
                    existing.ctr = insight.get("ctr", existing.ctr)
                    existing.cpc = insight.get("cpc", existing.cpc)
                    existing.cpm = insight.get("cpm", existing.cpm)
                    base_raw = insight.get("raw_data", existing.additional_metrics)
                    existing.additional_metrics = _append_ingestion_debug(
                        base_raw,
                        {**job_debug_tag, **placement_info},
                    )
                    existing.updated_at = now_rome()
                    records_updated += 1
                else:
                    logger.debug(
                        "[META_SYNC][MANUAL][INSERT] ad_db_id=%s date=%s spend=%s conv=%s",
                        ad_record.id,
                        insight_date,
                        insight.get("spend"),
                        insight.get("conversions"),
                    )
                    base_raw = insight.get("raw_data", {})
                    base_raw = _append_ingestion_debug(
                        base_raw,
                        {**job_debug_tag, **placement_info},
                    )
                    marketing_data = MetaMarketingData(
                        ad_id=ad_record.id,
                        date=insight_date,
                        spend=insight.get("spend", 0),
                        impressions=insight.get("impressions", 0),
                        clicks=insight.get("clicks", 0),
                        conversions=insight.get("conversions", 0),
                        ctr=insight.get("ctr", 0),
                        cpc=insight.get("cpc", 0),
                        cpm=insight.get("cpm", 0),
                        cpa=insight.get("cpa", 0),
                        additional_metrics=base_raw,
                    )
                    db.add(marketing_data)
                    records_created += 1

                if n_layer_a and (md_i % 150 == 0 or md_i == n_layer_a):
                    logger.info(
                        "Meta Marketing Manual Sync: layer A progress %s/%s (account %s)",
                        md_i,
                        n_layer_a,
                        account.account_id,
                    )

            db.commit()
            stats["campaigns_synced"] = len(campaigns_touched)

            logger.info(
                "Meta Marketing Manual Sync: account %s — Created: %s, Updated: %s, "
                "Skipped (no ad_id): %s, Skipped (no ad in DB): %s, campaigns_touched=%s",
                account.account_id,
                records_created,
                records_updated,
                records_skipped_no_ad_id,
                records_skipped_no_ad_record,
                len(campaigns_touched),
            )

        except Exception as e:
            logger.error(
                "Meta Marketing Manual Sync: Error syncing insights for account %s: %s",
                account.account_id,
                e,
                exc_info=True,
            )
            db.rollback()
            stats["errors"] += 1

        logger.info(
            "Meta Marketing Manual Sync: placement rows (account total) created=%s updated=%s",
            stats.get("placement_created", 0),
            stats.get("placement_updated", 0),
        )

        # Marker deploy: se dopo questa riga compaiono ancora "Meta Graph leads ingest" nello stesso job,
        # il worker Celery non sta usando questa versione del modulo (riavvio / rebuild immagine).
        logger.info(
            "Meta Marketing Manual Sync: marketing-only pipeline complete for account %s "
            "(no Graph /{ad_id}/leads in this function — use task meta_graph_leads_sync separately)",
            account.account_id,
        )

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
