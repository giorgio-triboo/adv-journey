"""
Sync meta_campaigns: bootstrap (periodo con impression) e incrementale (singola data).
Core dell'applicativo: usato da Celery tasks, API e CLI.
"""
from datetime import date, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from database import SessionLocal
from models import MetaAccount
from services.integrations.meta_marketing import MetaMarketingService
from services.utils.crypto import decrypt_token
import logging

logger = logging.getLogger("services.sync.meta_campaigns")


def _normalize_campaign_id(raw) -> str:
    if raw is None:
        return ""
    s = str(raw).strip()
    if "/" in s:
        s = s.split("/")[-1]
    if s.startswith("campaign_"):
        s = s.replace("campaign_", "", 1)
    return s


def run_bootstrap(
    start_date: date,
    end_date: date,
    db: Optional[Session] = None,
    dry_run: bool = False,
) -> dict:
    """
    Bootstrap: popola meta_campaigns con le campagne che hanno almeno 1 impression
    nel periodo [start_date, end_date]. Solo tabella meta_campaigns.

    Returns:
        dict con "accounts_processed", "campaigns_created", "campaigns_updated", "skipped", "errors"
    """
    own_db = db is None
    if own_db:
        db = SessionLocal()
    stats = {"accounts_processed": 0, "campaigns_created": 0, "campaigns_updated": 0, "skipped": 0, "errors": 0}
    try:
        accounts = db.query(MetaAccount).filter(MetaAccount.is_active == True).all()
        if not accounts:
            logger.info("meta_campaigns bootstrap: nessun MetaAccount attivo")
            return stats

        for acc in accounts:
            if not acc.access_token:
                logger.debug("Account %s: token assente, skip", acc.account_id)
                continue
            try:
                decrypted = decrypt_token(acc.access_token)
            except Exception as e:
                logger.warning("Account %s: decrypt token failed: %s", acc.account_id, e)
                stats["errors"] += 1
                continue

            service = MetaMarketingService(access_token=decrypted)
            insights = service.get_insights(
                account_id=acc.account_id,
                level="campaign",
                date_preset=None,
                start_date=start_date,
                end_date=end_date,
                fields=["impressions", "campaign_id", "date_start"],
            )
            campaign_ids = set()
            for row in insights:
                if int(row.get("impressions") or 0) > 0:
                    cid = _normalize_campaign_id(row.get("campaign_id"))
                    if cid:
                        campaign_ids.add(cid)

            if not campaign_ids:
                logger.debug("Account %s: nessuna campagna con impression nel periodo", acc.account_id)
                continue

            stats["accounts_processed"] += 1
            if dry_run:
                logger.info("Account %s: [DRY RUN] %s campagne con impression", acc.account_id, len(campaign_ids))
                continue

            result = service.sync_account_campaigns(
                account_id=acc.account_id,
                db_session=db,
                filters={"campaign_ids": campaign_ids},
            )
            if result.get("skipped"):
                stats["skipped"] += 1
            else:
                stats["campaigns_created"] += result.get("campaigns_created", 0)
                stats["campaigns_updated"] += result.get("campaigns_updated", 0)
    finally:
        if own_db:
            db.close()
    return stats


def run_incremental(
    target_date: date,
    db: Optional[Session] = None,
) -> dict:
    """
    Sync incrementale: aggiorna meta_campaigns per le campagne con almeno 1 impression
    nella data target_date (tipicamente ieri). Solo tabella meta_campaigns.

    Returns:
        dict con "accounts_processed", "campaigns_created", "campaigns_updated", "errors"
    """
    own_db = db is None
    if own_db:
        db = SessionLocal()
    stats = {"accounts_processed": 0, "campaigns_created": 0, "campaigns_updated": 0, "errors": 0}
    try:
        accounts = db.query(MetaAccount).filter(MetaAccount.is_active == True).all()
        for acc in accounts:
            if not acc.access_token:
                continue
            try:
                decrypted = decrypt_token(acc.access_token)
            except Exception as e:
                logger.warning("meta_campaigns incremental account %s decrypt failed: %s", acc.account_id, e)
                stats["errors"] += 1
                continue

            service = MetaMarketingService(access_token=decrypted)
            insights = service.get_insights(
                account_id=acc.account_id,
                level="campaign",
                date_preset=None,
                start_date=target_date,
                end_date=target_date,
                fields=["impressions", "campaign_id", "date_start"],
            )
            campaign_ids = set()
            for row in insights:
                if int(row.get("impressions") or 0) > 0:
                    cid = _normalize_campaign_id(row.get("campaign_id"))
                    if cid:
                        campaign_ids.add(cid)
            if not campaign_ids:
                continue

            stats["accounts_processed"] += 1
            result = service.sync_account_campaigns(
                account_id=acc.account_id,
                db_session=db,
                filters={"campaign_ids": campaign_ids},
            )
            if not result.get("skipped"):
                stats["campaigns_created"] += result.get("campaigns_created", 0)
                stats["campaigns_updated"] += result.get("campaigns_updated", 0)
    finally:
        if own_db:
            db.close()
    return stats
