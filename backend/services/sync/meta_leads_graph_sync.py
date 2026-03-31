"""
Ingest Lead Ads da Graph GET /{ad_id}/leads → tabella meta_graph_leads.

Pipeline distinta da meta_marketing_sync (Insights): schedulare o invocare questo flusso con
``run_for_active_accounts`` o il task Celery ``meta_graph_leads_sync_task``, non insieme al job marketing.
"""
from __future__ import annotations

import logging
from datetime import datetime, date, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from database import SessionLocal
from models import MetaAccount, MetaAd, MetaAdSet, MetaCampaign, MetaGraphLead, now_rome
from services.integrations.meta_marketing import MetaMarketingService

logger = logging.getLogger("services.sync")


def _parse_meta_created_time(value: Optional[str]) -> Optional[datetime]:
    """Parse created_time Meta (es. 2024-03-15T10:00:00+0000) → datetime timezone-aware UTC."""
    if not value or not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("+0000") and len(s) > 5:
        s = s[:-5] + "+00:00"
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        pass
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%dT%H:%M:%S%z").astimezone(timezone.utc)
    except ValueError:
        return None


def _lead_created_date_rome(utc_dt: Optional[datetime]) -> Optional[date]:
    """Data calendario Europe/Rome per confronto con start_date/end_date della sync marketing."""
    if utc_dt is None:
        return None
    from services.utils.timezone import utc_to_rome

    rome = utc_to_rome(utc_dt)
    return rome.date()


def sync_meta_graph_leads_for_account(
    db: Session,
    account: MetaAccount,
    service: MetaMarketingService,
    start_date: date,
    end_date: date,
    job_debug_tag: Dict[str, Any],
) -> Dict[str, int]:
    """
    Per ogni MetaAd dell'account: chiama get_leads_for_ad, filtra per created_time (Rome date)
    in [start_date, end_date], upsert su meta_graph_leads.
    """
    stats = {
        "graph_leads_fetched": 0,
        "graph_leads_created": 0,
        "graph_leads_updated": 0,
        "graph_leads_out_of_range": 0,
        "graph_leads_ad_errors": 0,
    }

    ads = (
        db.query(MetaAd)
        .join(MetaAdSet)
        .join(MetaCampaign)
        .filter(MetaCampaign.account_id == account.id)
        .all()
    )

    logger.info(
        "Meta Graph leads ingest: account=%s ads=%s range=%s..%s",
        account.account_id,
        len(ads),
        start_date,
        end_date,
    )

    for meta_ad in ads:
        try:
            rows: List[Dict[str, Any]] = service.get_leads_for_ad(meta_ad.ad_id)
        except Exception as e:
            logger.warning(
                "Meta Graph leads: skip ad %s after API error: %s",
                meta_ad.ad_id,
                e,
            )
            stats["graph_leads_ad_errors"] += 1
            continue

        for row in rows:
            if not isinstance(row, dict):
                continue
            stats["graph_leads_fetched"] += 1
            gid = str(row.get("id") or "").strip()
            if not gid:
                continue

            utc_dt = _parse_meta_created_time(row.get("created_time"))
            d_rome = _lead_created_date_rome(utc_dt)
            if d_rome is None or d_rome < start_date or d_rome > end_date:
                stats["graph_leads_out_of_range"] += 1
                continue

            form_raw = row.get("form_id")
            if form_raw is None or form_raw == "":
                form_id_str: str = ""
            else:
                form_id_str = str(form_raw)

            fd = row.get("field_data")
            if fd is None:
                field_data_json: Any = []
            elif isinstance(fd, list):
                field_data_json = fd
            else:
                field_data_json = []

            raw_payload = dict(row)
            raw_payload["_ingestion_debug"] = [job_debug_tag]

            created_naive = None
            if utc_dt is not None:
                from services.utils.timezone import utc_to_rome

                created_naive = utc_to_rome(utc_dt).replace(tzinfo=None)

            existing = (
                db.query(MetaGraphLead)
                .filter(MetaGraphLead.graph_lead_id == gid)
                .first()
            )
            if existing:
                existing.ad_id = meta_ad.id
                existing.form_id = form_id_str
                existing.created_time = created_naive
                existing.field_data = field_data_json
                existing.raw_payload = raw_payload
                existing.updated_at = now_rome()
                stats["graph_leads_updated"] += 1
            else:
                db.add(
                    MetaGraphLead(
                        graph_lead_id=gid,
                        ad_id=meta_ad.id,
                        form_id=form_id_str,
                        created_time=created_naive,
                        field_data=field_data_json,
                        raw_payload=raw_payload,
                    )
                )
                stats["graph_leads_created"] += 1

        try:
            db.commit()
        except Exception as commit_err:
            logger.error(
                "Meta Graph leads: commit failed for ad %s: %s",
                meta_ad.ad_id,
                commit_err,
                exc_info=True,
            )
            db.rollback()
            stats["graph_leads_ad_errors"] += 1

    logger.info("Meta Graph leads ingest done: %s", stats)
    return stats


def run_for_active_accounts(
    start_date: date,
    end_date: date,
    db: Optional[Session] = None,
) -> Dict[str, Any]:
    """
    Esegue ingest lead Graph per tutti gli account Meta attivi con sync abilitato.
    Utile da cron/script dedicato (stesso perimetro del job marketing).
    """
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True
    from services.utils.crypto import decrypt_token

    out: Dict[str, Any] = {"accounts": 0, "errors": 0, "totals": {}}
    try:
        accounts = (
            db.query(MetaAccount)
            .filter(MetaAccount.is_active == True, MetaAccount.sync_enabled == True)
            .all()
        )
        for account in accounts:
            try:
                token = decrypt_token(account.access_token)
                service = MetaMarketingService(access_token=token)
                tag = {
                    "ingestion_source": "meta_graph_leads_standalone",
                    "account_id": account.account_id,
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                }
                st = sync_meta_graph_leads_for_account(
                    db, account, service, start_date, end_date, tag
                )
                out["accounts"] += 1
                for k, v in st.items():
                    out["totals"][k] = out["totals"].get(k, 0) + v
            except Exception as e:
                logger.error(
                    "meta_leads_graph_sync run_for_active_accounts account=%s: %s",
                    account.account_id,
                    e,
                    exc_info=True,
                )
                out["errors"] += 1
        return out
    finally:
        if close_db:
            db.close()
