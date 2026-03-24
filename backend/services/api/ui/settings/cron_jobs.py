"""Settings: Gestione Cron Jobs"""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from database import get_db
from models import CronJob, ManagedCampaign
from datetime import datetime
import logging
from ..common import templates, require_super_admin
from services.cron_scheduler_reload_signal import notify_cron_scheduler_reload

logger = logging.getLogger('services.api.ui')

router = APIRouter(include_in_schema=False)

@router.get("/settings/cron-jobs")
async def settings_cron_jobs(request: Request, db: Session = Depends(get_db)):
    """Pagina gestione cron jobs - Solo super-admin"""
    current_user, redirect = require_super_admin(request, db)
    if redirect:
        return redirect
    
    # Recupera tutti i cron jobs
    cron_jobs = db.query(CronJob).order_by(CronJob.job_name).all()
    
    # Definisci i job di default per ogni integrazione
    default_jobs = [
        {
            "job_name": "nightly_sync",
            "job_type": "orchestrator",
            "enabled": False,
            "hour": 0,
            "minute": 30,
            "day_of_week": "*",
            "day_of_month": "*",
            "month": "*",
            "description": "Sync completo notturno - esegue tutti i job di sincronizzazione"
        },
        {
            "job_name": "magellano_export_pipeline",
            "job_type": "magellano",
            "enabled": False,
            "hour": 1,
            "minute": 0,
            "day_of_week": "*",
            "day_of_month": "*",
            "month": "*",
            "description": "Magellano - Pipeline automatica Export richiesto + Fetch & ingest"
        },
        {
            "job_name": "ulixe_sync",
            "job_type": "ulixe",
            "enabled": False,
            "hour": 2,
            "minute": 0,
            "day_of_week": "*",
            "day_of_month": "*",
            "month": "*",
            "description": "Sincronizzazione Ulixe - Controlla stati per lead attive"
        },
        {
            "job_name": "ulixe_rcrm_google_sync",
            "job_type": "ulixe_rcrm_google",
            "enabled": False,
            "hour": 2,
            "minute": 30,
            "day_of_week": "*",
            "day_of_month": "*",
            "month": "*",
            "description": "RCRM Ulixe - Import da Google Sheet (mese corrente, service account)"
        },
        {
            "job_name": "meta_marketing_sync",
            "job_type": "meta_marketing",
            "enabled": False,
            "hour": 3,
            "minute": 0,
            "day_of_week": "*",
            "day_of_month": "*",
            "month": "*",
            "description": "Meta Marketing - Ingestion dati marketing da Meta"
        },
        {
            "job_name": "meta_conversion_marker",
            "job_type": "meta_conversion_marker",
            "enabled": False,
            "hour": 8,
            "minute": 0,
            "day_of_week": "0-4",
            "day_of_month": "*",
            "month": "*",
            "description": "Meta Conversion Marker - Marca lead da sincronizzare (Lun-Ven)"
        },
        {
            "job_name": "meta_conversion_sync",
            "job_type": "meta_conversion",
            "enabled": False,
            "hour": 4,
            "minute": 0,
            "day_of_week": "*",
            "day_of_month": "*",
            "month": "*",
            "description": "Meta Conversion API - Invia eventi stati aggiornati"
        },
        {
            "job_name": "meta_campaigns_incremental",
            "job_type": "meta_campaigns_incremental",
            "enabled": False,
            "hour": 5,
            "minute": 0,
            "day_of_week": "*",
            "day_of_month": "*",
            "month": "*",
            "description": "Meta Campagne - Sync giornaliera campagne con impression (ieri)"
        }
    ]
    
    # Crea i job mancanti
    existing_job_names = {job.job_name for job in cron_jobs}
    new_jobs_created = False
    
    for job_data in default_jobs:
        if job_data["job_name"] not in existing_job_names:
            cron_job = CronJob(**job_data)
            db.add(cron_job)
            new_jobs_created = True
    
    if new_jobs_created:
        db.commit()
        # Ricarica tutti i cron jobs dopo il commit
        cron_jobs = db.query(CronJob).order_by(CronJob.job_name).all()
    
    # Campagne attive per selector job Magellano
    managed_campaigns = db.query(ManagedCampaign).filter(
        ManagedCampaign.is_active == True
    ).order_by(ManagedCampaign.cliente_name).all()
    
    return templates.TemplateResponse(request, "settings_cron_jobs.html", {
        "request": request,
        "title": "Gestione Cron Jobs",
        "user": current_user,
        "cron_jobs": cron_jobs,
        "managed_campaigns": managed_campaigns,
        "active_page": "cron_jobs"
    })

@router.post("/api/cron-jobs")
async def save_cron_job(request: Request, db: Session = Depends(get_db)):
    """Salva configurazione cron job - Solo super-admin"""
    current_user, redirect = require_super_admin(request, db)
    if redirect:
        return JSONResponse({"success": False, "error": "Non autorizzato"}, status_code=401)
    
    try:
        data = await request.json()
        job_id = data.get("id")
        
        if not job_id:
            return JSONResponse({"success": False, "error": "ID job richiesto"}, status_code=400)
        
        cron_job = db.query(CronJob).filter(CronJob.id == job_id).first()
        if not cron_job:
            return JSONResponse({"success": False, "error": "Job non trovato"}, status_code=404)
        
        # Aggiorna configurazione
        cron_job.enabled = data.get("enabled", cron_job.enabled)
        cron_job.hour = int(data.get("hour", cron_job.hour))
        cron_job.minute = int(data.get("minute", cron_job.minute))
        cron_job.day_of_week = data.get("day_of_week", cron_job.day_of_week) or "*"
        cron_job.day_of_month = data.get("day_of_month", cron_job.day_of_month) or "*"
        cron_job.month = data.get("month", cron_job.month) or "*"
        cron_job.updated_at = datetime.utcnow()
        
        # Config job-specifica (es. magellano: magellano_campaign_ids)
        if "config" in data:
            cron_job.config = data["config"]
        
        db.commit()

        notify_cron_scheduler_reload()

        return JSONResponse({
            "success": True,
            "message": (
                "Configurazione salvata. Il servizio scheduler applica le modifiche in automatico "
                "(se in esecuzione e raggiungibile Redis); altrimenti riavvia il container scheduler."
            ),
        })
        
    except Exception as e:
        logger.error(f"Errore salvataggio cron job: {e}", exc_info=True)
        db.rollback()
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)
