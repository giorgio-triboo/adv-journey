"""Celery task per pipeline Magellano (export/fetch)."""
from datetime import datetime
from celery_app import celery_app
from database import SessionLocal
from models import SyncLog, IngestionJob, Lead, StatusCategory, now_rome
from services.utils.crypto import hash_email_for_meta, hash_phone_for_meta
from services.integrations.lead_correlation import LeadCorrelationService
from services.utils.alert_sender import send_sync_alert_if_needed

@celery_app.task(name="tasks.magellano.export_request")
def magellano_export_request_task(
    campaigns: list, start_date_str: str, end_date_str: str, job_id: int | None = None
):
    """
    STEP 1: Richiede solo la generazione dell'export su Magellano (Playwright),
    senza attendere il completamento né scaricare file.

    Alla fine pianifica lo STEP 2 (fetch) dopo alcuni minuti.

    Nota: la password dello ZIP di Magellano dipende dal giorno in cui viene generato
    l'export (password_date), NON dall'intervallo dati (start_date/end_date).
    Per questo motivo salviamo e propaghiamo esplicitamente un password_date separato.
    """
    start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
    db = SessionLocal()
    try:
        from services.integrations.magellano_automation import MagellanoAutomation
        from playwright.sync_api import sync_playwright

        job = None
        if job_id:
            job = db.query(IngestionJob).filter(IngestionJob.id == job_id).first()
            if job:
                job.status = "RUNNING"
                job.started_at = now_rome()
                db.commit()

        logger = None
        import logging as _logging

        logger = _logging.getLogger("tasks.magellano.export_request")

        automation = MagellanoAutomation()
        with sync_playwright() as p:
            for campaign in campaigns:
                logger.info(
                    "Enqueue export for campaign %s (%s - %s)",
                    campaign,
                    start_date,
                    end_date,
                )
                automation.enqueue_export_only(p, campaign, start_date, end_date)

        # La data usata per la password ZIP è il giorno in cui chiediamo l'export.
        password_date = datetime.now().date()
        password_date_str = password_date.strftime("%Y-%m-%d")

        # Pianifica lo step 2 tra 5 minuti, propagando anche password_date_str.
        magellano_export_fetch_task.apply_async(
            args=[campaigns, start_date_str, end_date_str, password_date_str, job_id],
            countdown=300,
        )
    except Exception as e:
        db.rollback()
        # Prepara stats minime per alert
        stats = {
            "stage": "export_request",
            "campaigns": campaigns,
            "start_date": start_date_str,
            "end_date": end_date_str,
        }
        if job_id:
            job = db.query(IngestionJob).filter(IngestionJob.id == job_id).first()
            if job:
                job.status = "ERROR"
                job.completed_at = now_rome()
                job.message = f"Export request failed: {e}"
                job.params = (job.params or {}) | {"stats": stats}
                db.add(job)
                db.commit()

        # Alert su errore per lo step 1 (canale dedicato magellano_export)
        try:
            send_sync_alert_if_needed(
                db,
                "magellano_export",
                success=False,
                stats=stats,
                error_message=str(e),
            )
        except Exception:
            # Non bloccare il raise per errori di alert
            pass
        raise
    finally:
        db.close()


@celery_app.task(name="tasks.magellano.export_fetch")
def magellano_export_fetch_task(
    campaigns: list,
    start_date_str: str,
    end_date_str: str,
    password_date_str: str | None = None,
    job_id: int | None = None,
):
    """
    STEP 2: verifica se gli export sono pronti, scarica i file, li processa in lead
    e li salva nel DB, usando la stessa logica di ingest del flusso manuale.

    Se per una campagna l'export non è pronto/non trovato, il job viene marcato ERROR.
    """
    start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
    # Data usata per calcolare la password dello ZIP. È il giorno in cui è stato
    # richiesto l'export (STEP 1), non l'intervallo dati del report.
    if password_date_str:
        password_date = datetime.strptime(password_date_str, "%Y-%m-%d").date()
    else:
        # Backward-compat: se mancante (vecchie task), ripieghiamo su end_date.
        password_date = end_date
    db = SessionLocal()
    try:
        from services.integrations.magellano_automation import MagellanoAutomation
        from playwright.sync_api import sync_playwright

        import logging as _logging

        logger = _logging.getLogger("tasks.magellano.export_fetch")

        job = None
        if job_id:
            job = db.query(IngestionJob).filter(IngestionJob.id == job_id).first()

        correlation_service = LeadCorrelationService()
        stats = {
            "total_new": 0,
            "total_updated": 0,
            "total_errors": 0,
            "failed_campaigns": [],
            "per_campaign": {},
        }

        all_leads = []
        automation = MagellanoAutomation()
        import tempfile
        import shutil

        temp_dir = tempfile.mkdtemp()
        try:
            with sync_playwright() as p:
                for campaign in campaigns:
                    logger.info(
                        "Checking export for campaign %s (%s - %s)",
                        campaign,
                        start_date,
                        end_date,
                    )
                    leads = automation.fetch_export_and_process(
                        p,
                        campaign_number=campaign,
                        start_date=start_date,
                        end_date=end_date,
                        password_date=password_date,
                        download_dir=temp_dir,
                    )
                    if not leads:
                        stats["failed_campaigns"].append(str(campaign))
                        stats["total_errors"] += 1
                        continue
                    all_leads.extend(leads)
        finally:
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                logger.warning("Impossibile rimuovere la cartella temporanea %s", temp_dir, exc_info=True)

        if not all_leads:
            # Nessun export pronto: job in errore
            status_str = "ERROR"
            if job:
                job.status = status_str
                job.completed_at = now_rome()
                job.message = "Export Magellano non pronto o non trovato per tutte le campagne"
                job.params = (job.params or {}) | {"stats": stats}
                db.add(job)
                db.commit()

            sync_log = SyncLog(
                status=status_str,
                details={
                    "magellano": {
                        "type": "frontend_auto",
                        "campaigns": campaigns,
                        "start_date": start_date_str,
                        "end_date": end_date_str,
                        "errors": stats["total_errors"],
                        "failed_campaigns": stats["failed_campaigns"],
                    }
                },
            )
            db.add(sync_log)
            db.commit()

            # Alert su errore per step 2 (canale dedicato magellano_ingest)
            try:
                send_sync_alert_if_needed(
                    db,
                    "magellano_ingest",
                    success=False,
                    stats=stats,
                    error_message="Export Magellano non pronto o non trovato per tutte le campagne",
                )
            except Exception:
                pass
            return

        # Ingestion comune, ma a partire da all_leads già pronti
        def _get_campaign_key(data, existing=None) -> str:
            cid = (
                data.get("magellano_campaign_id")
                or data.get("campaign_id")
                or (existing.magellano_campaign_id if existing is not None else None)
            )
            return str(cid) if cid is not None else "unknown"

        new_leads = []
        for data in all_leads:
            magellano_id = data.get("magellano_id")
            existing = db.query(Lead).filter(Lead.magellano_id == magellano_id).first()

            magellano_status_raw = data.get("magellano_status_raw") or data.get("status_raw")
            magellano_status = data.get("magellano_status")
            magellano_status_category = data.get("magellano_status_category")

            current_status = magellano_status_raw if magellano_status_raw else magellano_status
            status_category = magellano_status_category if magellano_status_category else StatusCategory.UNKNOWN

            camp_key = _get_campaign_key(data, existing)
            if camp_key not in stats["per_campaign"]:
                stats["per_campaign"][camp_key] = {"new": 0, "updated": 0}

            if not existing:
                new_lead = Lead(
                    magellano_id=magellano_id,
                    external_user_id=data.get("external_user_id"),
                    email=hash_email_for_meta(data.get("email", "")),
                    phone=hash_phone_for_meta(data.get("phone", "")),
                    brand=data.get("brand"),
                    msg_id=data.get("msg_id"),
                    form_id=data.get("form_id"),
                    source=data.get("source"),
                    campaign_name=data.get("campaign_name"),
                    magellano_campaign_id=data.get("magellano_campaign_id"),
                    magellano_subscr_date=data.get("magellano_subscr_date"),
                    magellano_status_raw=magellano_status_raw,
                    magellano_status=magellano_status,
                    magellano_status_category=magellano_status_category,
                    payout_status=data.get("payout_status"),
                    is_paid=data.get("is_paid", False),
                    facebook_ad_name=data.get("facebook_ad_name"),
                    facebook_ad_set=data.get("facebook_ad_set"),
                    facebook_campaign_name=data.get("facebook_campaign_name"),
                    facebook_id=data.get("facebook_id"),
                    facebook_piattaforma=data.get("facebook_piattaforma"),
                    meta_campaign_id=data.get("meta_campaign_id"),
                    meta_adset_id=data.get("meta_adset_id"),
                    meta_ad_id=data.get("meta_ad_id"),
                    current_status=current_status,
                    status_category=status_category,
                )
                db.add(new_lead)
                new_leads.append(new_lead)

                stats["total_new"] += 1
                stats["per_campaign"][camp_key]["new"] += 1
            else:
                if magellano_status_raw:
                    existing.magellano_status_raw = magellano_status_raw
                if magellano_status:
                    existing.magellano_status = magellano_status
                if magellano_status_category:
                    existing.magellano_status_category = magellano_status_category

                if not existing.ulixe_status:
                    existing.current_status = current_status
                    existing.status_category = status_category

                if "payout_status" in data:
                    existing.payout_status = data.get("payout_status")
                if "is_paid" in data:
                    existing.is_paid = data.get("is_paid", False)
                if data.get("campaign_name"):
                    existing.campaign_name = data.get("campaign_name")
                if data.get("facebook_ad_name"):
                    existing.facebook_ad_name = data.get("facebook_ad_name")
                if data.get("facebook_ad_set"):
                    existing.facebook_ad_set = data.get("facebook_ad_set")
                if data.get("facebook_campaign_name"):
                    existing.facebook_campaign_name = data.get("facebook_campaign_name")
                if data.get("facebook_id"):
                    existing.facebook_id = data.get("facebook_id")
                if data.get("meta_campaign_id"):
                    existing.meta_campaign_id = data.get("meta_campaign_id")
                if data.get("meta_adset_id"):
                    existing.meta_adset_id = data.get("meta_adset_id")
                if data.get("meta_ad_id"):
                    existing.meta_ad_id = data.get("meta_ad_id")

                stats["total_updated"] += 1
                stats["per_campaign"][camp_key]["updated"] += 1

        db.commit()

        if new_leads:
            correlation_stats = correlation_service.correlate_batch(new_leads, db)
            import logging as _logging

            _logging.getLogger("tasks.magellano").info(
                "Lead Correlation (Magellano Sync): %s correlated, %s not found",
                correlation_stats["correlated"],
                correlation_stats["not_found"],
            )

        has_errors = bool(stats["failed_campaigns"] or stats["total_errors"])
        status_str = "ERROR" if has_errors else "SUCCESS"

        if job:
            params = job.params or {}
            params["stats"] = stats
            job.params = params
            job.status = status_str
            job.completed_at = now_rome()
            if has_errors:
                if stats["failed_campaigns"]:
                    job.message = (
                        "Sync Magellano completata con errori "
                        f"(campagne fallite: {', '.join(stats['failed_campaigns'])})"
                    )
                else:
                    job.message = "Sync Magellano completata con errori"
            else:
                job.message = (
                    f"Sync Magellano completata "
                    f"({stats['total_new']} nuove, {stats['total_updated']} aggiornate)"
                )
            db.add(job)

        sync_log = SyncLog(
            status=status_str,
            details={
                "magellano": {
                    "type": "frontend_auto",
                    "campaigns": campaigns,
                    "start_date": start_date_str,
                    "end_date": end_date_str,
                    "errors": stats["total_errors"],
                    "failed_campaigns": stats["failed_campaigns"],
                }
            },
        )
        db.add(sync_log)
        db.commit()

        # Alert per step 2 (successo/errore) - canale magellano_ingest
        try:
            send_sync_alert_if_needed(
                db,
                "magellano_ingest",
                success=not has_errors,
                stats=stats,
                error_message=None if not has_errors else "Magellano export fetch completed with errors",
            )
        except Exception:
            pass
    except Exception as e:
        db.rollback()
        if job_id:
            job = db.query(IngestionJob).filter(IngestionJob.id == job_id).first()
            if job:
                job.status = "ERROR"
                job.completed_at = now_rome()
                job.message = "Magellano export fetch failed"
                db.add(job)
                db.commit()

        # Alert su eccezione generica nello step 2 (canale magellano_ingest)
        try:
            fail_stats = {
                "stage": "export_fetch",
                "campaigns": campaigns,
                "start_date": start_date_str,
                "end_date": end_date_str,
            }
            send_sync_alert_if_needed(
                db,
                "magellano_ingest",
                success=False,
                stats=fail_stats,
                error_message=str(e),
            )
        except Exception:
            pass
            raise
    finally:
        db.close()
