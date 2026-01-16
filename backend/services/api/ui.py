from fastapi import APIRouter, Request, Depends, BackgroundTasks, UploadFile, File, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from database import get_db
from models import Lead, StatusCategory, User
from services.integrations.magellano import MagellanoService
from datetime import datetime, timedelta, date
from typing import List, Tuple, Optional
import logging
import httpx
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

def translate_error(error_code: str) -> str:
    """Traduce i codici di errore in messaggi italiani"""
    error_translations = {
        'not_found': 'Elemento non trovato',
        'missing_fields': 'Campi obbligatori mancanti',
        'missing_account_id': 'ID account mancante',
        'missing_token': 'Token di accesso mancante',
        'oauth_not_configured': 'OAuth non configurato',
        'invalid_state': 'Stato OAuth non valido',
        'no_code': 'Codice di autorizzazione mancante',
        'no_token': 'Token di accesso non ricevuto',
        'no_accounts': 'Nessun account disponibile',
        'session_expired': 'Sessione scaduta',
        'no_accounts_selected': 'Nessun account selezionato',
        'unauthorized': 'Non autorizzato',
        'inactive': 'Account inattivo',
        'Permissions error': 'Errore di permessi',
        'permissions_error': 'Errore di permessi',
        'Connection successful': 'Connessione riuscita',
        'Access token not configured': 'Token di accesso non configurato'
    }
    # Se il codice è già tradotto o contiene spazi, restituiscilo così com'è
    if error_code in error_translations:
        return error_translations[error_code]
    # Altrimenti prova a tradurre parti comuni
    if 'Permissions' in error_code or 'permissions' in error_code.lower():
        return 'Errore di permessi'
    if 'Access token' in error_code or 'access token' in error_code.lower():
        return 'Token di accesso non configurato'
    return error_code

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

@router.get("/lavorazioni")
async def lavorazioni(request: Request, db: Session = Depends(get_db)):
    """Maschera Lavorazioni - Vista dedicata per dati sulle lavorazioni (stati Ulixe)"""
    user = request.session.get('user')
    if not user:
        return RedirectResponse(url='/')
    
    from sqlalchemy import or_
    from models import LeadHistory, ManagedCampaign
    
    # Get filter parameters
    status_category_filter = request.query_params.get('status_category')
    date_from = request.query_params.get('date_from')
    date_to = request.query_params.get('date_to')
    campaign_id = request.query_params.get('campaign_id')
    search = request.query_params.get('search', '').strip()
    
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
    
    # Base query: solo lead con stati lavorazione (escludi UNKNOWN se non esplicitamente richiesto)
    leads_query = db.query(Lead).filter(
        Lead.status_category.in_([
            StatusCategory.IN_LAVORAZIONE,
            StatusCategory.RIFIUTATO,
            StatusCategory.CRM,
            StatusCategory.FINALE
        ]),
        Lead.created_at >= date_from_obj,
        Lead.created_at <= date_to_obj
    )
    
    # Apply status filter
    if status_category_filter:
        try:
            status_cat = StatusCategory(status_category_filter)
            leads_query = leads_query.filter(Lead.status_category == status_cat)
        except ValueError:
            pass  # Invalid status, ignore filter
    
    # Apply campaign filter
    if campaign_id:
        leads_query = leads_query.filter(Lead.magellano_campaign_id == campaign_id)
    
    # Apply search filter (nome, cognome, email)
    if search:
        search_pattern = f"%{search}%"
        leads_query = leads_query.filter(
            or_(
                Lead.first_name.ilike(search_pattern),
                Lead.last_name.ilike(search_pattern),
                Lead.email.ilike(search_pattern),
                Lead.phone.ilike(search_pattern)
            )
        )
    
    # Get leads with history
    leads = leads_query.order_by(Lead.last_check.desc().nullslast(), Lead.created_at.desc()).limit(500).all()
    
    # Load history for each lead (eager loading)
    for lead in leads:
        lead.history_ordered = sorted(lead.history, key=lambda h: h.checked_at, reverse=True) if lead.history else []
    
    # Calculate statistics
    total_leads = len(leads)
    stats = {
        'total': total_leads,
        'in_lavorazione': len([l for l in leads if l.status_category == StatusCategory.IN_LAVORAZIONE]),
        'rifiutati': len([l for l in leads if l.status_category == StatusCategory.RIFIUTATO]),
        'crm': len([l for l in leads if l.status_category == StatusCategory.CRM]),
        'finale': len([l for l in leads if l.status_category == StatusCategory.FINALE])
    }
    
    # Calculate conversion rate (finale / total)
    stats['conversion_rate'] = (stats['finale'] / stats['total'] * 100) if stats['total'] > 0 else 0
    
    # Get available campaigns for filter
    campaigns = db.query(ManagedCampaign).filter(ManagedCampaign.is_active == True).all()
    
    return templates.TemplateResponse("lavorazioni.html", {
        "request": request,
        "title": "Lavorazioni",
        "user": user,
        "leads": leads,
        "stats": stats,
        "campaigns": campaigns,
        "status_categories": [
            {"value": "in_lavorazione", "label": "In Lavorazione"},
            {"value": "rifiutato", "label": "Rifiutato"},
            {"value": "crm", "label": "CRM"},
            {"value": "finale", "label": "Finale"}
        ],
        "selected_status_category": status_category_filter,
        "selected_campaign_id": campaign_id,
        "search": search,
        "date_from": date_from or date_from_obj.strftime('%Y-%m-%d'),
        "date_to": date_to or date_to_obj.strftime('%Y-%m-%d'),
        "active_page": "lavorazioni"
    })

@router.get("/marketing")
async def marketing(request: Request, db: Session = Depends(get_db)):
    """Maschera Marketing - Vista unificata con tab gerarchica e dati"""
    try:
        user = request.session.get('user')
        if not user:
            return RedirectResponse(url='/')
        
        from models import MetaAccount, MetaCampaign, MetaAdSet, MetaAd, MetaMarketingData, User
        from sqlalchemy import func, desc
        from datetime import datetime, timedelta
        
        current_user = db.query(User).filter(User.email == user.get('email')).first()
        if not current_user:
            return RedirectResponse(url='/')
        
        # Get tab parameter (default: hierarchical)
        tab = request.query_params.get('tab', 'hierarchical')
        
        # Get user's accessible accounts
        accounts = db.query(MetaAccount).filter(
            MetaAccount.is_active == True,
            (MetaAccount.user_id == None) | (MetaAccount.user_id == current_user.id)
        ).all()
        
        # Get all campaigns from accessible accounts
        campaigns = db.query(MetaCampaign).join(MetaAccount).filter(
            MetaAccount.is_active == True,
            (MetaAccount.user_id == None) | (MetaAccount.user_id == current_user.id)
        ).order_by(MetaCampaign.name).all()
        
        # If tab is 'data', load marketing data
        marketing_data = []
        totals = type('Totals', (), {
            'total_spend': 0.0,
            'total_impressions': 0,
            'total_clicks': 0,
            'total_conversions': 0
        })()
        selected_account_id = request.query_params.get('account_id', '').strip()
        selected_campaign_id = request.query_params.get('campaign_id', '').strip()
        date_from = request.query_params.get('date_from', '')
        date_to = request.query_params.get('date_to', '')
        
        if tab == 'data':
            try:
                # Default: ultimi 30 giorni
                if not date_from:
                    date_from = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
                if not date_to:
                    date_to = datetime.now().strftime('%Y-%m-%d')
                
                # Parse dates
                try:
                    date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
                except (ValueError, TypeError):
                    date_from_obj = (datetime.now() - timedelta(days=30)).date()
                    date_from = date_from_obj.strftime('%Y-%m-%d')
                
                try:
                    date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
                except (ValueError, TypeError):
                    date_to_obj = datetime.now().date()
                    date_to = date_to_obj.strftime('%Y-%m-%d')
                
                # Query base per dati marketing
                # Filtriamo solo i dati con ad_id valido per evitare problemi nei join
                # Convertiamo date in datetime per il confronto (date è DateTime nel DB)
                date_from_datetime = datetime.combine(date_from_obj, datetime.min.time())
                date_to_datetime = datetime.combine(date_to_obj, datetime.max.time())
                
                query = db.query(
                    MetaMarketingData,
                    MetaAd,
                    MetaAdSet,
                    MetaCampaign,
                    MetaAccount
                ).join(
                    MetaAd, MetaMarketingData.ad_id == MetaAd.id
                ).join(
                    MetaAdSet, MetaAd.adset_id == MetaAdSet.id
                ).join(
                    MetaCampaign, MetaAdSet.campaign_id == MetaCampaign.id
                ).join(
                    MetaAccount, MetaCampaign.account_id == MetaAccount.id
                ).filter(
                    MetaMarketingData.ad_id.isnot(None),  # Solo dati con ad_id valido
                    MetaAccount.is_active == True,
                    (MetaAccount.user_id == None) | (MetaAccount.user_id == current_user.id),
                    MetaMarketingData.date >= date_from_datetime,
                    MetaMarketingData.date <= date_to_datetime
                )
                
                if selected_account_id:
                    query = query.filter(MetaAccount.account_id == selected_account_id)
                if selected_campaign_id:
                    query = query.filter(MetaCampaign.campaign_id == selected_campaign_id)
                
                marketing_data = query.order_by(desc(MetaMarketingData.date)).all()
                
                # Calcola totali aggregati
                total_spend = 0.0
                total_impressions = 0
                total_clicks = 0
                total_conversions = 0
                
                for data, ad, adset, campaign, account in marketing_data:
                    try:
                        spend_str = data.spend.replace(',', '.') if data.spend else '0.00'
                        total_spend += float(spend_str)
                    except (ValueError, AttributeError):
                        pass
                    
                    total_impressions += data.impressions or 0
                    total_clicks += data.clicks or 0
                    total_conversions += data.conversions or 0
                
                totals = type('Totals', (), {
                    'total_spend': total_spend,
                    'total_impressions': total_impressions,
                    'total_clicks': total_clicks,
                    'total_conversions': total_conversions
                })()
            except Exception as e:
                # In caso di errore, inizializza con valori vuoti
                import traceback
                logger.error(f"Errore nel caricamento dati marketing: {e}")
                logger.error(traceback.format_exc())
                marketing_data = []
                totals = type('Totals', (), {
                    'total_spend': 0.0,
                    'total_impressions': 0,
                    'total_clicks': 0,
                    'total_conversions': 0
                })()
        
        return templates.TemplateResponse("marketing.html", {
            "request": request,
            "title": "Marketing",
            "user": user,
            "campaigns": campaigns,
            "accounts": accounts,
            "tab": tab,
            "marketing_data": marketing_data if tab == 'data' else [],
            "totals": totals,
            "selected_account_id": selected_account_id,
            "selected_campaign_id": selected_campaign_id,
            "date_from": date_from,
            "date_to": date_to,
            "active_page": "marketing"
        })
    except Exception as e:
        # Logga tutti gli errori del route marketing
        import traceback
        logger.error(f"Errore nel route /marketing: {e}")
        logger.error(traceback.format_exc())
        # Re-solleva l'eccezione per essere gestita dall'exception handler globale
        raise

@router.get("/api/marketing/campaigns")
async def api_marketing_campaigns(request: Request, db: Session = Depends(get_db)):
    """API: Lista campagne con metriche aggregate"""
    user = request.session.get('user')
    if not user:
        return JSONResponse({"error": "Non autorizzato"}, status_code=401)
    
    from models import MetaCampaign, MetaAccount, MetaAdSet, MetaAd, MetaMarketingData, Lead, StatusCategory, User
    from sqlalchemy import func, case, and_, or_
    
    current_user = db.query(User).filter(User.email == user.get('email')).first()
    
    # Get accessible campaigns
    campaigns_query = db.query(MetaCampaign).join(MetaAccount).filter(
        MetaAccount.is_active == True,
        (MetaAccount.user_id == None) | (MetaAccount.user_id == current_user.id if current_user else None)
    )
    
    # Account filter
    account_id_filter = request.query_params.get('account_id')
    if account_id_filter:
        try:
            account_id_int = int(account_id_filter)
            campaigns_query = campaigns_query.filter(MetaAccount.id == account_id_int)
        except ValueError:
            pass
    
    # Status filter (ACTIVE, PAUSED, etc.)
    status_filter = request.query_params.get('status')
    if status_filter:
        if status_filter == 'active':
            campaigns_query = campaigns_query.filter(MetaCampaign.status == 'ACTIVE')
        elif status_filter == 'inactive':
            campaigns_query = campaigns_query.filter(MetaCampaign.status != 'ACTIVE')
        elif status_filter != 'all':
            campaigns_query = campaigns_query.filter(MetaCampaign.status == status_filter)
    
    # Date filters
    date_from = request.query_params.get('date_from')
    date_to = request.query_params.get('date_to')
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
    
    campaigns = campaigns_query.all()
    result = []
    
    for campaign in campaigns:
        # Get account info
        account = campaign.account
        
        # Get leads for this campaign
        leads = db.query(Lead).filter(
            Lead.meta_campaign_id == campaign.campaign_id,
            Lead.created_at >= date_from_obj,
            Lead.created_at <= date_to_obj
        ).all()
        
        total_leads = len(leads)
        
        # Calculate CPL Meta (from MetaMarketingData)
        marketing_data = db.query(MetaMarketingData).join(MetaAd).join(MetaAdSet).filter(
            MetaAdSet.campaign_id == campaign.id,
            MetaMarketingData.date >= date_from_obj,
            MetaMarketingData.date <= date_to_obj
        ).all()
        
        total_spend_meta = sum(float(md.spend.replace(',', '.')) for md in marketing_data if md.spend)
        cpl_meta = (total_spend_meta / total_leads) if total_leads > 0 else 0
        
        # Calculate leads in Magellano (have magellano_campaign_id)
        leads_magellano = [l for l in leads if l.magellano_campaign_id]
        total_magellano = len(leads_magellano)
        # CPL Magellano would need spend data from Magellano (not available, set to 0)
        cpl_magellano = 0
        
        # Calculate leads processed by Ulixe (have status_category)
        leads_ulixe = [l for l in leads if l.status_category != StatusCategory.UNKNOWN]
        total_ulixe = len(leads_ulixe)
        # CPL Ulixe would need spend data (not available, set to 0)
        cpl_ulixe = 0
        
        # Calculate status breakdown
        no_crm = len([l for l in leads if l.status_category == StatusCategory.IN_LAVORAZIONE or l.status_category == StatusCategory.UNKNOWN])
        lavorazioni = len([l for l in leads if l.status_category == StatusCategory.IN_LAVORAZIONE])
        ok = len([l for l in leads if l.status_category == StatusCategory.FINALE])
        
        result.append({
            "id": campaign.id,
            "campaign_id": campaign.campaign_id,
            "name": campaign.name,
            "status": campaign.status,
            "account_id": account.id if account else None,
            "account_name": account.name if account else None,
            "account_account_id": account.account_id if account else None,
            "total_leads": total_leads,
            "cpl_meta": round(cpl_meta, 2),
            "total_magellano": total_magellano,
            "cpl_magellano": cpl_magellano,
            "total_ulixe": total_ulixe,
            "cpl_ulixe": cpl_ulixe,
            "no_crm": no_crm,
            "lavorazioni": lavorazioni,
            "ok": ok
        })
    
    return JSONResponse(result)

@router.get("/api/marketing/accounts")
async def api_marketing_accounts(request: Request, db: Session = Depends(get_db)):
    """API: Lista account pubblicitari disponibili"""
    user = request.session.get('user')
    if not user:
        return JSONResponse({"error": "Non autorizzato"}, status_code=401)
    
    from models import MetaAccount, User
    
    current_user = db.query(User).filter(User.email == user.get('email')).first()
    
    # Get accessible accounts
    accounts = db.query(MetaAccount).filter(
        MetaAccount.is_active == True,
        (MetaAccount.user_id == None) | (MetaAccount.user_id == current_user.id if current_user else None)
    ).order_by(MetaAccount.name).all()
    
    result = []
    for account in accounts:
        result.append({
            "id": account.id,
            "account_id": account.account_id,
            "name": account.name
        })
    
    return JSONResponse(result)

@router.get("/api/marketing/datasets")
async def api_marketing_datasets(request: Request, db: Session = Depends(get_db)):
    """API: Lista dataset (pixel) Meta disponibili"""
    user = request.session.get('user')
    if not user:
        return JSONResponse({"error": "Non autorizzato"}, status_code=401)
    
    from models import MetaAccount, User
    from services.integrations.meta_marketing import MetaMarketingService
    from services.utils.crypto import decrypt_token
    
    current_user = db.query(User).filter(User.email == user.get('email')).first()
    
    # Get accessible accounts
    accounts = db.query(MetaAccount).filter(
        MetaAccount.is_active == True,
        (MetaAccount.user_id == None) | (MetaAccount.user_id == current_user.id if current_user else None)
    ).all()
    
    all_datasets = []
    seen_dataset_ids = set()
    
    # Prova a recuperare dataset da ogni account
    for account in accounts:
        if account.access_token:
            try:
                decrypted_token = decrypt_token(account.access_token)
                service = MetaMarketingService(access_token=decrypted_token)
                datasets = service.get_datasets(account_id=account.account_id)
                
                for dataset in datasets:
                    dataset_id = dataset.get('dataset_id')
                    if dataset_id and dataset_id not in seen_dataset_ids:
                        seen_dataset_ids.add(dataset_id)
                        all_datasets.append({
                            "dataset_id": dataset_id,
                            "name": dataset.get('name', f"Dataset {dataset_id}"),
                            "account_id": account.account_id,
                            "account_name": account.name
                        })
            except Exception as e:
                logger.error(f"Error fetching datasets for account {account.account_id}: {e}")
                continue
    
    # Se non abbiamo trovato dataset, prova con token di sistema
    if not all_datasets:
        try:
            from config import settings
            if settings.META_ACCESS_TOKEN:
                service = MetaMarketingService(access_token=settings.META_ACCESS_TOKEN)
                datasets = service.get_datasets()
                for dataset in datasets:
                    dataset_id = dataset.get('dataset_id')
                    if dataset_id and dataset_id not in seen_dataset_ids:
                        seen_dataset_ids.add(dataset_id)
                        all_datasets.append({
                            "dataset_id": dataset_id,
                            "name": dataset.get('name', f"Dataset {dataset_id}"),
                            "account_id": None,
                            "account_name": "Sistema"
                        })
        except Exception as e:
            logger.error(f"Error fetching datasets with system token: {e}")
    
    return JSONResponse(all_datasets)

@router.get("/api/marketing/campaigns/{campaign_id}/adsets")
async def api_marketing_campaign_adsets(campaign_id: int, request: Request, db: Session = Depends(get_db)):
    """API: Lista adset per una campagna con metriche aggregate"""
    user = request.session.get('user')
    if not user:
        return JSONResponse({"error": "Non autorizzato"}, status_code=401)
    
    from models import MetaCampaign, MetaAdSet, MetaAd, MetaMarketingData, Lead, StatusCategory
    
    campaign = db.query(MetaCampaign).filter(MetaCampaign.id == campaign_id).first()
    if not campaign:
        return JSONResponse({"error": "Campagna non trovata"}, status_code=404)
    
    # Date filters
    date_from = request.query_params.get('date_from')
    date_to = request.query_params.get('date_to')
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
    
    adsets = db.query(MetaAdSet).filter(MetaAdSet.campaign_id == campaign_id).all()
    result = []
    
    for adset in adsets:
        # Get leads for this adset
        leads = db.query(Lead).filter(
            Lead.meta_adset_id == adset.adset_id,
            Lead.created_at >= date_from_obj,
            Lead.created_at <= date_to_obj
        ).all()
        
        total_leads = len(leads)
        
        # Calculate CPL Meta
        marketing_data = db.query(MetaMarketingData).join(MetaAd).filter(
            MetaAd.adset_id == adset.id,
            MetaMarketingData.date >= date_from_obj,
            MetaMarketingData.date <= date_to_obj
        ).all()
        
        total_spend_meta = sum(float(md.spend.replace(',', '.')) for md in marketing_data if md.spend)
        cpl_meta = (total_spend_meta / total_leads) if total_leads > 0 else 0
        
        # Status breakdown
        no_crm = len([l for l in leads if l.status_category == StatusCategory.IN_LAVORAZIONE or l.status_category == StatusCategory.UNKNOWN])
        lavorazioni = len([l for l in leads if l.status_category == StatusCategory.IN_LAVORAZIONE])
        ok = len([l for l in leads if l.status_category == StatusCategory.FINALE])
        
        result.append({
            "id": adset.id,
            "adset_id": adset.adset_id,
            "name": adset.name,
            "status": adset.status,
            "total_leads": total_leads,
            "cpl_meta": round(cpl_meta, 2),
            "no_crm": no_crm,
            "lavorazioni": lavorazioni,
            "ok": ok
        })
    
    return JSONResponse(result)

@router.get("/api/marketing/adsets/{adset_id}/ads")
async def api_marketing_adset_ads(adset_id: int, request: Request, db: Session = Depends(get_db)):
    """API: Lista creatività (ads) per un adset con metriche aggregate"""
    user = request.session.get('user')
    if not user:
        return JSONResponse({"error": "Non autorizzato"}, status_code=401)
    
    from models import MetaAdSet, MetaAd, MetaMarketingData, Lead, StatusCategory
    
    adset = db.query(MetaAdSet).filter(MetaAdSet.id == adset_id).first()
    if not adset:
        return JSONResponse({"error": "AdSet non trovato"}, status_code=404)
    
    # Date filters
    date_from = request.query_params.get('date_from')
    date_to = request.query_params.get('date_to')
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
    
    ads = db.query(MetaAd).filter(MetaAd.adset_id == adset_id).all()
    result = []
    
    for ad in ads:
        # Get leads for this ad
        leads = db.query(Lead).filter(
            Lead.meta_ad_id == ad.ad_id,
            Lead.created_at >= date_from_obj,
            Lead.created_at <= date_to_obj
        ).all()
        
        total_leads = len(leads)
        
        # Calculate CPL Meta
        marketing_data = db.query(MetaMarketingData).filter(
            MetaMarketingData.ad_id == ad.id,
            MetaMarketingData.date >= date_from_obj,
            MetaMarketingData.date <= date_to_obj
        ).all()
        
        total_spend_meta = sum(float(md.spend.replace(',', '.')) for md in marketing_data if md.spend)
        cpl_meta = (total_spend_meta / total_leads) if total_leads > 0 else 0
        
        # Status breakdown
        no_crm = len([l for l in leads if l.status_category == StatusCategory.IN_LAVORAZIONE or l.status_category == StatusCategory.UNKNOWN])
        lavorazioni = len([l for l in leads if l.status_category == StatusCategory.IN_LAVORAZIONE])
        ok = len([l for l in leads if l.status_category == StatusCategory.FINALE])
        
        result.append({
            "id": ad.id,
            "ad_id": ad.ad_id,
            "name": ad.name,
            "status": ad.status,
            "total_leads": total_leads,
            "cpl_meta": round(cpl_meta, 2),
            "no_crm": no_crm,
            "lavorazioni": lavorazioni,
            "ok": ok
        })
    
    return JSONResponse(result)

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

@router.post("/api/magellano/sync")
async def api_magellano_sync(request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """
    API endpoint per sincronizzazione Magellano con date variabili.
    Accetta JSON con campaigns (lista ID), start_date, end_date (opzionali).
    Se le date non sono specificate, usa oggi-1 come default.
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
        end_date = today  # Default: oggi
    
    if start_date > end_date:
        return JSONResponse({"error": "start_date deve essere <= end_date"}, status_code=400)
    
    # Avvia sync in background
    from database import SessionLocal
    background_tasks.add_task(run_magellano_sync, SessionLocal(), campaigns, start_date, end_date)
    
    return JSONResponse({
        "success": True,
        "message": "Sincronizzazione Magellano avviata in background",
        "campaigns": campaigns,
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date": end_date.strftime("%Y-%m-%d")
    })

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

# Helper function per verificare super-admin
def require_super_admin(request: Request, db: Session) -> Tuple[Optional[User], Optional[RedirectResponse]]:
    """
    Verifica che l'utente sia super-admin.
    Returns: (current_user, None) se autorizzato, (None, RedirectResponse) se non autorizzato
    """
    user_session = request.session.get('user')
    if not user_session:
        return None, RedirectResponse(url='/')
    
    current_user = db.query(User).filter(User.email == user_session.get('email')).first()
    if not current_user:
        return None, RedirectResponse(url='/')
    
    if current_user.role != 'super-admin':
        return None, RedirectResponse(url='/dashboard?error=Non autorizzato - accesso riservato a super-admin')
    
    return current_user, None

@router.get("/settings/platform/users")
async def settings_platform_users(request: Request, db: Session = Depends(get_db)):
    """Gestione Utenti - Solo super-admin"""
    current_user, redirect = require_super_admin(request, db)
    if redirect:
        return redirect
        
    users = db.query(User).all()
    
    return templates.TemplateResponse("settings_platform_users.html", {
        "request": request,
        "title": "Gestione Utenti",
        "user": current_user,
        "users": users,
        "active_page": "platform_users"
    })

# Manteniamo il vecchio endpoint per compatibilità (redirect)
@router.get("/settings/users")
async def settings_users_redirect(request: Request, db: Session = Depends(get_db)):
    """Redirect al nuovo endpoint platform"""
    return RedirectResponse(url='/settings/platform/users', status_code=301)

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

@router.get("/settings/meta-datasets")
async def settings_meta_datasets(request: Request, db: Session = Depends(get_db)):
    """Vista per mapping campagne Magellano → Dataset Meta"""
    user_session = request.session.get('user')
    if not user_session:
        return RedirectResponse(url='/')
    
    current_user = db.query(User).filter(User.email == user_session.get('email')).first()
    if not current_user:
        return RedirectResponse(url='/')

    from models import ManagedCampaign
    
    # Recupera tutte le campagne attive
    campaigns = db.query(ManagedCampaign).filter(ManagedCampaign.is_active == True).order_by(ManagedCampaign.cliente_name).all()
    
    return templates.TemplateResponse("settings_meta_datasets.html", {
        "request": request,
        "title": "Mapping Dataset Meta",
        "user": current_user,
        "campaigns": campaigns,
        "active_page": "meta_datasets"
    })

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
    
    from models import ManagedCampaign
    campaign = db.query(ManagedCampaign).filter(ManagedCampaign.id == int(campaign_id)).first()
    
    if not campaign:
        return RedirectResponse(url='/settings/meta-datasets?error=campaign_not_found', status_code=303)
    
    campaign.meta_dataset_id = dataset_id
    db.commit()
    
    return RedirectResponse(url='/settings/meta-datasets?success=mapping_updated', status_code=303)

@router.get("/settings/campaigns/edit/{campaign_id}")
async def edit_campaign(request: Request, campaign_id: int, db: Session = Depends(get_db)):
    """Pagina di modifica campagna"""
    user_session = request.session.get('user')
    if not user_session:
        return RedirectResponse(url='/')
    
    current_user = db.query(User).filter(User.email == user_session.get('email')).first()
    if not current_user:
        return RedirectResponse(url='/')
    
    from models import ManagedCampaign
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
    from models import ManagedCampaign
    
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

@router.get("/settings")
async def settings_redirect(request: Request, db: Session = Depends(get_db)):
    """Redirect a settings appropriato in base al ruolo"""
    user_session = request.session.get('user')
    if not user_session:
        return RedirectResponse(url='/')
    
    current_user = db.query(User).filter(User.email == user_session.get('email')).first()
    if current_user and current_user.role == 'super-admin':
        return RedirectResponse(url='/settings/platform/users')
    else:
        return RedirectResponse(url='/settings/campaigns')

@router.post("/settings/platform/users")
async def add_platform_user(request: Request, db: Session = Depends(get_db)):
    """Aggiungi utente - Solo super-admin"""
    current_user, redirect = require_super_admin(request, db)
    if redirect:
        return redirect
    
    form = await request.form()
    email = form.get("email")
    role = form.get("role", "viewer")
    if email:
        new_user = User(email=email, is_active=True, role=role)
        db.add(new_user)
        db.commit()
    return RedirectResponse(url='/settings/platform/users', status_code=303)

@router.post("/settings/platform/users/role")
async def update_platform_user_role(request: Request, db: Session = Depends(get_db)):
    """Aggiorna ruolo utente - Solo super-admin"""
    current_user, redirect = require_super_admin(request, db)
    if redirect:
        return redirect
    
    form = await request.form()
    user_id = form.get("user_id")
    new_role = form.get("role")
    
    target_user = db.query(User).filter(User.id == user_id).first()
    if target_user:
        # Prevent self-role modification
        if target_user.id == current_user.id:
            return RedirectResponse(url='/settings/platform/users', status_code=303)
            
        target_user.role = new_role
        db.commit()
        
    return RedirectResponse(url='/settings/platform/users', status_code=303)

@router.post("/settings/platform/users/delete")
async def delete_platform_user(request: Request, db: Session = Depends(get_db)):
    """Elimina utente - Solo super-admin"""
    current_user, redirect = require_super_admin(request, db)
    if redirect:
        return redirect
    
    form = await request.form()
    user_id = form.get("user_id")
    if user_id:
        # Prevent self-deletion
        if current_user and str(current_user.id) == str(user_id):
            return RedirectResponse(url='/settings/platform/users', status_code=303)
            
        db.query(User).filter(User.id == user_id).delete()
        db.commit()
    return RedirectResponse(url='/settings/platform/users', status_code=303)

# Manteniamo i vecchi endpoint per compatibilità (redirect)
@router.post("/settings/users")
async def add_user_redirect(request: Request, db: Session = Depends(get_db)):
    return RedirectResponse(url='/settings/platform/users', status_code=301)

@router.post("/settings/users/role")
async def update_user_role_redirect(request: Request, db: Session = Depends(get_db)):
    return RedirectResponse(url='/settings/platform/users', status_code=301)

@router.post("/settings/users/delete")
async def delete_user_redirect(request: Request, db: Session = Depends(get_db)):
    return RedirectResponse(url='/settings/platform/users', status_code=301)

@router.post("/settings/campaigns")
async def add_campaign(request: Request, db: Session = Depends(get_db)):
    if not request.session.get('user'): return RedirectResponse(url='/')
    form = await request.form()
    from models import ManagedCampaign
    
    cliente_name = form.get("cliente_name", "").strip()
    name = form.get("name", "").strip() or cliente_name
    magellano_ids_str = form.get("magellano_ids", "").strip()
    msg_ids_str = form.get("msg_ids", "").strip()
    pay_level = form.get("pay_level", "").strip() or None
    
    if not cliente_name or not magellano_ids_str or not msg_ids_str:
        return RedirectResponse(url='/settings/campaigns?error=missing_fields', status_code=303)
    
    # Parse arrays
    magellano_ids = [mid.strip() for mid in magellano_ids_str.split(",") if mid.strip()]
    msg_ids_raw = [mid.strip() for mid in msg_ids_str.split(",") if mid.strip()]
    
    # Converti msg_ids in array di oggetti con id e name
    # Usa il mapping dal seeder o usa l'ID come nome di default
    from seeders.campaigns_seeder import MSG_ID_TO_NAME
    msg_ids_objects = [
        {"id": msg_id, "name": MSG_ID_TO_NAME.get(msg_id, msg_id)} 
        for msg_id in msg_ids_raw
    ]
    
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
        existing.is_active = True
    else:
        new_campaign = ManagedCampaign(
            cliente_name=cliente_name,
            name=name,
            magellano_ids=magellano_ids,
            msg_ids=msg_ids_objects,
            pay_level=pay_level,
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
@router.get("/settings/magellano/upload")
async def magellano_upload_page(request: Request, db: Session = Depends(get_db)):
    """Pagina per upload file Magellano"""
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
        "active_page": "magellano_upload"
    })

@router.post("/api/magellano/upload")
async def magellano_upload(
    request: Request,
    file: UploadFile = File(...),
    file_date: str = Form(...),
    campaign_id: str = Form(None),
    db: Session = Depends(get_db)
):
    """Endpoint per upload e processamento file Magellano"""
    user = request.session.get('user')
    if not user:
        return JSONResponse({"error": "Non autorizzato"}, status_code=401)
    
    import tempfile
    import os
    from models import Lead, StatusCategory
    
    # Validazione file
    if not file.filename:
        return JSONResponse({"error": "Nessun file selezionato"}, status_code=400)
    
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
        service = MagellanoService()
        leads_data = service.process_uploaded_file(temp_file_path, file_date_obj, campaign_id_int)
        
        if not leads_data:
            return JSONResponse({"error": "Nessuna lead trovata nel file"}, status_code=400)
        
        # Salva leads nel DB
        imported_count = 0
        updated_count = 0
        
        for data in leads_data:
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
                    payout_status=data.get('payout_status'),
                    is_paid=data.get('is_paid', False),
                    facebook_ad_name=data.get('facebook_ad_name'),
                    facebook_ad_set=data.get('facebook_ad_set'),
                    facebook_campaign_name=data.get('facebook_campaign_name'),
                    facebook_id=data.get('facebook_id'),
                    facebook_piattaforma=data.get('facebook_piattaforma'),
                    current_status='inviate WS Ulixe',
                    status_category=StatusCategory.IN_LAVORAZIONE
                )
                db.add(new_lead)
                imported_count += 1
            else:
                # Update existing lead (solo alcuni campi)
                existing.email = data.get('email') or existing.email
                existing.first_name = data.get('first_name') or existing.first_name
                existing.last_name = data.get('last_name') or existing.last_name
                existing.phone = data.get('phone') or existing.phone
                existing.payout_status = data.get('payout_status') or existing.payout_status
                existing.is_paid = data.get('is_paid', existing.is_paid)
                updated_count += 1
        
        db.commit()
        
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
    
    from models import MetaAccount, User
    from datetime import date, timedelta
    
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
async def manual_meta_sync(request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Endpoint per sync manuale con date e metriche custom"""
    if not request.session.get('user'):
        return JSONResponse({"success": False, "message": "Non autorizzato"}, status_code=401)
    
    from models import MetaAccount, User
    from datetime import datetime, date
    import json
    
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
        
        # Avvia sync in background per ogni account
        from database import SessionLocal
        from services.sync.meta_marketing_sync import run_manual_sync
        
        for account in accounts_to_sync:
            background_tasks.add_task(
                run_manual_sync,
                SessionLocal(),
                account.account_id,
                start_date,
                end_date,
                metrics
            )
        
        logger.info(f"Manual sync started: {account_name}, period: {start_date} - {end_date}, metrics: {metrics}")
        
        return JSONResponse({
            "success": True,
            "message": f"Sync avviata per {account_name}",
            "account_name": account_name,
            "start_date": start_date_str,
            "end_date": end_date_str,
            "metrics": metrics
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
    
    from models import Lead, User
    from config import settings
    
    # Verifica che le credenziali Ulixe siano configurate
    ulixe_configured = bool(settings.ULIXE_USER and settings.ULIXE_PASSWORD and settings.ULIXE_WSDL)
    
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
        "leads_examples": leads_with_user_id[:10],  # Solo 10 esempi
        "active_page": "ulixe_sync"
    })

@router.post("/api/ulixe/sync")
async def api_ulixe_sync(request: Request, db: Session = Depends(get_db)):
    """API endpoint per sincronizzazione Ulixe con user_id specifici (max 10)"""
    user = request.session.get('user')
    if not user:
        return JSONResponse({"success": False, "error": "Non autorizzato"}, status_code=401)
    
    from models import Lead, StatusCategory, LeadHistory, User
    from services.integrations.ulixe import UlixeClient
    from config import settings
    from datetime import datetime
    import time
    
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
        return JSONResponse({
            "success": False,
            "error": f"Errore: {str(e)}"
        }, status_code=500)

@router.get("/settings/cron-jobs")
async def settings_cron_jobs(request: Request, db: Session = Depends(get_db)):
    """Pagina gestione cron jobs - Solo super-admin"""
    current_user, redirect = require_super_admin(request, db)
    if redirect:
        return redirect
    
    from models import CronJob
    
    # Recupera tutti i cron jobs
    cron_jobs = db.query(CronJob).order_by(CronJob.job_name).all()
    
    # Se non ci sono job, crea quelli di default
    if not cron_jobs:
        default_jobs = [
            {
                "job_name": "nightly_sync",
                "job_type": "orchestrator",
                "enabled": True,
                "hour": 0,
                "minute": 30,
                "day_of_week": "*",
                "day_of_month": "*",
                "month": "*",
                "description": "Sync completo notturno - esegue tutti i job di sincronizzazione"
            }
        ]
        
        for job_data in default_jobs:
            cron_job = CronJob(**job_data)
            db.add(cron_job)
        db.commit()
        db.refresh(cron_jobs[0] if cron_jobs else None)
        cron_jobs = db.query(CronJob).order_by(CronJob.job_name).all()
    
    return templates.TemplateResponse("settings_cron_jobs.html", {
        "request": request,
        "title": "Gestione Cron Jobs",
        "user": current_user,
        "cron_jobs": cron_jobs,
        "active_page": "cron_jobs"
    })

@router.post("/api/cron-jobs")
async def save_cron_job(request: Request, db: Session = Depends(get_db)):
    """Salva configurazione cron job - Solo super-admin"""
    current_user, redirect = require_super_admin(request, db)
    if redirect:
        return JSONResponse({"success": False, "error": "Non autorizzato"}, status_code=401)
    
    from models import CronJob
    from datetime import datetime
    
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
        
        db.commit()
        
        return JSONResponse({
            "success": True,
            "message": "Configurazione cron job salvata. Riavvia l'applicazione per applicare le modifiche."
        })
        
    except Exception as e:
        logger.error(f"Errore salvataggio cron job: {e}", exc_info=True)
        db.rollback()
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

@router.get("/settings/meta-accounts")
async def settings_meta_accounts(request: Request, db: Session = Depends(get_db)):
    user_session = request.session.get('user')
    if not user_session:
        return RedirectResponse(url='/')
    
    current_user = db.query(User).filter(User.email == user_session.get('email')).first()
    if not current_user:
        return RedirectResponse(url='/')
    
    from models import MetaAccount, MetaCampaign
    from sqlalchemy import func
    from config import settings
    
    # Filtra account: mostra account condivisi (user_id IS NULL) + account dell'utente corrente
    accounts_query = db.query(MetaAccount).filter(
        (MetaAccount.user_id == None) | (MetaAccount.user_id == current_user.id)
    )
    
    # Aggiungi conteggio campagne sincronizzate per ogni account
    accounts = []
    for account in accounts_query.all():
        # Conta campagne totali e sincronizzate per questo account
        total_campaigns = db.query(func.count(MetaCampaign.id)).filter(
            MetaCampaign.account_id == account.id
        ).scalar() or 0
        
        synced_campaigns = db.query(func.count(MetaCampaign.id)).filter(
            MetaCampaign.account_id == account.id,
            MetaCampaign.is_synced == True
        ).scalar() or 0
        
        # Aggiungi attributi dinamici all'oggetto account
        account.total_campaigns = total_campaigns
        account.synced_campaigns = synced_campaigns
        accounts.append(account)
    
    # Verifica se OAuth è configurato (opzionale - il token può essere usato direttamente)
    oauth_enabled = bool(settings.META_APP_ID and settings.META_APP_SECRET)
    
    # Verifica se c'è un token di sistema disponibile
    has_system_token = bool(settings.META_ACCESS_TOKEN)
    
    # Verifica se c'è un token OAuth valido nella sessione (per tornare alla selezione)
    has_valid_oauth_token = False
    token_expires = request.session.get('meta_oauth_token_expires')
    if token_expires and datetime.utcnow().timestamp() < token_expires:
        has_valid_oauth_token = bool(request.session.get('meta_oauth_token'))
    
    return templates.TemplateResponse("settings_meta_accounts.html", {
        "request": request,
        "title": "Gestione Account Meta",
        "user": current_user,
        "accounts": accounts,
        "active_page": "meta_accounts",
        "oauth_enabled": oauth_enabled,
        "has_system_token": has_system_token,
        "has_valid_oauth_token": has_valid_oauth_token
    })

@router.post("/settings/meta-accounts")
async def add_meta_account(request: Request, db: Session = Depends(get_db)):
    """Aggiunge account Meta. Usa token dal form o dal .env se disponibile."""
    if not request.session.get('user'): return RedirectResponse(url='/')
    form = await request.form()
    from models import MetaAccount, User
    from services.integrations.meta_marketing import MetaMarketingService
    from services.utils.crypto import encrypt_token
    from config import settings
    
    user_session = request.session.get('user')
    current_user = db.query(User).filter(User.email == user_session.get('email')).first()
    if not current_user:
        return RedirectResponse(url='/')
    
    account_id = form.get("account_id", "").strip()
    access_token = form.get("access_token", "").strip()
    name = form.get("name", "").strip()
    
    # Se non è fornito un token nel form, usa quello dal .env (token di sistema)
    if not access_token and settings.META_ACCESS_TOKEN:
        access_token = settings.META_ACCESS_TOKEN
        logger.info(f"Usando token di sistema da META_ACCESS_TOKEN per account {account_id}")
    
    if not account_id:
        return RedirectResponse(url='/settings/meta-accounts?error=missing_account_id', status_code=303)
    
    if not access_token:
        return RedirectResponse(url='/settings/meta-accounts?error=missing_token', status_code=303)
    
    # Test connection
    service = MetaMarketingService(access_token=access_token)
    test_result = service.test_connection(account_id)
    
    if not test_result['success']:
        return RedirectResponse(url=f'/settings/meta-accounts?error={test_result["message"]}', status_code=303)
    
    # Cripta il token prima di salvarlo
    encrypted_token = encrypt_token(access_token)
    
    # Check if exists per questo utente (account condiviso o specifico)
    current_user_id = current_user.id if current_user else None
    existing = db.query(MetaAccount).filter(
        MetaAccount.account_id == account_id,
        (MetaAccount.user_id == None) | (MetaAccount.user_id == current_user_id)
    ).first()
    
    if existing:
        existing.access_token = encrypted_token
        existing.name = test_result.get('account_name', name) or name
        existing.is_active = True
        existing.updated_at = datetime.utcnow()
    else:
        # Crea nuovo account per questo utente
        new_account = MetaAccount(
            account_id=account_id,
            name=test_result.get('account_name', name) or name,
            access_token=encrypted_token,
            user_id=current_user_id,  # Account specifico per questo utente
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
    from models import MetaAccount, User
    
    user_session = request.session.get('user')
    current_user = db.query(User).filter(User.email == user_session.get('email')).first()
    current_user_id = current_user.id if current_user else None
    
    account_id = form.get("id")
    if account_id:
        account = db.query(MetaAccount).filter(
            MetaAccount.id == account_id,
            (MetaAccount.user_id == None) | (MetaAccount.user_id == current_user_id)
        ).first()
        if account:
            account.is_active = not account.is_active
            account.updated_at = datetime.utcnow()
            db.commit()
    
    return RedirectResponse(url='/settings/meta-accounts', status_code=303)

@router.post("/settings/meta-accounts/delete")
async def delete_meta_account(request: Request, db: Session = Depends(get_db)):
    if not request.session.get('user'): return RedirectResponse(url='/')
    form = await request.form()
    from models import MetaAccount, User
    
    user_session = request.session.get('user')
    current_user = db.query(User).filter(User.email == user_session.get('email')).first()
    current_user_id = current_user.id if current_user else None
    
    account_id = form.get("id")
    if account_id:
        # Puoi eliminare solo account tuoi (non quelli condivisi)
        db.query(MetaAccount).filter(
            MetaAccount.id == account_id,
            MetaAccount.user_id == current_user_id  # Solo account specifici utente, non condivisi
        ).delete()
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
    redirect_url = form.get("redirect_url", "/settings/meta-accounts")
    
    logger.info(f"Sync request received for account_id: {account_id}, redirect_url: {redirect_url}")
    
    if account_id:
        account = db.query(MetaAccount).filter(MetaAccount.id == account_id).first()
        if account and account.is_active:
            logger.info(f"Starting sync for account {account.account_id} ({account.name})")
            # Decripta il token prima di usarlo
            try:
                decrypted_token = decrypt_token(account.access_token)
                # Sync in background
                background_tasks.add_task(
                    sync_meta_account_task,
                    SessionLocal(),
                    account.account_id,
                    decrypted_token
                )
                logger.info(f"Background sync task queued for account {account.account_id}")
                
                # Se viene dalla pagina delle campagne, reindirizza lì con il filtro
                if "meta-campaigns" in redirect_url:
                    redirect_url = f"/settings/meta-campaigns?account_id={account.account_id}&sync_started=true"
                else:
                    # Aggiungi messaggio di successo per la pagina meta-accounts
                    redirect_url = f"/settings/meta-accounts?sync_started=true&account_name={account.name}"
            except Exception as e:
                logger.error(f"Error decrypting token for account {account.account_id}: {e}")
                redirect_url = f"/settings/meta-accounts?error=sync_failed&account_name={account.name}"
        else:
            logger.warning(f"Account {account_id} not found or not active")
            redirect_url = f"/settings/meta-accounts?error=account_not_found"
    else:
        logger.warning("Sync request without account_id")
        redirect_url = f"/settings/meta-accounts?error=missing_account_id"
    
    return RedirectResponse(url=redirect_url, status_code=303)

def sync_meta_account_task(db: Session, account_id: str, access_token: str):
    """Background task per sincronizzazione account Meta"""
    from services.integrations.meta_marketing import MetaMarketingService
    import traceback
    try:
        logger.info(f"[SYNC TASK] Starting background sync task for account {account_id}")
        service = MetaMarketingService(access_token=access_token)
        logger.info(f"[SYNC TASK] MetaMarketingService initialized, calling sync_account_campaigns for {account_id}")
        service.sync_account_campaigns(account_id, db)
        logger.info(f"[SYNC TASK] Meta account {account_id} synced successfully")
    except Exception as e:
        error_traceback = traceback.format_exc()
        logger.error(f"[SYNC TASK] Meta account sync failed for {account_id}: {e}")
        logger.error(f"[SYNC TASK] Traceback: {error_traceback}")
        # Non fare raise per evitare crash dell'app, solo loggare l'errore
    finally:
        try:
            db.close()
        except Exception as e:
            logger.warning(f"[SYNC TASK] Error closing DB session: {e}")

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
            
            # Ottieni account disponibili per verificare che ci siano
            service = MetaMarketingService(access_token=access_token)
            accounts = service.get_accounts()
            
            if not accounts:
                return RedirectResponse(url='/settings/meta-accounts?error=no_accounts', status_code=303)
            
            # Salva token temporaneamente nella sessione (criptato) con timestamp
            # Il token scade dopo 10 minuti per sicurezza
            encrypted_token = encrypt_token(access_token)
            request.session['meta_oauth_token'] = encrypted_token
            request.session['meta_oauth_token_expires'] = (datetime.utcnow() + timedelta(minutes=10)).timestamp()
            
            # Redirect alla pagina di selezione account
            return RedirectResponse(url='/settings/meta-accounts/oauth/select', status_code=303)
            
    except httpx.HTTPStatusError as e:
        logger.error(f"Meta OAuth HTTP error: {e}")
        error_msg = f"Errore HTTP durante autenticazione: {e.response.status_code}"
        return RedirectResponse(url=f'/settings/meta-accounts?error={error_msg}', status_code=303)
    except Exception as e:
        logger.error(f"Meta OAuth callback error: {e}")
        error_msg = str(e).replace('&', 'e').replace('?', '')[:100]  # Sanitizza per URL
        return RedirectResponse(url=f'/settings/meta-accounts?error={error_msg}', status_code=303)

@router.get("/settings/meta-accounts/oauth/select")
async def meta_oauth_select_accounts(request: Request, db: Session = Depends(get_db)):
    """Pagina di selezione account Meta dopo OAuth"""
    if not request.session.get('user'):
        return RedirectResponse(url='/')
    
    from services.integrations.meta_marketing import MetaMarketingService
    from services.utils.crypto import decrypt_token
    
    # Verifica che il token sia ancora valido (max 10 minuti)
    token_expires = request.session.get('meta_oauth_token_expires')
    if not token_expires or datetime.utcnow().timestamp() > token_expires:
        request.session.pop('meta_oauth_token', None)
        request.session.pop('meta_oauth_token_expires', None)
        return RedirectResponse(url='/settings/meta-accounts?error=session_expired', status_code=303)
    
    encrypted_token = request.session.get('meta_oauth_token')
    if not encrypted_token:
        return RedirectResponse(url='/settings/meta-accounts?error=no_token', status_code=303)
    
    try:
        # Ottieni utente corrente
        from models import User
        current_user = db.query(User).filter(User.email == request.session.get('user', {}).get('email')).first()
        if not current_user:
            return RedirectResponse(url='/')
        current_user_id = current_user.id
        
        # Decripta e ottieni account
        decrypted_token = decrypt_token(encrypted_token)
        service = MetaMarketingService(access_token=decrypted_token)
        accounts = service.get_accounts()
        
        # Verifica quali account sono già presenti nel DB per questo utente
        # (account condivisi + account dell'utente)
        from models import MetaAccount
        existing_accounts = {
            acc.account_id 
            for acc in db.query(MetaAccount).filter(
                (MetaAccount.user_id == None) | (MetaAccount.user_id == current_user_id)
            ).all()
        }
        
        # Aggiungi flag per account esistenti e conta nuovi
        new_accounts_count = 0
        for account in accounts:
            account['already_added'] = account['account_id'] in existing_accounts
            if not account['already_added']:
                new_accounts_count += 1
        
        return templates.TemplateResponse("settings_meta_accounts_select.html", {
            "request": request,
            "title": "Seleziona Account Meta",
            "user": current_user,
            "accounts": accounts,
            "active_page": "meta_accounts",
            "new_accounts_count": new_accounts_count,
            "total_accounts": len(accounts)
        })
    except Exception as e:
        logger.error(f"Error loading accounts for selection: {e}")
        return RedirectResponse(url=f'/settings/meta-accounts?error={str(e)}', status_code=303)

@router.post("/settings/meta-accounts/oauth/save")
async def meta_oauth_save_accounts(request: Request, db: Session = Depends(get_db)):
    """Salva solo gli account selezionati dopo OAuth"""
    if not request.session.get('user'):
        return RedirectResponse(url='/')
    
    from models import MetaAccount
    from services.integrations.meta_marketing import MetaMarketingService
    from services.utils.crypto import decrypt_token, encrypt_token
    
    # Verifica token ancora valido
    token_expires = request.session.get('meta_oauth_token_expires')
    if not token_expires or datetime.utcnow().timestamp() > token_expires:
        request.session.pop('meta_oauth_token', None)
        request.session.pop('meta_oauth_token_expires', None)
        return RedirectResponse(url='/settings/meta-accounts?error=session_expired', status_code=303)
    
    encrypted_token = request.session.get('meta_oauth_token')
    if not encrypted_token:
        return RedirectResponse(url='/settings/meta-accounts?error=no_token', status_code=303)
    
    form = await request.form()
    selected_account_ids = form.getlist('account_ids')  # Lista di account selezionati
    
    if not selected_account_ids:
        # Pulisci sessione e torna indietro
        request.session.pop('meta_oauth_token', None)
        request.session.pop('meta_oauth_token_expires', None)
        return RedirectResponse(url='/settings/meta-accounts?info=no_accounts_selected', status_code=303)
    
    try:
        # Ottieni utente corrente
        from models import User
        current_user = db.query(User).filter(User.email == request.session.get('user', {}).get('email')).first()
        if not current_user:
            return RedirectResponse(url='/')
        current_user_id = current_user.id
        
        decrypted_token = decrypt_token(encrypted_token)
        service = MetaMarketingService(access_token=decrypted_token)
        all_accounts = service.get_accounts()
        
        # Cripta token per salvataggio
        encrypted_token_for_db = encrypt_token(decrypted_token)
        
        saved_count = 0
        
        for account_data in all_accounts:
            account_id = account_data.get('account_id')
            if account_id in selected_account_ids:
                # Verifica se esiste già per questo utente (account condiviso o specifico)
                existing = db.query(MetaAccount).filter(
                    MetaAccount.account_id == account_id,
                    (MetaAccount.user_id == None) | (MetaAccount.user_id == current_user_id)
                ).first()
                
                if existing:
                    # Se esiste già come account condiviso, crea una copia per questo utente
                    # Se esiste già come account specifico utente, aggiornalo
                    if existing.user_id is None:
                        # Account condiviso: crea copia per questo utente
                        new_account = MetaAccount(
                            account_id=account_id,
                            name=account_data.get('name', existing.name),
                            access_token=encrypted_token_for_db,
                            user_id=current_user_id,  # Account specifico per questo utente
                            is_active=True,
                            sync_enabled=True
                        )
                        db.add(new_account)
                    else:
                        # Account già specifico utente: aggiorna
                        existing.access_token = encrypted_token_for_db
                        existing.name = account_data.get('name', existing.name)
                        existing.is_active = True
                        existing.updated_at = datetime.utcnow()
                else:
                    # Crea nuovo account per questo utente (user_id = current_user_id)
                    # NULL = condiviso, user_id = specifico utente
                    new_account = MetaAccount(
                        account_id=account_id,
                        name=account_data.get('name', 'Unknown'),
                        access_token=encrypted_token_for_db,
                        user_id=current_user_id,  # Account specifico per questo utente
                        is_active=True,
                        sync_enabled=True
                    )
                    db.add(new_account)
                saved_count += 1
        
        db.commit()
        
        # Pulisci token dalla sessione
        request.session.pop('meta_oauth_token', None)
        request.session.pop('meta_oauth_token_expires', None)
        
        if saved_count == 1:
            success_msg = f"{saved_count} account aggiunto"
        else:
            success_msg = f"{saved_count} account aggiunti"
        return RedirectResponse(url=f'/settings/meta-accounts?success={success_msg}', status_code=303)
        
    except Exception as e:
        logger.error(f"Error saving selected accounts: {e}")
        db.rollback()
        return RedirectResponse(url=f'/settings/meta-accounts?error={str(e)}', status_code=303)

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
    
    # Filtra account: mostra account condivisi (user_id IS NULL) + account dell'utente corrente
    accounts = db.query(MetaAccount).filter(
        MetaAccount.is_active == True,
        (MetaAccount.user_id == None) | (MetaAccount.user_id == current_user.id)
    ).all()
    
    # Recupera i filtri master dalla sessione (usati solo per ingestion, non per visualizzazione)
    master_filter = request.session.get('meta_campaigns_master_filter', {})
    
    # Mostra TUTTE le campagne sincronizzate degli account accessibili all'utente
    # Il filtro master viene applicato solo durante l'ingestion (sync), non sulla visualizzazione
    account_ids = [acc.id for acc in accounts]
    campaigns = []
    
    if account_ids:
        from sqlalchemy.orm import joinedload
        # Mostra tutte le campagne sincronizzate, senza filtri sulla visualizzazione
        campaigns = db.query(MetaCampaign).options(joinedload(MetaCampaign.account)).filter(
            MetaCampaign.account_id.in_(account_ids)
        ).all()
        logger.info(f"Found {len(campaigns)} total campaigns (master filter for ingestion only: {master_filter})")
    else:
        logger.info("No accounts found for user")
    
    return templates.TemplateResponse("settings_meta_campaigns.html", {
        "request": request,
        "title": "Gestione Campagne Meta",
        "user": current_user,
        "accounts": accounts,
        "campaigns": campaigns,
        "master_filter": master_filter,
        "active_page": "meta_campaigns"
    })

@router.post("/settings/meta-campaigns/filter")
async def filter_meta_campaigns(request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Filtra e sincronizza campagne Meta in tutti gli account con filtri master"""
    if not request.session.get('user'): 
        return RedirectResponse(url='/')
    
    form = await request.form()
    from models import MetaAccount
    from services.utils.crypto import decrypt_token
    from database import SessionLocal
    
    current_user = db.query(User).filter(User.email == request.session.get('user').get('email')).first()
    if not current_user:
        return RedirectResponse(url='/')
    
    name_pattern = form.get("name_pattern", "").strip()
    status = form.get("status", "").strip()
    
    # Validazione: pattern nome è obbligatorio
    if not name_pattern:
        return RedirectResponse(url='/settings/meta-campaigns?error=name_pattern_required', status_code=303)
    
    # Salva i filtri nella sessione
    master_filter = {
        'name_pattern': name_pattern
    }
    if status:
        master_filter['status'] = status
    
    request.session['meta_campaigns_master_filter'] = master_filter
    
    logger.info(f"[FILTER] Master filter applied: {master_filter}")
    
    # Ottieni tutti gli account attivi accessibili all'utente
    accounts = db.query(MetaAccount).filter(
        MetaAccount.is_active == True,
        (MetaAccount.user_id == None) | (MetaAccount.user_id == current_user.id)
    ).all()
    
    # Costruisci i filtri per la sync - SEMPRE applicati
    filters = {
        'name_pattern': name_pattern  # Sempre presente
    }
    if status:
        filters['status'] = [status]
    
    # Sincronizza tutti gli account con i filtri
    synced_accounts = []
    for account in accounts:
        try:
            decrypted_token = decrypt_token(account.access_token)
            # Sync in background con filtri
            background_tasks.add_task(
                sync_meta_account_task_with_filters,
                SessionLocal(),
                account.account_id,
                decrypted_token,
                filters
            )
            synced_accounts.append(account.account_id)
            logger.info(f"[FILTER] Background sync queued for account {account.account_id} with filters: {filters}")
        except Exception as e:
            logger.error(f"[FILTER] Error queuing sync for account {account.account_id}: {e}")
    
    redirect_url = f"/settings/meta-campaigns?filter_applied=true&accounts_synced={len(synced_accounts)}"
    return RedirectResponse(url=redirect_url, status_code=303)

def sync_meta_account_task_with_filters(db: Session, account_id: str, access_token: str, filters: dict):
    """Background task per sincronizzazione account Meta con filtri"""
    from services.integrations.meta_marketing import MetaMarketingService
    import traceback
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

@router.get("/settings/meta-campaigns/logs")
@router.get("/settings/alerts")
async def settings_alerts(request: Request, db: Session = Depends(get_db)):
    """Pagina gestione configurazioni alert email"""
    user = request.session.get('user')
    if not user:
        return RedirectResponse(url='/')
    
    from models import AlertConfig
    
    alert_configs = db.query(AlertConfig).all()
    
    # Crea dict per tipo
    configs_by_type = {}
    for config in alert_configs:
        configs_by_type[config.alert_type] = config
    
    # Tipi di alert disponibili
    alert_types = [
        {'value': 'magellano', 'label': 'Magellano'},
        {'value': 'ulixe', 'label': 'Ulixe'},
        {'value': 'meta_marketing', 'label': 'Meta Marketing'},
        {'value': 'meta_conversion', 'label': 'Meta Conversion API'}
    ]
    
    return templates.TemplateResponse("settings_alerts.html", {
        "request": request,
        "title": "Alert Email",
        "user": user,
        "alert_types": alert_types,
        "configs_by_type": configs_by_type,
        "active_page": "alerts"
    })

@router.post("/api/alerts")
async def save_alert_config(request: Request, db: Session = Depends(get_db)):
    """Salva/aggiorna configurazione alert"""
    user = request.session.get('user')
    if not user:
        return JSONResponse({"error": "Non autorizzato"}, status_code=401)
    
    from models import AlertConfig, User
    current_user = db.query(User).filter(User.email == user.get('email')).first()
    if not current_user or current_user.role not in ['admin', 'super-admin']:
        return JSONResponse({"error": "Non autorizzato"}, status_code=403)
    
    try:
        data = await request.json()
        alert_type = data.get('alert_type')
        enabled = data.get('enabled', True)
        recipients = data.get('recipients', [])
        on_success = data.get('on_success', False)
        on_error = data.get('on_error', True)
        
        if not alert_type:
            return JSONResponse({"error": "alert_type richiesto"}, status_code=400)
        
        # Valida recipients
        if not isinstance(recipients, list):
            return JSONResponse({"error": "recipients deve essere una lista"}, status_code=400)
        
        # Cerca configurazione esistente
        config = db.query(AlertConfig).filter(AlertConfig.alert_type == alert_type).first()
        
        if config:
            # Update
            config.enabled = enabled
            config.recipients = recipients
            config.on_success = on_success
            config.on_error = on_error
            config.updated_at = datetime.utcnow()
        else:
            # Create
            config = AlertConfig(
                alert_type=alert_type,
                enabled=enabled,
                recipients=recipients,
                on_success=on_success,
                on_error=on_error
            )
            db.add(config)
        
        db.commit()
        return JSONResponse({"success": True, "message": "Configurazione salvata"})
        
    except Exception as e:
        logger.error(f"Errore salvataggio alert config: {e}", exc_info=True)
        db.rollback()
        return JSONResponse({"error": str(e)}, status_code=500)

@router.post("/api/alerts/test")
async def test_alert_email(request: Request, db: Session = Depends(get_db)):
    """Test invio email alert"""
    user = request.session.get('user')
    if not user:
        return JSONResponse({"error": "Non autorizzato"}, status_code=401)
    
    from models import User
    current_user = db.query(User).filter(User.email == user.get('email')).first()
    if not current_user or current_user.role not in ['admin', 'super-admin']:
        return JSONResponse({"error": "Non autorizzato"}, status_code=403)
    
    try:
        data = await request.json()
        recipients = data.get('recipients', [])
        
        if not recipients:
            return JSONResponse({"error": "Destinatari richiesti"}, status_code=400)
        
        from services.utils.email import EmailService
        email_service = EmailService(db=db)
        
        if not email_service.is_configured():
            return JSONResponse({"error": "SMTP non configurato"}, status_code=400)
        
        # Invia email di test
        success = email_service.send_alert(
            recipients=recipients,
            subject="Test Alert Email - Cepu Lavorazioni",
            body_html="""
            <html>
            <body>
                <h2>Test Email Alert</h2>
                <p>Questa è una email di test per verificare la configurazione SMTP.</p>
                <p>Se ricevi questa email, la configurazione è corretta!</p>
                <p><strong>Timestamp:</strong> """ + datetime.now().strftime('%d/%m/%Y %H:%M:%S') + """</p>
            </body>
            </html>
            """
        )
        
        if success:
            return JSONResponse({"success": True, "message": "Email di test inviata con successo"})
        else:
            return JSONResponse({"error": "Errore durante l'invio dell'email"}, status_code=500)
            
    except Exception as e:
        logger.error(f"Errore test email: {e}", exc_info=True)
        return JSONResponse({"error": str(e)}, status_code=500)

@router.get("/settings/smtp")
async def settings_smtp(request: Request, db: Session = Depends(get_db)):
    """Pagina gestione configurazione SMTP - Solo super-admin"""
    current_user, redirect = require_super_admin(request, db)
    if redirect:
        return redirect
    
    from models import SMTPConfig
    from services.utils.crypto import decrypt_token
    
    # Recupera configurazione esistente (solo una configurazione attiva)
    smtp_config = db.query(SMTPConfig).filter(SMTPConfig.is_active == True).first()
    
    # Decripta i dati se presenti
    config_data = None
    if smtp_config:
        try:
            config_data = {
                "id": smtp_config.id,
                "host": decrypt_token(smtp_config.host) if smtp_config.host else "",
                "port": smtp_config.port or 587,
                "user": decrypt_token(smtp_config.user) if smtp_config.user else "",
                "password": "",  # Non mostrare la password
                "from_email": decrypt_token(smtp_config.from_email) if smtp_config.from_email else "",
                "use_tls": smtp_config.use_tls if smtp_config.use_tls is not None else True,
                "is_active": smtp_config.is_active
            }
        except Exception as e:
            logger.error(f"Errore decriptazione SMTP config: {e}")
            config_data = None
    
    return templates.TemplateResponse("settings_smtp.html", {
        "request": request,
        "title": "Configurazione SMTP",
        "user": current_user,
        "smtp_config": config_data,
        "active_page": "smtp"
    })

@router.post("/settings/smtp")
async def save_smtp_config(request: Request, db: Session = Depends(get_db)):
    """Salva configurazione SMTP - Solo super-admin"""
    current_user, redirect = require_super_admin(request, db)
    if redirect:
        return redirect
    
    from models import SMTPConfig
    from services.utils.crypto import encrypt_token
    from datetime import datetime
    
    try:
        form = await request.form()
        
        host = form.get("host", "").strip()
        port = int(form.get("port", 587) or 587)
        user = form.get("user", "").strip()
        password = form.get("password", "").strip()
        from_email = form.get("from_email", "").strip()
        use_tls = form.get("use_tls") == "on"
        is_active = form.get("is_active") == "on"
        
        # Validazione
        if not host or not user:
            return RedirectResponse(url='/settings/smtp?error=Host e User sono obbligatori', status_code=303)
        
        # Recupera configurazione esistente
        smtp_config = db.query(SMTPConfig).filter(SMTPConfig.is_active == True).first()
        
        if smtp_config:
            # Update configurazione esistente
            smtp_config.host = encrypt_token(host)
            smtp_config.port = port
            smtp_config.user = encrypt_token(user)
            if password:  # Aggiorna password solo se fornita
                smtp_config.password = encrypt_token(password)
            smtp_config.from_email = encrypt_token(from_email) if from_email else None
            smtp_config.use_tls = use_tls
            smtp_config.is_active = is_active
            smtp_config.updated_at = datetime.utcnow()
        else:
            # Crea nuova configurazione
            if not password:
                return RedirectResponse(url='/settings/smtp?error=Password obbligatoria per nuova configurazione', status_code=303)
            
            smtp_config = SMTPConfig(
                host=encrypt_token(host),
                port=port,
                user=encrypt_token(user),
                password=encrypt_token(password),
                from_email=encrypt_token(from_email) if from_email else None,
                use_tls=use_tls,
                is_active=is_active
            )
            db.add(smtp_config)
        
        db.commit()
        return RedirectResponse(url='/settings/smtp?success=Configurazione SMTP salvata con successo', status_code=303)
        
    except Exception as e:
        logger.error(f"Errore salvataggio SMTP config: {e}", exc_info=True)
        db.rollback()
        return RedirectResponse(url=f'/settings/smtp?error=Errore nel salvataggio: {str(e)}', status_code=303)

@router.post("/api/smtp/test")
async def test_smtp_config(request: Request, db: Session = Depends(get_db)):
    """Test configurazione SMTP - Solo super-admin"""
    current_user, redirect = require_super_admin(request, db)
    if redirect:
        return JSONResponse({"error": "Non autorizzato"}, status_code=401)
    
    from models import SMTPConfig
    from services.utils.crypto import decrypt_token
    
    try:
        # Recupera configurazione attiva
        smtp_config = db.query(SMTPConfig).filter(SMTPConfig.is_active == True).first()
        
        if not smtp_config:
            return JSONResponse({"error": "Configurazione SMTP non trovata"}, status_code=400)
        
        # Decripta credenziali
        host = decrypt_token(smtp_config.host)
        user = decrypt_token(smtp_config.user)
        password = decrypt_token(smtp_config.password)
        from_email = decrypt_token(smtp_config.from_email) if smtp_config.from_email else user
        
        # Test connessione SMTP
        import smtplib
        from email.mime.text import MIMEText
        
        test_email = current_user.email
        
        msg = MIMEText("Questa è una email di test per verificare la configurazione SMTP.")
        msg['From'] = from_email
        msg['To'] = test_email
        msg['Subject'] = "Test SMTP - Cepu Lavorazioni"
        
        with smtplib.SMTP(host, smtp_config.port or 587) as server:
            if smtp_config.use_tls:
                server.starttls()
            server.login(user, password)
            server.send_message(msg)
        
        return JSONResponse({"success": True, "message": f"Email di test inviata con successo a {test_email}"})
        
    except Exception as e:
        logger.error(f"Errore test SMTP: {e}", exc_info=True)
        return JSONResponse({"error": f"Errore test SMTP: {str(e)}"}, status_code=500)

async def sync_logs_viewer(request: Request, db: Session = Depends(get_db)):
    """Visualizza i log delle attività di sincronizzazione"""
    user_session = request.session.get('user')
    if not user_session:
        return RedirectResponse(url='/')
    
    current_user = db.query(User).filter(User.email == user_session.get('email')).first()
    if not current_user:
        return RedirectResponse(url='/')
    
    from models import MetaAccount
    from pathlib import Path
    import re
    
    # Filtra account accessibili
    accounts = db.query(MetaAccount).filter(
        MetaAccount.is_active == True,
        (MetaAccount.user_id == None) | (MetaAccount.user_id == current_user.id)
    ).all()
    
    # Parametri di filtro
    account_id_filter = request.query_params.get('account_id', '')
    level_filter = request.query_params.get('level', '')
    lines_filter = request.query_params.get('lines', '100')
    
    # Leggi il file di log
    base_dir = Path(__file__).parent.parent
    log_file = base_dir / "logs" / "app.log"
    
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
    
    return templates.TemplateResponse("settings_meta_campaigns_logs.html", {
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

@router.get("/marketing-data")
async def marketing_data_redirect(request: Request):
    """Redirect a /marketing con tab=data per retrocompatibilità"""
    # Preserva i parametri query
    query_params = str(request.url.query)
    if query_params:
        return RedirectResponse(url=f"/marketing?tab=data&{query_params}")
    return RedirectResponse(url="/marketing?tab=data")

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
