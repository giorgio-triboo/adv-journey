"""Marketing views e API"""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from database import get_db
from models import MetaAccount, MetaCampaign, MetaAdSet, MetaAd, MetaMarketingData, Lead, StatusCategory, User
from sqlalchemy import func, desc
from datetime import datetime, timedelta
from typing import List
import logging
from .common import templates

logger = logging.getLogger('services.api.ui')

router = APIRouter(include_in_schema=False)

@router.get("/marketing")
async def marketing(request: Request, db: Session = Depends(get_db)):
    """Maschera Marketing - Vista unificata con tab gerarchica e dati"""
    try:
        logger.debug(f"Accesso a /marketing - verifica sessione")
        user = request.session.get('user')
        logger.debug(f"Sessione user: {user is not None}")
        if not user:
            logger.warning(f"Accesso a /marketing negato: sessione user non trovata")
            return RedirectResponse(url='/')
        
        logger.debug(f"Email utente dalla sessione: {user.get('email')}")
        current_user = db.query(User).filter(User.email == user.get('email')).first()
        if not current_user:
            logger.warning(f"Accesso a /marketing negato: utente non trovato nel DB per email {user.get('email')}")
            return RedirectResponse(url='/')
        
        logger.debug(f"Utente trovato: {current_user.id}, recupero accounts e campaigns")
        # Get user's accessible accounts
        accounts = db.query(MetaAccount).filter(
            MetaAccount.is_active == True,
            (MetaAccount.user_id == None) | (MetaAccount.user_id == current_user.id)
        ).all()
        logger.debug(f"Trovati {len(accounts)} accounts")
        
        # Get all campaigns from accessible accounts
        campaigns = db.query(MetaCampaign).join(MetaAccount).filter(
            MetaAccount.is_active == True,
            (MetaAccount.user_id == None) | (MetaAccount.user_id == current_user.id)
        ).order_by(MetaCampaign.name).all()
        logger.debug(f"Trovate {len(campaigns)} campaigns")
        
        logger.debug(f"Rendering template marketing.html")
        return templates.TemplateResponse("marketing.html", {
            "request": request,
            "title": "Marketing",
            "user": user,
            "campaigns": campaigns,
            "accounts": accounts,
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
    try:
        user = request.session.get('user')
        if not user:
            return JSONResponse({"error": "Non autorizzato"}, status_code=401)
        
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
        
        # Name filters
        campaign_name_filter = request.query_params.get('campaign_name')
        if campaign_name_filter:
            campaigns_query = campaigns_query.filter(MetaCampaign.name.ilike(f"%{campaign_name_filter}%"))
        
        adset_name_filter = request.query_params.get('adset_name')
        ad_name_filter = request.query_params.get('ad_name')
        
        # Filtra campagne per adset_name se specificato
        if adset_name_filter:
            campaigns_query = campaigns_query.join(MetaAdSet).filter(
                MetaAdSet.name.ilike(f"%{adset_name_filter}%")
            ).distinct()
        
        # Filtra campagne per ad_name se specificato
        if ad_name_filter:
            campaigns_query = campaigns_query.join(MetaAdSet).join(MetaAd).filter(
                MetaAd.name.ilike(f"%{ad_name_filter}%")
            ).distinct()
        
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
        
        # Totali aggregati
        total_leads_sum = 0
        total_spend_sum = 0.0
        total_cpl_sum = 0.0
        campaigns_with_cpl = 0
        
        for campaign in campaigns:
            try:
                # Get account info
                account = campaign.account
                
                # Get leads for this campaign (per calcoli Magellano/Ulixe)
                leads = db.query(Lead).filter(
                    Lead.meta_campaign_id == campaign.campaign_id,
                    Lead.created_at >= date_from_obj,
                    Lead.created_at <= date_to_obj
                ).all()
                
                # Calculate CPL Meta (from MetaMarketingData)
                marketing_data = db.query(MetaMarketingData).join(MetaAd).join(MetaAdSet).filter(
                    MetaAdSet.campaign_id == campaign.id,
                    MetaMarketingData.date >= date_from_obj,
                    MetaMarketingData.date <= date_to_obj
                ).all()
                
                total_spend_meta = sum(float(md.spend.replace(',', '.')) if md.spend else 0 for md in marketing_data)
                total_conversions_meta = sum(md.conversions or 0 for md in marketing_data)
                
                # Lead = Conversioni (sono la stessa cosa)
                total_leads = total_conversions_meta
                cpl_meta = (total_spend_meta / total_leads) if total_leads > 0 else 0
                
                # Log per debug
                if marketing_data:
                    logger.debug(f"Campaign {campaign.campaign_id}: {len(marketing_data)} marketing data records, total_spend={total_spend_meta}, cpl_meta={cpl_meta}")
                
                # Ingresso Magellano: entrate (leads con magellano_campaign_id)
                leads_magellano_entrate = [l for l in leads if l.magellano_campaign_id]
                magellano_entrate = len(leads_magellano_entrate)
                magellano_scartate = total_leads - magellano_entrate
                cpl_ingresso = (total_spend_meta / magellano_entrate) if magellano_entrate > 0 else 0
                # Percentuale scarto ingresso: scartate / total_leads * 100
                magellano_scarto_pct_ingresso = (magellano_scartate / total_leads * 100) if total_leads > 0 else 0
                
                # Uscita Magellano: inviate e rifiutate
                magellano_inviate = len([l for l in leads if l.magellano_status == 'magellano_sent'])
                magellano_rifiutate = len([l for l in leads if l.magellano_status in ['magellano_firewall', 'magellano_refused']])
                cpl_uscita = (total_spend_meta / magellano_inviate) if magellano_inviate > 0 else 0
                # Percentuale scarto uscita: rifiutate / magellano_inviate * 100
                magellano_scarto_pct_uscita = (magellano_rifiutate / magellano_inviate * 100) if magellano_inviate > 0 else 0
                
                # Ulixe: stati principali
                ulixe_lavorazione = len([l for l in leads if l.status_category == StatusCategory.IN_LAVORAZIONE])
                ulixe_rifiutate = len([l for l in leads if l.status_category == StatusCategory.RIFIUTATO])
                ulixe_chiusure = len([l for l in leads if l.status_category == StatusCategory.FINALE])
                
                result.append({
                    "id": campaign.id,
                    "campaign_id": campaign.campaign_id,
                    "name": campaign.name or "",
                    "status": campaign.status or "UNKNOWN",
                    "account_id": account.id if account else None,
                    "account_name": account.name if account else None,
                    "account_account_id": account.account_id if account else None,
                    # Dati Meta
                    "total_leads": total_leads,
                    "cpl_meta": round(cpl_meta, 2),
                    "spend": round(total_spend_meta, 2),
                    "conversions": total_conversions_meta,
                    # Ingresso Magellano
                    "magellano_entrate": magellano_entrate,
                    "magellano_scartate": magellano_scartate,
                    "magellano_scarto_pct_ingresso": round(magellano_scarto_pct_ingresso, 2),
                    "cpl_ingresso": round(cpl_ingresso, 2),
                    # Uscita Magellano
                    "magellano_inviate": magellano_inviate,
                    "magellano_rifiutate": magellano_rifiutate,
                    "magellano_scarto_pct_uscita": round(magellano_scarto_pct_uscita, 2),
                    "cpl_uscita": round(cpl_uscita, 2),
                    # Ulixe
                    "ulixe_lavorazione": ulixe_lavorazione,
                    "ulixe_rifiutate": ulixe_rifiutate,
                    "ulixe_chiusure": ulixe_chiusure
                })
                
                # Aggiorna totali per le 4 fasi
                total_leads_sum += total_leads
                total_spend_sum += total_spend_meta
                if cpl_meta > 0:
                    total_cpl_sum += cpl_meta
                    campaigns_with_cpl += 1
            except Exception as camp_error:
                logger.error(f"Errore processando campagna {campaign.campaign_id if campaign else 'unknown'}: {camp_error}", exc_info=True)
                continue
        
        # Calcola totali delle 4 fasi
        total_magellano_entrate = sum(c.get('magellano_entrate', 0) for c in result)
        total_magellano_inviate = sum(c.get('magellano_inviate', 0) for c in result)
        total_ulixe_lavorazione = sum(c.get('ulixe_lavorazione', 0) for c in result)
        total_ulixe_chiusure = sum(c.get('ulixe_chiusure', 0) for c in result)
        
        # Calcola CPL medio
        average_cpl = (total_cpl_sum / campaigns_with_cpl) if campaigns_with_cpl > 0 else 0
        
        return JSONResponse({
            "campaigns": result,
            "totals": {
                "total_leads": total_leads_sum,
                "total_spend": round(total_spend_sum, 2),
                "average_cpl": round(average_cpl, 2),
                "total_magellano_entrate": total_magellano_entrate,
                "total_magellano_inviate": total_magellano_inviate,
                "total_ulixe_lavorazione": total_ulixe_lavorazione,
                "total_ulixe_chiusure": total_ulixe_chiusure
            }
        })
    except Exception as e:
        logger.error(f"Errore in api_marketing_campaigns: {e}", exc_info=True)
        return JSONResponse({
            "error": f"Errore nel caricamento delle campagne: {str(e)}",
            "campaigns": [],
            "totals": {
                "total_leads": 0,
                "total_spend": 0,
                "average_cpl": 0,
                "total_magellano_entrate": 0,
                "total_magellano_inviate": 0,
                "total_ulixe_lavorazione": 0,
                "total_ulixe_chiusure": 0
            }
        }, status_code=500)

@router.get("/api/marketing/accounts")
async def api_marketing_accounts(request: Request, db: Session = Depends(get_db)):
    """API: Lista account pubblicitari disponibili"""
    user = request.session.get('user')
    if not user:
        return JSONResponse({"error": "Non autorizzato"}, status_code=401)
    
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
        # Get leads for this adset (per calcoli Magellano/Ulixe)
        leads = db.query(Lead).filter(
            Lead.meta_adset_id == adset.adset_id,
            Lead.created_at >= date_from_obj,
            Lead.created_at <= date_to_obj
        ).all()
        
        # Calculate CPL Meta
        marketing_data = db.query(MetaMarketingData).join(MetaAd).filter(
            MetaAd.adset_id == adset.id,
            MetaMarketingData.date >= date_from_obj,
            MetaMarketingData.date <= date_to_obj
        ).all()
        
        total_spend_meta = sum(float(md.spend.replace(',', '.')) for md in marketing_data if md.spend)
        total_conversions_meta = sum(md.conversions or 0 for md in marketing_data)
        
        # Lead = Conversioni (sono la stessa cosa)
        total_leads = total_conversions_meta
        cpl_meta = (total_spend_meta / total_leads) if total_leads > 0 else 0
        
        # Ingresso Magellano: entrate (leads con magellano_campaign_id)
        leads_magellano_entrate = [l for l in leads if l.magellano_campaign_id]
        magellano_entrate = len(leads_magellano_entrate)
        magellano_scartate = total_leads - magellano_entrate
        cpl_ingresso = (total_spend_meta / magellano_entrate) if magellano_entrate > 0 else 0
        # Percentuale scarto ingresso: scartate / total_leads * 100
        magellano_scarto_pct_ingresso = (magellano_scartate / total_leads * 100) if total_leads > 0 else 0
        
        # Uscita Magellano: inviate e rifiutate
        magellano_inviate = len([l for l in leads if l.magellano_status == 'magellano_sent'])
        magellano_rifiutate = len([l for l in leads if l.magellano_status in ['magellano_firewall', 'magellano_refused']])
        cpl_uscita = (total_spend_meta / magellano_inviate) if magellano_inviate > 0 else 0
        # Percentuale scarto uscita: rifiutate / magellano_inviate * 100
        magellano_scarto_pct_uscita = (magellano_rifiutate / magellano_inviate * 100) if magellano_inviate > 0 else 0
        
        # Ulixe: stati principali
        ulixe_lavorazione = len([l for l in leads if l.status_category == StatusCategory.IN_LAVORAZIONE])
        ulixe_rifiutate = len([l for l in leads if l.status_category == StatusCategory.RIFIUTATO])
        ulixe_chiusure = len([l for l in leads if l.status_category == StatusCategory.FINALE])
        
        result.append({
            "id": adset.id,
            "adset_id": adset.adset_id,
            "name": adset.name,
            "status": adset.status,
            # Dati Meta
            "total_leads": total_leads,
            "cpl_meta": round(cpl_meta, 2),
            "spend": round(total_spend_meta, 2),
            "conversions": total_conversions_meta,
            # Ingresso Magellano
            "magellano_entrate": magellano_entrate,
            "magellano_scartate": magellano_scartate,
            "magellano_scarto_pct_ingresso": round(magellano_scarto_pct_ingresso, 2),
            "cpl_ingresso": round(cpl_ingresso, 2),
            # Uscita Magellano
            "magellano_inviate": magellano_inviate,
            "magellano_rifiutate": magellano_rifiutate,
            "magellano_scarto_pct_uscita": round(magellano_scarto_pct_uscita, 2),
            "cpl_uscita": round(cpl_uscita, 2),
            # Ulixe
            "ulixe_lavorazione": ulixe_lavorazione,
            "ulixe_rifiutate": ulixe_rifiutate,
            "ulixe_chiusure": ulixe_chiusure
        })
    
    return JSONResponse(result)

@router.get("/api/marketing/adsets/{adset_id}/ads")
async def api_marketing_adset_ads(adset_id: int, request: Request, db: Session = Depends(get_db)):
    """API: Lista creatività (ads) per un adset con metriche aggregate"""
    user = request.session.get('user')
    if not user:
        return JSONResponse({"error": "Non autorizzato"}, status_code=401)
    
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
        # Get leads for this ad (per calcoli Magellano/Ulixe)
        leads = db.query(Lead).filter(
            Lead.meta_ad_id == ad.ad_id,
            Lead.created_at >= date_from_obj,
            Lead.created_at <= date_to_obj
        ).all()
        
        # Calculate CPL Meta
        marketing_data = db.query(MetaMarketingData).filter(
            MetaMarketingData.ad_id == ad.id,
            MetaMarketingData.date >= date_from_obj,
            MetaMarketingData.date <= date_to_obj
        ).all()
        
        total_spend_meta = sum(float(md.spend.replace(',', '.')) for md in marketing_data if md.spend)
        total_conversions_meta = sum(md.conversions or 0 for md in marketing_data)
        
        # Lead = Conversioni (sono la stessa cosa)
        total_leads = total_conversions_meta
        cpl_meta = (total_spend_meta / total_leads) if total_leads > 0 else 0
        
        # Ingresso Magellano: entrate (leads con magellano_campaign_id)
        leads_magellano_entrate = [l for l in leads if l.magellano_campaign_id]
        magellano_entrate = len(leads_magellano_entrate)
        magellano_scartate = total_leads - magellano_entrate
        cpl_ingresso = (total_spend_meta / magellano_entrate) if magellano_entrate > 0 else 0
        # Percentuale scarto ingresso: scartate / total_leads * 100
        magellano_scarto_pct_ingresso = (magellano_scartate / total_leads * 100) if total_leads > 0 else 0
        
        # Uscita Magellano: inviate e rifiutate
        magellano_inviate = len([l for l in leads if l.magellano_status == 'magellano_sent'])
        magellano_rifiutate = len([l for l in leads if l.magellano_status in ['magellano_firewall', 'magellano_refused']])
        cpl_uscita = (total_spend_meta / magellano_inviate) if magellano_inviate > 0 else 0
        # Percentuale scarto uscita: rifiutate / magellano_inviate * 100
        magellano_scarto_pct_uscita = (magellano_rifiutate / magellano_inviate * 100) if magellano_inviate > 0 else 0
        
        # Ulixe: stati principali
        ulixe_lavorazione = len([l for l in leads if l.status_category == StatusCategory.IN_LAVORAZIONE])
        ulixe_rifiutate = len([l for l in leads if l.status_category == StatusCategory.RIFIUTATO])
        ulixe_chiusure = len([l for l in leads if l.status_category == StatusCategory.FINALE])
        
        result.append({
            "id": ad.id,
            "ad_id": ad.ad_id,
            "name": ad.name,
            "status": ad.status,
            "creative_thumbnail_url": ad.creative_thumbnail_url or "",
            # Dati Meta
            "total_leads": total_leads,
            "cpl_meta": round(cpl_meta, 2),
            "spend": round(total_spend_meta, 2),
            "conversions": total_conversions_meta,
            # Ingresso Magellano
            "magellano_entrate": magellano_entrate,
            "magellano_scartate": magellano_scartate,
            "magellano_scarto_pct_ingresso": round(magellano_scarto_pct_ingresso, 2),
            "cpl_ingresso": round(cpl_ingresso, 2),
            # Uscita Magellano
            "magellano_inviate": magellano_inviate,
            "magellano_rifiutate": magellano_rifiutate,
            "magellano_scarto_pct_uscita": round(magellano_scarto_pct_uscita, 2),
            "cpl_uscita": round(cpl_uscita, 2),
            # Ulixe
            "ulixe_lavorazione": ulixe_lavorazione,
            "ulixe_rifiutate": ulixe_rifiutate,
            "ulixe_chiusure": ulixe_chiusure
        })
    
    return JSONResponse(result)

@router.get("/api/marketing/adsets")
async def api_marketing_adsets(request: Request, db: Session = Depends(get_db)):
    """API: Lista adset con metriche aggregate (quando filtrato per adset_name)"""
    user = request.session.get('user')
    if not user:
        return JSONResponse({"error": "Non autorizzato"}, status_code=401)
    
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
    
    # Status filter
    status_filter = request.query_params.get('status')
    if status_filter:
        if status_filter == 'active':
            campaigns_query = campaigns_query.filter(MetaCampaign.status == 'ACTIVE')
        elif status_filter == 'inactive':
            campaigns_query = campaigns_query.filter(MetaCampaign.status != 'ACTIVE')
        elif status_filter != 'all':
            campaigns_query = campaigns_query.filter(MetaCampaign.status == status_filter)
    
    # Campaign name filter
    campaign_name_filter = request.query_params.get('campaign_name')
    if campaign_name_filter:
        campaigns_query = campaigns_query.filter(MetaCampaign.name.ilike(f"%{campaign_name_filter}%"))
    
    # Adset name filter (required for this endpoint)
    adset_name_filter = request.query_params.get('adset_name')
    if not adset_name_filter:
        return JSONResponse({"error": "adset_name filter required"}, status_code=400)
    
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
    
    # Get adsets matching the filter
    campaigns = campaigns_query.all()
    result = []
    
    for campaign in campaigns:
        adsets = db.query(MetaAdSet).filter(
            MetaAdSet.campaign_id == campaign.id,
            MetaAdSet.name.ilike(f"%{adset_name_filter}%")
        ).all()
        
        for adset in adsets:
            # Get leads for this adset
            leads = db.query(Lead).filter(
                Lead.meta_adset_id == adset.adset_id,
                Lead.created_at >= date_from_obj,
                Lead.created_at <= date_to_obj
            ).all()
            
            # Calculate CPL Meta
            marketing_data = db.query(MetaMarketingData).join(MetaAd).filter(
                MetaAd.adset_id == adset.id,
                MetaMarketingData.date >= date_from_obj,
                MetaMarketingData.date <= date_to_obj
            ).all()
            
            total_spend_meta = sum(float(md.spend.replace(',', '.')) for md in marketing_data if md.spend)
            total_conversions_meta = sum(md.conversions or 0 for md in marketing_data)
            
            total_leads = total_conversions_meta
            cpl_meta = (total_spend_meta / total_leads) if total_leads > 0 else 0
            
            # Ingresso Magellano
            leads_magellano_entrate = [l for l in leads if l.magellano_campaign_id]
            magellano_entrate = len(leads_magellano_entrate)
            magellano_scartate = total_leads - magellano_entrate
            cpl_ingresso = (total_spend_meta / magellano_entrate) if magellano_entrate > 0 else 0
            magellano_scarto_pct_ingresso = (magellano_scartate / total_leads * 100) if total_leads > 0 else 0
            
            # Uscita Magellano
            magellano_inviate = len([l for l in leads if l.magellano_status == 'magellano_sent'])
            magellano_rifiutate = len([l for l in leads if l.magellano_status in ['magellano_firewall', 'magellano_refused']])
            cpl_uscita = (total_spend_meta / magellano_inviate) if magellano_inviate > 0 else 0
            magellano_scarto_pct_uscita = (magellano_rifiutate / magellano_inviate * 100) if magellano_inviate > 0 else 0
            
            # Ulixe
            ulixe_lavorazione = len([l for l in leads if l.status_category == StatusCategory.IN_LAVORAZIONE])
            ulixe_rifiutate = len([l for l in leads if l.status_category == StatusCategory.RIFIUTATO])
            ulixe_chiusure = len([l for l in leads if l.status_category == StatusCategory.FINALE])
            
            result.append({
                "id": adset.id,
                "adset_id": adset.adset_id,
                "name": adset.name,
                "status": adset.status,
                "campaign_id": campaign.id,
                "campaign_name": campaign.name,
                "account_id": campaign.account.id if campaign.account else None,
                "account_name": campaign.account.name if campaign.account else None,
                # Dati Meta
                "total_leads": total_leads,
                "cpl_meta": round(cpl_meta, 2),
                "spend": round(total_spend_meta, 2),
                "conversions": total_conversions_meta,
                # Ingresso Magellano
                "magellano_entrate": magellano_entrate,
                "magellano_scartate": magellano_scartate,
                "magellano_scarto_pct_ingresso": round(magellano_scarto_pct_ingresso, 2),
                "cpl_ingresso": round(cpl_ingresso, 2),
                # Uscita Magellano
                "magellano_inviate": magellano_inviate,
                "magellano_rifiutate": magellano_rifiutate,
                "magellano_scarto_pct_uscita": round(magellano_scarto_pct_uscita, 2),
                "cpl_uscita": round(cpl_uscita, 2),
                # Ulixe
                "ulixe_lavorazione": ulixe_lavorazione,
                "ulixe_rifiutate": ulixe_rifiutate,
                "ulixe_chiusure": ulixe_chiusure
            })
    
    return JSONResponse(result)

@router.get("/api/marketing/ads")
async def api_marketing_ads(request: Request, db: Session = Depends(get_db)):
    """API: Lista ads con metriche aggregate (quando filtrato per ad_name)"""
    user = request.session.get('user')
    if not user:
        return JSONResponse({"error": "Non autorizzato"}, status_code=401)
    
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
    
    # Status filter
    status_filter = request.query_params.get('status')
    if status_filter:
        if status_filter == 'active':
            campaigns_query = campaigns_query.filter(MetaCampaign.status == 'ACTIVE')
        elif status_filter == 'inactive':
            campaigns_query = campaigns_query.filter(MetaCampaign.status != 'ACTIVE')
        elif status_filter != 'all':
            campaigns_query = campaigns_query.filter(MetaCampaign.status == status_filter)
    
    # Campaign name filter
    campaign_name_filter = request.query_params.get('campaign_name')
    if campaign_name_filter:
        campaigns_query = campaigns_query.filter(MetaCampaign.name.ilike(f"%{campaign_name_filter}%"))
    
    # Adset name filter
    adset_name_filter = request.query_params.get('adset_name')
    
    # Ad name filter (required for this endpoint)
    ad_name_filter = request.query_params.get('ad_name')
    if not ad_name_filter:
        return JSONResponse({"error": "ad_name filter required"}, status_code=400)
    
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
    
    # Get ads matching the filter
    campaigns = campaigns_query.all()
    result = []
    
    for campaign in campaigns:
        adsets_query = db.query(MetaAdSet).filter(MetaAdSet.campaign_id == campaign.id)
        if adset_name_filter:
            adsets_query = adsets_query.filter(MetaAdSet.name.ilike(f"%{adset_name_filter}%"))
        adsets = adsets_query.all()
        
        for adset in adsets:
            ads = db.query(MetaAd).filter(
                MetaAd.adset_id == adset.id,
                MetaAd.name.ilike(f"%{ad_name_filter}%")
            ).all()
            
            for ad in ads:
                # Get leads for this ad
                leads = db.query(Lead).filter(
                    Lead.meta_ad_id == ad.ad_id,
                    Lead.created_at >= date_from_obj,
                    Lead.created_at <= date_to_obj
                ).all()
                
                # Calculate CPL Meta
                marketing_data = db.query(MetaMarketingData).filter(
                    MetaMarketingData.ad_id == ad.id,
                    MetaMarketingData.date >= date_from_obj,
                    MetaMarketingData.date <= date_to_obj
                ).all()
                
                total_spend_meta = sum(float(md.spend.replace(',', '.')) for md in marketing_data if md.spend)
                total_conversions_meta = sum(md.conversions or 0 for md in marketing_data)
                
                total_leads = total_conversions_meta
                cpl_meta = (total_spend_meta / total_leads) if total_leads > 0 else 0
                
                # Ingresso Magellano
                leads_magellano_entrate = [l for l in leads if l.magellano_campaign_id]
                magellano_entrate = len(leads_magellano_entrate)
                magellano_scartate = total_leads - magellano_entrate
                cpl_ingresso = (total_spend_meta / magellano_entrate) if magellano_entrate > 0 else 0
                magellano_scarto_pct_ingresso = (magellano_scartate / total_leads * 100) if total_leads > 0 else 0
                
                # Uscita Magellano
                magellano_inviate = len([l for l in leads if l.magellano_status == 'magellano_sent'])
                magellano_rifiutate = len([l for l in leads if l.magellano_status in ['magellano_firewall', 'magellano_refused']])
                cpl_uscita = (total_spend_meta / magellano_inviate) if magellano_inviate > 0 else 0
                magellano_scarto_pct_uscita = (magellano_rifiutate / magellano_inviate * 100) if magellano_inviate > 0 else 0
                
                # Ulixe
                ulixe_lavorazione = len([l for l in leads if l.status_category == StatusCategory.IN_LAVORAZIONE])
                ulixe_rifiutate = len([l for l in leads if l.status_category == StatusCategory.RIFIUTATO])
                ulixe_chiusure = len([l for l in leads if l.status_category == StatusCategory.FINALE])
                
                result.append({
                    "id": ad.id,
                    "ad_id": ad.ad_id,
                    "name": ad.name,
                    "status": ad.status,
                    "creative_thumbnail_url": ad.creative_thumbnail_url or "",
                    "adset_id": adset.id,
                    "adset_name": adset.name,
                    "campaign_id": campaign.id,
                    "campaign_name": campaign.name,
                    "account_id": campaign.account.id if campaign.account else None,
                    "account_name": campaign.account.name if campaign.account else None,
                    # Dati Meta
                    "total_leads": total_leads,
                    "cpl_meta": round(cpl_meta, 2),
                    "spend": round(total_spend_meta, 2),
                    "conversions": total_conversions_meta,
                    # Ingresso Magellano
                    "magellano_entrate": magellano_entrate,
                    "magellano_scartate": magellano_scartate,
                    "magellano_scarto_pct_ingresso": round(magellano_scarto_pct_ingresso, 2),
                    "cpl_ingresso": round(cpl_ingresso, 2),
                    # Uscita Magellano
                    "magellano_inviate": magellano_inviate,
                    "magellano_rifiutate": magellano_rifiutate,
                    "magellano_scarto_pct_uscita": round(magellano_scarto_pct_uscita, 2),
                    "cpl_uscita": round(cpl_uscita, 2),
                    # Ulixe
                    "ulixe_lavorazione": ulixe_lavorazione,
                    "ulixe_rifiutate": ulixe_rifiutate,
                    "ulixe_chiusure": ulixe_chiusure
                })
    
    return JSONResponse(result)

