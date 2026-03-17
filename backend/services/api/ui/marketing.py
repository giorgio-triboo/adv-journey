"""Marketing views e API"""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse, JSONResponse, Response
from sqlalchemy.orm import Session
from database import get_db
from models import MetaAccount, MetaCampaign, MetaAdSet, MetaAd, MetaMarketingData, Lead, StatusCategory, User, ManagedCampaign, UlixeRcrmTemp
from sqlalchemy import func, desc, and_
from datetime import datetime, timedelta
from typing import List
from urllib.parse import urlparse
import httpx
import logging
from .common import templates

logger = logging.getLogger('services.api.ui')

router = APIRouter(include_in_schema=False)


def _get_mag_to_pay(db: Session) -> dict:
    """Mappa magellano_campaign_id -> pay_level da ManagedCampaign attive."""
    managed = db.query(ManagedCampaign).filter(ManagedCampaign.is_active == True).all()
    mag_to_pay = {}
    for mc in managed:
        if mc.magellano_ids and mc.pay_level:
            try:
                pay_val = float(str(mc.pay_level).replace(',', '.'))
                for mid in mc.magellano_ids:
                    mag_to_pay[str(mid)] = pay_val
            except (ValueError, TypeError):
                pass
    return mag_to_pay


def _get_pay_for_leads(db: Session, leads: list) -> float | None:
    """
    Ottiene il pay più frequente tra le lead (moda).
    Usato per pay_level di riferimento; per ricavo effettivo usare _compute_ricavo_for_leads.
    """
    if not leads:
        return None
    mag_to_pay = _get_mag_to_pay(db)
    pays = []
    for l in leads:
        if l.magellano_campaign_id and str(l.magellano_campaign_id) in mag_to_pay:
            pays.append(mag_to_pay[str(l.magellano_campaign_id)])
    if not pays:
        return None
    from collections import Counter
    counts = Counter(pays)
    return counts.most_common(1)[0][0]


def _compute_ricavo_for_leads(db: Session, leads: list) -> float:
    """
    Ricavo = somma del pay di ogni lead (ogni lead ha magellano_campaign_id -> campagna -> pay).
    """
    if not leads:
        return 0.0
    mag_to_pay = _get_mag_to_pay(db)
    total = 0.0
    for l in leads:
        if l.magellano_campaign_id and str(l.magellano_campaign_id) in mag_to_pay:
            total += mag_to_pay[str(l.magellano_campaign_id)]
    return total


def _get_msg_to_pay(db: Session) -> dict:
    """Mappa msg_id (Ulixe) -> pay_level da ManagedCampaign.msg_ids."""
    managed = db.query(ManagedCampaign).filter(ManagedCampaign.is_active == True).all()
    msg_to_pay = {}
    for mc in managed:
        if not mc.msg_ids or not mc.pay_level:
            continue
        try:
            pay_val = float(str(mc.pay_level).replace(',', '.'))
        except (ValueError, TypeError):
            continue
        for item in mc.msg_ids:
            if isinstance(item, dict):
                vid = item.get("id")
            else:
                vid = str(item)
            if vid:
                msg_to_pay[str(vid)] = pay_val
    return msg_to_pay


def _get_ricavo_from_rcrm_temp(db: Session, date_from, date_to) -> float:
    """
    Ricavo da ulixe_rcrm_temp: somma di (rcrm_count × pay per msg_id) per periodi nel range.
    Usato quando le approvate provengono da RCRM e non dalle lead.
    """
    date_from_d = date_from.date() if hasattr(date_from, "date") else date_from
    date_to_d = date_to.date() if hasattr(date_to, "date") else date_to
    periods = []
    y, m = date_from_d.year, date_from_d.month
    end_y, end_m = date_to_d.year, date_to_d.month
    while (y, m) <= (end_y, end_m):
        periods.append(f"{y}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    if not periods:
        return 0.0
    msg_to_pay = _get_msg_to_pay(db)
    if not msg_to_pay:
        return 0.0
    rows = db.query(UlixeRcrmTemp.msg_id, UlixeRcrmTemp.rcrm_count).filter(
        UlixeRcrmTemp.period.in_(periods),
        UlixeRcrmTemp.msg_id.in_(list(msg_to_pay.keys())),
    ).all()
    total = 0.0
    for msg_id, rcrm_count in rows:
        pay = msg_to_pay.get(str(msg_id))
        if pay is not None and rcrm_count:
            total += rcrm_count * pay
    return total


def _lead_date_filter(date_from_obj, date_to_obj):
    """Filtra lead per data: usa SEMPRE magellano_subscr_date (lead senza data subscr. escluse)."""
    date_from_d = date_from_obj.date() if hasattr(date_from_obj, "date") else date_from_obj
    date_to_d = date_to_obj.date() if hasattr(date_to_obj, "date") else date_to_obj
    return and_(
        Lead.magellano_subscr_date.isnot(None),
        Lead.magellano_subscr_date >= date_from_d,
        Lead.magellano_subscr_date <= date_to_d,
    )


def _get_valid_msg_ids_from_managed(db: Session) -> set:
    """Msg_id configurati in ManagedCampaign (solo attive)."""
    managed = db.query(ManagedCampaign).filter(ManagedCampaign.is_active == True).all()
    valid = set()
    for mc in managed:
        if not mc.msg_ids:
            continue
        for item in mc.msg_ids:
            if isinstance(item, dict):
                vid = item.get("id")
                if vid:
                    valid.add(str(vid))
            else:
                valid.add(str(item))
    return {x for x in valid if x}


def get_unmapped_ulixe_ids(db: Session) -> list[str]:
    """
    Msg_id presenti in ulixe_rcrm_temp ma NON configurati in ManagedCampaign.
    Usato per avvisare che alcuni ID da export RCRM non sono mappati.
    """
    valid = _get_valid_msg_ids_from_managed(db)
    rcrm_msg_ids = db.query(UlixeRcrmTemp.msg_id).distinct().all()
    rcrm_set = {str(m[0]) for m in rcrm_msg_ids if m[0]}
    unmapped = sorted(rcrm_set - valid)
    return unmapped


def _get_ulixe_approvate_from_rcrm_temp(db: Session, date_from, date_to) -> int | None:
    """
    Somma RCRM dalla tabella provvisoria ulixe_rcrm_temp per i periodi nel range.
    Considera SOLO msg_id configurati in ManagedCampaign (esclude ID Ulixe non mappati).
    Ritorna None se non ci sono dati (usa status_category come fallback).
    """
    date_from_d = date_from.date() if hasattr(date_from, "date") else date_from
    date_to_d = date_to.date() if hasattr(date_to, "date") else date_to
    periods = []
    y, m = date_from_d.year, date_from_d.month
    end_y, end_m = date_to_d.year, date_to_d.month
    while (y, m) <= (end_y, end_m):
        periods.append(f"{y}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    if not periods:
        return None
    valid_msg_ids = _get_valid_msg_ids_from_managed(db)
    if not valid_msg_ids:
        return None
    from sqlalchemy import func
    row = db.query(func.sum(UlixeRcrmTemp.rcrm_count)).filter(
        UlixeRcrmTemp.period.in_(periods),
        UlixeRcrmTemp.msg_id.in_(valid_msg_ids),
    ).scalar()
    # None = nessun record per periodi+msg_id validi -> fallback status_category
    if row is None:
        return None
    return int(row)  # 0 è valido (somma filtrata = 0)


@router.get("/api/ui/unmapped-ulixe-ids")
async def api_unmapped_ulixe_ids(request: Request, db: Session = Depends(get_db)):
    """
    Ritorna gli msg_id presenti in ulixe_rcrm_temp ma NON in ManagedCampaign.
    Usato dalla sidebar per mostrare banner '(!) N id da mappare'.
    """
    if not request.session.get("user"):
        return JSONResponse({"ids": [], "count": 0})
    ids = get_unmapped_ulixe_ids(db)
    return JSONResponse({"ids": ids, "count": len(ids)})


def _parse_amount(val) -> float:
    """
    Normalizza importi provenienti da MetaMarketingData:
    - supporta tipi numerici (int/float/Decimal)
    - supporta vecchie stringhe EU (\"1.360,71\") e nuove US (\"1360.71\").
    """
    if val is None:
        return 0.0
    # Numerici puri
    if isinstance(val, (int, float)):
        return float(val)
    try:
        from decimal import Decimal
        if isinstance(val, Decimal):
            return float(val)
    except ImportError:
        pass
    s = str(val).strip()
    if not s:
        return 0.0
    if '.' in s and ',' in s:
        s = s.replace('.', '').replace(',', '.')
    elif ',' in s:
        s = s.replace(',', '.')
    return float(s)


@router.get("/marketing/analysis")
async def marketing_analysis(request: Request, db: Session = Depends(get_db)):
    """
    Vista Analysis: filtri + KPI aggregati sui MetaMarketingData.
    I grafici verranno definiti in una fase successiva.
    """
    try:
        user = request.session.get('user')
        if not user:
            return RedirectResponse(url='/')

        current_user = db.query(User).filter(User.email == user.get('email')).first()
        if not current_user:
            return RedirectResponse(url='/')

        # Filtri base
        params = request.query_params
        selected_account_id = params.get('account_id') or ''
        selected_campaign_id = params.get('campaign_id') or ''
        selected_adset_id_param = params.get('adset_id') or ''
        try:
            selected_adset_id = int(selected_adset_id_param) if selected_adset_id_param else None
        except ValueError:
            selected_adset_id = None

        # Date range con default ultimi 30 giorni
        date_from_str = params.get('date_from')
        date_to_str = params.get('date_to')

        try:
            date_from = datetime.strptime(date_from_str, '%Y-%m-%d') if date_from_str else datetime.now() - timedelta(days=30)
        except Exception:
            date_from = datetime.now() - timedelta(days=30)

        try:
            date_to = datetime.strptime(date_to_str, '%Y-%m-%d') if date_to_str else datetime.now()
        except Exception:
            date_to = datetime.now()

        # Accounts accessibili all'utente
        accounts = db.query(MetaAccount).filter(
            MetaAccount.is_active == True,
            (MetaAccount.user_id == None) | (MetaAccount.user_id == current_user.id)
        ).order_by(MetaAccount.name).all()

        # Campagne accessibili (per select)
        campaigns_query = db.query(MetaCampaign).join(MetaAccount).filter(
            MetaAccount.is_active == True,
            (MetaAccount.user_id == None) | (MetaAccount.user_id == current_user.id)
        )

        if selected_account_id:
            campaigns_query = campaigns_query.filter(MetaAccount.account_id == selected_account_id)

        campaigns = campaigns_query.order_by(MetaCampaign.name).all()

        # AdSet accessibili (per select, dipendono da account/campagna)
        adsets_query = db.query(MetaAdSet).join(MetaCampaign).join(MetaAccount).filter(
            MetaAccount.is_active == True,
            (MetaAccount.user_id == None) | (MetaAccount.user_id == current_user.id)
        )
        if selected_account_id:
            adsets_query = adsets_query.filter(MetaAccount.account_id == selected_account_id)
        if selected_campaign_id:
            adsets_query = adsets_query.filter(MetaCampaign.campaign_id == selected_campaign_id)
        adsets = adsets_query.order_by(MetaAdSet.name).all()

        # Query principale sui MetaMarketingData
        query = (
            db.query(MetaMarketingData, MetaAd, MetaAdSet, MetaCampaign, MetaAccount)
            .join(MetaAd, MetaMarketingData.ad_id == MetaAd.id)
            .join(MetaAdSet, MetaAd.adset_id == MetaAdSet.id)
            .join(MetaCampaign, MetaAdSet.campaign_id == MetaCampaign.id)
            .join(MetaAccount, MetaCampaign.account_id == MetaAccount.id)
            .filter(
                MetaAccount.is_active == True,
                (MetaAccount.user_id == None) | (MetaAccount.user_id == current_user.id),
                MetaMarketingData.date >= date_from,
                MetaMarketingData.date <= date_to,
            )
        )

        if selected_account_id:
            query = query.filter(MetaAccount.account_id == selected_account_id)
        if selected_campaign_id:
            query = query.filter(MetaCampaign.campaign_id == selected_campaign_id)
        if selected_adset_id:
            query = query.filter(MetaAdSet.id == selected_adset_id)

        marketing_rows = query.all()

        # Breakdown per piattaforma (facebook / instagram)
        platform_totals = {
            "facebook": {},
            "instagram": {},
        }
        platform_chart_points = {
            "facebook": [],
            "instagram": [],
        }
        platform_distribution_points = {
            "facebook": [],
            "instagram": [],
        }


        # Calcolo KPI aggregati base
        total_spend = 0.0
        total_impressions = 0
        total_clicks = 0
        total_conversions = 0
        ctr_values = []
        cpc_values = []
        cpm_values = []

        for md, _ad, _adset, _campaign, _account in marketing_rows:
            total_spend += _parse_amount(md.spend)
            total_impressions += md.impressions or 0
            total_clicks += md.clicks or 0
            total_conversions += md.conversions or 0

            if md.ctr is not None:
                ctr_values.append(float(md.ctr))
            if md.cpc is not None:
                cpc_values.append(float(md.cpc))
            if md.cpm is not None:
                cpm_values.append(float(md.cpm))

        def _avg(values):
            return float(sum(values) / len(values)) if values else 0.0

        # CPL aggregato (spend totale / lead totali)
        global_cpl = (total_spend / total_conversions) if total_conversions > 0 else 0.0

        totals = {
            "total_spend": round(total_spend, 2),
            "total_impressions": total_impressions,
            "total_clicks": total_clicks,
            "total_conversions": total_conversions,
            "global_cpl": round(global_cpl, 2),
            "avg_ctr": round(_avg(ctr_values), 2),
            "avg_cpc": round(_avg(cpc_values), 4),
            "avg_cpm": round(_avg(cpm_values), 2),
        }

        # Serie giornaliera per grafico Spend vs CPL
        daily_query = (
            db.query(
                func.date(MetaMarketingData.date).label("day"),
                func.sum(MetaMarketingData.spend).label("total_spend"),
                func.sum(MetaMarketingData.conversions).label("total_conversions"),
            )
            .join(MetaAd, MetaMarketingData.ad_id == MetaAd.id)
            .join(MetaAdSet, MetaAd.adset_id == MetaAdSet.id)
            .join(MetaCampaign, MetaAdSet.campaign_id == MetaCampaign.id)
            .join(MetaAccount, MetaCampaign.account_id == MetaAccount.id)
            .filter(
                MetaAccount.is_active == True,
                (MetaAccount.user_id == None) | (MetaAccount.user_id == current_user.id),
                MetaMarketingData.date >= date_from,
                MetaMarketingData.date <= date_to,
            )
        )

        if selected_account_id:
            daily_query = daily_query.filter(MetaAccount.account_id == selected_account_id)
        if selected_campaign_id:
            daily_query = daily_query.filter(MetaCampaign.campaign_id == selected_campaign_id)
        if selected_adset_id:
            daily_query = daily_query.filter(MetaAdSet.id == selected_adset_id)

        daily_rows = (
            daily_query
            .group_by(func.date(MetaMarketingData.date))
            .order_by(func.date(MetaMarketingData.date))
            .all()
        )

        chart_points = []
        for row in daily_rows:
            day = row.day
            try:
                date_str = day.strftime('%Y-%m-%d')
            except AttributeError:
                date_str = str(day)

            day_spend = _parse_amount(row.total_spend) if row.total_spend is not None else 0.0
            day_conversions = int(row.total_conversions or 0)
            day_cpl = (day_spend / day_conversions) if day_conversions > 0 else 0.0

            chart_points.append(
                {
                    "date": date_str,
                    "spend": round(day_spend, 2),
                    "conversions": day_conversions,
                    "cpl": round(day_cpl, 2),
                }
            )

        # Distribuzione per campagne: periodo corrente vs periodo precedente (stessa durata)
        period_days = max((date_to.date() - date_from.date()).days + 1, 1)
        prev_end = date_from - timedelta(days=1)
        prev_start = prev_end - timedelta(days=period_days - 1)

        # Aggregazione per campagna - periodo corrente (speso + lead)
        current_dist_query = (
            db.query(
                MetaCampaign.id.label("campaign_id"),
                MetaCampaign.name.label("campaign_name"),
                func.sum(MetaMarketingData.spend).label("spend_current"),
                func.sum(MetaMarketingData.conversions).label("conv_current"),
            )
            .join(MetaAdSet, MetaAdSet.campaign_id == MetaCampaign.id)
            .join(MetaAd, MetaAd.adset_id == MetaAdSet.id)
            .join(MetaMarketingData, MetaMarketingData.ad_id == MetaAd.id)
            .join(MetaAccount, MetaCampaign.account_id == MetaAccount.id)
            .filter(
                MetaAccount.is_active == True,
                (MetaAccount.user_id == None) | (MetaAccount.user_id == current_user.id),
                MetaMarketingData.date >= date_from,
                MetaMarketingData.date <= date_to,
            )
        )

        # Applica sempre i filtri selezionati (account / campagna / adset)
        if selected_account_id:
            current_dist_query = current_dist_query.filter(MetaAccount.account_id == selected_account_id)
        if selected_campaign_id:
            current_dist_query = current_dist_query.filter(MetaCampaign.campaign_id == selected_campaign_id)
        if selected_adset_id:
            current_dist_query = current_dist_query.filter(MetaAdSet.id == selected_adset_id)

        current_dist_rows = (
            current_dist_query
            .group_by(MetaCampaign.id, MetaCampaign.name)
            .all()
        )

        # Aggregazione per campagna - periodo precedente (speso + lead)
        prev_dist_query = (
            db.query(
                MetaCampaign.id.label("campaign_id"),
                func.sum(MetaMarketingData.spend).label("spend_prev"),
                func.sum(MetaMarketingData.conversions).label("conv_prev"),
            )
            .join(MetaAdSet, MetaAdSet.campaign_id == MetaCampaign.id)
            .join(MetaAd, MetaAd.adset_id == MetaAdSet.id)
            .join(MetaMarketingData, MetaMarketingData.ad_id == MetaAd.id)
            .join(MetaAccount, MetaCampaign.account_id == MetaAccount.id)
            .filter(
                MetaAccount.is_active == True,
                (MetaAccount.user_id == None) | (MetaAccount.user_id == current_user.id),
                MetaMarketingData.date >= prev_start,
                MetaMarketingData.date <= prev_end,
            )
        )

        if selected_account_id:
            prev_dist_query = prev_dist_query.filter(MetaAccount.account_id == selected_account_id)
        if selected_campaign_id:
            prev_dist_query = prev_dist_query.filter(MetaCampaign.campaign_id == selected_campaign_id)
        if selected_adset_id:
            prev_dist_query = prev_dist_query.filter(MetaAdSet.id == selected_adset_id)

        prev_dist_rows = (
            prev_dist_query
            .group_by(MetaCampaign.id)
            .all()
        )

        prev_map = {
            row.campaign_id: {
                "spend_prev": _parse_amount(row.spend_prev) if row.spend_prev is not None else 0.0,
                "conv_prev": int(row.conv_prev or 0),
            }
            for row in prev_dist_rows
        }

        # Aggrega su TUTTE le campagne: confronto solo per periodo (data come discriminante)
        total_spend_current = 0.0
        total_spend_prev = 0.0
        total_leads_current = 0
        total_leads_prev = 0

        for row in current_dist_rows:
            current_spend = _parse_amount(row.spend_current) if row.spend_current is not None else 0.0
            current_leads = int(row.conv_current or 0)
            total_spend_current += current_spend
            total_leads_current += current_leads

            prev_info = prev_map.get(row.campaign_id, {"spend_prev": 0.0, "conv_prev": 0})
            prev_spend = prev_info["spend_prev"]
            prev_leads = prev_info["conv_prev"]
            total_spend_prev += prev_spend
            total_leads_prev += prev_leads

        cpl_current_agg = (total_spend_current / total_leads_current) if total_leads_current > 0 else 0.0
        cpl_prev_agg = (total_spend_prev / total_leads_prev) if total_leads_prev > 0 else 0.0

        distribution_points = [
            {
                "name": "Periodo selezionato",
                "spend_current": round(total_spend_current, 2),
                "spend_prev": round(total_spend_prev, 2),
                "leads_current": total_leads_current,
                "leads_prev": total_leads_prev,
                "cpl_current": round(cpl_current_agg, 2),
                "cpl_prev": round(cpl_prev_agg, 2),
            }
        ]

        # Metriche Magellano/Ulixe: scope da campaign_ids/adset_ids presenti in marketing_rows
        campaign_ids = set()
        adset_ids = set()
        for md, ad, adset, campaign, account in marketing_rows:
            if campaign and campaign.campaign_id:
                campaign_ids.add(str(campaign.campaign_id))
            if adset and adset.adset_id:
                adset_ids.add(str(adset.adset_id))

        total_magellano_entrate = 0
        total_magellano_doppioni = 0
        total_magellano_scartate = 0
        total_magellano_inviate = 0
        total_ulixe_approvate = 0
        total_ulixe_scartate = 0
        rcrm_approvate = None
        leads_count = 0
        total_ricavo = 0.0
        total_margine = 0.0
        total_margine_pct = None
        pay_campagna = None

        if campaign_ids:
            lead_query = db.query(Lead).filter(_lead_date_filter(date_from, date_to))
            lead_query = lead_query.filter(Lead.meta_campaign_id.in_(campaign_ids))
            if adset_ids and selected_adset_id:
                lead_query = lead_query.filter(Lead.meta_adset_id.in_(adset_ids))
            leads_in_scope = lead_query.all()
            leads_count = len(leads_in_scope)
            total_magellano_entrate = len([l for l in leads_in_scope if l.magellano_campaign_id])
            total_magellano_inviate = len([l for l in leads_in_scope if l.magellano_status == "magellano_sent"])
            # Approvate: preferisci RCRM da tabella temp (export Ulixe) se disponibile, altrimenti status_category
            rcrm_approvate = _get_ulixe_approvate_from_rcrm_temp(db, date_from, date_to)
            total_ulixe_approvate = rcrm_approvate if rcrm_approvate is not None else len([l for l in leads_in_scope if l.status_category == StatusCategory.FINALE])
            # Doppioni = Meta conta più di noi (conversioni duplicate in Meta)
            total_magellano_doppioni = max(0, total_conversions - leads_count)
            # Scartate = lead in Magellano non inviate al cliente (include firewall; esclude solo refused da WS)
            total_magellano_scartate = len([
                l for l in leads_in_scope
                if l.magellano_campaign_id
                and l.magellano_status not in ("magellano_sent", "magellano_refused")
            ])
            total_ulixe_scartate = len([l for l in leads_in_scope if l.status_category == StatusCategory.RIFIUTATO])

            # Ricavo = somma del pay di ogni lead approvata (ogni lead → campagna → pay)
            leads_approvate = [l for l in leads_in_scope if l.status_category == StatusCategory.FINALE]
            if rcrm_approvate is not None:
                # Usando RCRM per il conteggio: ricavo da ulixe_rcrm_temp (msg_id × pay)
                total_ricavo = _get_ricavo_from_rcrm_temp(db, date_from, date_to)
            else:
                # Usando leads: somma pay per ogni lead approvata
                total_ricavo = _compute_ricavo_for_leads(db, leads_approvate)
            pay_campagna = _get_pay_for_leads(db, leads_in_scope)
            if total_ricavo > 0:
                total_margine = total_ricavo - total_spend
                total_margine_pct = round((total_margine / total_ricavo * 100), 2)

        totals["pay_level"] = round(pay_campagna, 2) if pay_campagna is not None else None
        totals["total_magellano_entrate"] = total_magellano_entrate
        totals["total_magellano_inviate"] = total_magellano_inviate
        # Se nessuna campagna in scope, usa comunque RCRM per riferimento
        if not campaign_ids:
            rcrm_approvate = _get_ulixe_approvate_from_rcrm_temp(db, date_from, date_to)
            if rcrm_approvate is not None:
                total_ulixe_approvate = rcrm_approvate
                total_ricavo = _get_ricavo_from_rcrm_temp(db, date_from, date_to)
                if total_ricavo > 0:
                    total_margine = total_ricavo - total_spend
                    total_margine_pct = round((total_margine / total_ricavo * 100), 2)
        totals["total_ulixe_approvate"] = total_ulixe_approvate
        totals["ulixe_approvate_from_rcrm"] = rcrm_approvate is not None
        totals["total_ricavo"] = round(total_ricavo, 2)
        totals["total_margine"] = round(total_margine, 2)
        totals["total_margine_pct"] = total_margine_pct
        totals["total_magellano_doppioni"] = total_magellano_doppioni
        totals["total_magellano_scartate"] = total_magellano_scartate
        totals["total_ulixe_scartate"] = total_ulixe_scartate
        totals["leads_count"] = leads_count
        # % rispetto a Lead (leads_count per scartate; total_conversions per doppioni)
        totals["magellano_doppioni_pct"] = round((total_magellano_doppioni / total_conversions * 100), 1) if total_conversions > 0 else 0
        totals["magellano_scartate_pct"] = round((total_magellano_scartate / leads_count * 100), 1) if leads_count > 0 else 0
        totals["ulixe_scartate_pct"] = round((total_ulixe_scartate / leads_count * 100), 1) if leads_count > 0 else 0

        # Calcolo breakdown per piattaforma (Meta only + Magellano/Ulixe)
        for platform_key in ("facebook", "instagram"):
            # Meta KPI per piattaforma
            p_query = (
                db.query(MetaMarketingData, MetaAd, MetaAdSet, MetaCampaign, MetaAccount)
                .join(MetaAd, MetaMarketingData.ad_id == MetaAd.id)
                .join(MetaAdSet, MetaAd.adset_id == MetaAdSet.id)
                .join(MetaCampaign, MetaAdSet.campaign_id == MetaCampaign.id)
                .join(MetaAccount, MetaCampaign.account_id == MetaAccount.id)
                .filter(
                    MetaAccount.is_active == True,
                    (MetaAccount.user_id == None) | (MetaAccount.user_id == current_user.id),
                    MetaMarketingData.date >= date_from,
                    MetaMarketingData.date <= date_to,
                    MetaMarketingData.publisher_platform == platform_key,
                )
            )
            if selected_account_id:
                p_query = p_query.filter(MetaAccount.account_id == selected_account_id)
            if selected_campaign_id:
                p_query = p_query.filter(MetaCampaign.campaign_id == selected_campaign_id)
            if selected_adset_id:
                p_query = p_query.filter(MetaAdSet.id == selected_adset_id)

            p_rows = p_query.all()

            p_spend = 0.0
            p_impr = 0
            p_clicks = 0
            p_convs = 0
            p_ctr_vals: list[float] = []
            p_cpc_vals: list[float] = []
            p_cpm_vals: list[float] = []

            p_campaign_ids: set[str] = set()
            for md, ad, adset, campaign, account in p_rows:
                p_spend += _parse_amount(md.spend)
                p_impr += md.impressions or 0
                p_clicks += md.clicks or 0
                p_convs += md.conversions or 0
                if md.ctr is not None:
                    p_ctr_vals.append(float(md.ctr))
                if md.cpc is not None:
                    p_cpc_vals.append(float(md.cpc))
                if md.cpm is not None:
                    p_cpm_vals.append(float(md.cpm))
                if campaign and campaign.campaign_id:
                    p_campaign_ids.add(str(campaign.campaign_id))

            p_cpl = (p_spend / p_convs) if p_convs > 0 else 0.0

            # Serie giornaliera per piattaforma
            p_daily_query = (
                db.query(
                    func.date(MetaMarketingData.date).label("day"),
                    func.sum(MetaMarketingData.spend).label("total_spend"),
                    func.sum(MetaMarketingData.conversions).label("total_conversions"),
                )
                .join(MetaAd, MetaMarketingData.ad_id == MetaAd.id)
                .join(MetaAdSet, MetaAd.adset_id == MetaAdSet.id)
                .join(MetaCampaign, MetaAdSet.campaign_id == MetaCampaign.id)
                .join(MetaAccount, MetaCampaign.account_id == MetaAccount.id)
                .filter(
                    MetaAccount.is_active == True,
                    (MetaAccount.user_id == None) | (MetaAccount.user_id == current_user.id),
                    MetaMarketingData.date >= date_from,
                    MetaMarketingData.date <= date_to,
                    MetaMarketingData.publisher_platform == platform_key,
                )
            )
            if selected_account_id:
                p_daily_query = p_daily_query.filter(MetaAccount.account_id == selected_account_id)
            if selected_campaign_id:
                p_daily_query = p_daily_query.filter(MetaCampaign.campaign_id == selected_campaign_id)
            if selected_adset_id:
                p_daily_query = p_daily_query.filter(MetaAdSet.id == selected_adset_id)

            p_daily_rows = (
                p_daily_query
                .group_by(func.date(MetaMarketingData.date))
                .order_by(func.date(MetaMarketingData.date))
                .all()
            )

            p_chart = []
            for row in p_daily_rows:
                day = row.day
                try:
                    date_str = day.strftime('%Y-%m-%d')
                except AttributeError:
                    date_str = str(day)
                d_spend = _parse_amount(row.total_spend) if row.total_spend is not None else 0.0
                d_convs = int(row.total_conversions or 0)
                d_cpl = (d_spend / d_convs) if d_convs > 0 else 0.0
                p_chart.append(
                    {
                        "date": date_str,
                        "spend": round(d_spend, 2),
                        "conversions": d_convs,
                        "cpl": round(d_cpl, 2),
                    }
                )
            platform_chart_points[platform_key] = p_chart

            # Metriche Magellano/Ulixe per piattaforma
            p_total_mag_entrate = 0
            p_total_mag_inviate = 0
            p_total_ulixe_approvate = 0
            p_total_ulixe_scartate = 0
            p_total_mag_scartate = 0
            p_total_mag_doppioni = 0
            p_leads_count = 0
            p_total_ricavo = 0.0
            p_total_margine = 0.0
            p_total_margine_pct = None

            if p_campaign_ids:
                p_lead_query = db.query(Lead).filter(_lead_date_filter(date_from, date_to))
                p_lead_query = p_lead_query.filter(Lead.meta_campaign_id.in_(p_campaign_ids))
                p_lead_query = p_lead_query.filter(Lead.platform == platform_key)
                p_leads = p_lead_query.all()
                p_leads_count = len(p_leads)
                p_total_mag_entrate = len([l for l in p_leads if l.magellano_campaign_id])
                p_total_mag_inviate = len([l for l in p_leads if l.magellano_status == "magellano_sent"])
                p_total_ulixe_approvate = len([l for l in p_leads if l.status_category == StatusCategory.FINALE])
                p_total_ulixe_scartate = len([l for l in p_leads if l.status_category == StatusCategory.RIFIUTATO])
                p_total_mag_scartate = len([
                    l for l in p_leads
                    if l.magellano_campaign_id
                    and l.magellano_status not in ("magellano_sent", "magellano_refused")
                ])
                p_total_mag_doppioni = max(0, p_convs - p_leads_count)

                p_leads_approvate = [l for l in p_leads if l.status_category == StatusCategory.FINALE]
                if p_leads_approvate:
                    p_total_ricavo = _compute_ricavo_for_leads(db, p_leads_approvate)
                    if p_total_ricavo > 0:
                        p_total_margine = p_total_ricavo - p_spend
                        p_total_margine_pct = round((p_total_margine / p_total_ricavo * 100), 2)

            platform_totals[platform_key] = {
                "total_spend": round(p_spend, 2),
                "total_impressions": p_impr,
                "total_clicks": p_clicks,
                "total_conversions": p_convs,
                "global_cpl": round(p_cpl, 2),
                "avg_ctr": round(_avg(p_ctr_vals), 2),
                "avg_cpc": round(_avg(p_cpc_vals), 4),
                "avg_cpm": round(_avg(p_cpm_vals), 2),
                "total_magellano_entrate": p_total_mag_entrate,
                "total_magellano_inviate": p_total_mag_inviate,
                "total_ulixe_approvate": p_total_ulixe_approvate,
                "total_ulixe_scartate": p_total_ulixe_scartate,
                "total_magellano_scartate": p_total_mag_scartate,
                "total_magellano_doppioni": p_total_mag_doppioni,
                "total_ricavo": round(p_total_ricavo, 2),
                "total_margine": round(p_total_margine, 2),
                "total_margine_pct": p_total_margine_pct,
                "leads_count": p_leads_count,
            }

        # Focus posizionamenti per piattaforma (publisher_platform + platform_position)
        placement_insights_by_platform: dict[str, list[dict[str, Any]]] = {
            "facebook": [],
            "instagram": [],
        }

        placement_query = (
            db.query(
                MetaMarketingData.publisher_platform.label("platform"),
                MetaMarketingData.platform_position.label("position"),
                func.sum(MetaMarketingData.spend).label("total_spend"),
                func.sum(MetaMarketingData.conversions).label("total_conversions"),
            )
            .join(MetaAd, MetaMarketingData.ad_id == MetaAd.id)
            .join(MetaAdSet, MetaAd.adset_id == MetaAdSet.id)
            .join(MetaCampaign, MetaAdSet.campaign_id == MetaCampaign.id)
            .join(MetaAccount, MetaCampaign.account_id == MetaAccount.id)
            .filter(
                MetaAccount.is_active == True,
                (MetaAccount.user_id == None) | (MetaAccount.user_id == current_user.id),
                MetaMarketingData.date >= date_from,
                MetaMarketingData.date <= date_to,
                MetaMarketingData.publisher_platform.in_(["facebook", "instagram"]),
            )
        )
        if selected_account_id:
            placement_query = placement_query.filter(MetaAccount.account_id == selected_account_id)
        if selected_campaign_id:
            placement_query = placement_query.filter(MetaCampaign.campaign_id == selected_campaign_id)
        if selected_adset_id:
            placement_query = placement_query.filter(MetaAdSet.id == selected_adset_id)

        placement_rows = (
            placement_query.group_by(
                MetaMarketingData.publisher_platform,
                MetaMarketingData.platform_position,
            )
            .order_by(func.sum(MetaMarketingData.spend).desc())
            .all()
        )

        for row in placement_rows:
            platform_key = (row.platform or "").lower()
            if platform_key not in placement_insights_by_platform:
                continue
            total_spend = _parse_amount(row.total_spend) if row.total_spend is not None else 0.0
            total_conversions = int(row.total_conversions or 0)
            cpl = (total_spend / total_conversions) if total_conversions > 0 else 0.0
            position_label = row.position or "unknown"
            placement_insights_by_platform[platform_key].append(
                {
                    "position": position_label,
                    "total_spend": round(total_spend, 2),
                    "total_conversions": total_conversions,
                    "cpl": round(cpl, 2),
                }
            )

        return templates.TemplateResponse(
            "marketing_analysis.html",
            {
                "request": request,
                "title": "Marketing Analysis",
                "user": user,
                "accounts": accounts,
                "campaigns": campaigns,
                "adsets": adsets,
                "totals": totals,
                "chart_points": chart_points,
                "distribution_points": distribution_points,
                "platform_totals": platform_totals,
                "platform_chart_points": platform_chart_points,
                "platform_distribution_points": platform_distribution_points,
                "placement_insights_by_platform": placement_insights_by_platform,
                "selected_account_id": selected_account_id,
                "selected_campaign_id": selected_campaign_id,
                "selected_adset_id": selected_adset_id,
                "date_from": date_from.strftime('%Y-%m-%d'),
                "date_to": date_to.strftime('%Y-%m-%d'),
                "active_page": "marketing_analysis",
            },
        )
    except Exception as e:
        logger.error(f"Errore nel route /marketing/analysis: {e}", exc_info=True)
        raise


@router.get("/marketing/prediction")
async def marketing_prediction(request: Request, db: Session = Depends(get_db)):
    """
    Vista Marketing Prediction (WIP) con sola documentazione e layout base.
    """
    try:
        user = request.session.get('user')
        if not user:
            return RedirectResponse(url='/')

        # Manteniamo controllo utente coerente con le altre viste
        current_user = db.query(User).filter(User.email == user.get('email')).first()
        if not current_user:
            return RedirectResponse(url='/')

        return templates.TemplateResponse(
            "marketing_prediction.html",
            {
                "request": request,
                "title": "Marketing Prediction",
                "user": user,
                "active_page": "marketing_prediction",
            },
        )
    except Exception as e:
        logger.error(f"Errore nel route /marketing/prediction: {e}", exc_info=True)
        raise

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
            "title": "Marketing ADV",
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


@router.get("/api/marketing/proxy-image")
async def proxy_creative_image(request: Request, db: Session = Depends(get_db)):
    """
    Proxy per le thumbnail delle creatività Meta.
    Ottiene un URL fresco dalla Graph API (con token) poi scarica l'immagine.
    """
    from services.utils.crypto import decrypt_token

    ad_id_param = request.query_params.get("ad_id")
    if not ad_id_param:
        return Response(status_code=400)
    try:
        ad_id_int = int(ad_id_param)
    except ValueError:
        return Response(status_code=400)

    ad = db.query(MetaAd).filter(MetaAd.id == ad_id_int).first()
    if not ad or not ad.creative_id:
        return Response(status_code=404)
    account = None
    if ad.adset and ad.adset.campaign:
        account = ad.adset.campaign.account
    if not account or not account.access_token:
        return Response(status_code=404)
    try:
        access_token = decrypt_token(account.access_token)
    except Exception:
        return Response(status_code=500)

    # Ottieni URL fresco dalla Graph API (evita URL scaduti/signed)
    graph_url = f"https://graph.facebook.com/v21.0/{ad.creative_id}/?fields=thumbnail_url,image_url&access_token={access_token}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(graph_url)
            r.raise_for_status()
            data = r.json()
            thumbnail_url = data.get("thumbnail_url") or data.get("image_url")
            if not thumbnail_url:
                return Response(status_code=404)
            # Scarica l'immagine (URL dalla Graph API è valido)
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            r2 = await client.get(thumbnail_url, headers=headers, follow_redirects=True)
            r2.raise_for_status()
            content_type = r2.headers.get("content-type", "image/jpeg")
            return Response(content=r2.content, media_type=content_type)
    except httpx.HTTPStatusError as e:
        logger.debug(f"Proxy image HTTP error: {e}")
        return Response(status_code=502)
    except Exception as e:
        logger.debug(f"Proxy image failed: {e}")
        return Response(status_code=502)


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
        
        # Piattaforma (facebook / instagram / all)
        platform = request.query_params.get('platform', 'all')

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
                leads_query = db.query(Lead).filter(
                    Lead.meta_campaign_id == campaign.campaign_id,
                    _lead_date_filter(date_from_obj, date_to_obj),
                )
                if platform in ('facebook', 'instagram'):
                    leads_query = leads_query.filter(Lead.platform == platform)
                leads = leads_query.all()
                
                # Calculate CPL Meta (from MetaMarketingData)
                marketing_query = db.query(MetaMarketingData).join(MetaAd).join(MetaAdSet).filter(
                    MetaAdSet.campaign_id == campaign.id,
                    MetaMarketingData.date >= date_from_obj,
                    MetaMarketingData.date <= date_to_obj
                )
                if platform in ('facebook', 'instagram'):
                    marketing_query = marketing_query.filter(MetaMarketingData.publisher_platform == platform)
                marketing_data = marketing_query.all()
                
                total_spend_meta = sum(_parse_amount(md.spend) for md in marketing_data)
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
                # % scarto totale: acquisto Meta -> uscita Magellano (lead perse lungo tutto il funnel)
                scarto_totale_pct = ((total_leads - magellano_inviate) / total_leads * 100) if total_leads > 0 else 0
                
                # Ulixe: stati principali
                ulixe_lavorazione = len([l for l in leads if l.status_category == StatusCategory.IN_LAVORAZIONE])
                ulixe_rifiutate = len([l for l in leads if l.status_category == StatusCategory.RIFIUTATO])
                ulixe_approvate = len([l for l in leads if l.status_category == StatusCategory.FINALE])
                leads_approvate = [l for l in leads if l.status_category == StatusCategory.FINALE]

                # Ricavo e margine: somma pay per ogni lead approvata (ogni lead → campagna → pay)
                revenue = _compute_ricavo_for_leads(db, leads_approvate)
                pay_campagna = _get_pay_for_leads(db, leads)
                cpl_approvate = (total_spend_meta / ulixe_approvate) if ulixe_approvate > 0 else 0
                margine_singola = (pay_campagna - cpl_approvate) if pay_campagna and ulixe_approvate else None
                margine_lordo = (revenue - total_spend_meta) if revenue > 0 else None
                margine_pct = (margine_lordo / revenue * 100) if revenue and margine_lordo is not None else None
                
                # Nascondi campagne a 0 per il periodo (meno rumore)
                if total_leads == 0 and total_spend_meta == 0:
                    continue
                
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
                    "ulixe_approvate": ulixe_approvate,
                    # Ricavo e margine (da approvate)
                    "revenue": round(revenue, 2),
                    "margine_singola_lead": round(margine_singola, 2) if margine_singola is not None else None,
                    "margine_lordo": round(margine_lordo, 2) if margine_lordo is not None else None,
                    "margine_pct": round(margine_pct, 2) if margine_pct is not None else None,
                    "scarto_totale_pct": round(scarto_totale_pct, 2),
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
        total_ulixe_approvate = sum(c.get('ulixe_approvate', 0) for c in result)
        
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
                "total_ulixe_approvate": total_ulixe_approvate
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
                "total_ulixe_approvate": 0
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
    
    # Piattaforma (facebook / instagram / all)
    platform = request.query_params.get('platform', 'all')

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
        leads_query = db.query(Lead).filter(
            Lead.meta_adset_id == adset.adset_id,
            _lead_date_filter(date_from_obj, date_to_obj),
        )
        if platform in ('facebook', 'instagram'):
            leads_query = leads_query.filter(Lead.platform == platform)
        leads = leads_query.all()
        
        # Calculate CPL Meta
        marketing_query = db.query(MetaMarketingData).join(MetaAd).filter(
            MetaAd.adset_id == adset.id,
            MetaMarketingData.date >= date_from_obj,
            MetaMarketingData.date <= date_to_obj
        )
        if platform in ('facebook', 'instagram'):
            marketing_query = marketing_query.filter(MetaMarketingData.publisher_platform == platform)
        marketing_data = marketing_query.all()
        
        total_spend_meta = sum(_parse_amount(md.spend) for md in marketing_data)
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
        # % scarto totale: acquisto Meta -> uscita Magellano
        scarto_totale_pct = ((total_leads - magellano_inviate) / total_leads * 100) if total_leads > 0 else 0
        
        # Ulixe: stati principali
        ulixe_lavorazione = len([l for l in leads if l.status_category == StatusCategory.IN_LAVORAZIONE])
        ulixe_rifiutate = len([l for l in leads if l.status_category == StatusCategory.RIFIUTATO])
        ulixe_approvate = len([l for l in leads if l.status_category == StatusCategory.FINALE])
        leads_approvate = [l for l in leads if l.status_category == StatusCategory.FINALE]

        # Ricavo e margine: somma pay per ogni lead approvata (ogni lead → campagna → pay)
        revenue = _compute_ricavo_for_leads(db, leads_approvate)
        pay_campagna = _get_pay_for_leads(db, leads)
        cpl_approvate = (total_spend_meta / ulixe_approvate) if ulixe_approvate > 0 else 0
        margine_singola = (pay_campagna - cpl_approvate) if pay_campagna and ulixe_approvate else None
        margine_lordo = (revenue - total_spend_meta) if revenue > 0 else None
        margine_pct = (margine_lordo / revenue * 100) if revenue and margine_lordo is not None else None

        # Nascondi adset a 0 per il periodo
        if total_leads == 0 and total_spend_meta == 0:
            continue

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
            "ulixe_approvate": ulixe_approvate,
            # Ricavo e margine (da approvate)
            "revenue": round(revenue, 2),
            "margine_singola_lead": round(margine_singola, 2) if margine_singola is not None else None,
            "margine_lordo": round(margine_lordo, 2) if margine_lordo is not None else None,
            "margine_pct": round(margine_pct, 2) if margine_pct is not None else None,
            "scarto_totale_pct": round(scarto_totale_pct, 2),
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
    
    # Piattaforma (facebook / instagram / all)
    platform = request.query_params.get('platform', 'all')

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
        leads_query = db.query(Lead).filter(
            Lead.meta_ad_id == ad.ad_id,
            _lead_date_filter(date_from_obj, date_to_obj),
        )
        if platform in ('facebook', 'instagram'):
            leads_query = leads_query.filter(Lead.platform == platform)
        leads = leads_query.all()
        
        # Calculate CPL Meta
        marketing_query = db.query(MetaMarketingData).filter(
            MetaMarketingData.ad_id == ad.id,
            MetaMarketingData.date >= date_from_obj,
            MetaMarketingData.date <= date_to_obj
        )
        if platform in ('facebook', 'instagram'):
            marketing_query = marketing_query.filter(MetaMarketingData.publisher_platform == platform)
        marketing_data = marketing_query.all()
        
        total_spend_meta = sum(_parse_amount(md.spend) for md in marketing_data)
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
        magellano_scarto_pct_uscita = (magellano_rifiutate / magellano_inviate * 100) if magellano_inviate > 0 else 0
        # % scarto totale: acquisto Meta -> uscita Magellano
        scarto_totale_pct = ((total_leads - magellano_inviate) / total_leads * 100) if total_leads > 0 else 0
        
        # Ulixe: stati principali
        ulixe_lavorazione = len([l for l in leads if l.status_category == StatusCategory.IN_LAVORAZIONE])
        ulixe_rifiutate = len([l for l in leads if l.status_category == StatusCategory.RIFIUTATO])
        ulixe_approvate = len([l for l in leads if l.status_category == StatusCategory.FINALE])
        leads_approvate = [l for l in leads if l.status_category == StatusCategory.FINALE]

        # Ricavo e margine: somma pay per ogni lead approvata (ogni lead → campagna → pay)
        revenue = _compute_ricavo_for_leads(db, leads_approvate)
        pay_campagna = _get_pay_for_leads(db, leads)
        cpl_approvate = (total_spend_meta / ulixe_approvate) if ulixe_approvate > 0 else 0
        margine_singola = (pay_campagna - cpl_approvate) if pay_campagna and ulixe_approvate else None
        margine_lordo = (revenue - total_spend_meta) if revenue > 0 else None
        margine_pct = (margine_lordo / revenue * 100) if revenue and margine_lordo is not None else None

        # Nascondi creatività a 0 per il periodo
        if total_leads == 0 and total_spend_meta == 0:
            continue

        result.append({
            "id": ad.id,
            "ad_id": ad.ad_id,
            "name": ad.name,
            "status": ad.status,
            "creative_thumbnail_url": ad.creative_thumbnail_url or "",
            "creative_id": ad.creative_id or "",
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
            "ulixe_approvate": ulixe_approvate,
            # Ricavo e margine (da approvate)
            "revenue": round(revenue, 2),
            "margine_singola_lead": round(margine_singola, 2) if margine_singola is not None else None,
            "margine_lordo": round(margine_lordo, 2) if margine_lordo is not None else None,
            "margine_pct": round(margine_pct, 2) if margine_pct is not None else None,
            "scarto_totale_pct": round(scarto_totale_pct, 2),
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
    
    # Piattaforma (facebook / instagram / all)
    platform = request.query_params.get('platform', 'all')

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
            leads_query = db.query(Lead).filter(
                Lead.meta_adset_id == adset.adset_id,
                _lead_date_filter(date_from_obj, date_to_obj),
            )
            if platform in ('facebook', 'instagram'):
                leads_query = leads_query.filter(Lead.platform == platform)
            leads = leads_query.all()
            
            # Calculate CPL Meta
            marketing_query = db.query(MetaMarketingData).join(MetaAd).filter(
                MetaAd.adset_id == adset.id,
                MetaMarketingData.date >= date_from_obj,
                MetaMarketingData.date <= date_to_obj
            )
            if platform in ('facebook', 'instagram'):
                marketing_query = marketing_query.filter(MetaMarketingData.publisher_platform == platform)
            marketing_data = marketing_query.all()
            
            total_spend_meta = sum(_parse_amount(md.spend) for md in marketing_data)
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
            # % scarto totale: acquisto Meta -> uscita Magellano
            scarto_totale_pct = ((total_leads - magellano_inviate) / total_leads * 100) if total_leads > 0 else 0
            
            # Ulixe
            ulixe_lavorazione = len([l for l in leads if l.status_category == StatusCategory.IN_LAVORAZIONE])
            ulixe_rifiutate = len([l for l in leads if l.status_category == StatusCategory.RIFIUTATO])
            ulixe_approvate = len([l for l in leads if l.status_category == StatusCategory.FINALE])
            leads_approvate = [l for l in leads if l.status_category == StatusCategory.FINALE]

            # Ricavo e margine: somma pay per ogni lead approvata (ogni lead → campagna → pay)
            revenue = _compute_ricavo_for_leads(db, leads_approvate)
            pay_campagna = _get_pay_for_leads(db, leads)
            cpl_approvate = (total_spend_meta / ulixe_approvate) if ulixe_approvate > 0 else 0
            margine_singola = (pay_campagna - cpl_approvate) if pay_campagna and ulixe_approvate else None
            margine_lordo = (revenue - total_spend_meta) if revenue > 0 else None
            margine_pct = (margine_lordo / revenue * 100) if revenue and margine_lordo is not None else None

            # Nascondi adset a 0 per il periodo
            if total_leads == 0 and total_spend_meta == 0:
                continue
            
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
                "ulixe_approvate": ulixe_approvate,
                # Ricavo e margine (da approvate)
                "revenue": round(revenue, 2),
                "margine_singola_lead": round(margine_singola, 2) if margine_singola is not None else None,
                "margine_lordo": round(margine_lordo, 2) if margine_lordo is not None else None,
                "margine_pct": round(margine_pct, 2) if margine_pct is not None else None,
                "scarto_totale_pct": round(scarto_totale_pct, 2),
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
    
    # Piattaforma (facebook / instagram / all)
    platform = request.query_params.get('platform', 'all')

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
                leads_query = db.query(Lead).filter(
                    Lead.meta_ad_id == ad.ad_id,
                    _lead_date_filter(date_from_obj, date_to_obj),
                )
                if platform in ('facebook', 'instagram'):
                    leads_query = leads_query.filter(Lead.platform == platform)
                leads = leads_query.all()
                
                # Calculate CPL Meta
                marketing_query = db.query(MetaMarketingData).filter(
                    MetaMarketingData.ad_id == ad.id,
                    MetaMarketingData.date >= date_from_obj,
                    MetaMarketingData.date <= date_to_obj
                )
                if platform in ('facebook', 'instagram'):
                    marketing_query = marketing_query.filter(MetaMarketingData.publisher_platform == platform)
                marketing_data = marketing_query.all()
                
                total_spend_meta = sum(_parse_amount(md.spend) for md in marketing_data)
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
                # % scarto totale: acquisto Meta -> uscita Magellano
                scarto_totale_pct = ((total_leads - magellano_inviate) / total_leads * 100) if total_leads > 0 else 0
                
                # Ulixe
                ulixe_lavorazione = len([l for l in leads if l.status_category == StatusCategory.IN_LAVORAZIONE])
                ulixe_rifiutate = len([l for l in leads if l.status_category == StatusCategory.RIFIUTATO])
                ulixe_approvate = len([l for l in leads if l.status_category == StatusCategory.FINALE])
                leads_approvate = [l for l in leads if l.status_category == StatusCategory.FINALE]

                # Ricavo e margine: somma pay per ogni lead approvata (ogni lead → campagna → pay)
                revenue = _compute_ricavo_for_leads(db, leads_approvate)
                pay_campagna = _get_pay_for_leads(db, leads)
                cpl_approvate = (total_spend_meta / ulixe_approvate) if ulixe_approvate > 0 else 0
                margine_singola = (pay_campagna - cpl_approvate) if pay_campagna and ulixe_approvate else None
                margine_lordo = (revenue - total_spend_meta) if revenue > 0 else None
                margine_pct = (margine_lordo / revenue * 100) if revenue and margine_lordo is not None else None

                # Nascondi creatività a 0 per il periodo
                if total_leads == 0 and total_spend_meta == 0:
                    continue

                result.append({
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
                    "ulixe_approvate": ulixe_approvate,
                    # Ricavo e margine (da approvate)
                    "revenue": round(revenue, 2),
                    "margine_singola_lead": round(margine_singola, 2) if margine_singola is not None else None,
                    "margine_lordo": round(margine_lordo, 2) if margine_lordo is not None else None,
                    "margine_pct": round(margine_pct, 2) if margine_pct is not None else None,
                    "scarto_totale_pct": round(scarto_totale_pct, 2),
                })
    
    return JSONResponse(result)

