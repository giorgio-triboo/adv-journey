"""API gerarchia account / campagne / adset / ads (dati come maschera Marketing)."""
import logging
from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, joinedload

from database import get_db
from models import (
    MetaAccount,
    MetaCampaign,
    MetaAdSet,
    MetaAd,
    MetaMarketingData,
    MetaMarketingPlacement,
    Lead,
    StatusCategory,
    User,
)

from services.integrations.meta_marketing import MetaMarketingService
from services.utils.crypto import decrypt_token

from .helpers import (
    _get_mag_to_pay,
    _lead_date_filter,
    _parse_amount,
    _compute_ricavo_for_leads,
    _get_pay_for_leads,
    default_marketing_filter_date_range,
    ulixe_ws_scartata_lead,
)

logger = logging.getLogger('services.api.ui')
router = APIRouter(include_in_schema=False)


def _marketing_date_range_from_request(request: Request) -> tuple[datetime, datetime]:
    """date_from / date_to da query; default = inizio mese corrente → ieri (allineato alle altre viste marketing)."""
    date_from = request.query_params.get("date_from")
    date_to = request.query_params.get("date_to")
    date_from_obj = None
    date_to_obj = None
    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, "%Y-%m-%d")
        except ValueError:
            pass
    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, "%Y-%m-%d")
        except ValueError:
            pass
    d_def_f, d_def_t = default_marketing_filter_date_range()
    if not date_from_obj:
        date_from_obj = d_def_f
    if not date_to_obj:
        date_to_obj = d_def_t
    return date_from_obj, date_to_obj


def _marketing_metrics_block(leads: list, marketing_data: list, mag_to_pay: dict, db: Session) -> dict:
    """
    KPI condivisi tra campagna / adset / ad (stessa logica della vecchia API).
    Ritorna dict con chiavi JSON; "_skip" True se riga da omettere (zero lead e zero spend).
    """
    total_spend_meta = sum(_parse_amount(md.spend) for md in marketing_data)
    total_conversions_meta = sum(md.conversions or 0 for md in marketing_data)
    total_leads = total_conversions_meta
    cpl_meta = (total_spend_meta / total_leads) if total_leads > 0 else 0

    leads_magellano_entrate = [l for l in leads if l.magellano_campaign_id]
    magellano_entrate = len(leads_magellano_entrate)
    magellano_scartate = total_leads - magellano_entrate
    cpl_ingresso = (total_spend_meta / magellano_entrate) if magellano_entrate > 0 else 0
    magellano_scarto_pct_ingresso = (magellano_scartate / total_leads * 100) if total_leads > 0 else 0

    magellano_inviate = len([l for l in leads if l.magellano_status == "magellano_sent"])
    magellano_rifiutate = len(
        [l for l in leads if l.magellano_status in ["magellano_firewall", "magellano_refused"]]
    )
    cpl_uscita = (total_spend_meta / magellano_inviate) if magellano_inviate > 0 else 0
    uscita_magellano_totale = magellano_inviate + magellano_rifiutate
    magellano_scarto_pct_uscita = (
        (magellano_rifiutate / uscita_magellano_totale * 100) if uscita_magellano_totale > 0 else 0
    )
    ulixe_lavorazione = len([l for l in leads if l.status_category == StatusCategory.IN_LAVORAZIONE])
    ulixe_rifiutate = len([l for l in leads if l.status_category == StatusCategory.RIFIUTATO])
    ulixe_approvate = len([l for l in leads if l.status_category == StatusCategory.FINALE])
    ulixe_ws_scartate = len([l for l in leads if ulixe_ws_scartata_lead(l)])
    # Scarto totale %: (conversioni Meta − inviate al WS Ulixe) ÷ conversioni Meta × 100 (stesso "Lead" di Dati Meta).
    inviate_ws = magellano_inviate
    if total_leads > 0:
        inv_eff = min(inviate_ws, total_leads)
        scarto_totale_pct = round((total_leads - inv_eff) / total_leads * 100, 2)
    else:
        scarto_totale_pct = 0.0

    leads_approvate = [l for l in leads if l.status_category == StatusCategory.FINALE]

    revenue = _compute_ricavo_for_leads(db, leads_approvate, mag_to_pay)
    pay_campagna = _get_pay_for_leads(db, leads, mag_to_pay)
    cpl_approvate = (total_spend_meta / ulixe_approvate) if ulixe_approvate > 0 else 0
    # CPL «finale»: Speso Meta ÷ lead inviate al WS Ulixe (stesso denominatore di CPL uscita Magellano).
    cpl_finale_reale = round(total_spend_meta / magellano_inviate, 2) if magellano_inviate > 0 else None
    margine_singola = (pay_campagna - cpl_approvate) if pay_campagna and ulixe_approvate else None
    margine_lordo = (revenue - total_spend_meta) if revenue > 0 else None
    margine_pct = (margine_lordo / revenue * 100) if revenue and margine_lordo is not None else None

    return {
        "_skip": total_leads == 0 and total_spend_meta == 0,
        "total_leads": total_leads,
        "cpl_meta": round(cpl_meta, 2),
        "spend": round(total_spend_meta, 2),
        "conversions": total_conversions_meta,
        "magellano_entrate": magellano_entrate,
        "magellano_scartate": magellano_scartate,
        "magellano_scarto_pct_ingresso": round(magellano_scarto_pct_ingresso, 2),
        "cpl_ingresso": round(cpl_ingresso, 2),
        "magellano_inviate": magellano_inviate,
        "magellano_rifiutate": magellano_rifiutate,
        "magellano_scarto_pct_uscita": round(magellano_scarto_pct_uscita, 2),
        "cpl_uscita": round(cpl_uscita, 2),
        "ulixe_lavorazione": ulixe_lavorazione,
        "ulixe_rifiutate": ulixe_rifiutate,
        "ulixe_approvate": ulixe_approvate,
        "ulixe_ws_scartate": ulixe_ws_scartate,
        "cpl_finale_reale": cpl_finale_reale,
        "revenue": round(revenue, 2),
        "margine_singola_lead": round(margine_singola, 2) if margine_singola is not None else None,
        "margine_lordo": round(margine_lordo, 2) if margine_lordo is not None else None,
        "margine_pct": round(margine_pct, 2) if margine_pct is not None else None,
        "scarto_totale_pct": round(scarto_totale_pct, 2),
    }


def _bulk_leads_by_meta_campaign(
    db: Session, meta_campaign_ids: list[str], date_from_obj, date_to_obj, platform: str
) -> dict[str, list]:
    """Una query: lead nel periodo, bucket per meta_campaign_id (stringa)."""
    if not meta_campaign_ids:
        return {}
    conds = [
        Lead.meta_campaign_id.in_(meta_campaign_ids),
        _lead_date_filter(date_from_obj, date_to_obj),
    ]
    if platform in ("facebook", "instagram"):
        conds.append(Lead.platform == platform)
    rows = db.query(Lead).filter(*conds).all()
    out: dict[str, list] = defaultdict(list)
    for L in rows:
        if L.meta_campaign_id:
            out[str(L.meta_campaign_id).strip()].append(L)
    return out


def _bulk_marketing_by_campaign_pk(
    db: Session, campaign_internal_ids: list[int], date_from_obj, date_to_obj, platform: str
) -> dict[int, list]:
    """Una query: metriche nel periodo, bucket per PK interna MetaCampaign."""
    out: dict[int, list] = defaultdict(list)
    if not campaign_internal_ids:
        return out
    if platform in ("facebook", "instagram"):
        q = (
            db.query(MetaMarketingPlacement, MetaAdSet.campaign_id)
            .join(MetaAd, MetaMarketingPlacement.ad_id == MetaAd.id)
            .join(MetaAdSet, MetaAd.adset_id == MetaAdSet.id)
            .filter(
                MetaAdSet.campaign_id.in_(campaign_internal_ids),
                MetaMarketingPlacement.date >= date_from_obj,
                MetaMarketingPlacement.date <= date_to_obj,
                MetaMarketingPlacement.publisher_platform == platform,
            )
        )
        for md, camp_pk in q.all():
            out[camp_pk].append(md)
    else:
        q = (
            db.query(MetaMarketingData, MetaAdSet.campaign_id)
            .join(MetaAd, MetaMarketingData.ad_id == MetaAd.id)
            .join(MetaAdSet, MetaAd.adset_id == MetaAdSet.id)
            .filter(
                MetaAdSet.campaign_id.in_(campaign_internal_ids),
                MetaMarketingData.date >= date_from_obj,
                MetaMarketingData.date <= date_to_obj,
            )
        )
        for md, camp_pk in q.all():
            out[camp_pk].append(md)
    return out


def _bulk_leads_by_meta_adset(
    db: Session, meta_adset_ids: list[str], date_from_obj, date_to_obj, platform: str
) -> dict[str, list]:
    if not meta_adset_ids:
        return {}
    conds = [
        Lead.meta_adset_id.in_(meta_adset_ids),
        _lead_date_filter(date_from_obj, date_to_obj),
    ]
    if platform in ("facebook", "instagram"):
        conds.append(Lead.platform == platform)
    out: dict[str, list] = defaultdict(list)
    for L in db.query(Lead).filter(*conds).all():
        if L.meta_adset_id:
            out[str(L.meta_adset_id).strip()].append(L)
    return out


def _bulk_marketing_by_adset_pk(
    db: Session, adset_internal_ids: list[int], date_from_obj, date_to_obj, platform: str
) -> dict[int, list]:
    out: dict[int, list] = defaultdict(list)
    if not adset_internal_ids:
        return out
    if platform in ("facebook", "instagram"):
        q = (
            db.query(MetaMarketingPlacement, MetaAd.adset_id)
            .join(MetaAd, MetaMarketingPlacement.ad_id == MetaAd.id)
            .filter(
                MetaAd.adset_id.in_(adset_internal_ids),
                MetaMarketingPlacement.date >= date_from_obj,
                MetaMarketingPlacement.date <= date_to_obj,
                MetaMarketingPlacement.publisher_platform == platform,
            )
        )
        for md, adset_pk in q.all():
            out[adset_pk].append(md)
    else:
        q = (
            db.query(MetaMarketingData, MetaAd.adset_id)
            .join(MetaAd, MetaMarketingData.ad_id == MetaAd.id)
            .filter(
                MetaAd.adset_id.in_(adset_internal_ids),
                MetaMarketingData.date >= date_from_obj,
                MetaMarketingData.date <= date_to_obj,
            )
        )
        for md, adset_pk in q.all():
            out[adset_pk].append(md)
    return out


def _bulk_leads_by_meta_ad_id(
    db: Session, meta_ad_ids: list[str], date_from_obj, date_to_obj, platform: str
) -> dict[str, list]:
    if not meta_ad_ids:
        return {}
    conds = [
        Lead.meta_ad_id.in_(meta_ad_ids),
        _lead_date_filter(date_from_obj, date_to_obj),
    ]
    if platform in ("facebook", "instagram"):
        conds.append(Lead.platform == platform)
    out: dict[str, list] = defaultdict(list)
    for L in db.query(Lead).filter(*conds).all():
        if L.meta_ad_id:
            out[str(L.meta_ad_id).strip()].append(L)
    return out


def _bulk_marketing_by_ad_pk(
    db: Session, ad_internal_ids: list[int], date_from_obj, date_to_obj, platform: str
) -> dict[int, list]:
    out: dict[int, list] = defaultdict(list)
    if not ad_internal_ids:
        return out
    if platform in ("facebook", "instagram"):
        q = db.query(MetaMarketingPlacement).filter(
            MetaMarketingPlacement.ad_id.in_(ad_internal_ids),
            MetaMarketingPlacement.date >= date_from_obj,
            MetaMarketingPlacement.date <= date_to_obj,
            MetaMarketingPlacement.publisher_platform == platform,
        )
        for md in q.all():
            out[md.ad_id].append(md)
    else:
        q = db.query(MetaMarketingData).filter(
            MetaMarketingData.ad_id.in_(ad_internal_ids),
            MetaMarketingData.date >= date_from_obj,
            MetaMarketingData.date <= date_to_obj,
        )
        for md in q.all():
            out[md.ad_id].append(md)
    return out

@router.get("/api/marketing/campaigns")
async def api_marketing_campaigns(request: Request, db: Session = Depends(get_db)):
    """API: Lista campagne con metriche aggregate"""
    try:
        user = request.session.get('user')
        if not user:
            return JSONResponse({"error": "Non autorizzato"}, status_code=401)
        
        if not db.query(User).filter(User.email == user.get('email')).first():
            return JSONResponse({"error": "Non autorizzato"}, status_code=401)

        campaigns_query = db.query(MetaCampaign).join(MetaAccount).filter(
            MetaAccount.is_active == True,
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
        
        # Piattaforma (facebook / instagram / all)
        platform = request.query_params.get('platform', 'all')

        date_from_obj, date_to_obj = _marketing_date_range_from_request(request)

        campaigns = campaigns_query.options(joinedload(MetaCampaign.account)).all()
        result = []

        total_leads_sum = 0
        total_spend_sum = 0.0
        total_cpl_sum = 0.0
        campaigns_with_cpl = 0

        if campaigns:
            campaign_internal_ids = [c.id for c in campaigns]
            meta_ids = [str(c.campaign_id).strip() for c in campaigns if c.campaign_id]
            mag_to_pay = _get_mag_to_pay(db)
            leads_by_cid = _bulk_leads_by_meta_campaign(db, meta_ids, date_from_obj, date_to_obj, platform)
            md_by_cpk = _bulk_marketing_by_campaign_pk(
                db, campaign_internal_ids, date_from_obj, date_to_obj, platform
            )

            for campaign in campaigns:
                try:
                    account = campaign.account
                    mid = str(campaign.campaign_id).strip() if campaign.campaign_id else ""
                    leads = leads_by_cid.get(mid, [])
                    marketing_data = md_by_cpk.get(campaign.id, [])

                    if marketing_data:
                        total_spend_dbg = sum(_parse_amount(md.spend) for md in marketing_data)
                        total_conv_dbg = sum(md.conversions or 0 for md in marketing_data)
                        cpl_dbg = (total_spend_dbg / total_conv_dbg) if total_conv_dbg > 0 else 0
                        logger.debug(
                            f"Campaign {campaign.campaign_id}: {len(marketing_data)} marketing rows, "
                            f"total_spend={total_spend_dbg}, cpl_meta={cpl_dbg}"
                        )

                    m = _marketing_metrics_block(leads, marketing_data, mag_to_pay, db)
                    if m.pop("_skip"):
                        continue

                    raw_spend = sum(_parse_amount(md.spend) for md in marketing_data)
                    total_leads_sum += m["total_leads"]
                    total_spend_sum += raw_spend
                    if m["cpl_meta"] > 0:
                        total_cpl_sum += m["cpl_meta"]
                        campaigns_with_cpl += 1

                    result.append(
                        {
                            "id": campaign.id,
                            "campaign_id": campaign.campaign_id,
                            "name": campaign.name or "",
                            "status": campaign.status or "UNKNOWN",
                            "account_id": account.id if account else None,
                            "account_name": account.name if account else None,
                            "account_account_id": account.account_id if account else None,
                            **m,
                        }
                    )
                except Exception as camp_error:
                    logger.error(
                        f"Errore processando campagna {campaign.campaign_id if campaign else 'unknown'}: {camp_error}",
                        exc_info=True,
                    )
                    continue
        
        # Calcola totali delle 4 fasi
        total_magellano_entrate = sum(c.get('magellano_entrate', 0) for c in result)
        total_magellano_inviate = sum(c.get('magellano_inviate', 0) for c in result)
        total_ulixe_lavorazione = sum(c.get('ulixe_lavorazione', 0) for c in result)
        total_ulixe_approvate = sum(c.get('ulixe_approvate', 0) for c in result)
        total_ulixe_ws_scartate = sum(c.get('ulixe_ws_scartate', 0) for c in result)
        
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
                "total_ulixe_approvate": total_ulixe_approvate,
                "total_ulixe_ws_scartate": total_ulixe_ws_scartate,
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
                "total_ulixe_approvate": 0,
                "total_ulixe_ws_scartate": 0,
            }
        }, status_code=500)

@router.get("/api/marketing/accounts")
async def api_marketing_accounts(request: Request, db: Session = Depends(get_db)):
    """API: Lista account pubblicitari disponibili"""
    user = request.session.get('user')
    if not user:
        return JSONResponse({"error": "Non autorizzato"}, status_code=401)
    
    if not db.query(User).filter(User.email == user.get('email')).first():
        return JSONResponse({"error": "Non autorizzato"}, status_code=401)

    accounts = db.query(MetaAccount).filter(
        MetaAccount.is_active == True,
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
    
    if not db.query(User).filter(User.email == user.get('email')).first():
        return JSONResponse({"error": "Non autorizzato"}, status_code=401)

    accounts = db.query(MetaAccount).filter(
        MetaAccount.is_active == True,
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
    
    campaign = (
        db.query(MetaCampaign)
        .options(joinedload(MetaCampaign.account))
        .filter(MetaCampaign.id == campaign_id)
        .first()
    )
    if not campaign:
        return JSONResponse({"error": "Campagna non trovata"}, status_code=404)
    
    # Piattaforma (facebook / instagram / all)
    platform = request.query_params.get('platform', 'all')

    date_from_obj, date_to_obj = _marketing_date_range_from_request(request)

    adsets = db.query(MetaAdSet).filter(MetaAdSet.campaign_id == campaign_id).all()
    result = []

    if adsets:
        adset_pks = [a.id for a in adsets]
        adset_meta_ids = [str(a.adset_id).strip() for a in adsets if a.adset_id]
        mag_to_pay = _get_mag_to_pay(db)
        leads_by_as = _bulk_leads_by_meta_adset(db, adset_meta_ids, date_from_obj, date_to_obj, platform)
        md_by_as = _bulk_marketing_by_adset_pk(db, adset_pks, date_from_obj, date_to_obj, platform)

        for adset in adsets:
            aid = str(adset.adset_id).strip() if adset.adset_id else ""
            leads = leads_by_as.get(aid, [])
            marketing_data = md_by_as.get(adset.id, [])
            m = _marketing_metrics_block(leads, marketing_data, mag_to_pay, db)
            if m.pop("_skip"):
                continue
            result.append(
                {
                    "id": adset.id,
                    "adset_id": adset.adset_id,
                    "name": adset.name,
                    "status": adset.status,
                    **m,
                }
            )

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
    
    # Piattaforma (facebook / instagram / all)
    platform = request.query_params.get('platform', 'all')

    date_from_obj, date_to_obj = _marketing_date_range_from_request(request)

    ads = db.query(MetaAd).filter(MetaAd.adset_id == adset_id).all()
    result = []

    if ads:
        ad_pks = [a.id for a in ads]
        meta_ad_ids = [str(a.ad_id).strip() for a in ads if a.ad_id]
        mag_to_pay = _get_mag_to_pay(db)
        leads_by_ad = _bulk_leads_by_meta_ad_id(db, meta_ad_ids, date_from_obj, date_to_obj, platform)
        md_by_ad = _bulk_marketing_by_ad_pk(db, ad_pks, date_from_obj, date_to_obj, platform)

        for ad in ads:
            mid = str(ad.ad_id).strip() if ad.ad_id else ""
            leads = leads_by_ad.get(mid, [])
            marketing_data = md_by_ad.get(ad.id, [])
            m = _marketing_metrics_block(leads, marketing_data, mag_to_pay, db)
            if m.pop("_skip"):
                continue
            result.append(
                {
                    "id": ad.id,
                    "ad_id": ad.ad_id,
                    "name": ad.name,
                    "status": ad.status,
                    "creative_thumbnail_url": ad.creative_thumbnail_url or "",
                    "creative_id": ad.creative_id or "",
                    **m,
                }
            )

    return JSONResponse(result)

@router.get("/api/marketing/adsets")
async def api_marketing_adsets(request: Request, db: Session = Depends(get_db)):
    """API: Lista adset con metriche aggregate (quando filtrato per adset_name)"""
    user = request.session.get('user')
    if not user:
        return JSONResponse({"error": "Non autorizzato"}, status_code=401)
    
    if not db.query(User).filter(User.email == user.get('email')).first():
        return JSONResponse({"error": "Non autorizzato"}, status_code=401)

    account_id_filter = request.query_params.get('account_id')
    status_filter = request.query_params.get('status')
    campaign_name_filter = request.query_params.get('campaign_name')

    # Adset name filter (required for this endpoint)
    adset_name_filter = request.query_params.get('adset_name')
    if not adset_name_filter:
        return JSONResponse({"error": "adset_name filter required"}, status_code=400)
    
    # Piattaforma (facebook / instagram / all)
    platform = request.query_params.get('platform', 'all')

    date_from_obj, date_to_obj = _marketing_date_range_from_request(request)

    adsets_q = (
        db.query(MetaAdSet, MetaCampaign)
        .join(MetaCampaign, MetaAdSet.campaign_id == MetaCampaign.id)
        .join(MetaAccount, MetaCampaign.account_id == MetaAccount.id)
        .filter(
            MetaAccount.is_active == True,
            MetaAdSet.name.ilike(f"%{adset_name_filter}%"),
        )
    )
    if account_id_filter:
        try:
            adsets_q = adsets_q.filter(MetaAccount.id == int(account_id_filter))
        except ValueError:
            pass
    if status_filter:
        if status_filter == "active":
            adsets_q = adsets_q.filter(MetaCampaign.status == "ACTIVE")
        elif status_filter == "inactive":
            adsets_q = adsets_q.filter(MetaCampaign.status != "ACTIVE")
        elif status_filter != "all":
            adsets_q = adsets_q.filter(MetaCampaign.status == status_filter)
    if campaign_name_filter:
        adsets_q = adsets_q.filter(MetaCampaign.name.ilike(f"%{campaign_name_filter}%"))

    pairs = adsets_q.options(joinedload(MetaCampaign.account)).all()
    result = []

    if pairs:
        adset_pks = [a.id for a, _c in pairs]
        adset_meta_ids = [str(a.adset_id).strip() for a, _c in pairs if a.adset_id]
        mag_to_pay = _get_mag_to_pay(db)
        leads_by_as = _bulk_leads_by_meta_adset(db, adset_meta_ids, date_from_obj, date_to_obj, platform)
        md_by_as = _bulk_marketing_by_adset_pk(db, adset_pks, date_from_obj, date_to_obj, platform)

        for adset, campaign in pairs:
            account = campaign.account
            aid = str(adset.adset_id).strip() if adset.adset_id else ""
            leads = leads_by_as.get(aid, [])
            marketing_data = md_by_as.get(adset.id, [])
            m = _marketing_metrics_block(leads, marketing_data, mag_to_pay, db)
            if m.pop("_skip"):
                continue
            result.append(
                {
                    "id": adset.id,
                    "adset_id": adset.adset_id,
                    "name": adset.name,
                    "status": adset.status,
                    "campaign_id": campaign.id,
                    "campaign_name": campaign.name,
                    "account_id": account.id if account else None,
                    "account_name": account.name if account else None,
                    **m,
                }
            )

    return JSONResponse(result)

@router.get("/api/marketing/ads")
async def api_marketing_ads(request: Request, db: Session = Depends(get_db)):
    """API: Lista ads con metriche aggregate (quando filtrato per ad_name)"""
    user = request.session.get('user')
    if not user:
        return JSONResponse({"error": "Non autorizzato"}, status_code=401)
    
    if not db.query(User).filter(User.email == user.get('email')).first():
        return JSONResponse({"error": "Non autorizzato"}, status_code=401)

    account_id_filter = request.query_params.get('account_id')
    status_filter = request.query_params.get('status')
    campaign_name_filter = request.query_params.get('campaign_name')
    adset_name_filter = request.query_params.get('adset_name')
    ad_name_filter = request.query_params.get('ad_name')
    if not ad_name_filter:
        return JSONResponse({"error": "ad_name filter required"}, status_code=400)
    
    # Piattaforma (facebook / instagram / all)
    platform = request.query_params.get('platform', 'all')

    date_from_obj, date_to_obj = _marketing_date_range_from_request(request)

    triples_q = (
        db.query(MetaAd, MetaAdSet, MetaCampaign)
        .join(MetaAdSet, MetaAd.adset_id == MetaAdSet.id)
        .join(MetaCampaign, MetaAdSet.campaign_id == MetaCampaign.id)
        .join(MetaAccount, MetaCampaign.account_id == MetaAccount.id)
        .filter(
            MetaAccount.is_active == True,
            MetaAd.name.ilike(f"%{ad_name_filter}%"),
        )
    )
    if account_id_filter:
        try:
            triples_q = triples_q.filter(MetaAccount.id == int(account_id_filter))
        except ValueError:
            pass
    if status_filter:
        if status_filter == "active":
            triples_q = triples_q.filter(MetaCampaign.status == "ACTIVE")
        elif status_filter == "inactive":
            triples_q = triples_q.filter(MetaCampaign.status != "ACTIVE")
        elif status_filter != "all":
            triples_q = triples_q.filter(MetaCampaign.status == status_filter)
    if campaign_name_filter:
        triples_q = triples_q.filter(MetaCampaign.name.ilike(f"%{campaign_name_filter}%"))
    if adset_name_filter:
        triples_q = triples_q.filter(MetaAdSet.name.ilike(f"%{adset_name_filter}%"))

    triples = triples_q.options(joinedload(MetaCampaign.account)).all()
    result = []

    if triples:
        ad_pks = [ad.id for ad, _s, _c in triples]
        meta_ad_ids = [str(ad.ad_id).strip() for ad, _s, _c in triples if ad.ad_id]
        mag_to_pay = _get_mag_to_pay(db)
        leads_by_ad = _bulk_leads_by_meta_ad_id(db, meta_ad_ids, date_from_obj, date_to_obj, platform)
        md_by_ad = _bulk_marketing_by_ad_pk(db, ad_pks, date_from_obj, date_to_obj, platform)

        for ad, adset, campaign in triples:
            account = campaign.account
            mid = str(ad.ad_id).strip() if ad.ad_id else ""
            leads = leads_by_ad.get(mid, [])
            marketing_data = md_by_ad.get(ad.id, [])
            m = _marketing_metrics_block(leads, marketing_data, mag_to_pay, db)
            if m.pop("_skip"):
                continue
            result.append(
                {
                    "id": ad.id,
                    "ad_id": ad.ad_id,
                    "name": ad.name,
                    "status": ad.status,
                    "creative_thumbnail_url": ad.creative_thumbnail_url or "",
                    "creative_id": ad.creative_id or "",
                    "adset_id": adset.id,
                    "adset_name": adset.name,
                    "campaign_id": campaign.id,
                    "campaign_name": campaign.name,
                    "account_id": account.id if account else None,
                    "account_name": account.name if account else None,
                    **m,
                }
            )

    return JSONResponse(result)
