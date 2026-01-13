from fastapi import APIRouter, Request, Depends, BackgroundTasks
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from database import get_db
from models import Lead, StatusCategory, User
from services.integrations.magellano import MagellanoService
from datetime import datetime, timedelta, date
from typing import List
import logging
import httpx
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

router = APIRouter(include_in_schema=False)
import os
# In Docker: frontend è montato in /app/frontend
# In sviluppo locale: calcola percorso relativo alla root del progetto
if os.path.exists("frontend"):
    FRONTEND_DIR = "frontend"  # Docker container
else:
    # Da services/api/ui.py -> services/api -> services -> backend -> root
    FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "frontend")

templates = Jinja2Templates(directory=os.path.join(FRONTEND_DIR, "templates"))

@router.get("/dashboard")
async def dashboard(request: Request, db: Session = Depends(get_db)):
    user = request.session.get('user')
    if not user:
        return RedirectResponse(url='/')
    
    # Calculate stats
    total_leads = db.query(Lead).count()
    in_processing = db.query(Lead).filter(Lead.status_category == StatusCategory.IN_LAVORAZIONE).count()
    converted = db.query(Lead).filter(Lead.status_category == StatusCategory.FINALE).count() # Or CRM + FINAL

    stats = {
        "total_leads": total_leads,
        "in_processing": in_processing,
        "converted": converted
    }

    # Get recent leads
    leads = db.query(Lead).order_by(Lead.created_at.desc()).limit(50).all()

    from models import ManagedCampaign
    managed_campaigns = db.query(ManagedCampaign).filter(ManagedCampaign.is_active == True).all()

    return templates.TemplateResponse("dashboard.html", {
        "request": request, 
        "title": "Dashboard",
        "user": user,
        "stats": stats,
        "leads": leads,
        "managed_campaigns": managed_campaigns,
        "active_page": "dashboard"
    })

@router.get("/analytics")
async def analytics(request: Request, db: Session = Depends(get_db)):
    """Dashboard Analytics 360° - Viste Aggregate Marketing ↔ Feedback"""
    user = request.session.get('user')
    if not user:
        return RedirectResponse(url='/')
    
    from models import MetaAccount, MetaCampaign, MetaAd, MetaAdSet, MetaMarketingData
    from sqlalchemy import func, and_, case
    
    # Get filter parameters
    view_type = request.query_params.get('view', 'overview')  # overview, magellano_campaign, msg_id, meta_campaign, meta_adset, meta_ad
    magellano_campaign_id = request.query_params.get('magellano_campaign_id')
    msg_id_filter = request.query_params.get('msg_id')
    meta_campaign_id = request.query_params.get('meta_campaign_id')
    meta_adset_id = request.query_params.get('meta_adset_id')
    meta_ad_id = request.query_params.get('meta_ad_id')
    date_from = request.query_params.get('date_from')
    date_to = request.query_params.get('date_to')
    
    # Date filters
    date_from_obj = None
    date_to_obj = None
    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d')
        except:
            pass
    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d')
        except:
            pass
    if not date_from_obj:
        date_from_obj = datetime.now() - timedelta(days=30)
    if not date_to_obj:
        date_to_obj = datetime.now()
    
    # Base query for leads
    leads_query = db.query(Lead).filter(
        Lead.created_at >= date_from_obj,
        Lead.created_at <= date_to_obj
    )
    
    # Apply filters based on view type
    if view_type == 'magellano_campaign' and magellano_campaign_id:
        leads_query = leads_query.filter(Lead.magellano_campaign_id == magellano_campaign_id)
    elif view_type == 'msg_id' and msg_id_filter:
        leads_query = leads_query.filter(Lead.msg_id == msg_id_filter)
    elif view_type == 'meta_campaign' and meta_campaign_id:
        leads_query = leads_query.filter(Lead.meta_campaign_id == meta_campaign_id)
    elif view_type == 'meta_adset' and meta_adset_id:
        leads_query = leads_query.filter(Lead.meta_adset_id == meta_adset_id)
    elif view_type == 'meta_ad' and meta_ad_id:
        leads_query = leads_query.filter(Lead.meta_ad_id == meta_ad_id)
    
    all_leads = leads_query.all()
    
    # Calculate aggregated stats
    total_leads = len(all_leads)
    leads_by_status = {}
    for status_cat in StatusCategory:
        count = len([l for l in all_leads if l.status_category == status_cat])
        if count > 0:
            leads_by_status[status_cat.value] = count
    
    converted = leads_by_status.get('finale', 0)
    in_lavorazione = leads_by_status.get('in_lavorazione', 0)
    rifiutati = leads_by_status.get('rifiutato', 0)
    crm = leads_by_status.get('crm', 0)
    
    conversion_rate = (converted / total_leads * 100) if total_leads > 0 else 0
    
    # Aggregate by dimension based on view type
    aggregates = []
    
    if view_type == 'overview':
        # Overview generale - aggregate by status
        aggregates = [{
            'dimension': 'Totale',
            'total_leads': total_leads,
            'converted': converted,
            'in_lavorazione': in_lavorazione,
            'rifiutati': rifiutati,
            'crm': crm,
            'conversion_rate': conversion_rate
        }]
    
    elif view_type == 'magellano_campaign':
        # Aggregate by Magellano Campaign
        from collections import defaultdict
        by_campaign = defaultdict(lambda: {'total': 0, 'converted': 0, 'in_lavorazione': 0, 'rifiutati': 0, 'crm': 0})
        
        for lead in all_leads:
            camp_id = lead.magellano_campaign_id or 'N/A'
            by_campaign[camp_id]['total'] += 1
            if lead.status_category == StatusCategory.FINALE:
                by_campaign[camp_id]['converted'] += 1
            elif lead.status_category == StatusCategory.IN_LAVORAZIONE:
                by_campaign[camp_id]['in_lavorazione'] += 1
            elif lead.status_category == StatusCategory.RIFIUTATO:
                by_campaign[camp_id]['rifiutati'] += 1
            elif lead.status_category == StatusCategory.CRM:
                by_campaign[camp_id]['crm'] += 1
        
        for camp_id, stats in by_campaign.items():
            conv_rate = (stats['converted'] / stats['total'] * 100) if stats['total'] > 0 else 0
            aggregates.append({
                'dimension': f"Campagna {camp_id}",
                'total_leads': stats['total'],
                'converted': stats['converted'],
                'in_lavorazione': stats['in_lavorazione'],
                'rifiutati': stats['rifiutati'],
                'crm': stats['crm'],
                'conversion_rate': conv_rate
            })
    
    elif view_type == 'msg_id':
        # Aggregate by ID Messaggio
        from collections import defaultdict
        by_msg = defaultdict(lambda: {'total': 0, 'converted': 0, 'in_lavorazione': 0, 'rifiutati': 0, 'crm': 0})
        
        for lead in all_leads:
            msg_id = lead.msg_id or 'N/A'
            by_msg[msg_id]['total'] += 1
            if lead.status_category == StatusCategory.FINALE:
                by_msg[msg_id]['converted'] += 1
            elif lead.status_category == StatusCategory.IN_LAVORAZIONE:
                by_msg[msg_id]['in_lavorazione'] += 1
            elif lead.status_category == StatusCategory.RIFIUTATO:
                by_msg[msg_id]['rifiutati'] += 1
            elif lead.status_category == StatusCategory.CRM:
                by_msg[msg_id]['crm'] += 1
        
        for msg_id, stats in by_msg.items():
            conv_rate = (stats['converted'] / stats['total'] * 100) if stats['total'] > 0 else 0
            aggregates.append({
                'dimension': f"Msg ID {msg_id}",
                'total_leads': stats['total'],
                'converted': stats['converted'],
                'in_lavorazione': stats['in_lavorazione'],
                'rifiutati': stats['rifiutati'],
                'crm': stats['crm'],
                'conversion_rate': conv_rate
            })
    
    elif view_type in ['meta_campaign', 'meta_adset', 'meta_ad']:
        # Aggregate by Meta dimension (campaign, adset, or ad)
        from collections import defaultdict
        by_dimension = defaultdict(lambda: {'total': 0, 'converted': 0, 'in_lavorazione': 0, 'rifiutati': 0, 'crm': 0})
        
        for lead in all_leads:
            if view_type == 'meta_campaign':
                dim_value = lead.facebook_campaign_name or lead.meta_campaign_id or 'N/A'
            elif view_type == 'meta_adset':
                dim_value = lead.facebook_ad_set or lead.meta_adset_id or 'N/A'
            else:  # meta_ad
                dim_value = lead.facebook_ad_name or lead.meta_ad_id or 'N/A'
            
            by_dimension[dim_value]['total'] += 1
            if lead.status_category == StatusCategory.FINALE:
                by_dimension[dim_value]['converted'] += 1
            elif lead.status_category == StatusCategory.IN_LAVORAZIONE:
                by_dimension[dim_value]['in_lavorazione'] += 1
            elif lead.status_category == StatusCategory.RIFIUTATO:
                by_dimension[dim_value]['rifiutati'] += 1
            elif lead.status_category == StatusCategory.CRM:
                by_dimension[dim_value]['crm'] += 1
        
        for dim_value, stats in by_dimension.items():
            conv_rate = (stats['converted'] / stats['total'] * 100) if stats['total'] > 0 else 0
            aggregates.append({
                'dimension': dim_value,
                'total_leads': stats['total'],
                'converted': stats['converted'],
                'in_lavorazione': stats['in_lavorazione'],
                'rifiutati': stats['rifiutati'],
                'crm': stats['crm'],
                'conversion_rate': conv_rate
            })
    
    # Get filter options
    magellano_campaigns = db.query(Lead.magellano_campaign_id).distinct().all()
    msg_ids = db.query(Lead.msg_id).distinct().filter(Lead.msg_id.isnot(None)).all()
    meta_campaigns = db.query(Lead.facebook_campaign_name).distinct().filter(Lead.facebook_campaign_name.isnot(None)).all()
    
    return templates.TemplateResponse("analytics.html", {
        "request": request,
        "title": "Analytics 360°",
        "user": user,
        "view_type": view_type,
        "aggregates": aggregates,
        "total_leads": total_leads,
        "converted": converted,
        "in_lavorazione": in_lavorazione,
        "rifiutati": rifiutati,
        "crm": crm,
        "conversion_rate": conversion_rate,
        "magellano_campaigns": [c[0] for c in magellano_campaigns if c[0]],
        "msg_ids": [m[0] for m in msg_ids if m[0]],
        "meta_campaigns": [c[0] for c in meta_campaigns if c[0]],
        "selected_magellano_campaign_id": magellano_campaign_id,
        "selected_msg_id": msg_id_filter,
        "selected_meta_campaign_id": meta_campaign_id,
        "date_from": date_from or date_from_obj.strftime('%Y-%m-%d'),
        "date_to": date_to or date_to_obj.strftime('%Y-%m-%d'),
        "active_page": "analytics"
    })

def run_magellano_sync(db: Session, campaigns: List[int], start_date: date, end_date: date):
    logger.info(f"Starting Magellano Sync Task for campaigns {campaigns} ({start_date} to {end_date})...")
    from services.integrations.magellano import MagellanoService
    service = MagellanoService()
    try:
        leads_data = service.fetch_leads(start_date, end_date, campaigns)
        logger.info(f"Fetched {len(leads_data)} leads from Magellano.")
        
        for data in leads_data:
            # Check if exists
            magellano_id = data.get('magellano_id')
            existing = db.query(Lead).filter(Lead.magellano_id == magellano_id).first()
            
            if not existing:
                new_lead = Lead(
                    magellano_id=magellano_id,
                    external_user_id=data.get('external_user_id'),
                    email=data.get('email'),
                    first_name=data.get('first_name'),
                    last_name=data.get('last_name'),
                    phone=data.get('phone'),
                    brand=data.get('brand'),
                    msg_id=data.get('msg_id'),
                    form_id=data.get('form_id'),
                    source=data.get('source'),
                    campaign_name=data.get('campaign_name'),
                    magellano_campaign_id=data.get('magellano_campaign_id'),
                    # Facebook/Meta fields from Magellano
                    facebook_ad_name=data.get('facebook_ad_name'),
                    facebook_ad_set=data.get('facebook_ad_set'),
                    facebook_campaign_name=data.get('facebook_campaign_name'),
                    facebook_id=data.get('facebook_id'),
                    facebook_piattaforma=data.get('facebook_piattaforma'),
                    current_status='inviate WS Ulixe',
                    status_category=StatusCategory.IN_LAVORAZIONE
                )
                db.add(new_lead)
        
        db.commit()
        logger.info("Magellano Sync Task Completed Successfully.")
        
    except Exception as e:
        logger.error(f"Magellano Sync Task Failed: {e}")
        db.rollback()
    finally:
        db.close()

@router.post("/sync")
async def trigger_sync(request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    user = request.session.get('user')
    if not user:
        return RedirectResponse(url='/')
    
    form_data = await request.form()
    campaigns_str = form_data.get("campaigns", "635,669,723")
    campaigns = [int(c.strip()) for c in campaigns_str.split(",") if c.strip().isdigit()]
    
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
        end_date = today

    from database import SessionLocal
    background_tasks.add_task(run_magellano_sync, SessionLocal(), campaigns, start_date, end_date)
    
    return RedirectResponse(url='/dashboard', status_code=303)

@router.post("/sync/full")
async def trigger_full_sync(request: Request, background_tasks: BackgroundTasks):
    """Esegue il sync completo tramite orchestrator"""
    user = request.session.get('user')
    if not user:
        return RedirectResponse(url='/')
    
    from services.sync_orchestrator import SyncOrchestrator
    
    def run_full_sync():
        orchestrator = SyncOrchestrator()
        orchestrator.run_all()
    
    background_tasks.add_task(run_full_sync)
    
    return RedirectResponse(url='/dashboard?sync_started=true', status_code=303)

@router.get("/settings/users")
async def settings_users(request: Request, db: Session = Depends(get_db)):
    user_session = request.session.get('user')
    if not user_session:
        return RedirectResponse(url='/')
    
    current_user = db.query(User).filter(User.email == user_session.get('email')).first()
    if not current_user:
        return RedirectResponse(url='/')
        
    users = db.query(User).all()
    
    return templates.TemplateResponse("settings_users.html", {
        "request": request,
        "title": "Gestione Utenti",
        "user": current_user, # Passing DB user for role check
        "users": users,
        "active_page": "users"
    })

@router.get("/settings/campaigns")
async def settings_campaigns(request: Request, db: Session = Depends(get_db)):
    user_session = request.session.get('user')
    if not user_session:
        return RedirectResponse(url='/')
    
    current_user = db.query(User).filter(User.email == user_session.get('email')).first()
    if not current_user:
        return RedirectResponse(url='/')

    from models import ManagedCampaign
    campaigns = db.query(ManagedCampaign).all()
    
    return templates.TemplateResponse("settings_campaigns.html", {
        "request": request,
        "title": "Gestione Campagne",
        "user": current_user,
        "campaigns": campaigns,
        "active_page": "campaigns"
    })

@router.get("/settings")
async def settings_redirect(request: Request):
    return RedirectResponse(url='/settings/users')

@router.post("/settings/users")
async def add_user(request: Request, db: Session = Depends(get_db)):
    if not request.session.get('user'): return RedirectResponse(url='/')
    form = await request.form()
    email = form.get("email")
    role = form.get("role", "viewer")
    if email:
        new_user = User(email=email, is_active=True, role=role)
        db.add(new_user)
        db.commit()
    return RedirectResponse(url='/settings/users', status_code=303)

@router.post("/settings/users/role")
async def update_user_role(request: Request, db: Session = Depends(get_db)):
    user_session = request.session.get('user')
    if not user_session: return RedirectResponse(url='/')
    
    current_user = db.query(User).filter(User.email == user_session.get('email')).first()
    if not current_user or current_user.role not in ['admin', 'super-admin']:
        return RedirectResponse(url='/settings/users')
    
    form = await request.form()
    user_id = form.get("user_id")
    new_role = form.get("role")
    
    target_user = db.query(User).filter(User.id == user_id).first()
    if target_user:
        # Prevent self-role modification
        if target_user.id == current_user.id:
            return RedirectResponse(url='/settings/users', status_code=303)

        # Prevent non-super-admins from assigning super-admin role
        if new_role == "super-admin" and current_user.role != "super-admin":
            return RedirectResponse(url='/settings/users', status_code=303)
            
        target_user.role = new_role
        db.commit()
        
    return RedirectResponse(url='/settings/users', status_code=303)

@router.post("/settings/users/delete")
async def delete_user(request: Request, db: Session = Depends(get_db)):
    user_session = request.session.get('user')
    if not user_session: return RedirectResponse(url='/')
    
    current_user = db.query(User).filter(User.email == user_session.get('email')).first()
    
    form = await request.form()
    user_id = form.get("user_id")
    if user_id:
        # Prevent self-deletion
        if current_user and str(current_user.id) == str(user_id):
            return RedirectResponse(url='/settings/users', status_code=303)
            
        db.query(User).filter(User.id == user_id).delete()
        db.commit()
    return RedirectResponse(url='/settings/users', status_code=303)

@router.post("/settings/campaigns")
async def add_campaign(request: Request, db: Session = Depends(get_db)):
    if not request.session.get('user'): return RedirectResponse(url='/')
    form = await request.form()
    from models import ManagedCampaign
    
    ulixe_ids_str = form.get("ulixe_ids", "")
    ulixe_ids = [uid.strip() for uid in ulixe_ids_str.split(",") if uid.strip()]
    
    new_campaign = ManagedCampaign(
        campaign_id=form.get("campaign_id"),
        name=form.get("name"),
        ulixe_ids=ulixe_ids,
        is_active=True
    )
    db.add(new_campaign)
    db.commit()
    return RedirectResponse(url='/settings/campaigns', status_code=303)

@router.post("/settings/campaigns/delete")
async def delete_campaign(request: Request, db: Session = Depends(get_db)):
    if not request.session.get('user'): return RedirectResponse(url='/')
    form = await request.form()
    from models import ManagedCampaign
    camp_id = form.get("id")
    if camp_id:
        db.query(ManagedCampaign).filter(ManagedCampaign.id == camp_id).delete()
        db.commit()
    return RedirectResponse(url='/settings/campaigns', status_code=303)

# Meta Marketing Settings Routes
@router.get("/settings/meta-accounts")
async def settings_meta_accounts(request: Request, db: Session = Depends(get_db)):
    user_session = request.session.get('user')
    if not user_session:
        return RedirectResponse(url='/')
    
    current_user = db.query(User).filter(User.email == user_session.get('email')).first()
    if not current_user:
        return RedirectResponse(url='/')
    
    from models import MetaAccount
    from config import settings
    accounts = db.query(MetaAccount).all()
    
    # Verifica se OAuth è configurato
    oauth_enabled = bool(settings.META_APP_ID and settings.META_APP_SECRET)
    
    return templates.TemplateResponse("settings_meta_accounts.html", {
        "request": request,
        "title": "Gestione Account Meta",
        "user": current_user,
        "accounts": accounts,
        "active_page": "meta_accounts",
        "oauth_enabled": oauth_enabled
    })

@router.post("/settings/meta-accounts")
async def add_meta_account(request: Request, db: Session = Depends(get_db)):
    """Endpoint legacy per aggiungere account con token manuale (deprecato, usa OAuth)"""
    if not request.session.get('user'): return RedirectResponse(url='/')
    form = await request.form()
    from models import MetaAccount
    from services.integrations.meta_marketing import MetaMarketingService
    from services.utils.crypto import encrypt_token
    
    account_id = form.get("account_id", "").strip()
    access_token = form.get("access_token", "").strip()
    name = form.get("name", "").strip()
    
    if not account_id or not access_token:
        return RedirectResponse(url='/settings/meta-accounts?error=missing_fields', status_code=303)
    
    # Test connection
    service = MetaMarketingService(access_token=access_token)
    test_result = service.test_connection(account_id)
    
    if not test_result['success']:
        return RedirectResponse(url=f'/settings/meta-accounts?error={test_result["message"]}', status_code=303)
    
    # Cripta il token prima di salvarlo
    encrypted_token = encrypt_token(access_token)
    
    # Check if exists
    existing = db.query(MetaAccount).filter(MetaAccount.account_id == account_id).first()
    if existing:
        existing.access_token = encrypted_token
        existing.name = test_result.get('account_name', name) or name
        existing.is_active = True
        existing.updated_at = datetime.utcnow()
    else:
        new_account = MetaAccount(
            account_id=account_id,
            name=test_result.get('account_name', name) or name,
            access_token=encrypted_token,
            is_active=True,
            sync_enabled=True
        )
        db.add(new_account)
    
    db.commit()
    return RedirectResponse(url='/settings/meta-accounts', status_code=303)

@router.post("/settings/meta-accounts/toggle")
async def toggle_meta_account(request: Request, db: Session = Depends(get_db)):
    if not request.session.get('user'): return RedirectResponse(url='/')
    form = await request.form()
    from models import MetaAccount
    
    account_id = form.get("id")
    if account_id:
        account = db.query(MetaAccount).filter(MetaAccount.id == account_id).first()
        if account:
            account.is_active = not account.is_active
            account.updated_at = datetime.utcnow()
            db.commit()
    
    return RedirectResponse(url='/settings/meta-accounts', status_code=303)

@router.post("/settings/meta-accounts/delete")
async def delete_meta_account(request: Request, db: Session = Depends(get_db)):
    if not request.session.get('user'): return RedirectResponse(url='/')
    form = await request.form()
    from models import MetaAccount
    
    account_id = form.get("id")
    if account_id:
        db.query(MetaAccount).filter(MetaAccount.id == account_id).delete()
        db.commit()
    
    return RedirectResponse(url='/settings/meta-accounts', status_code=303)

@router.post("/settings/meta-accounts/sync")
async def sync_meta_account(request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    if not request.session.get('user'): return RedirectResponse(url='/')
    form = await request.form()
    from models import MetaAccount
    from services.integrations.meta_marketing import MetaMarketingService
    from services.utils.crypto import decrypt_token
    from database import SessionLocal
    
    account_id = form.get("id")
    if account_id:
        account = db.query(MetaAccount).filter(MetaAccount.id == account_id).first()
        if account and account.is_active:
            # Decripta il token prima di usarlo
            decrypted_token = decrypt_token(account.access_token)
            # Sync in background
            background_tasks.add_task(
                sync_meta_account_task,
                SessionLocal(),
                account.account_id,
                decrypted_token
            )
    
    return RedirectResponse(url='/settings/meta-accounts', status_code=303)

def sync_meta_account_task(db: Session, account_id: str, access_token: str):
    """Background task per sincronizzazione account Meta"""
    from services.integrations.meta_marketing import MetaMarketingService
    try:
        service = MetaMarketingService(access_token=access_token)
        service.sync_account_campaigns(account_id, db)
        logger.info(f"Meta account {account_id} synced successfully")
    except Exception as e:
        logger.error(f"Meta account sync failed: {e}")
    finally:
        db.close()

# Meta OAuth Endpoints
@router.get("/settings/meta-accounts/oauth/start")
async def meta_oauth_start(request: Request):
    """Inizia il flusso OAuth Meta"""
    if not request.session.get('user'):
        return RedirectResponse(url='/')
    
    from config import settings
    
    if not settings.META_APP_ID or not settings.META_APP_SECRET:
        return RedirectResponse(url='/settings/meta-accounts?error=oauth_not_configured', status_code=303)
    
    # Genera state per CSRF protection
    import secrets
    state = secrets.token_urlsafe(32)
    request.session['meta_oauth_state'] = state
    
    # Scopes necessari per Meta Marketing API
    scopes = [
        'ads_read',
        'ads_management',
        'business_management'
    ]
    
    # URL di autorizzazione Meta
    base_url = str(request.base_url).rstrip('/')
    redirect_uri = f"{base_url}/settings/meta-accounts/oauth/callback"
    
    auth_url = (
        f"https://www.facebook.com/v18.0/dialog/oauth?"
        f"client_id={settings.META_APP_ID}&"
        f"redirect_uri={redirect_uri}&"
        f"scope={','.join(scopes)}&"
        f"state={state}&"
        f"response_type=code"
    )
    
    return RedirectResponse(url=auth_url, status_code=302)

@router.get("/settings/meta-accounts/oauth/callback")
async def meta_oauth_callback(request: Request, db: Session = Depends(get_db)):
    """Callback OAuth Meta - riceve il token e salva l'account"""
    if not request.session.get('user'):
        return RedirectResponse(url='/')
    
    from config import settings
    from models import MetaAccount
    from services.integrations.meta_marketing import MetaMarketingService
    from services.utils.crypto import encrypt_token
    
    # Verifica state per CSRF protection
    state = request.query_params.get('state')
    stored_state = request.session.get('meta_oauth_state')
    
    if not state or state != stored_state:
        return RedirectResponse(url='/settings/meta-accounts?error=invalid_state', status_code=303)
    
    # Rimuovi state dalla sessione
    request.session.pop('meta_oauth_state', None)
    
    code = request.query_params.get('code')
    error = request.query_params.get('error')
    
    if error:
        error_description = request.query_params.get('error_description', error)
        return RedirectResponse(url=f'/settings/meta-accounts?error={error_description}', status_code=303)
    
    if not code:
        return RedirectResponse(url='/settings/meta-accounts?error=no_code', status_code=303)
    
    # Scambia code con access token
    base_url = str(request.base_url).rstrip('/')
    redirect_uri = f"{base_url}/settings/meta-accounts/oauth/callback"
    
    token_url = "https://graph.facebook.com/v18.0/oauth/access_token"
    token_params = {
        'client_id': settings.META_APP_ID,
        'client_secret': settings.META_APP_SECRET,
        'redirect_uri': redirect_uri,
        'code': code
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(token_url, params=token_params)
            response.raise_for_status()
            token_data = response.json()
            
            access_token = token_data.get('access_token')
            if not access_token:
                return RedirectResponse(url='/settings/meta-accounts?error=no_token', status_code=303)
            
            # Ottieni informazioni utente e account disponibili
            service = MetaMarketingService(access_token=access_token)
            accounts = service.get_accounts()
            
            if not accounts:
                return RedirectResponse(url='/settings/meta-accounts?error=no_accounts', status_code=303)
            
            # Cripta il token
            encrypted_token = encrypt_token(access_token)
            
            # Salva tutti gli account disponibili
            for account_data in accounts:
                account_id = account_data.get('account_id')
                account_name = account_data.get('name', 'Unknown')
                
                existing = db.query(MetaAccount).filter(MetaAccount.account_id == account_id).first()
                if existing:
                    # Aggiorna token e nome
                    existing.access_token = encrypted_token
                    existing.name = account_name
                    existing.is_active = True
                    existing.updated_at = datetime.utcnow()
                else:
                    # Crea nuovo account
                    new_account = MetaAccount(
                        account_id=account_id,
                        name=account_name,
                        access_token=encrypted_token,
                        is_active=True,
                        sync_enabled=True
                    )
                    db.add(new_account)
            
            db.commit()
            return RedirectResponse(url='/settings/meta-accounts?success=oauth_connected', status_code=303)
            
    except httpx.HTTPStatusError as e:
        logger.error(f"Meta OAuth HTTP error: {e}")
        error_msg = f"Errore HTTP durante autenticazione: {e.response.status_code}"
        return RedirectResponse(url=f'/settings/meta-accounts?error={error_msg}', status_code=303)
    except Exception as e:
        logger.error(f"Meta OAuth callback error: {e}")
        error_msg = str(e).replace('&', 'e').replace('?', '')[:100]  # Sanitizza per URL
        return RedirectResponse(url=f'/settings/meta-accounts?error={error_msg}', status_code=303)

@router.post("/settings/meta-accounts/test")
async def test_meta_account(request: Request, db: Session = Depends(get_db)):
    """Testa la connessione di un account Meta senza esporre il token"""
    if not request.session.get('user'):
        return JSONResponse({"success": False, "message": "Unauthorized"}, status_code=401)
    
    form = await request.form()
    from models import MetaAccount
    from services.integrations.meta_marketing import MetaMarketingService
    from services.utils.crypto import decrypt_token
    
    account_id = form.get("id")
    if not account_id:
        return JSONResponse({"success": False, "message": "Account ID required"}, status_code=400)
    
    account = db.query(MetaAccount).filter(MetaAccount.id == account_id).first()
    if not account:
        return JSONResponse({"success": False, "message": "Account not found"}, status_code=404)
    
    try:
        # Decripta il token
        decrypted_token = decrypt_token(account.access_token)
        service = MetaMarketingService(access_token=decrypted_token)
        test_result = service.test_connection(account.account_id)
        
        return JSONResponse({
            "success": test_result['success'],
            "message": test_result.get('message', ''),
            "account_name": test_result.get('account_name', account.name)
        })
    except Exception as e:
        logger.error(f"Error testing Meta account {account_id}: {e}")
        return JSONResponse({
            "success": False,
            "message": f"Errore durante il test: {str(e)}"
        }, status_code=500)

@router.get("/settings/meta-campaigns")
async def settings_meta_campaigns(request: Request, db: Session = Depends(get_db)):
    user_session = request.session.get('user')
    if not user_session:
        return RedirectResponse(url='/')
    
    current_user = db.query(User).filter(User.email == user_session.get('email')).first()
    if not current_user:
        return RedirectResponse(url='/')
    
    from models import MetaAccount, MetaCampaign
    accounts = db.query(MetaAccount).filter(MetaAccount.is_active == True).all()
    
    # Get account_id from query params if provided
    account_id_filter = request.query_params.get('account_id')
    if account_id_filter:
        campaigns = db.query(MetaCampaign).join(MetaAccount).filter(
            MetaAccount.account_id == account_id_filter
        ).all()
    else:
        campaigns = db.query(MetaCampaign).all()
    
    return templates.TemplateResponse("settings_meta_campaigns.html", {
        "request": request,
        "title": "Gestione Campagne Meta",
        "user": current_user,
        "accounts": accounts,
        "campaigns": campaigns,
        "selected_account_id": account_id_filter,
        "active_page": "meta_campaigns"
    })

@router.post("/settings/meta-campaigns/filters")
async def update_campaign_filters(request: Request, db: Session = Depends(get_db)):
    if not request.session.get('user'): return RedirectResponse(url='/')
    form = await request.form()
    from models import MetaCampaign
    import json
    
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

@router.get("/leads/{lead_id}")
async def lead_detail(request: Request, lead_id: int, db: Session = Depends(get_db)):
    """Vista dettaglio lead estesa con due livelli di analisi"""
    user = request.session.get('user')
    if not user:
        return RedirectResponse(url='/')
    
    from models import (
        LeadHistory, MetaCampaign, MetaAdSet, MetaAd, 
        MetaMarketingData, Lead
    )
    from sqlalchemy import func, and_, case, desc
    
    # Get lead
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        return RedirectResponse(url='/dashboard')
    
    # Get history
    history = db.query(LeadHistory).filter(
        LeadHistory.lead_id == lead_id
    ).order_by(desc(LeadHistory.checked_at)).all()
    
    # Get Meta Marketing data if correlated
    meta_campaign = None
    meta_adset = None
    meta_ad = None
    marketing_metrics = []
    
    if lead.meta_campaign_id:
        meta_campaign = db.query(MetaCampaign).filter(
            MetaCampaign.campaign_id == lead.meta_campaign_id
        ).first()
        
        if lead.meta_adset_id and meta_campaign:
            meta_adset = db.query(MetaAdSet).filter(
                MetaAdSet.adset_id == lead.meta_adset_id,
                MetaAdSet.campaign_id == meta_campaign.id
            ).first()
            
            if lead.meta_ad_id and meta_adset:
                meta_ad = db.query(MetaAd).filter(
                    MetaAd.ad_id == lead.meta_ad_id,
                    MetaAd.adset_id == meta_adset.id
                ).first()
                
                # Get marketing metrics for this ad
                marketing_metrics = db.query(MetaMarketingData).filter(
                    MetaMarketingData.ad_id == meta_ad.id
                ).order_by(desc(MetaMarketingData.date)).limit(30).all()
    
    # ===== ANALISI LIVELLO 1: Overview per msg_id =====
    msg_id_overview = None
    if lead.msg_id:
        # Aggregate stats per questo msg_id
        msg_id_stats = db.query(
            func.count(Lead.id).label('total_leads'),
            func.sum(case(
                (Lead.status_category == StatusCategory.FINALE, 1),
                else_=0
            )).label('converted'),
            func.sum(case(
                (Lead.status_category == StatusCategory.RIFIUTATO, 1),
                else_=0
            )).label('rejected'),
            func.sum(case(
                (Lead.status_category == StatusCategory.CRM, 1),
                else_=0
            )).label('crm')
        ).filter(
            Lead.msg_id == lead.msg_id
        ).first()
        
        # Get all leads with same msg_id
        msg_id_leads = db.query(Lead).filter(
            Lead.msg_id == lead.msg_id
        ).order_by(desc(Lead.created_at)).limit(50).all()
        
        msg_id_overview = {
            'msg_id': lead.msg_id,
            'stats': {
                'total': msg_id_stats.total_leads or 0,
                'converted': msg_id_stats.converted or 0,
                'rejected': msg_id_stats.rejected or 0,
                'crm': msg_id_stats.crm or 0,
                'conversion_rate': round((msg_id_stats.converted or 0) / max(msg_id_stats.total_leads or 1, 1) * 100, 2)
            },
            'leads': msg_id_leads
        }
    
    # ===== ANALISI LIVELLO 2: Overview per campagne Meta =====
    meta_campaign_overview = None
    if lead.meta_campaign_id and meta_campaign:
        # Aggregate stats per questa campagna Meta
        campaign_stats = db.query(
            func.count(Lead.id).label('total_leads'),
            func.sum(case(
                (Lead.status_category == StatusCategory.FINALE, 1),
                else_=0
            )).label('converted'),
            func.sum(case(
                (Lead.status_category == StatusCategory.RIFIUTATO, 1),
                else_=0
            )).label('rejected'),
            func.sum(case(
                (Lead.status_category == StatusCategory.CRM, 1),
                else_=0
            )).label('crm')
        ).filter(
            Lead.meta_campaign_id == lead.meta_campaign_id
        ).first()
        
        # Get all leads with same meta_campaign_id
        campaign_leads = db.query(Lead).filter(
            Lead.meta_campaign_id == lead.meta_campaign_id
        ).order_by(desc(Lead.created_at)).limit(50).all()
        
        # Calculate marketing metrics aggregate
        total_spend = 0.0
        total_impressions = 0
        total_clicks = 0
        total_conversions = 0
        
        if meta_ad:
            ad_metrics = db.query(
                func.sum(func.cast(func.replace(MetaMarketingData.spend, ',', '.'), func.Float)).label('spend'),
                func.sum(MetaMarketingData.impressions).label('impressions'),
                func.sum(MetaMarketingData.clicks).label('clicks'),
                func.sum(MetaMarketingData.conversions).label('conversions')
            ).filter(
                MetaMarketingData.ad_id == meta_ad.id
            ).first()
            
            if ad_metrics:
                total_spend = float(ad_metrics.spend or 0)
                total_impressions = ad_metrics.impressions or 0
                total_clicks = ad_metrics.clicks or 0
                total_conversions = ad_metrics.conversions or 0
        
        # Calculate payout metrics (sent = pagate, blocked/altri = scartate)
        payout_stats = db.query(
            func.sum(case((Lead.is_paid == True, 1), else_=0)).label('paid'),
            func.sum(case((Lead.is_paid == False, 1), else_=0)).label('rejected_payout')
        ).filter(
            Lead.meta_campaign_id == lead.meta_campaign_id
        ).first()
        
        paid_count = payout_stats.paid or 0 if payout_stats else 0
        rejected_payout_count = payout_stats.rejected_payout or 0 if payout_stats else 0
        
        cpl = total_spend / max(campaign_stats.total_leads or 1, 1)
        roas = (campaign_stats.converted or 0) / max(total_spend, 0.01) if total_spend > 0 else 0
        payout_rate = (paid_count / max(campaign_stats.total_leads or 1, 1) * 100) if campaign_stats.total_leads else 0
        
        meta_campaign_overview = {
            'campaign': meta_campaign,
            'adset': meta_adset,
            'ad': meta_ad,
            'stats': {
                'total': campaign_stats.total_leads or 0,
                'converted': campaign_stats.converted or 0,
                'rejected': campaign_stats.rejected or 0,
                'crm': campaign_stats.crm or 0,
                'conversion_rate': round((campaign_stats.converted or 0) / max(campaign_stats.total_leads or 1, 1) * 100, 2)
            },
            'marketing': {
                'spend': total_spend,
                'impressions': total_impressions,
                'clicks': total_clicks,
                'conversions': total_conversions,
                'cpl': round(cpl, 2),
                'roas': round(roas, 2),
                'payout': {
                    'paid': paid_count,
                    'rejected': rejected_payout_count,
                    'payout_rate': round(payout_rate, 2)
                }
            },
            'leads': campaign_leads,
            'marketing_metrics': marketing_metrics
        }
    
    return templates.TemplateResponse("lead_detail.html", {
        "request": request,
        "title": f"Lead #{lead.id}",
        "user": user,
        "lead": lead,
        "history": history,
        "msg_id_overview": msg_id_overview,
        "meta_campaign_overview": meta_campaign_overview
    })
