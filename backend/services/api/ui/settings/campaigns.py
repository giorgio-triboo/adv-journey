"""Settings: Gestione Campagne"""
from fastapi import APIRouter, Request, Depends, BackgroundTasks
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session, joinedload
from database import get_db, SessionLocal
from models import User, ManagedCampaign, MetaAccount, MetaDataset, MetaDatasetFetchJob
from ..common import templates, translate_error
from datetime import datetime
import logging
import secrets

logger = logging.getLogger('services.api.ui')

router = APIRouter(include_in_schema=False)

@router.get("/settings/campaigns")
async def settings_campaigns(request: Request, db: Session = Depends(get_db)):
    user_session = request.session.get('user')
    if not user_session:
        return RedirectResponse(url='/')
    
    current_user = db.query(User).filter(User.email == user_session.get('email')).first()
    if not current_user:
        return RedirectResponse(url='/')

    campaigns = db.query(ManagedCampaign).all()
    
    return templates.TemplateResponse("settings_campaigns.html", {
        "request": request,
        "title": "Gestione Campagne",
        "user": current_user,
        "campaigns": campaigns,
        "active_page": "campaigns"
    })

@router.get("/settings/meta-datasets")
async def settings_meta_datasets(request: Request, db: Session = Depends(get_db)):
    """Vista per mapping campagne Magellano → Dataset Meta"""
    user_session = request.session.get('user')
    if not user_session:
        return RedirectResponse(url='/')
    
    current_user = db.query(User).filter(User.email == user_session.get('email')).first()
    if not current_user:
        return RedirectResponse(url='/')
    
    # Recupera tutte le campagne attive
    campaigns = db.query(ManagedCampaign).filter(ManagedCampaign.is_active == True).order_by(ManagedCampaign.cliente_name).all()
    
    # Recupera i dataset salvati nel DB (collegati agli account accessibili)
    accounts = db.query(MetaAccount).filter(
        MetaAccount.is_active == True,
        (MetaAccount.user_id == None) | (MetaAccount.user_id == current_user.id)
    ).all()
    account_ids = [acc.id for acc in accounts]
    
    datasets = []
    if account_ids:
        datasets = db.query(MetaDataset).options(joinedload(MetaDataset.account)).filter(
            MetaDataset.is_active == True,
            MetaDataset.account_id.in_(account_ids)
        ).all()
    
    return templates.TemplateResponse("settings_meta_datasets.html", {
        "request": request,
        "title": "Mapping Dataset Meta",
        "user": current_user,
        "campaigns": campaigns,
        "datasets": datasets,
        "active_page": "meta_datasets"
    })

@router.get("/settings/meta-datasets/select-accounts")
async def settings_meta_datasets_select_accounts(request: Request, db: Session = Depends(get_db)):
    """Pagina di selezione account per recuperare dataset"""
    user_session = request.session.get('user')
    if not user_session:
        return RedirectResponse(url='/')
    
    current_user = db.query(User).filter(User.email == user_session.get('email')).first()
    if not current_user:
        return RedirectResponse(url='/')
    
    # Recupera account accessibili
    accounts = db.query(MetaAccount).filter(
        MetaAccount.is_active == True,
        (MetaAccount.user_id == None) | (MetaAccount.user_id == current_user.id)
    ).all()
    
    # Verifica quali account hanno già dataset salvati
    existing_datasets = db.query(MetaDataset).filter(
        MetaDataset.is_active == True,
        MetaDataset.account_id.in_([acc.id for acc in accounts])
    ).all()
    accounts_with_datasets = {ds.account_id for ds in existing_datasets if ds.account_id}
    
    for account in accounts:
        account.has_datasets = account.id in accounts_with_datasets
    
    return templates.TemplateResponse("settings_meta_datasets_select.html", {
        "request": request,
        "title": "Seleziona Account per Dataset",
        "user": current_user,
        "accounts": accounts,
        "active_page": "meta_datasets"
    })

def fetch_datasets_background_task(job_id: int, account_ids: list, user_id: int):
    """Task in background per recuperare dataset dagli account"""
    db = SessionLocal()
    try:
        from services.integrations.meta_marketing import MetaMarketingService
        from services.utils.crypto import decrypt_token
        from models import MetaAccount, MetaDataset
        
        job = db.query(MetaDatasetFetchJob).filter(MetaDatasetFetchJob.id == job_id).first()
        if not job:
            logger.error(f"Job {job_id} not found")
            return
        
        job.status = "processing"
        db.commit()
        
        all_datasets = []
        account_map = {}
        
        for account_id in account_ids:
            try:
                account = db.query(MetaAccount).filter(
                    MetaAccount.id == account_id,
                    MetaAccount.is_active == True
                ).first()
                
                if not account or not account.access_token:
                    continue
                
                account_map[account_id] = {
                    'name': account.name,
                    'account_id': account.account_id
                }
                
                # Recupera dataset dall'account
                decrypted_token = decrypt_token(account.access_token)
                service = MetaMarketingService(access_token=decrypted_token)
                datasets = service.get_datasets(account_id=account.account_id)
                
                # Aggiungi informazioni account a ogni dataset
                for dataset_data in datasets:
                    dataset_id = dataset_data.get('dataset_id')
                    if not dataset_id:
                        continue
                    
                    all_datasets.append({
                        'dataset_id': dataset_id,
                        'name': dataset_data.get('name', f"Dataset {dataset_id}"),
                        'account_id': account.id,
                        'account_name': account.name,
                        'account_account_id': account.account_id
                    })
                
            except Exception as e:
                logger.error(f"Error fetching datasets for account {account_id}: {e}")
                continue
        
        if not all_datasets:
            job.status = "error"
            job.error_message = "Nessun dataset trovato"
            job.completed_at = datetime.utcnow()
            db.commit()
            return
        
        # Verifica quali dataset sono già salvati nel DB
        existing_datasets = db.query(MetaDataset).filter(
            MetaDataset.dataset_id.in_([d['dataset_id'] for d in all_datasets])
        ).all()
        existing_dataset_ids = {ds.dataset_id for ds in existing_datasets}
        
        # Aggiungi flag per dataset esistenti
        for dataset in all_datasets:
            dataset['already_saved'] = dataset['dataset_id'] in existing_dataset_ids
        
        # Salva risultati nel job
        job.status = "completed"
        job.datasets = all_datasets
        job.account_map = account_map
        job.completed_at = datetime.utcnow()
        db.commit()
        
        logger.info(f"Job {job_id} completed: {len(all_datasets)} datasets found")
        
    except Exception as e:
        logger.error(f"Error in fetch_datasets_background_task: {e}")
        job = db.query(MetaDatasetFetchJob).filter(MetaDatasetFetchJob.id == job_id).first()
        if job:
            job.status = "error"
            job.error_message = str(e)
            job.completed_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()

@router.post("/settings/meta-datasets/fetch")
async def fetch_datasets(request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Avvia recupero dataset dagli account selezionati in background"""
    user_session = request.session.get('user')
    if not user_session:
        return RedirectResponse(url='/')
    
    current_user = db.query(User).filter(User.email == user_session.get('email')).first()
    if not current_user:
        return RedirectResponse(url='/')
    
    form = await request.form()
    selected_account_ids = form.getlist('account_ids')
    
    if not selected_account_ids:
        return RedirectResponse(url='/settings/meta-datasets?error=no_accounts_selected', status_code=303)
    
    try:
        # Crea job per tracciare il processo
        job = MetaDatasetFetchJob(
            user_id=current_user.id,
            status="pending"
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        
        # Converti account IDs a int
        account_ids = [int(aid) for aid in selected_account_ids]
        
        # Avvia task in background
        background_tasks.add_task(
            fetch_datasets_background_task,
            job.id,
            account_ids,
            current_user.id
        )
        
        return RedirectResponse(url=f'/settings/meta-datasets/select-datasets?job_id={job.id}', status_code=303)
            
    except Exception as e:
        logger.error(f"Error in fetch_datasets: {e}")
        return RedirectResponse(url=f'/settings/meta-datasets?error={str(e)}', status_code=303)

@router.get("/api/meta-datasets/fetch-status/{job_id}")
async def fetch_datasets_status(job_id: int, request: Request, db: Session = Depends(get_db)):
    """API endpoint per verificare lo stato del job di recupero dataset"""
    user_session = request.session.get('user')
    if not user_session:
        return JSONResponse({"error": "Non autorizzato"}, status_code=401)
    
    current_user = db.query(User).filter(User.email == user_session.get('email')).first()
    if not current_user:
        return JSONResponse({"error": "Non autorizzato"}, status_code=401)
    
    job = db.query(MetaDatasetFetchJob).filter(
        MetaDatasetFetchJob.id == job_id,
        MetaDatasetFetchJob.user_id == current_user.id
    ).first()
    
    if not job:
        return JSONResponse({"error": "Job non trovato"}, status_code=404)
    
    return JSONResponse({
        "status": job.status,
        "datasets": job.datasets if job.datasets else [],
        "account_map": job.account_map if job.account_map else {},
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None
    })

@router.get("/settings/meta-datasets/select-datasets")
async def settings_meta_datasets_select_datasets(request: Request, db: Session = Depends(get_db)):
    """Pagina di selezione dataset recuperati"""
    user_session = request.session.get('user')
    if not user_session:
        return RedirectResponse(url='/')
    
    current_user = db.query(User).filter(User.email == user_session.get('email')).first()
    if not current_user:
        return RedirectResponse(url='/')
    
    # Recupera job_id dalla query string
    job_id = request.query_params.get('job_id')
    if not job_id:
        return RedirectResponse(url='/settings/meta-datasets?error=no_job_id', status_code=303)
    
    try:
        job_id = int(job_id)
    except ValueError:
        return RedirectResponse(url='/settings/meta-datasets?error=invalid_job_id', status_code=303)
    
    # Recupera job dal database
    job = db.query(MetaDatasetFetchJob).filter(
        MetaDatasetFetchJob.id == job_id,
        MetaDatasetFetchJob.user_id == current_user.id
    ).first()
    
    if not job:
        return RedirectResponse(url='/settings/meta-datasets?error=job_not_found', status_code=303)
    
    # Se il job è ancora in processing, mostra pagina di attesa
    if job.status == "pending" or job.status == "processing":
        return templates.TemplateResponse("settings_meta_datasets_select_datasets.html", {
            "request": request,
            "title": "Recupero Dataset",
            "user": current_user,
            "job_id": job_id,
            "status": job.status,
            "datasets": [],
            "account_map": {},
            "new_datasets_count": 0,
            "total_datasets": 0,
            "active_page": "meta_datasets"
        })
    
    # Se c'è un errore
    if job.status == "error":
        return RedirectResponse(url=f'/settings/meta-datasets?error={job.error_message or "Errore durante il recupero"}', status_code=303)
    
    # Job completato, mostra dataset
    datasets = job.datasets if job.datasets else []
    account_map = job.account_map if job.account_map else {}
    
    # Conta nuovi dataset
    new_datasets_count = sum(1 for d in datasets if not d.get('already_saved', False))
    
    return templates.TemplateResponse("settings_meta_datasets_select_datasets.html", {
        "request": request,
        "title": "Seleziona Dataset",
        "user": current_user,
        "job_id": job_id,
        "status": job.status,
        "datasets": datasets,
        "account_map": account_map,
        "new_datasets_count": new_datasets_count,
        "total_datasets": len(datasets),
        "active_page": "meta_datasets"
    })

@router.post("/settings/meta-datasets/save")
async def save_selected_datasets(request: Request, db: Session = Depends(get_db)):
    """Salva solo i dataset selezionati nel DB"""
    user_session = request.session.get('user')
    if not user_session:
        return RedirectResponse(url='/')
    
    current_user = db.query(User).filter(User.email == user_session.get('email')).first()
    if not current_user:
        return RedirectResponse(url='/')
    
    form = await request.form()
    job_id = form.get('job_id')
    selected_dataset_ids = form.getlist('dataset_ids')
    
    if not job_id:
        return RedirectResponse(url='/settings/meta-datasets?error=no_job_id', status_code=303)
    
    try:
        job_id = int(job_id)
    except ValueError:
        return RedirectResponse(url='/settings/meta-datasets?error=invalid_job_id', status_code=303)
    
    # Recupera job dal database
    job = db.query(MetaDatasetFetchJob).filter(
        MetaDatasetFetchJob.id == job_id,
        MetaDatasetFetchJob.user_id == current_user.id,
        MetaDatasetFetchJob.status == "completed"
    ).first()
    
    if not job or not job.datasets:
        return RedirectResponse(url='/settings/meta-datasets?error=job_not_found_or_incomplete', status_code=303)
    
    if not selected_dataset_ids:
        # Elimina il job e torna indietro
        db.delete(job)
        db.commit()
        return RedirectResponse(url='/settings/meta-datasets?info=no_datasets_selected', status_code=303)
    
    try:
        saved_count = 0
        
        # Crea un dizionario per lookup veloce
        datasets_dict = {d['dataset_id']: d for d in job.datasets}
        
        for dataset_id in selected_dataset_ids:
            dataset_data = datasets_dict.get(dataset_id)
            if not dataset_data:
                continue
            
            # Verifica se esiste già
            existing = db.query(MetaDataset).filter(
                MetaDataset.dataset_id == dataset_id
            ).first()
            
            if existing:
                # Aggiorna se necessario
                if existing.account_id != dataset_data['account_id']:
                    existing.account_id = dataset_data['account_id']
                    existing.name = dataset_data['name']
                    existing.is_active = True
                    existing.updated_at = datetime.utcnow()
            else:
                # Crea nuovo
                new_dataset = MetaDataset(
                    dataset_id=dataset_id,
                    name=dataset_data['name'],
                    account_id=dataset_data['account_id'],
                    is_active=True
                )
                db.add(new_dataset)
            
            saved_count += 1
        
        # Elimina il job dopo il salvataggio
        db.delete(job)
        db.commit()
        
        return RedirectResponse(url=f'/settings/meta-datasets?success={saved_count}_datasets_saved', status_code=303)
            
    except Exception as e:
        logger.error(f"Error in save_selected_datasets: {e}")
        db.rollback()
        return RedirectResponse(url=f'/settings/meta-datasets?error={str(e)}', status_code=303)

@router.post("/settings/meta-datasets/delete")
async def delete_meta_dataset(request: Request, db: Session = Depends(get_db)):
    """Elimina un dataset salvato"""
    user_session = request.session.get('user')
    if not user_session:
        return RedirectResponse(url='/')
    
    current_user = db.query(User).filter(User.email == user_session.get('email')).first()
    if not current_user:
        return RedirectResponse(url='/')
    
    form = await request.form()
    dataset_id = form.get("dataset_id")
    
    if not dataset_id:
        return RedirectResponse(url='/settings/meta-datasets?error=missing_dataset_id', status_code=303)
    
    try:
        # Verifica che il dataset esista e sia collegato a un account accessibile all'utente
        dataset = db.query(MetaDataset).filter(MetaDataset.id == int(dataset_id)).first()
        
        if not dataset:
            return RedirectResponse(url='/settings/meta-datasets?error=dataset_not_found', status_code=303)
        
        # Verifica che l'utente abbia accesso all'account associato al dataset
        if dataset.account_id:
            account = db.query(MetaAccount).filter(
                MetaAccount.id == dataset.account_id,
                MetaAccount.is_active == True,
                (MetaAccount.user_id == None) | (MetaAccount.user_id == current_user.id)
            ).first()
            
            if not account:
                return RedirectResponse(url='/settings/meta-datasets?error=unauthorized', status_code=303)
        
        # Rimuovi il mapping dalle campagne che usano questo dataset
        campaigns = db.query(ManagedCampaign).filter(
            ManagedCampaign.meta_dataset_id == dataset.dataset_id
        ).all()
        
        for campaign in campaigns:
            campaign.meta_dataset_id = None
        
        # Elimina il dataset
        db.delete(dataset)
        db.commit()
        
        return RedirectResponse(url='/settings/meta-datasets?success=dataset_deleted', status_code=303)
        
    except Exception as e:
        logger.error(f"Error deleting dataset: {e}")
        db.rollback()
        return RedirectResponse(url=f'/settings/meta-datasets?error={str(e)}', status_code=303)

@router.post("/settings/meta-datasets/update")
async def update_meta_dataset_mapping(request: Request, db: Session = Depends(get_db)):
    """Aggiorna mapping campagna → dataset"""
    user_session = request.session.get('user')
    if not user_session:
        return RedirectResponse(url='/')
    
    form = await request.form()
    campaign_id = form.get("campaign_id")
    dataset_id = form.get("dataset_id", "").strip() or None
    
    if not campaign_id:
        return RedirectResponse(url='/settings/meta-datasets?error=missing_campaign_id', status_code=303)
    
    campaign = db.query(ManagedCampaign).filter(ManagedCampaign.id == int(campaign_id)).first()
    
    if not campaign:
        return RedirectResponse(url='/settings/meta-datasets?error=campaign_not_found', status_code=303)
    
    campaign.meta_dataset_id = dataset_id
    db.commit()
    
    return RedirectResponse(url='/settings/meta-datasets?success=mapping_updated', status_code=303)

@router.get("/settings/campaigns/create/")
async def create_campaign(request: Request, db: Session = Depends(get_db)):
    """Pagina di creazione nuova campagna"""
    user_session = request.session.get('user')
    if not user_session:
        return RedirectResponse(url='/')
    
    current_user = db.query(User).filter(User.email == user_session.get('email')).first()
    if not current_user:
        return RedirectResponse(url='/')
    
    return templates.TemplateResponse("settings_campaigns_create.html", {
        "request": request,
        "title": "Nuova Campagna",
        "user": current_user,
        "active_page": "campaigns"
    })

@router.get("/settings/campaigns/edit/{campaign_id}")
async def edit_campaign(request: Request, campaign_id: int, db: Session = Depends(get_db)):
    """Pagina di modifica campagna"""
    user_session = request.session.get('user')
    if not user_session:
        return RedirectResponse(url='/')
    
    current_user = db.query(User).filter(User.email == user_session.get('email')).first()
    if not current_user:
        return RedirectResponse(url='/')
    
    campaign = db.query(ManagedCampaign).filter(ManagedCampaign.id == campaign_id).first()
    
    if not campaign:
        return RedirectResponse(url=f'/settings/campaigns?error={translate_error("not_found")}', status_code=303)
    
    return templates.TemplateResponse("settings_campaigns_edit.html", {
        "request": request,
        "title": f"Modifica Campagna {campaign.cliente_name}",
        "user": current_user,
        "campaign": campaign,
        "active_page": "campaigns"
    })

@router.post("/settings/campaigns/edit/{campaign_id}")
async def update_campaign(request: Request, campaign_id: int, db: Session = Depends(get_db)):
    """Aggiorna campagna esistente"""
    if not request.session.get('user'): return RedirectResponse(url='/')
    form = await request.form()
    
    campaign = db.query(ManagedCampaign).filter(ManagedCampaign.id == campaign_id).first()
    if not campaign:
        return RedirectResponse(url=f'/settings/campaigns?error={translate_error("not_found")}', status_code=303)
    
    cliente_name = form.get("cliente_name", "").strip()
    name = form.get("name", "").strip() or cliente_name
    magellano_ids_str = form.get("magellano_ids", "").strip()
    msg_ids_str = form.get("msg_ids", "").strip()
    msg_names_str = form.get("msg_names", "").strip()  # Nomi separati da virgola (opzionale)
    pay_level = form.get("pay_level", "").strip() or None
    is_active = form.get("is_active") == "on"
    
    if not cliente_name or not magellano_ids_str or not msg_ids_str:
        return RedirectResponse(url=f'/settings/campaigns/edit/{campaign_id}?error=missing_fields', status_code=303)
    
    # Parse arrays
    magellano_ids = [mid.strip() for mid in magellano_ids_str.split(",") if mid.strip()]
    msg_ids_raw = [mid.strip() for mid in msg_ids_str.split(",") if mid.strip()]
    msg_names_list = [mn.strip() for mn in msg_names_str.split(",") if mn.strip()] if msg_names_str else []
    
    # Converti msg_ids in array di oggetti con id e name
    from seeders.campaigns_seeder import MSG_ID_TO_NAME
    msg_ids_objects = []
    for i, msg_id in enumerate(msg_ids_raw):
        # Se c'è un nome fornito nel form, usalo, altrimenti usa il mapping o l'ID
        if i < len(msg_names_list) and msg_names_list[i]:
            name_value = msg_names_list[i]
        else:
            name_value = MSG_ID_TO_NAME.get(msg_id, msg_id)
        msg_ids_objects.append({"id": msg_id, "name": name_value})
    
    # ID Messaggio e ID Ulixe sono la stessa cosa, sincronizziamo automaticamente
    ulixe_ids = msg_ids_raw.copy()
    
    # Check if cliente_name changed and if it conflicts with another campaign
    if cliente_name != campaign.cliente_name:
        existing = db.query(ManagedCampaign).filter(
            ManagedCampaign.cliente_name == cliente_name,
            ManagedCampaign.id != campaign_id
        ).first()
        if existing:
            return RedirectResponse(url=f'/settings/campaigns/edit/{campaign_id}?error=cliente_name_exists', status_code=303)
    
    campaign.cliente_name = cliente_name
    campaign.name = name
    campaign.magellano_ids = magellano_ids
    campaign.msg_ids = msg_ids_objects
    campaign.pay_level = pay_level
    campaign.ulixe_ids = ulixe_ids
    # meta_dataset_id viene gestito nella vista separata /settings/meta-datasets
    campaign.is_active = is_active
    
    db.commit()
    return RedirectResponse(url='/settings/campaigns?success=updated', status_code=303)

@router.post("/settings/campaigns")
async def add_campaign(request: Request, db: Session = Depends(get_db)):
    if not request.session.get('user'): return RedirectResponse(url='/')
    form = await request.form()
    
    cliente_name = form.get("cliente_name", "").strip()
    name = form.get("name", "").strip() or cliente_name
    magellano_ids_str = form.get("magellano_ids", "").strip()
    msg_ids_str = form.get("msg_ids", "").strip()
    msg_names_str = form.get("msg_names", "").strip()  # Nomi separati da virgola (opzionale)
    pay_level = form.get("pay_level", "").strip() or None
    is_active = form.get("is_active") == "on"
    
    if not cliente_name or not magellano_ids_str or not msg_ids_str:
        return RedirectResponse(url='/settings/campaigns/create/?error=missing_fields', status_code=303)
    
    # Parse arrays
    magellano_ids = [mid.strip() for mid in magellano_ids_str.split(",") if mid.strip()]
    msg_ids_raw = [mid.strip() for mid in msg_ids_str.split(",") if mid.strip()]
    msg_names_list = [mn.strip() for mn in msg_names_str.split(",") if mn.strip()] if msg_names_str else []
    
    # Converti msg_ids in array di oggetti con id e name
    from seeders.campaigns_seeder import MSG_ID_TO_NAME
    msg_ids_objects = []
    for i, msg_id in enumerate(msg_ids_raw):
        # Se c'è un nome fornito nel form, usalo, altrimenti usa il mapping o l'ID
        if i < len(msg_names_list) and msg_names_list[i]:
            name_value = msg_names_list[i]
        else:
            name_value = MSG_ID_TO_NAME.get(msg_id, msg_id)
        msg_ids_objects.append({"id": msg_id, "name": name_value})
    
    # ID Messaggio e ID Ulixe sono la stessa cosa, sincronizziamo automaticamente
    ulixe_ids = msg_ids_raw.copy()
    
    # Check if exists (by cliente_name, which is unique)
    existing = db.query(ManagedCampaign).filter(ManagedCampaign.cliente_name == cliente_name).first()
    if existing:
        existing.name = name
        existing.magellano_ids = magellano_ids
        existing.msg_ids = msg_ids_objects
        existing.pay_level = pay_level
        existing.ulixe_ids = ulixe_ids
        existing.is_active = is_active
    else:
        new_campaign = ManagedCampaign(
            cliente_name=cliente_name,
            name=name,
            magellano_ids=magellano_ids,
            msg_ids=msg_ids_objects,
            pay_level=pay_level,
            ulixe_ids=ulixe_ids,
            is_active=is_active
        )
        db.add(new_campaign)
    
    db.commit()
    return RedirectResponse(url='/settings/campaigns?success=created', status_code=303)

@router.post("/settings/campaigns/delete")
async def delete_campaign(request: Request, db: Session = Depends(get_db)):
    if not request.session.get('user'): return RedirectResponse(url='/')
    form = await request.form()
    camp_id = form.get("id")
    if camp_id:
        db.query(ManagedCampaign).filter(ManagedCampaign.id == camp_id).delete()
        db.commit()
    return RedirectResponse(url='/settings/campaigns', status_code=303)
