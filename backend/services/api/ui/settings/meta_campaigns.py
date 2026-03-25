"""Settings: Gestione Campagne Meta"""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session, joinedload
from database import get_db
from models import MetaAccount, MetaCampaign, User, IngestionJob
from services.utils.crypto import decrypt_token
from database import SessionLocal
from datetime import datetime
from pathlib import Path
import logging
import traceback
import time
from ..common import templates
from celery_app import celery_app

logger = logging.getLogger('services.api.ui')

router = APIRouter(include_in_schema=False)

def sync_meta_account_task_with_filters(db: Session, account_id: str, access_token: str, filters: dict):
    """Background task per sincronizzazione account Meta con filtri"""
    from services.integrations.meta_marketing import MetaMarketingService
    try:
        logger.info(f"[SYNC TASK] Starting background sync task for account {account_id} with filters: {filters}")
        service = MetaMarketingService(access_token=access_token)
        logger.info(f"[SYNC TASK] MetaMarketingService initialized, calling sync_account_campaigns with filters")
        service.sync_account_campaigns(account_id, db, filters=filters)
        logger.info(f"[SYNC TASK] Meta account {account_id} synced successfully with filters")
    except Exception as e:
        error_traceback = traceback.format_exc()
        logger.error(f"[SYNC TASK] Meta account sync failed for {account_id}: {e}")
        logger.error(f"[SYNC TASK] Traceback: {error_traceback}")
    finally:
        try:
            db.close()
        except Exception as e:
            logger.warning(f"[SYNC TASK] Error closing DB session: {e}")

@router.get("/settings/meta-campaigns")
async def settings_meta_campaigns(request: Request, db: Session = Depends(get_db)):
    user_session = request.session.get('user')
    if not user_session:
        return RedirectResponse(url='/')
    
    current_user = db.query(User).filter(User.email == user_session.get('email')).first()
    if not current_user:
        return RedirectResponse(url='/')
    
    accounts = db.query(MetaAccount).filter(
        MetaAccount.is_active == True,
    ).all()
    
    # Recupera i filtri master dalla sessione (usati solo per ingestion, non per visualizzazione)
    master_filter = request.session.get('meta_campaigns_master_filter', {})
    
    # Mostra TUTTE le campagne sincronizzate degli account accessibili all'utente
    # Il filtro master viene applicato solo durante l'ingestion (sync), non sulla visualizzazione
    account_ids = [acc.id for acc in accounts]
    campaigns = []
    
    if account_ids:
        # Mostra tutte le campagne sincronizzate, senza filtri sulla visualizzazione
        campaigns = db.query(MetaCampaign).options(joinedload(MetaCampaign.account)).filter(
            MetaCampaign.account_id.in_(account_ids)
        ).all()
        logger.info(f"Found {len(campaigns)} total campaigns (master filter for ingestion only: {master_filter})")
    else:
        logger.info("No accounts found for user")
    
    return templates.TemplateResponse(request, "settings_meta_campaigns.html", {
        "request": request,
        "title": "Gestione Campagne Meta",
        "user": current_user,
        "accounts": accounts,
        "campaigns": campaigns,
        "master_filter": master_filter,
        "active_page": "meta_campaigns"
    })


@router.get("/api/tasks/{task_id}/status")
async def api_task_status(task_id: str, request: Request):
    """
    Restituisce lo stato di un task Celery dato il task_id.
    Usato dal front-end per mostrare \"processo in esecuzione\" / completato.
    """
    if not request.session.get("user"):
        return JSONResponse({"success": False, "error": "Non autorizzato"}, status_code=401)
    
    try:
        async_result = celery_app.AsyncResult(task_id)
        state = async_result.state
        ready = async_result.ready()
        response = {
            "success": True,
            "task_id": task_id,
            "state": state,
            "ready": ready,
        }
        if async_result.failed():
            # info può essere un'eccezione o un dict
            info = async_result.info
            response["error"] = str(info)
        return JSONResponse(response)
    except Exception as e:
        logger.exception("api_task_status")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.post("/api/meta-campaigns/bootstrap")
async def api_meta_campaigns_bootstrap(request: Request, db: Session = Depends(get_db)):
    """Avvia bootstrap meta_campaigns (periodo con impression). Richiede start_date, end_date (YYYY-MM-DD)."""
    if not request.session.get("user"):
        return JSONResponse({"success": False, "error": "Non autorizzato"}, status_code=401)
    try:
        data = await request.json()
        start_date = (data.get("start_date") or "").strip()
        end_date = (data.get("end_date") or "").strip()
        if not start_date or not end_date:
            return JSONResponse({"success": False, "error": "start_date e end_date obbligatori (YYYY-MM-DD)"}, status_code=400)
        from datetime import date
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
        if start > end:
            return JSONResponse({"success": False, "error": "start_date deve essere <= end_date"}, status_code=400)
        from tasks.meta_marketing import meta_campaigns_bootstrap_task

        # Registra un job di ingestion per il bootstrap campagne Meta
        job = IngestionJob(
            job_type="meta_campaigns_bootstrap",
            status="PENDING",
            params={
                "source": "meta_campaigns_page",
                "start_date": start_date,
                "end_date": end_date,
            },
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        t = meta_campaigns_bootstrap_task.delay(start_date, end_date, dry_run=False, job_id=job.id)

        job.celery_task_id = t.id
        job.status = "QUEUED"
        db.commit()

        return JSONResponse(
            {
                "success": True,
                "task_id": t.id,
                "job_id": job.id,
                "message": "Bootstrap avviato in background.",
            }
        )
    except ValueError as e:
        return JSONResponse({"success": False, "error": f"Date non valide: {e}"}, status_code=400)
    except Exception as e:
        logger.exception("api_meta_campaigns_bootstrap")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.post("/api/meta-campaigns/incremental-sync")
async def api_meta_campaigns_incremental_sync(request: Request, db: Session = Depends(get_db)):
    """Avvia sync incrementale meta_campaigns per una data (default ieri). Richiede target_date (YYYY-MM-DD) opzionale."""
    if not request.session.get("user"):
        return JSONResponse({"success": False, "error": "Non autorizzato"}, status_code=401)
    try:
        data = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        if not data:
            data = {}
        target_date = (data.get("target_date") or "").strip()
        from tasks.meta_marketing import meta_campaigns_incremental_task

        # Registra un job di ingestion per la sync incrementale campagne Meta
        job = IngestionJob(
            job_type="meta_campaigns_incremental",
            status="PENDING",
            params={
                "source": "meta_campaigns_page",
                "target_date": target_date or None,
            },
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        t = meta_campaigns_incremental_task.delay(target_date if target_date else None, job_id=job.id)

        job.celery_task_id = t.id
        job.status = "QUEUED"
        db.commit()

        return JSONResponse(
            {
                "success": True,
                "task_id": t.id,
                "job_id": job.id,
                "message": "Sync incrementale avviata in background.",
            }
        )
    except Exception as e:
        logger.exception("api_meta_campaigns_incremental_sync")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.post("/settings/meta-campaigns/filter")
async def filter_meta_campaigns(request: Request, db: Session = Depends(get_db)):
    """Deprecato: la pagina meta-campaigns è ora sola lettura. Redirect senza sync."""
    return RedirectResponse(url='/settings/meta-campaigns', status_code=303)

def sync_meta_accounts_sequentially(account_ids: list, filters: dict):
    """
    Sincronizza gli account uno per volta in sequenza per evitare rate limiting.
    Processa un account, attende, poi passa al successivo.
    """
    from services.integrations.meta_marketing import MetaMarketingService
    from services.utils.crypto import decrypt_token
    from models import MetaAccount
    
    logger.info(f"[SYNC SEQUENTIAL] Starting sequential sync for {len(account_ids)} accounts")
    
    for idx, account_id in enumerate(account_ids, 1):
        db = SessionLocal()
        try:
            logger.info(f"[SYNC SEQUENTIAL] Processing account {idx}/{len(account_ids)}: {account_id}")
            
            # Recupera l'account dal database
            account = db.query(MetaAccount).filter(MetaAccount.account_id == account_id).first()
            if not account or not account.is_active:
                logger.warning(f"[SYNC SEQUENTIAL] Account {account_id} non trovato o non attivo, skip")
                continue
            
            # Decripta il token
            decrypted_token = decrypt_token(account.access_token)
            
            # Crea il service e sincronizza
            service = MetaMarketingService(access_token=decrypted_token)
            logger.info(f"[SYNC SEQUENTIAL] Syncing account {account_id} ({account.name})...")
            service.sync_account_campaigns(account_id, db, filters=filters)
            logger.info(f"[SYNC SEQUENTIAL] Account {account_id} synced successfully")
            
            # Attendi tra un account e l'altro per evitare rate limiting
            if idx < len(account_ids):
                wait_time = 30  # 30 secondi tra un account e l'altro
                logger.info(f"[SYNC SEQUENTIAL] Waiting {wait_time} seconds before processing next account...")
                time.sleep(wait_time)
                
        except Exception as e:
            error_traceback = traceback.format_exc()
            logger.error(f"[SYNC SEQUENTIAL] Error syncing account {account_id}: {e}")
            logger.error(f"[SYNC SEQUENTIAL] Traceback: {error_traceback}")
        finally:
            try:
                db.close()
            except Exception as e:
                logger.warning(f"[SYNC SEQUENTIAL] Error closing DB session: {e}")
    
    logger.info(f"[SYNC SEQUENTIAL] Sequential sync completed for all {len(account_ids)} accounts")

@router.get("/settings/meta-campaigns/reset")
async def reset_meta_campaigns_filter(request: Request, db: Session = Depends(get_db)):
    """Rimuove i filtri master dalla sessione"""
    if not request.session.get('user'): 
        return RedirectResponse(url='/')
    
    # Rimuovi i filtri dalla sessione
    if 'meta_campaigns_master_filter' in request.session:
        del request.session['meta_campaigns_master_filter']
        logger.info("[FILTER] Master filter removed from session")
    
    return RedirectResponse(url='/settings/meta-campaigns', status_code=303)

@router.get("/settings/meta-campaigns/logs")
async def sync_logs_viewer(request: Request, db: Session = Depends(get_db)):
    """Visualizza i log delle attività di sincronizzazione"""
    user_session = request.session.get('user')
    if not user_session:
        return RedirectResponse(url='/')
    
    current_user = db.query(User).filter(User.email == user_session.get('email')).first()
    if not current_user:
        return RedirectResponse(url='/')
    
    accounts = db.query(MetaAccount).filter(
        MetaAccount.is_active == True,
    ).all()
    
    # Parametri di filtro
    account_id_filter = request.query_params.get('account_id', '')
    level_filter = request.query_params.get('level', '')
    lines_filter = request.query_params.get('lines', '100')
    
    # Leggi il file di log
    # Da settings/meta_campaigns.py -> settings -> ui -> api -> services -> backend
    base_dir = Path(__file__).parent.parent.parent.parent.parent
    log_file = base_dir / "logs" / "app.log"
    
    # Fallback: prova anche il percorso relativo
    if not log_file.exists():
        log_file = Path("logs/app.log")
    
    logs = []
    if log_file.exists():
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                all_lines = f.readlines()
            
            # Filtra solo i log di sync
            sync_lines = []
            for line in all_lines:
                # Cerca log con [SYNC] o [SYNC TASK]
                if '[SYNC]' in line or '[SYNC TASK]' in line:
                    # Filtra per account se specificato
                    if account_id_filter:
                        if account_id_filter not in line:
                            continue
                    
                    # Filtra per livello se specificato
                    if level_filter:
                        if f' - {level_filter} - ' not in line:
                            continue
                    
                    sync_lines.append(line.strip())
            
            # Prendi le ultime N righe
            if lines_filter == 'all':
                logs = sync_lines
            else:
                try:
                    num_lines = int(lines_filter)
                    logs = sync_lines[-num_lines:] if len(sync_lines) > num_lines else sync_lines
                except ValueError:
                    logs = sync_lines[-100:]
            
            # Inverti l'ordine per mostrare i più recenti in alto
            logs.reverse()
            
        except Exception as e:
            logger.error(f"Error reading log file: {e}")
            logs = [f"Errore nella lettura del file di log: {e}"]
    else:
        logs = ["File di log non trovato. Assicurati che il logging sia configurato correttamente."]
    
    return templates.TemplateResponse(request, "settings_meta_campaigns_logs.html", {
        "request": request,
        "title": "Log Sincronizzazione",
        "user": current_user,
        "accounts": accounts,
        "logs": logs,
        "selected_account_id": account_id_filter,
        "selected_level": level_filter,
        "selected_lines": lines_filter,
        "active_page": "meta_campaigns"
    })

@router.post("/settings/meta-campaigns/filters")
async def update_campaign_filters(request: Request, db: Session = Depends(get_db)):
    if not request.session.get('user'): return RedirectResponse(url='/')
    form = await request.form()
    
    campaign_id = form.get("id")
    tag_filter = form.get("tag_filter", "").strip()
    name_pattern = form.get("name_pattern", "").strip()
    sync_enabled = form.get("sync_enabled") == "on"
    
    if campaign_id:
        campaign = db.query(MetaCampaign).filter(MetaCampaign.id == campaign_id).first()
        if campaign:
            filters = {}
            if tag_filter:
                filters['tag'] = tag_filter
            if name_pattern:
                filters['name_pattern'] = name_pattern
            
            campaign.sync_filters = filters
            campaign.is_synced = sync_enabled
            campaign.updated_at = datetime.utcnow()
            db.commit()
    
    return RedirectResponse(url='/settings/meta-campaigns', status_code=303)
