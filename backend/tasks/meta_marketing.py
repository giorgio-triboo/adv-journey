"""Celery tasks per sync Meta marketing."""
from datetime import datetime, date, timedelta
from celery_app import celery_app
from database import SessionLocal
from services.sync.meta_marketing_sync import run_manual_sync
from services.sync.meta_campaigns_sync import run_bootstrap, run_incremental


@celery_app.task(name="tasks.meta.manual_sync")
def meta_manual_sync_task(account_id: str, start_date_str: str, end_date_str: str, metrics: list):
    """Sync manuale dati marketing per un account Meta (date e metriche custom)."""
    start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
    db = SessionLocal()
    try:
        return run_manual_sync(db, account_id, start_date, end_date, metrics)
    finally:
        db.close()


@celery_app.task(name="tasks.meta.sync_accounts_sequentially")
def meta_sync_accounts_sequentially_task(account_ids: list, filters: dict):
    """Sincronizza più account Meta in sequenza (con attesa tra uno e l'altro per rate limiting)."""
    from services.api.ui.settings.meta_campaigns import sync_meta_accounts_sequentially
    sync_meta_accounts_sequentially(account_ids, filters)


@celery_app.task(name="tasks.meta.sync_single_account")
def meta_sync_single_account_task(meta_account_id: int):
    """Sync campagne per un singolo account Meta (usa id DB MetaAccount)."""
    from models import MetaAccount
    from services.integrations.meta_marketing import MetaMarketingService
    from services.utils.crypto import decrypt_token
    import logging
    logger = logging.getLogger("tasks.meta")
    db = SessionLocal()
    try:
        account = db.query(MetaAccount).filter(MetaAccount.id == meta_account_id).first()
        if not account or not account.is_active:
            logger.warning(f"[CELERY] Meta account id={meta_account_id} non trovato o non attivo")
            return
        decrypted_token = decrypt_token(account.access_token)
        service = MetaMarketingService(access_token=decrypted_token)
        service.sync_account_campaigns(account.account_id, db)
        logger.info(f"[CELERY] Meta account {account.account_id} synced successfully")
    except Exception as e:
        logger.error(f"[CELERY] Meta account sync failed for id={meta_account_id}: {e}", exc_info=True)
    finally:
        db.close()


@celery_app.task(name="tasks.meta.campaigns_bootstrap")
def meta_campaigns_bootstrap_task(start_date_str: str, end_date_str: str, dry_run: bool = False):
    """
    Bootstrap meta_campaigns: campagne con almeno 1 impression nel periodo [start_date, end_date].
    Usa services.sync.meta_campaigns_sync.run_bootstrap.
    """
    import logging
    logger = logging.getLogger("tasks.meta")
    start_date = date.fromisoformat(start_date_str)
    end_date = date.fromisoformat(end_date_str)
    try:
        stats = run_bootstrap(start_date=start_date, end_date=end_date, db=None, dry_run=dry_run)
        logger.info("meta_campaigns_bootstrap %s..%s: %s", start_date_str, end_date_str, stats)
        return stats
    except Exception as e:
        logger.error("meta_campaigns_bootstrap failed: %s", e, exc_info=True)
        raise


@celery_app.task(name="tasks.meta.campaigns_incremental")
def meta_campaigns_incremental_task(target_date_str: str | None = None):
    """
    Sync incrementale meta_campaigns: campagne con almeno 1 impression nella data target (default: ieri).
    Usa services.sync.meta_campaigns_sync.run_incremental.
    """
    import logging
    logger = logging.getLogger("tasks.meta")
    target = (
        date.fromisoformat(target_date_str)
        if target_date_str
        else (date.today() - timedelta(days=1))
    )
    try:
        stats = run_incremental(target_date=target, db=None)
        logger.info("meta_campaigns_incremental %s: %s", target, stats)
        return stats
    except Exception as e:
        logger.error("meta_campaigns_incremental failed: %s", e, exc_info=True)
        raise
