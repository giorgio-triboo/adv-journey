"""Sync endpoints per Magellano, Ulixe e Meta"""
from fastapi import APIRouter, Request, Depends, UploadFile, File, Form
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from database import get_db
from models import (
    Lead,
    StatusCategory,
    LeadHistory,
    MetaAccount,
    User,
    SyncLog,
    IngestionJob,
    UlixeRcrmTemp,
)
from services.utils.crypto import hash_email_for_meta, hash_phone_for_meta
from datetime import datetime, timedelta, date
from typing import List
import logging
import time
import tempfile
import os
from services.integrations.magellano import MagellanoService
from services.integrations.lead_correlation import LeadCorrelationService
from .common import templates

logger = logging.getLogger('services.api.ui')

router = APIRouter(include_in_schema=False)


def run_magellano_sync(
    db: Session,
    campaigns: List[int],
    start_date: date,
    end_date: date,
    headless: bool = True,
    job_id: int | None = None,
) -> dict:
    """
    Esegue la sync Magellano per le campagne/date indicate e restituisce
    statistiche aggregate, inclusa la ripartizione per campagna.
    """
    logger.info(f"Starting Magellano Sync Task for campaigns {campaigns} ({start_date} to {end_date})...")
    from services.integrations.magellano import MagellanoService

    service = MagellanoService(headless=headless)
    correlation_service = LeadCorrelationService()

    stats = {
        "total_new": 0,
        "total_updated": 0,
        "total_errors": 0,
        "failed_campaigns": [],
        "per_campaign": {},
    }

    def _get_campaign_key(data, existing=None) -> str:
        cid = (
            data.get("magellano_campaign_id")
            or data.get("campaign_id")
            or (existing.magellano_campaign_id if existing is not None else None)
        )
        return str(cid) if cid is not None else "unknown"

    try:
        leads_data = service.fetch_leads(start_date, end_date, campaigns, job_id=job_id)
        logger.info(f"Fetched {len(leads_data)} leads from Magellano.")

        failed_campaigns = getattr(service, "failed_campaigns", []) or []
        stats["failed_campaigns"] = [str(c) for c in failed_campaigns]
        stats["total_errors"] = len(stats["failed_campaigns"])

        new_leads = []

        for data in leads_data:
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
                    # ID Meta se presenti nell'export
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

                if existing.ulixe_status:
                    pass
                else:
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
                # Aggiorna ID Meta se presenti (gli ID sono la fonte autorevole)
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
            logger.info(
                f"Lead Correlation (Magellano Sync): "
                f"{correlation_stats['correlated']} correlated, "
                f"{correlation_stats['not_found']} not found"
            )

        logger.info(
            "Magellano Sync Task Completed Successfully. "
            f"New: {stats['total_new']}, updated: {stats['total_updated']}"
        )
        return stats
    except Exception as e:
        stats["total_errors"] += 1
        logger.error(f"Magellano Sync Task Failed: {e}")
        db.rollback()
        raise

@router.post("/sync")
async def trigger_sync(request: Request, db: Session = Depends(get_db)):
    user = request.session.get('user')
    if not user:
        return RedirectResponse(url='/')
    
    form_data = await request.form()
    # Gestisce select multiple (dropdown) - getlist restituisce lista vuota se nessuna selezione
    campaigns_list = form_data.getlist("campaigns")
    
    # Parse campaigns
    campaigns = []
    if campaigns_list:
        # Se è una lista (select multiple)
        campaigns = [int(c.strip()) for c in campaigns_list if str(c).strip().isdigit()]
    else:
        # Fallback per input text (retrocompatibilità)
        campaigns_str = form_data.get("campaigns", "")
        if campaigns_str:
            campaigns = [int(c.strip()) for c in campaigns_str.split(",") if c.strip().isdigit()]
    
    # Se nessuna campagna è specificata, usa tutte le campagne attive
    if not campaigns:
        from models import ManagedCampaign
        managed_campaigns = db.query(ManagedCampaign).filter(ManagedCampaign.is_active == True).all()
        for campaign in managed_campaigns:
            if campaign.magellano_ids:
                for mag_id in campaign.magellano_ids:
                    try:
                        campaigns.append(int(mag_id))
                    except (ValueError, TypeError):
                        continue
        campaigns = list(dict.fromkeys(campaigns))  # Rimuovi duplicati
    
    start_date_str = form_data.get("start_date")
    end_date_str = form_data.get("end_date")
    
    today = datetime.now().date()
    if start_date_str:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    else:
        start_date = today - timedelta(days=1)
        
    if end_date_str:
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
    else:
        # Default allineato al job giornaliero: solo ieri
        end_date = start_date

    from tasks.magellano import magellano_export_request_task

    # Registra un job di ingestion per tracking
    job = IngestionJob(
        job_type="magellano",
        status="PENDING",
        params={
            "source": "frontend_form",
            "campaigns": campaigns,
            "start_date": start_date.strftime("%Y-%m-%d"),
            "end_date": end_date.strftime("%Y-%m-%d"),
        },
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    async_result = magellano_export_request_task.delay(
        campaigns,
        start_date.strftime("%Y-%m-%d"),
        end_date.strftime("%Y-%m-%d"),
        job_id=job.id,
    )

    job.celery_task_id = async_result.id
    job.status = "QUEUED"
    db.commit()

    return RedirectResponse(url="/dashboard", status_code=303)

@router.post("/api/magellano/sync")
async def api_magellano_sync(request: Request, db: Session = Depends(get_db)):
    """
    API endpoint per sincronizzazione Magellano con date variabili.
    Accetta JSON con campaigns (lista ID), start_date, end_date (opzionali).
    Se le date non sono specificate, usa solo ieri (start=end=oggi-1).
    """
    user = request.session.get('user')
    if not user:
        return JSONResponse({"error": "Non autorizzato"}, status_code=401)
    
    try:
        data = await request.json()
    except:
        # Fallback a form data se non è JSON
        form_data = await request.form()
        data = {
            "campaigns": form_data.get("campaigns", ""),
            "start_date": form_data.get("start_date"),
            "end_date": form_data.get("end_date")
        }
    
    # Parse campaigns
    campaigns_str = data.get("campaigns", "")
    if isinstance(campaigns_str, str):
        campaigns = [int(c.strip()) for c in campaigns_str.split(",") if c.strip().isdigit()]
    elif isinstance(campaigns_str, list):
        campaigns = [int(c) for c in campaigns_str if str(c).strip().isdigit()]
    else:
        campaigns = []
    
    if not campaigns:
        # Se non specificato, usa tutte le campagne attive
        from models import ManagedCampaign
        managed_campaigns = db.query(ManagedCampaign).filter(ManagedCampaign.is_active == True).all()
        for campaign in managed_campaigns:
            if campaign.magellano_ids:
                for mag_id in campaign.magellano_ids:
                    try:
                        campaigns.append(int(mag_id))
                    except (ValueError, TypeError):
                        continue
        campaigns = list(dict.fromkeys(campaigns))  # Rimuovi duplicati
    
    if not campaigns:
        return JSONResponse({"error": "Nessuna campagna specificata o attiva"}, status_code=400)
    
    # Parse dates
    today = datetime.now().date()
    start_date_str = data.get("start_date")
    end_date_str = data.get("end_date")
    
    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        except ValueError:
            return JSONResponse({"error": "Formato start_date non valido. Usa YYYY-MM-DD"}, status_code=400)
    else:
        start_date = today - timedelta(days=1)  # Default: ieri
    
    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
        except ValueError:
            return JSONResponse({"error": "Formato end_date non valido. Usa YYYY-MM-DD"}, status_code=400)
    else:
        end_date = start_date  # Default: solo ieri
    
    if start_date > end_date:
        return JSONResponse({"error": "start_date deve essere <= end_date"}, status_code=400)

    from tasks.magellano import magellano_export_request_task

    # Registra un job di ingestion per tracking
    job = IngestionJob(
        job_type="magellano",
        status="PENDING",
        params={
            "source": "api",
            "campaigns": campaigns,
            "start_date": start_date.strftime("%Y-%m-%d"),
            "end_date": end_date.strftime("%Y-%m-%d"),
        },
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    async_result = magellano_export_request_task.delay(
        campaigns,
        start_date.strftime("%Y-%m-%d"),
        end_date.strftime("%Y-%m-%d"),
        job_id=job.id,
    )

    job.celery_task_id = async_result.id
    job.status = "QUEUED"
    db.commit()

    return JSONResponse(
        {
            "success": True,
            "message": "Sincronizzazione Magellano avviata in background",
            "campaigns": campaigns,
            "start_date": start_date.strftime("%Y-%m-%d"),
            "end_date": end_date.strftime("%Y-%m-%d"),
            "job_id": job.id,
        }
    )

@router.post("/sync/full")
async def trigger_full_sync(request: Request):
    """Esegue il sync completo tramite orchestrator (coda Celery)."""
    user = request.session.get('user')
    if not user:
        return RedirectResponse(url='/')

    from tasks.sync_pipeline import run_full_sync_task
    from database import SessionLocal
    from models import IngestionJob

    # Crea un job di ingestion per la full pipeline
    db = SessionLocal()
    try:
        job = IngestionJob(
            job_type="full_pipeline",
            status="PENDING",
            params={"source": "full_sync_button"},
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        async_result = run_full_sync_task.delay(job_id=job.id)

        job.celery_task_id = async_result.id
        job.status = "QUEUED"
        db.commit()
    finally:
        db.close()

    return RedirectResponse(url="/dashboard?sync_started=true", status_code=303)

@router.get("/settings/magellano-sync")
async def magellano_sync_page(request: Request, db: Session = Depends(get_db)):
    """Pagina per sync Magellano"""
    user = request.session.get('user')
    if not user:
        return RedirectResponse(url='/')
    
    from models import ManagedCampaign
    campaigns = db.query(ManagedCampaign).filter(ManagedCampaign.is_active == True).all()
    
    return templates.TemplateResponse("settings_magellano_upload.html", {
        "request": request,
        "title": "Sync Magellano",
        "user": user,
        "campaigns": campaigns,
        "active_page": "magellano_sync"
    })

@router.post("/api/magellano/upload")
async def magellano_upload(
    request: Request,
    db: Session = Depends(get_db),
):
    """Endpoint per upload e processamento file Magellano."""
    user = request.session.get('user')
    if not user:
        return JSONResponse({"error": "Non autorizzato"}, status_code=401)

    # Recupera form già parsato dal middleware CSRF (se presente) oppure parsalo qui
    form = getattr(request.state, "_parsed_form", None)
    if form is None:
        form = await request.form()

    file = form.get("file")
    file_date = form.get("file_date")
    campaign_id = form.get("campaign_id")

    # Validazione parametri form/file per evitare 422 FastAPI e dare errori espliciti
    if file is None or not getattr(file, "filename", None):
        return JSONResponse({"error": "Nessun file selezionato"}, status_code=400)

    if not file_date:
        return JSONResponse({"error": "Data file mancante"}, status_code=400)

    allowed_extensions = ['.zip', '.xls', '.xlsx', '.csv']
    file_ext = os.path.splitext(file.filename)[1].lower()
    if file_ext not in allowed_extensions:
        return JSONResponse({"error": f"Formato file non supportato. Usa: {', '.join(allowed_extensions)}"}, status_code=400)
    
    # Parse data
    try:
        file_date_obj = datetime.strptime(file_date, '%Y-%m-%d').date()
    except ValueError:
        return JSONResponse({"error": "Formato data non valido. Usa YYYY-MM-DD"}, status_code=400)
    
    # Parse campaign_id
    campaign_id_int = None
    if campaign_id:
        try:
            campaign_id_int = int(campaign_id)
        except ValueError:
            return JSONResponse({"error": "ID campagna non valido"}, status_code=400)
    
    # Salva file temporaneo
    temp_file_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as temp_file:
            content = await file.read()
            temp_file.write(content)
            temp_file_path = temp_file.name
        
        # Processa file
        logger.info(f"Processing uploaded file: {file.filename}, date: {file_date_obj}, campaign_id: {campaign_id_int}")
        service = MagellanoService()
        # Passa il nome originale del file per permettere l'estrazione dell'ID campagna
        leads_data = service.process_uploaded_file(temp_file_path, file_date_obj, campaign_id_int, original_filename=file.filename)
        
        logger.info(f"Processed {len(leads_data) if leads_data else 0} leads from file")
        
        if not leads_data:
            return JSONResponse({"error": "Nessuna lead trovata nel file"}, status_code=400)
        
        # Salva leads nel DB
        imported_count = 0
        updated_count = 0
        new_leads = []
        
        for data in leads_data:
            magellano_id = data.get('magellano_id')
            existing = db.query(Lead).filter(Lead.magellano_id == magellano_id).first()
            
            if not existing:
                # Recupera dati Magellano
                magellano_status_raw = data.get('magellano_status_raw') or data.get('status_raw')
                magellano_status = data.get('magellano_status')
                magellano_status_category = data.get('magellano_status_category')
                
                # Calcola current_status e status_category (priorità: Ulixe > Magellano)
                # Per nuove lead, usa sempre Magellano (Ulixe non ha ancora sincronizzato)
                current_status = magellano_status_raw if magellano_status_raw else magellano_status
                status_category = magellano_status_category if magellano_status_category else StatusCategory.UNKNOWN
                
                new_lead = Lead(
                    magellano_id=magellano_id,
                    external_user_id=data.get('external_user_id'),
                    email=hash_email_for_meta(data.get('email', '')),
                    phone=hash_phone_for_meta(data.get('phone', '')),
                    brand=data.get('brand'),
                    msg_id=data.get('msg_id'),
                    form_id=data.get('form_id'),
                    source=data.get('source'),
                    campaign_name=data.get('campaign_name'),
                    magellano_campaign_id=data.get('magellano_campaign_id'),
                    magellano_subscr_date=data.get('magellano_subscr_date'),
                    # Stato Magellano: originale, normalizzato e categoria
                    magellano_status_raw=magellano_status_raw,
                    magellano_status=magellano_status,
                    magellano_status_category=magellano_status_category,
                    payout_status=data.get('payout_status'),
                    is_paid=data.get('is_paid', False),
                    facebook_ad_name=data.get('facebook_ad_name'),
                    facebook_ad_set=data.get('facebook_ad_set'),
                    facebook_campaign_name=data.get('facebook_campaign_name'),
                    facebook_id=data.get('facebook_id'),
                    facebook_piattaforma=data.get('facebook_piattaforma'),
                    # Stato corrente (calcolato: preferisce Ulixe se disponibile, altrimenti Magellano)
                    current_status=current_status,
                    status_category=status_category
                )
                db.add(new_lead)
                imported_count += 1
                new_leads.append(new_lead)
            else:
                # Update existing lead - aggiorna anche lo stato Magellano
                magellano_status_raw = data.get('magellano_status_raw') or data.get('status_raw')
                magellano_status = data.get('magellano_status')
                magellano_status_category = data.get('magellano_status_category')
                
                # Aggiorna sempre i campi Magellano
                if magellano_status_raw:
                    existing.magellano_status_raw = magellano_status_raw
                if magellano_status:
                    existing.magellano_status = magellano_status
                if magellano_status_category:
                    existing.magellano_status_category = magellano_status_category
                
                # Calcola current_status e status_category (priorità: Ulixe > Magellano)
                # Se Ulixe ha già sincronizzato, mantieni quello, altrimenti usa Magellano
                if existing.ulixe_status:
                    # Ulixe ha priorità - non sovrascrivere
                    current_status = existing.ulixe_status
                    status_category = existing.ulixe_status_category or existing.status_category
                else:
                    # Usa Magellano (Ulixe non ha ancora sincronizzato)
                    current_status = magellano_status_raw if magellano_status_raw else magellano_status
                    status_category = magellano_status_category if magellano_status_category else existing.status_category
                    existing.current_status = current_status
                    existing.status_category = status_category
                # Aggiorna sempre payout_status e is_paid (anche se None)
                if 'payout_status' in data:
                    existing.payout_status = data.get('payout_status')
                if 'is_paid' in data:
                    existing.is_paid = data.get('is_paid', False)
                
                # Update altri campi se disponibili
                if data.get('email'):
                    existing.email = hash_email_for_meta(data.get('email'))
                if data.get('phone'):
                    existing.phone = hash_phone_for_meta(data.get('phone'))
                if data.get('campaign_name'):
                    existing.campaign_name = data.get('campaign_name')
                if data.get('facebook_ad_name'):
                    existing.facebook_ad_name = data.get('facebook_ad_name')
                if data.get('facebook_ad_set'):
                    existing.facebook_ad_set = data.get('facebook_ad_set')
                if data.get('facebook_campaign_name'):
                    existing.facebook_campaign_name = data.get('facebook_campaign_name')
                if data.get('facebook_id'):
                    existing.facebook_id = data.get('facebook_id')
                if data.get('magellano_subscr_date'):
                    existing.magellano_subscr_date = data.get('magellano_subscr_date')
                updated_count += 1
        
        db.commit()
        
        # Correlazione automatica delle nuove lead con Meta Marketing
        if new_leads:
            correlation_service = LeadCorrelationService()
            correlation_stats = correlation_service.correlate_batch(new_leads, db)
            logger.info(
                f"Lead Correlation (Magellano Upload): "
                f"{correlation_stats['correlated']} correlated, "
                f"{correlation_stats['not_found']} not found"
            )
        
        logger.info(
            f"Magellano upload completed: {imported_count} imported, "
            f"{updated_count} updated, {len(leads_data)} total"
        )

        # Registra nel riepilogo ingestion come sync manuale Magellano
        try:
            sync_log = SyncLog(
                status="SUCCESS",
                details={
                    "magellano": {
                        "type": "manual_upload",
                        "file_name": file.filename,
                        "campaign_id": campaign_id_int,
                        "imported": imported_count,
                        "updated": updated_count,
                        "total": len(leads_data),
                        "errors": 0,
                    }
                },
            )
            db.add(sync_log)
            db.commit()
        except Exception as log_exc:
            # Non bloccare il flusso utente per errori di logging
            logger.error(f"Errore salvataggio SyncLog per upload Magellano: {log_exc}", exc_info=True)
        
        return JSONResponse({
            "success": True,
            "message": f"File processato con successo",
            "imported": imported_count,
            "updated": updated_count,
            "total": len(leads_data)
        })
        
    except Exception as e:
        logger.error(f"Errore upload Magellano: {e}")
        db.rollback()

        # Prova a registrare comunque il fallimento nel riepilogo ingestion
        try:
            error_details = {
                "error": str(e),
                "stats": {
                    "magellano": {
                        "type": "manual_upload",
                        "file_name": getattr(file, "filename", None),
                        "campaign_id": campaign_id_int,
                        "errors": 1,
                    }
                },
            }
            sync_log = SyncLog(status="ERROR", details=error_details)
            db.add(sync_log)
            db.commit()
        except Exception as log_exc:
            logger.error(f"Errore salvataggio SyncLog per upload Magellano fallito: {log_exc}", exc_info=True)

        return JSONResponse({"error": f"Errore durante il processamento: {str(e)}"}, status_code=500)
    
    finally:
        # Rimuovi file temporaneo
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.unlink(temp_file_path)
            except:
                pass

@router.get("/settings/meta-sync")
async def settings_meta_sync(request: Request, db: Session = Depends(get_db)):
    """Maschera per sync manuale dati marketing Meta"""
    if not request.session.get('user'):
        return RedirectResponse(url='/')
    
    user_session = request.session.get('user')
    current_user = db.query(User).filter(User.email == user_session.get('email')).first()
    if not current_user:
        return RedirectResponse(url='/')
    
    current_user_id = current_user.id
    
    # Get active accounts (condivisi + dell'utente)
    accounts = db.query(MetaAccount).filter(
        MetaAccount.is_active == True,
        (MetaAccount.user_id == None) | (MetaAccount.user_id == current_user_id)
    ).order_by(MetaAccount.name).all()
    
    # Date di default: dal 1 gennaio a oggi-1
    today = date.today()
    default_end_date = (today - timedelta(days=1)).strftime('%Y-%m-%d')
    default_start_date = date(today.year, 1, 1).strftime('%Y-%m-%d')
    
    return templates.TemplateResponse("settings_meta_sync.html", {
        "request": request,
        "title": "Sync Manuale Meta",
        "user": current_user,
        "accounts": accounts,
        "active_page": "meta_sync",
        "default_start_date": default_start_date,
        "default_end_date": default_end_date
    })

@router.post("/settings/meta-sync/manual")
async def manual_meta_sync(request: Request, db: Session = Depends(get_db)):
    """Endpoint per sync manuale con date e metriche custom"""
    if not request.session.get('user'):
        return JSONResponse({"success": False, "message": "Non autorizzato"}, status_code=401)
    
    try:
        data = await request.json()
        account_id = data.get('account_id')  # Può essere None per tutti gli account
        start_date_str = data.get('start_date')
        end_date_str = data.get('end_date')
        metrics = data.get('metrics', [])
        
        # Validazione
        if not start_date_str or not end_date_str:
            return JSONResponse({"success": False, "message": "Date obbligatorie"}, status_code=400)
        
        if not metrics:
            return JSONResponse({"success": False, "message": "Seleziona almeno una metrica"}, status_code=400)
        
        # Parse date
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        
        if start_date > end_date:
            return JSONResponse({"success": False, "message": "Data inizio deve essere precedente alla data fine"}, status_code=400)
        
        # Verifica che spend e actions siano sempre inclusi (necessari per CPL)
        required_metrics = ['spend', 'actions']
        if not all(m in metrics for m in required_metrics):
            # Aggiungi automaticamente se mancanti
            for m in required_metrics:
                if m not in metrics:
                    metrics.append(m)
        
        user_session = request.session.get('user')
        current_user = db.query(User).filter(User.email == user_session.get('email')).first()
        if not current_user:
            return JSONResponse({"success": False, "message": "Utente non trovato"}, status_code=401)
        
        current_user_id = current_user.id
        
        # Determina account da sincronizzare
        if account_id:
            # Sync account specifico
            account = db.query(MetaAccount).filter(
                MetaAccount.account_id == account_id,
                MetaAccount.is_active == True,
                (MetaAccount.user_id == None) | (MetaAccount.user_id == current_user_id)
            ).first()
            
            if not account:
                return JSONResponse({"success": False, "message": "Account non trovato o non autorizzato"}, status_code=404)
            
            accounts_to_sync = [account]
            account_name = account.name
        else:
            # Sync tutti gli account attivi
            accounts_to_sync = db.query(MetaAccount).filter(
                MetaAccount.is_active == True,
                MetaAccount.sync_enabled == True,
                (MetaAccount.user_id == None) | (MetaAccount.user_id == current_user_id)
            ).all()
            
            if not accounts_to_sync:
                return JSONResponse({"success": False, "message": "Nessun account attivo trovato"}, status_code=404)
            
            account_name = f"{len(accounts_to_sync)} account"
        
        from tasks.meta_marketing import meta_manual_sync_task

        jobs_created = []
        for account in accounts_to_sync:
            job = IngestionJob(
                job_type="meta_marketing",
                status="PENDING",
                params={
                    "source": "frontend_manual",
                    "account_id": account.account_id,
                    "account_name": account.name,
                    "start_date": start_date_str,
                    "end_date": end_date_str,
                    "metrics": metrics,
                },
            )
            db.add(job)
            db.commit()
            db.refresh(job)

            async_result = meta_manual_sync_task.delay(
                account.account_id,
                start_date_str,
                end_date_str,
                metrics,
                job_id=job.id,
            )

            job.celery_task_id = async_result.id
            job.status = "QUEUED"
            db.commit()
            jobs_created.append(job.id)

        logger.info(
            f"Manual sync started: {account_name}, period: {start_date} - {end_date}, metrics: {metrics}, jobs={jobs_created}"
        )
        
        return JSONResponse({
            "success": True,
            "message": f"Sync avviata per {account_name}",
            "account_name": account_name,
            "start_date": start_date_str,
            "end_date": end_date_str,
            "metrics": metrics,
            "job_ids": jobs_created,
        })
        
    except ValueError as e:
        return JSONResponse({"success": False, "message": f"Formato date non valido: {str(e)}"}, status_code=400)
    except Exception as e:
        logger.error(f"Error in manual sync: {e}", exc_info=True)
        return JSONResponse({"success": False, "message": f"Errore: {str(e)}"}, status_code=500)

@router.get("/settings/ulixe-sync")
async def settings_ulixe_sync(request: Request, db: Session = Depends(get_db)):
    """Maschera per sync manuale Ulixe"""
    user = request.session.get('user')
    if not user:
        return RedirectResponse(url='/')
    
    from config import settings
    from services.integrations.google_sheets_rcrm import is_rcrm_google_sheet_configured

    # Verifica che le credenziali Ulixe siano configurate
    ulixe_configured = bool(settings.ULIXE_USER and settings.ULIXE_PASSWORD and settings.ULIXE_WSDL)
    google_rcrm_configured = is_rcrm_google_sheet_configured()
    
    # Recupera leads con external_user_id per mostrare esempi
    leads_with_user_id = db.query(Lead).filter(
        Lead.external_user_id.isnot(None),
        Lead.external_user_id != ""
    ).order_by(Lead.created_at.desc()).limit(50).all()
    
    return templates.TemplateResponse("settings_ulixe_sync.html", {
        "request": request,
        "title": "Sync Manuale Ulixe",
        "user": user,
        "ulixe_configured": ulixe_configured,
        "google_rcrm_configured": google_rcrm_configured,
        "leads_examples": leads_with_user_id[:10],  # Solo 10 esempi
        "active_page": "ulixe_sync"
    })


@router.post("/api/ulixe/rcrm/sync")
async def api_ulixe_rcrm_sync(request: Request, db: Session = Depends(get_db)):
    """
    Sincronizzazione RCRM Ulixe in ulixe_rcrm_temp.

    - Con Google Sheet configurato (service account + foglio condiviso): legge via Sheets API.
    - In alternativa (source=auto senza Google): file rcrm-*.csv in exports/ulixe_temp.

    Body JSON: period (YYYY-MM, obbligatorio), source opzionale: auto | google_sheet | local_files
    """
    user = request.session.get("user")
    if not user:
        return JSONResponse({"success": False, "error": "Non autorizzato"}, status_code=401)

    try:
        data = await request.json()
    except Exception:
        data = {}

    requested_period = (data.get("period") or "").strip()
    source = (data.get("source") or "auto").strip().lower()

    if not requested_period:
        return JSONResponse(
            {"success": False, "error": "Parametro period (YYYY-MM) obbligatorio"},
            status_code=400,
        )
    try:
        datetime.strptime(f"{requested_period}-01", "%Y-%m-%d")
    except ValueError:
        return JSONResponse(
            {"success": False, "error": "Periodo non valido. Usa formato YYYY-MM"},
            status_code=400,
        )

    if source not in ("auto", "google_sheet", "local_files", ""):
        return JSONResponse(
            {"success": False, "error": 'source non valido (usa auto, google_sheet o local_files)'},
            status_code=400,
        )
    if not source:
        source = "auto"

    try:
        from services.sync.ulixe_rcrm_google_sync import run_ulixe_rcrm_sync

        stats = run_ulixe_rcrm_sync(db, requested_period, source=source)
        db.commit()

        log_type = (
            "auto_sync_from_google_sheet"
            if stats.get("mode") == "google_sheet"
            else "auto_sync_from_files"
        )
        try:
            details = {
                "ulixe_rcrm": {
                    "type": log_type,
                    "stats": stats,
                    "requested_period": requested_period,
                    "source_requested": source,
                }
            }
            sync_log = SyncLog(status="SUCCESS", details=details)
            db.add(sync_log)
            db.commit()
        except Exception as log_exc:
            logger.error(
                f"Errore salvataggio SyncLog per sync RCRM Ulixe: {log_exc}",
                exc_info=True,
            )

        try:
            from services.utils.alert_sender import notify_ulixe_rcrm_google_after_api

            notify_ulixe_rcrm_google_after_api(
                db,
                source=source,
                period=requested_period,
                success=True,
                stats=stats,
            )
        except Exception:
            pass

        return JSONResponse({"success": True, "stats": stats})

    except ValueError as e:
        db.rollback()
        try:
            from services.utils.alert_sender import notify_ulixe_rcrm_google_after_api

            notify_ulixe_rcrm_google_after_api(
                db,
                source=source,
                period=requested_period,
                success=False,
                error_message=str(e),
            )
        except Exception:
            pass
        return JSONResponse({"success": False, "error": str(e)}, status_code=400)
    except FileNotFoundError as e:
        db.rollback()
        try:
            from services.utils.alert_sender import notify_ulixe_rcrm_google_after_api

            notify_ulixe_rcrm_google_after_api(
                db,
                source=source,
                period=requested_period,
                success=False,
                error_message=str(e),
            )
        except Exception:
            pass
        return JSONResponse({"success": False, "error": str(e)}, status_code=400)
    except RuntimeError as e:
        db.rollback()
        try:
            from services.utils.alert_sender import notify_ulixe_rcrm_google_after_api

            notify_ulixe_rcrm_google_after_api(
                db,
                source=source,
                period=requested_period,
                success=False,
                error_message=str(e),
            )
        except Exception:
            pass
        return JSONResponse({"success": False, "error": str(e)}, status_code=400)
    except Exception as e:
        logger.error(f"Errore sync RCRM Ulixe: {e}", exc_info=True)
        db.rollback()

        try:
            error_details = {
                "error": str(e),
                "stats": {
                    "ulixe_rcrm": {
                        "type": "auto_sync_error",
                        "errors": 1,
                        "requested_period": requested_period,
                        "source_requested": source,
                    }
                },
            }
            sync_log = SyncLog(status="ERROR", details=error_details)
            db.add(sync_log)
            db.commit()
        except Exception as log_exc:
            logger.error(
                f"Errore salvataggio SyncLog per sync RCRM Ulixe fallita: {log_exc}",
                exc_info=True,
            )

        err_msg = str(e)
        status_code = 500
        try:
            from googleapiclient.errors import HttpError

            if isinstance(e, HttpError):
                status_code = 502
                st = e.resp.status if e.resp is not None else "?"
                err_msg = f"Google Sheets API (HTTP {st}): {e}"
        except ImportError:
            pass

        try:
            from services.utils.alert_sender import notify_ulixe_rcrm_google_after_api

            notify_ulixe_rcrm_google_after_api(
                db,
                source=source,
                period=requested_period,
                success=False,
                error_message=err_msg,
            )
        except Exception:
            pass

        return JSONResponse(
            {"success": False, "error": f"Errore durante la sync RCRM Ulixe: {err_msg}"},
            status_code=status_code,
        )


@router.post("/api/ulixe/rcrm/upload")
async def ulixe_rcrm_upload(
    request: Request,
    db: Session = Depends(get_db),
):
    """Endpoint per upload file RCRM Ulixe (mensile).

    - Richiede: file CSV con colonne almeno IDMessaggio e RCRM
    - Richiede: periodo nel formato YYYY-MM (es. 2026-03)
    - Comportamento: prima cancella tutte le righe esistenti per quel periodo,
      poi ricarica dal file (sovrascrive intero mese).
    """
    user = request.session.get("user")
    if not user:
        return JSONResponse({"error": "Non autorizzato"}, status_code=401)

    # Recupera form già parsato dal middleware CSRF (se presente) oppure parsalo qui
    form = getattr(request.state, "_parsed_form", None)
    if form is None:
        form = await request.form()

    file = form.get("file")
    period = form.get("period")  # atteso formato YYYY-MM

    if file is None or not getattr(file, "filename", None):
        return JSONResponse({"error": "Nessun file selezionato"}, status_code=400)

    if not period:
        return JSONResponse({"error": "Periodo mancante"}, status_code=400)

    # Validazione periodo di riferimento
    try:
        # Aggiunge "-01" solo per validare come data
        datetime.strptime(f"{period}-01", "%Y-%m-%d")
    except ValueError:
        return JSONResponse({"error": "Periodo non valido. Usa formato YYYY-MM"}, status_code=400)

    allowed_extensions = [".csv"]
    file_ext = os.path.splitext(file.filename)[1].lower()
    if file_ext not in allowed_extensions:
        return JSONResponse(
            {"error": f"Formato file non supportato. Usa: {', '.join(allowed_extensions)}"},
            status_code=400,
        )

    from scripts.load_ulixe_rcrm_temp import load_csv

    temp_file_path = None
    deleted_rows = 0
    inserted_or_updated = 0

    try:
        # Salva file temporaneo
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as temp_file:
            content = await file.read()
            temp_file.write(content)
            temp_file_path = temp_file.name

        # Rimuovi tutte le righe esistenti per il periodo selezionato
        deleted_rows = (
            db.query(UlixeRcrmTemp)
            .filter(UlixeRcrmTemp.period == period)
            .delete(synchronize_session=False)
        )

        # Carica nuovo file per il periodo
        inserted_or_updated = load_csv(temp_file_path, period, db)
        db.commit()

        # Registra nel riepilogo ingestion come upload manuale RCRM Ulixe
        try:
            details = {
                "ulixe_rcrm": {
                    "type": "manual_upload",
                    "period": period,
                    "file_name": file.filename,
                    "deleted_before": int(deleted_rows),
                    "rows_loaded": int(inserted_or_updated),
                }
            }
            sync_log = SyncLog(status="SUCCESS", details=details)
            db.add(sync_log)
            db.commit()
        except Exception as log_exc:
            logger.error(
                f"Errore salvataggio SyncLog per upload RCRM Ulixe: {log_exc}",
                exc_info=True,
            )

        return JSONResponse(
            {
                "success": True,
                "message": "File RCRM Ulixe processato con successo",
                "period": period,
                "deleted_before": deleted_rows,
                "rows_loaded": inserted_or_updated,
            }
        )

    except Exception as e:
        logger.error(f"Errore upload RCRM Ulixe: {e}", exc_info=True)
        db.rollback()

        # Prova a registrare comunque il fallimento nel riepilogo ingestion
        try:
            error_details = {
                "error": str(e),
                "stats": {
                    "ulixe_rcrm": {
                        "type": "manual_upload",
                        "period": period,
                        "file_name": getattr(file, "filename", None),
                        "errors": 1,
                    }
                },
            }
            sync_log = SyncLog(status="ERROR", details=error_details)
            db.add(sync_log)
            db.commit()
        except Exception as log_exc:
            logger.error(
                f"Errore salvataggio SyncLog per upload RCRM Ulixe fallito: {log_exc}",
                exc_info=True,
            )

        return JSONResponse(
            {"error": f"Errore durante il processamento: {str(e)}"}, status_code=500
        )

    finally:
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.unlink(temp_file_path)
            except Exception:
                pass

@router.post("/api/ulixe/sync")
async def api_ulixe_sync(request: Request, db: Session = Depends(get_db)):
    """API endpoint per sincronizzazione Ulixe con user_id specifici (max 10)"""
    user = request.session.get('user')
    if not user:
        return JSONResponse({"success": False, "error": "Non autorizzato"}, status_code=401)
    
    from services.integrations.ulixe import UlixeClient
    from config import settings
    
    try:
        data = await request.json()
        user_ids = data.get("user_ids", [])
        
        # Validazione
        if not settings.ULIXE_USER or not settings.ULIXE_PASSWORD or not settings.ULIXE_WSDL:
            return JSONResponse({
                "success": False,
                "error": "Credenziali Ulixe non configurate. Sync disabilitata."
            }, status_code=400)
        
        if not user_ids:
            return JSONResponse({
                "success": False,
                "error": "Nessun user_id specificato"
            }, status_code=400)
        
        # Limita a massimo 10 chiamate
        if len(user_ids) > 10:
            return JSONResponse({
                "success": False,
                "error": f"Massimo 10 user_id consentiti. Hai specificato {len(user_ids)}."
            }, status_code=400)
        
        # Rimuovi duplicati e valori vuoti
        user_ids = list(set([uid.strip() for uid in user_ids if uid and uid.strip()]))
        
        if not user_ids:
            return JSONResponse({
                "success": False,
                "error": "Nessun user_id valido specificato"
            }, status_code=400)
        
        # Verifica che gli user_id esistano nel database
        leads = db.query(Lead).filter(Lead.external_user_id.in_(user_ids)).all()
        found_user_ids = {lead.external_user_id for lead in leads}
        missing_user_ids = set(user_ids) - found_user_ids
        
        stats = {
            "checked": 0,
            "updated": 0,
            "errors": 0,
            "not_found": len(missing_user_ids),
            "results": []
        }
        
        client = UlixeClient()
        
        # Esegui sync per ogni user_id
        for user_id in user_ids:
            try:
                # Rate limiting: 0.5s tra chiamate per non sovraccaricare Ulixe
                if stats["checked"] > 0:
                    time.sleep(0.5)
                
                # Chiama Ulixe
                status_info = client.get_lead_status(user_id)
                stats["checked"] += 1
                
                # Trova lead corrispondente
                lead = next((l for l in leads if l.external_user_id == user_id), None)
                
                if not lead:
                    stats["results"].append({
                        "user_id": user_id,
                        "status": "not_found",
                        "message": "Lead non trovata nel database"
                    })
                    continue
                
                # Check if status changed
                old_status = lead.current_status
                lead.current_status = status_info.status
                try:
                    lead.status_category = StatusCategory(status_info.category)
                except ValueError:
                    lead.status_category = StatusCategory.UNKNOWN
                lead.last_check = status_info.checked_at
                lead.updated_at = datetime.utcnow()
                
                # Save history
                history = LeadHistory(
                    lead_id=lead.id,
                    status=status_info.status,
                    status_category=lead.status_category,
                    raw_response={"raw": status_info.raw_response},
                    checked_at=status_info.checked_at
                )
                db.add(history)
                
                if old_status != status_info.status:
                    stats["updated"] += 1
                    stats["results"].append({
                        "user_id": user_id,
                        "lead_id": lead.id,
                        "status": "updated",
                        "old_status": old_status,
                        "new_status": status_info.status,
                        "category": status_info.category
                    })
                else:
                    stats["results"].append({
                        "user_id": user_id,
                        "lead_id": lead.id,
                        "status": "unchanged",
                        "current_status": status_info.status
                    })
                
            except Exception as e:
                stats["errors"] += 1
                logger.error(f"Error checking Ulixe for user_id {user_id}: {e}")
                stats["results"].append({
                    "user_id": user_id,
                    "status": "error",
                    "error": str(e)
                })
        
        db.commit()

        # Registra la sync manuale Ulixe nel riepilogo ingestion
        try:
            sync_log = SyncLog(
                status="SUCCESS",
                details={
                    "ulixe": {
                        "type": "manual_api",
                        "user_ids_count": len(user_ids),
                        "checked": stats.get("checked", 0),
                        "updated": stats.get("updated", 0),
                        "errors": stats.get("errors", 0),
                        "not_found": stats.get("not_found", 0),
                    }
                },
            )
            db.add(sync_log)
            db.commit()
        except Exception as log_exc:
            logger.error(f"Errore salvataggio SyncLog per sync Ulixe manuale: {log_exc}", exc_info=True)
        
        return JSONResponse({
            "success": True,
            "stats": stats,
            "message": f"Sync completata: {stats['checked']} controllati, {stats['updated']} aggiornati, {stats['errors']} errori"
        })
        
    except ValueError as e:
        # UlixeClient initialization error
        return JSONResponse({
            "success": False,
            "error": f"Errore configurazione Ulixe: {str(e)}"
        }, status_code=400)
    except Exception as e:
        logger.error(f"Error in Ulixe sync: {e}", exc_info=True)
        db.rollback()

        # Prova a registrare il fallimento nel riepilogo ingestion
        try:
            error_details = {
                "error": str(e),
                "stats": {
                    "ulixe": {
                        "type": "manual_api",
                        "errors": 1,
                    }
                },
            }
            sync_log = SyncLog(status="ERROR", details=error_details)
            db.add(sync_log)
            db.commit()
        except Exception as log_exc:
            logger.error(f"Errore salvataggio SyncLog per sync Ulixe fallita: {log_exc}", exc_info=True)

        return JSONResponse({
            "success": False,
            "error": f"Errore: {str(e)}"
        }, status_code=500)
