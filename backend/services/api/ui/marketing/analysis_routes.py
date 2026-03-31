"""Marketing Analysis + API Sankey lavorazioni."""
import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Request, Depends
from markupsafe import Markup
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import func, desc, and_, or_
from sqlalchemy.orm import Session

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

from ..common import templates
from .helpers import (
    _lead_date_filter,
    _parse_amount,
    _parse_optional_int_param,
    _leads_for_lavorazioni_sankey,
    _resolve_ad_meta_ids_for_sankey_name_scope,
    build_lead_lavorazioni_sankey_data,
    build_lead_lavorazioni_daily_chart_payload,
    build_lead_lavorazioni_heatmap_payload,
    lavorazioni_heatmap_lavorazione_filter_ui_payload,
    _get_ulixe_approvate_from_rcrm_temp,
    _compute_ricavo_for_leads,
    _get_pay_for_leads,
    _get_ricavo_from_rcrm_temp,
)

logger = logging.getLogger('services.api.ui')
router = APIRouter(include_in_schema=False)


def _htmlsafe_json_for_script(value: Any) -> Markup:
    """JSON embeddabile in <script type=\"application/json\"> (evita </...> che chiude il tag)."""
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    text = text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return Markup(text)


def _meta_account_id_sql_match(column, selected_account_id: str):
    """Match su Ad Account Meta: valore form/URL e variante act_."""
    s = (selected_account_id or "").strip()
    variants = [s]
    if s.lower().startswith("act_"):
        variants.append(s[4:])
    else:
        variants.append(f"act_{s}")
    return column.in_(list(dict.fromkeys(variants)))


def _placement_publisher_platform_eq(platform_column, platform_key: str):
    """Confronto case-insensitive su publisher_platform (Insights Meta / DB)."""
    return func.lower(func.coalesce(platform_column, "")) == platform_key.lower()


def _apply_analysis_entity_filters(
    q,
    *,
    selected_account_id: str = "",
    selected_campaign_id: str = "",
    selected_adset_id: int | None = None,
    campaign_name_q: str = "",
    adset_name_q: str = "",
    creative_name_q: str = "",
    analysis_status: str = "all",
):
    """Filtri gerarchici su query con MetaAccount, MetaCampaign, MetaAdSet, MetaAd già joinati."""
    sacc = (selected_account_id or "").strip()
    scamp = (selected_campaign_id or "").strip()
    cn = (campaign_name_q or "").strip()
    an = (adset_name_q or "").strip()
    cr = (creative_name_q or "").strip()
    st = (analysis_status or "all").strip().lower()

    if sacc:
        q = q.filter(_meta_account_id_sql_match(MetaAccount.account_id, sacc))
    if cn:
        q = q.filter(MetaCampaign.name.ilike(f"%{cn}%"))
    elif scamp:
        q = q.filter(MetaCampaign.campaign_id == scamp)
    if an:
        q = q.filter(MetaAdSet.name.ilike(f"%{an}%"))
    elif selected_adset_id is not None:
        q = q.filter(MetaAdSet.id == selected_adset_id)
    if cr:
        q = q.filter(MetaAd.name.ilike(f"%{cr}%"))

    if st == "active":
        q = q.filter(MetaCampaign.status == "ACTIVE")
    elif st == "inactive":
        q = q.filter(MetaCampaign.status != "ACTIVE")
    return q


def _apply_analysis_platform_meta_marketing_data(q, analysis_platform: str):
    pk = (analysis_platform or "all").strip().lower()
    if pk in ("facebook", "instagram"):
        return q.filter(_placement_publisher_platform_eq(MetaMarketingData.publisher_platform, pk))
    return q


def _apply_analysis_platform_meta_marketing_placement(q, analysis_platform: str):
    pk = (analysis_platform or "all").strip().lower()
    if pk in ("facebook", "instagram"):
        return q.filter(_placement_publisher_platform_eq(MetaMarketingPlacement.publisher_platform, pk))
    return q


def _meta_marketing_conversions_sum_by_campaign(
    db: Session,
    date_from,
    date_to,
    *,
    meta_account_id: str | None,
    meta_campaign_id: str | None,
    adset_db_id: int | None,
    ad_db_id: int | None,
    campaign_name_q: str,
    adset_name_q: str,
    creative_name_q: str,
) -> dict[str, int]:
    """
    Somma conversioni MetaMarketingData per campaign_id (stessi filtri entity/nome del Sankey lavorazioni).
    Serve a stimare i doppioni: conversioni − lead nel periodo per campagna.
    """
    q = (
        db.query(MetaCampaign.campaign_id, func.coalesce(func.sum(MetaMarketingData.conversions), 0))
        .select_from(MetaMarketingData)
        .join(MetaAd, MetaMarketingData.ad_id == MetaAd.id)
        .join(MetaAdSet, MetaAd.adset_id == MetaAdSet.id)
        .join(MetaCampaign, MetaAdSet.campaign_id == MetaCampaign.id)
        .join(MetaAccount, MetaCampaign.account_id == MetaAccount.id)
        .filter(
            MetaAccount.is_active == True,
            MetaMarketingData.date >= date_from,
            MetaMarketingData.date <= date_to,
        )
    )
    q = _apply_analysis_entity_filters(
        q,
        selected_account_id=(meta_account_id or "").strip(),
        selected_campaign_id=(meta_campaign_id or "").strip(),
        selected_adset_id=adset_db_id,
        campaign_name_q=campaign_name_q,
        adset_name_q=adset_name_q,
        creative_name_q=creative_name_q,
        analysis_status="all",
    )
    if ad_db_id is not None:
        q = q.filter(MetaAd.id == ad_db_id)
    scope_ads = _resolve_ad_meta_ids_for_sankey_name_scope(
        db,
        campaign_name_q,
        adset_name_q,
        creative_name_q,
        "all",
        meta_account_id,
    )
    if scope_ads is not None:
        if not scope_ads:
            return {}
        q = q.filter(MetaAd.ad_id.in_(scope_ads))
    q = q.group_by(MetaCampaign.campaign_id)
    out: dict[str, int] = {}
    for cid, total in q.all():
        if not cid:
            continue
        out[str(cid).strip()] = int(total or 0)
    return out


def _sql_date_to_iso_key(d) -> str:
    """Normalizza il giorno restituito da func.date(...) in YYYY-MM-DD."""
    if d is None:
        return ""
    if hasattr(d, "isoformat"):
        return d.isoformat()[:10]
    s = str(d).strip()
    return s[:10] if len(s) >= 10 and s[4] == "-" else s


def _meta_marketing_conversions_sum_by_day(
    db: Session,
    date_from,
    date_to,
    *,
    meta_account_id: str | None,
    meta_campaign_id: str | None,
    adset_db_id: int | None,
    ad_db_id: int | None,
    campaign_name_q: str,
    adset_name_q: str,
    creative_name_q: str,
) -> dict[str, int]:
    """
    Somma conversioni MetaMarketingData per giorno (data metrica), stessi filtri del Sankey / sum-by-campaign.
    Allineato al «Lead» lordo / conversioni della tabella /marketing.
    """
    day_expr = func.date(MetaMarketingData.date)
    q = (
        db.query(day_expr, func.coalesce(func.sum(MetaMarketingData.conversions), 0))
        .select_from(MetaMarketingData)
        .join(MetaAd, MetaMarketingData.ad_id == MetaAd.id)
        .join(MetaAdSet, MetaAd.adset_id == MetaAdSet.id)
        .join(MetaCampaign, MetaAdSet.campaign_id == MetaCampaign.id)
        .join(MetaAccount, MetaCampaign.account_id == MetaAccount.id)
        .filter(
            MetaAccount.is_active == True,
            MetaMarketingData.date >= date_from,
            MetaMarketingData.date <= date_to,
        )
    )
    q = _apply_analysis_entity_filters(
        q,
        selected_account_id=(meta_account_id or "").strip(),
        selected_campaign_id=(meta_campaign_id or "").strip(),
        selected_adset_id=adset_db_id,
        campaign_name_q=campaign_name_q,
        adset_name_q=adset_name_q,
        creative_name_q=creative_name_q,
        analysis_status="all",
    )
    if ad_db_id is not None:
        q = q.filter(MetaAd.id == ad_db_id)
    scope_ads = _resolve_ad_meta_ids_for_sankey_name_scope(
        db,
        campaign_name_q,
        adset_name_q,
        creative_name_q,
        "all",
        meta_account_id,
    )
    if scope_ads is not None:
        if not scope_ads:
            return {}
        q = q.filter(MetaAd.ad_id.in_(scope_ads))
    q = q.group_by(day_expr)
    out: dict[str, int] = {}
    for row_d, total in q.all():
        k = _sql_date_to_iso_key(row_d)
        if not k:
            continue
        out[k] = int(total or 0)
    return out


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
        _tab_raw = (params.get("tab") or "analysis").strip().lower()
        analysis_tab = _tab_raw if _tab_raw in (
            "analysis",
            "breakdown",
            "placement_creative",
            "lead_wip",
        ) else "analysis"

        selected_account_id = params.get("account_id") or ""
        selected_campaign_id = params.get("campaign_id") or ""
        selected_adset_id_param = params.get("adset_id") or ""
        try:
            selected_adset_id = int(selected_adset_id_param) if selected_adset_id_param else None
        except ValueError:
            selected_adset_id = None

        campaign_name_q = (params.get("campaign_name") or "").strip()
        adset_name_q = (params.get("adset_name") or "").strip()
        creative_name_q = (params.get("creative_name") or "").strip()
        # Nessun filtro stato/piattaforma in UI: sempre tutte le campagne e tutte le piattaforme nei dati aggregati.
        analysis_status = "all"
        analysis_platform = "all"

        af = dict(
            selected_account_id=selected_account_id,
            selected_campaign_id=selected_campaign_id,
            selected_adset_id=selected_adset_id,
            campaign_name_q=campaign_name_q,
            adset_name_q=adset_name_q,
            creative_name_q=creative_name_q,
            analysis_status=analysis_status,
        )
        placement_creative_expand_by_ad = bool(selected_adset_id) or bool(adset_name_q)

        # Date range con default ultimi 30 giorni
        date_from_str = params.get('date_from')
        date_to_str = params.get('date_to')

        try:
            date_from = datetime.strptime(date_from_str, '%Y-%m-%d') if date_from_str else datetime.now() - timedelta(days=30)
        except Exception:
            date_from = datetime.now() - timedelta(days=30)

        try:
            if date_to_str:
                date_to = datetime.strptime(date_to_str, '%Y-%m-%d').replace(
                    hour=23, minute=59, second=59, microsecond=999999
                )
            else:
                date_to = datetime.now()
        except Exception:
            date_to = datetime.now()

        # Dati per JSON gerarchia (filtri combobox / export lato client se presenti)
        accounts = (
            db.query(MetaAccount).filter(MetaAccount.is_active == True).order_by(MetaAccount.name).all()
        )
        campaigns = (
            db.query(MetaCampaign)
            .join(MetaAccount)
            .filter(MetaAccount.is_active == True)
            .order_by(MetaCampaign.name)
            .all()
        )
        adsets = (
            db.query(MetaAdSet)
            .join(MetaCampaign)
            .join(MetaAccount)
            .filter(MetaAccount.is_active == True)
            .order_by(MetaAdSet.name)
            .all()
        )

        # Query principale sui MetaMarketingData
        query = (
            db.query(MetaMarketingData, MetaAd, MetaAdSet, MetaCampaign, MetaAccount)
            .join(MetaAd, MetaMarketingData.ad_id == MetaAd.id)
            .join(MetaAdSet, MetaAd.adset_id == MetaAdSet.id)
            .join(MetaCampaign, MetaAdSet.campaign_id == MetaCampaign.id)
            .join(MetaAccount, MetaCampaign.account_id == MetaAccount.id)
            .filter(
                MetaAccount.is_active == True,
                MetaMarketingData.date >= date_from,
                MetaMarketingData.date <= date_to,
            )
        )

        query = _apply_analysis_entity_filters(query, **af)
        query = _apply_analysis_platform_meta_marketing_data(query, analysis_platform)

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
                MetaMarketingData.date >= date_from,
                MetaMarketingData.date <= date_to,
            )
        )

        daily_query = _apply_analysis_entity_filters(daily_query, **af)
        daily_query = _apply_analysis_platform_meta_marketing_data(daily_query, analysis_platform)

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
                MetaMarketingData.date >= date_from,
                MetaMarketingData.date <= date_to,
            )
        )

        current_dist_query = _apply_analysis_entity_filters(current_dist_query, **af)
        current_dist_query = _apply_analysis_platform_meta_marketing_data(current_dist_query, analysis_platform)

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
                MetaMarketingData.date >= prev_start,
                MetaMarketingData.date <= prev_end,
            )
        )

        prev_dist_query = _apply_analysis_entity_filters(prev_dist_query, **af)
        prev_dist_query = _apply_analysis_platform_meta_marketing_data(prev_dist_query, analysis_platform)

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
            if adset_ids and placement_creative_expand_by_ad:
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
            # Meta KPI per piattaforma (layer B: meta_marketing_placement)
            p_query = (
                db.query(MetaMarketingPlacement, MetaAd, MetaAdSet, MetaCampaign, MetaAccount)
                .join(MetaAd, MetaMarketingPlacement.ad_id == MetaAd.id)
                .join(MetaAdSet, MetaAd.adset_id == MetaAdSet.id)
                .join(MetaCampaign, MetaAdSet.campaign_id == MetaCampaign.id)
                .join(MetaAccount, MetaCampaign.account_id == MetaAccount.id)
                .filter(
                    MetaAccount.is_active == True,
                    MetaMarketingPlacement.date >= date_from,
                    MetaMarketingPlacement.date <= date_to,
                    _placement_publisher_platform_eq(MetaMarketingPlacement.publisher_platform, platform_key),
                )
            )
            p_query = _apply_analysis_entity_filters(p_query, **af)

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
                    func.date(MetaMarketingPlacement.date).label("day"),
                    func.sum(MetaMarketingPlacement.spend).label("total_spend"),
                    func.sum(MetaMarketingPlacement.conversions).label("total_conversions"),
                )
                .join(MetaAd, MetaMarketingPlacement.ad_id == MetaAd.id)
                .join(MetaAdSet, MetaAd.adset_id == MetaAdSet.id)
                .join(MetaCampaign, MetaAdSet.campaign_id == MetaCampaign.id)
                .join(MetaAccount, MetaCampaign.account_id == MetaAccount.id)
                .filter(
                    MetaAccount.is_active == True,
                    MetaMarketingPlacement.date >= date_from,
                    MetaMarketingPlacement.date <= date_to,
                    _placement_publisher_platform_eq(MetaMarketingPlacement.publisher_platform, platform_key),
                )
            )
            p_daily_query = _apply_analysis_entity_filters(p_daily_query, **af)

            p_daily_rows = (
                p_daily_query
                .group_by(func.date(MetaMarketingPlacement.date))
                .order_by(func.date(MetaMarketingPlacement.date))
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

        # Focus posizionamenti per piattaforma: una riga per posizionamento (somma su tutte le creatività / ad).
        # Chiave normalizzata lower+trim per evitare duplicati (es. stesso placement con stringhe leggermente diverse).
        placement_insights_by_platform: dict[str, list[dict[str, Any]]] = {
            "facebook": [],
            "instagram": [],
        }

        _mpp_pub_key = func.lower(func.trim(func.coalesce(MetaMarketingPlacement.publisher_platform, "")))
        _mpp_pos_key = func.lower(func.trim(func.coalesce(MetaMarketingPlacement.platform_position, "")))

        placement_query = (
            db.query(
                _mpp_pub_key.label("platform"),
                _mpp_pos_key.label("position_key"),
                func.max(MetaMarketingPlacement.platform_position).label("position_display"),
                func.sum(MetaMarketingPlacement.spend).label("total_spend"),
                func.sum(MetaMarketingPlacement.conversions).label("total_conversions"),
            )
            .join(MetaAd, MetaMarketingPlacement.ad_id == MetaAd.id)
            .join(MetaAdSet, MetaAd.adset_id == MetaAdSet.id)
            .join(MetaCampaign, MetaAdSet.campaign_id == MetaCampaign.id)
            .join(MetaAccount, MetaCampaign.account_id == MetaAccount.id)
            .filter(
                MetaAccount.is_active == True,
                MetaMarketingPlacement.date >= date_from,
                MetaMarketingPlacement.date <= date_to,
                _mpp_pub_key.in_(["facebook", "instagram"]),
            )
        )
        placement_query = _apply_analysis_entity_filters(placement_query, **af)

        placement_rows = (
            placement_query.group_by(_mpp_pub_key, _mpp_pos_key)
            .order_by(func.sum(MetaMarketingPlacement.spend).desc())
            .all()
        )

        for row in placement_rows:
            platform_key = (row.platform or "").strip()
            if platform_key not in placement_insights_by_platform:
                continue
            total_spend = _parse_amount(row.total_spend) if row.total_spend is not None else 0.0
            total_conversions = int(row.total_conversions or 0)
            cpl = (total_spend / total_conversions) if total_conversions > 0 else 0.0
            pos_k = (row.position_key or "").strip()
            raw_disp = (row.position_display or "").strip()
            if raw_disp:
                position_label = raw_disp
            else:
                position_label = "unknown" if not pos_k else pos_k
            placement_insights_by_platform[platform_key].append(
                {
                    "position": position_label,
                    "total_spend": round(total_spend, 2),
                    "total_conversions": total_conversions,
                    "cpl": round(cpl, 2),
                }
            )

        # Posizionamento × creatività: filtri posizione indipendenti per Facebook e Instagram
        placement_creative_by_platform: dict[str, list[dict[str, Any]]] = {
            "facebook": [],
            "instagram": [],
        }

        def _placement_creative_base_for_platform(pub: str):
            """Join + filtri date/account/campagna/adset + singola publisher_platform."""
            q = (
                db.query(MetaMarketingPlacement)
                .join(MetaAd, MetaMarketingPlacement.ad_id == MetaAd.id)
                .join(MetaAdSet, MetaAd.adset_id == MetaAdSet.id)
                .join(MetaCampaign, MetaAdSet.campaign_id == MetaCampaign.id)
                .join(MetaAccount, MetaCampaign.account_id == MetaAccount.id)
                .filter(
                    MetaAccount.is_active == True,
                    MetaMarketingPlacement.date >= date_from,
                    MetaMarketingPlacement.date <= date_to,
                    _placement_publisher_platform_eq(MetaMarketingPlacement.publisher_platform, pub),
                )
            )
            q = _apply_analysis_entity_filters(q, **af)
            return q

        def _position_options_for_platform(pub: str) -> list[dict[str, str]]:
            _pos_opts_q = (
                _placement_creative_base_for_platform(pub)
                .with_entities(MetaMarketingPlacement.platform_position)
                .distinct()
            )
            _raw_positions = {((r[0] or "").strip() or "__empty__") for r in _pos_opts_q.all()}
            opts: list[dict[str, str]] = []
            for raw in sorted(_raw_positions, key=lambda x: (x != "__empty__", x.lower())):
                if raw == "__empty__":
                    opts.append({"value": "__empty__", "label": "(senza posizionamento)"})
                else:
                    opts.append({"value": raw, "label": raw})
            return opts

        placement_position_options_facebook = _position_options_for_platform("facebook")
        placement_position_options_instagram = _position_options_for_platform("instagram")
        allowed_pc_pos_fb = {o["value"] for o in placement_position_options_facebook}
        allowed_pc_pos_ig = {o["value"] for o in placement_position_options_instagram}
        _pc_pos_fb = (params.get("pc_position_facebook") or "").strip()
        _pc_pos_ig = (params.get("pc_position_instagram") or "").strip()
        selected_pc_position_facebook = _pc_pos_fb if _pc_pos_fb in allowed_pc_pos_fb else ""
        selected_pc_position_instagram = _pc_pos_ig if _pc_pos_ig in allowed_pc_pos_ig else ""

        def _aggregate_placement_creative_for_platform(pub: str, selected_position: str) -> None:
            base_pf = (
                db.query(MetaMarketingPlacement)
                .join(MetaAd, MetaMarketingPlacement.ad_id == MetaAd.id)
                .join(MetaAdSet, MetaAd.adset_id == MetaAdSet.id)
                .join(MetaCampaign, MetaAdSet.campaign_id == MetaCampaign.id)
                .join(MetaAccount, MetaCampaign.account_id == MetaAccount.id)
                .filter(
                    MetaAccount.is_active == True,
                    MetaMarketingPlacement.date >= date_from,
                    MetaMarketingPlacement.date <= date_to,
                    _placement_publisher_platform_eq(MetaMarketingPlacement.publisher_platform, pub),
                )
            )
            base_pf = _apply_analysis_entity_filters(base_pf, **af)
            if selected_position:
                if selected_position == "__empty__":
                    base_pf = base_pf.filter(MetaMarketingPlacement.platform_position == "")
                else:
                    base_pf = base_pf.filter(
                        MetaMarketingPlacement.platform_position == selected_position
                    )

            having_any = or_(
                func.sum(MetaMarketingPlacement.spend) > 0,
                func.sum(MetaMarketingPlacement.conversions) > 0,
                func.sum(MetaMarketingPlacement.impressions) > 0,
                func.sum(MetaMarketingPlacement.clicks) > 0,
            )

            if selected_position:
                placement_creative_q = base_pf.with_entities(
                    MetaMarketingPlacement.publisher_platform.label("platform"),
                    MetaMarketingPlacement.platform_position.label("position"),
                    MetaAd.id.label("internal_ad_id"),
                    MetaAd.name.label("ad_name"),
                    MetaAd.creative_id.label("creative_id"),
                    func.sum(MetaMarketingPlacement.spend).label("total_spend"),
                    func.sum(MetaMarketingPlacement.conversions).label("total_conversions"),
                )
                rows = (
                    placement_creative_q.group_by(
                        MetaMarketingPlacement.publisher_platform,
                        MetaMarketingPlacement.platform_position,
                        MetaAd.id,
                        MetaAd.name,
                        MetaAd.creative_id,
                    )
                    .having(having_any)
                    .order_by(
                        MetaMarketingPlacement.platform_position,
                        desc(func.sum(MetaMarketingPlacement.spend)),
                    )
                    .all()
                )
                for crow in rows:
                    pk = (crow.platform or "").lower()
                    if pk not in placement_creative_by_platform:
                        continue
                    ts = _parse_amount(crow.total_spend) if crow.total_spend is not None else 0.0
                    tc = int(crow.total_conversions or 0)
                    cpl_c = (ts / tc) if tc > 0 else 0.0
                    placement_creative_by_platform[pk].append(
                        {
                            "position": (crow.position or "").strip() or "unknown",
                            "ad_name": crow.ad_name or "",
                            "internal_ad_id": int(crow.internal_ad_id),
                            "show_thumbnail": bool((crow.creative_id or "").strip() and crow.internal_ad_id),
                            "total_spend": round(ts, 2),
                            "total_conversions": tc,
                            "cpl": round(cpl_c, 2),
                        }
                    )
                return

            if placement_creative_expand_by_ad:
                # AdSet nel filtro (ID o nome) + "tutti i posizionamenti": una riga per annuncio (somma sui placement)
                q_ads = (
                    base_pf.with_entities(
                        MetaMarketingPlacement.publisher_platform.label("platform"),
                        MetaAd.id.label("internal_ad_id"),
                        MetaAd.name.label("ad_name"),
                        MetaAd.creative_id.label("creative_id"),
                        func.sum(MetaMarketingPlacement.spend).label("total_spend"),
                        func.sum(MetaMarketingPlacement.conversions).label("total_conversions"),
                    )
                    .group_by(
                        MetaMarketingPlacement.publisher_platform,
                        MetaAd.id,
                        MetaAd.name,
                        MetaAd.creative_id,
                    )
                    .having(having_any)
                    .order_by(desc(func.sum(MetaMarketingPlacement.spend)))
                )
                for crow in q_ads.all():
                    pk = (crow.platform or "").lower()
                    if pk not in placement_creative_by_platform:
                        continue
                    ts = _parse_amount(crow.total_spend) if crow.total_spend is not None else 0.0
                    tc = int(crow.total_conversions or 0)
                    cpl_c = (ts / tc) if tc > 0 else 0.0
                    placement_creative_by_platform[pk].append(
                        {
                            "position": "",
                            "ad_name": crow.ad_name or "",
                            "internal_ad_id": int(crow.internal_ad_id),
                            "show_thumbnail": bool((crow.creative_id or "").strip() and crow.internal_ad_id),
                            "total_spend": round(ts, 2),
                            "total_conversions": tc,
                            "cpl": round(cpl_c, 2),
                        }
                    )
                return

            # Tutti i posizionamenti e senza espansione per ad: una riga per placement (chiave normalizzata
            # come la card Breakdown / POSIZIONAMENTI: lower+trim, così varianti DB non duplicano la colonna).
            q_agg = (
                base_pf.with_entities(
                    MetaMarketingPlacement.publisher_platform.label("platform"),
                    _mpp_pos_key.label("position_key"),
                    func.max(MetaMarketingPlacement.platform_position).label("position_display"),
                    func.sum(MetaMarketingPlacement.spend).label("total_spend"),
                    func.sum(MetaMarketingPlacement.conversions).label("total_conversions"),
                )
                .group_by(
                    MetaMarketingPlacement.publisher_platform,
                    _mpp_pos_key,
                )
                .having(having_any)
                .order_by(desc(func.sum(MetaMarketingPlacement.spend)))
            )
            # Unica riga per posizionamento (come card Breakdown): chiave lower+trim; somma lead/spesa e CPL ricalcolato.
            _pc_buckets: dict[tuple[str, str], dict[str, Any]] = {}
            for crow in q_agg.all():
                pk = (crow.platform or "").lower()
                if pk not in placement_creative_by_platform:
                    continue
                ts = _parse_amount(crow.total_spend) if crow.total_spend is not None else 0.0
                tc = int(crow.total_conversions or 0)
                pos_k = (getattr(crow, "position_key", None) or "").strip()
                raw_disp = (getattr(crow, "position_display", None) or "").strip()
                if raw_disp:
                    position_label = raw_disp
                else:
                    position_label = "unknown" if not pos_k else pos_k
                norm = position_label.strip().lower()
                bkey = (pk, norm)
                if bkey not in _pc_buckets:
                    _pc_buckets[bkey] = {"position": position_label, "spend": 0.0, "conv": 0}
                _pc_buckets[bkey]["spend"] += ts
                _pc_buckets[bkey]["conv"] += tc
                if len(position_label) > len(_pc_buckets[bkey]["position"]):
                    _pc_buckets[bkey]["position"] = position_label

            for (_pk, _norm), b in sorted(
                _pc_buckets.items(),
                key=lambda kv: kv[1]["spend"],
                reverse=True,
            ):
                ts_b, tc_b = b["spend"], b["conv"]
                cpl_b = (ts_b / tc_b) if tc_b > 0 else 0.0
                placement_creative_by_platform[_pk].append(
                    {
                        "position": b["position"],
                        "total_spend": round(ts_b, 2),
                        "total_conversions": tc_b,
                        "cpl": round(cpl_b, 2),
                    }
                )

        _aggregate_placement_creative_for_platform("facebook", selected_pc_position_facebook)
        _aggregate_placement_creative_for_platform("instagram", selected_pc_position_instagram)

        # CPL giornaliero per posizionamento, aggregato in due grafici (Facebook / Instagram), solo asse CPL
        chart_date_order = [p["date"] for p in chart_points]
        if not chart_date_order:
            d0 = date_from.date() if hasattr(date_from, "date") else date_from
            d1 = date_to.date() if hasattr(date_to, "date") else date_to
            cur = d0
            while cur <= d1:
                chart_date_order.append(cur.isoformat())
                cur += timedelta(days=1)

        placement_daily_q = (
            db.query(
                func.date(MetaMarketingPlacement.date).label("day"),
                _mpp_pub_key.label("platform"),
                _mpp_pos_key.label("position_key"),
                func.max(MetaMarketingPlacement.platform_position).label("position_display"),
                func.sum(MetaMarketingPlacement.spend).label("total_spend"),
                func.sum(MetaMarketingPlacement.conversions).label("total_conversions"),
            )
            .join(MetaAd, MetaMarketingPlacement.ad_id == MetaAd.id)
            .join(MetaAdSet, MetaAd.adset_id == MetaAdSet.id)
            .join(MetaCampaign, MetaAdSet.campaign_id == MetaCampaign.id)
            .join(MetaAccount, MetaCampaign.account_id == MetaAccount.id)
            .filter(
                MetaAccount.is_active == True,
                MetaMarketingPlacement.date >= date_from,
                MetaMarketingPlacement.date <= date_to,
                _mpp_pub_key.in_(["facebook", "instagram"]),
            )
        )
        placement_daily_q = _apply_analysis_entity_filters(placement_daily_q, **af)
        placement_daily_q = _apply_analysis_platform_meta_marketing_placement(
            placement_daily_q, analysis_platform
        )

        placement_daily_rows = (
            placement_daily_q.group_by(
                func.date(MetaMarketingPlacement.date),
                _mpp_pub_key,
                _mpp_pos_key,
            )
            .order_by(func.date(MetaMarketingPlacement.date))
            .all()
        )

        placement_day_pos_labels: dict[tuple[str, str], str] = {}
        by_placement_day: dict[tuple[str, str], dict[str, dict[str, float | int]]] = defaultdict(dict)
        for row in placement_daily_rows:
            pk = (row.platform or "").strip()
            if pk not in ("facebook", "instagram"):
                continue
            pos_k = (row.position_key or "").strip() or "__empty__"
            raw_disp = (row.position_display or "").strip()
            pos_label = raw_disp if raw_disp else ("unknown" if pos_k == "__empty__" else pos_k)
            placement_day_pos_labels.setdefault((pk, pos_k), pos_label)
            day = row.day
            try:
                date_str = day.strftime("%Y-%m-%d")
            except AttributeError:
                date_str = str(day)
            spend = _parse_amount(row.total_spend) if row.total_spend is not None else 0.0
            conv = int(row.total_conversions or 0)
            cell_key = (pk, pos_k)
            cell = by_placement_day[cell_key].get(date_str)
            if cell:
                cell["spend"] = float(cell["spend"]) + spend
                cell["conv"] = int(cell["conv"]) + conv
            else:
                by_placement_day[cell_key][date_str] = {"spend": spend, "conv": conv}

        totals_by_placement: dict[tuple[str, str], tuple[float, int]] = {}
        for key, day_map in by_placement_day.items():
            ts = sum(float(v["spend"]) for v in day_map.values())
            tc = sum(int(v["conv"]) for v in day_map.values())
            totals_by_placement[key] = (ts, tc)

        def _build_platform_placement_chart(platform_key: str) -> dict[str, Any] | None:
            """Serie giornaliere per posizionamento: CPL, speso e lead (per grafico con filtro UI)."""
            keys = [(pk, pos_k) for pk, pos_k in by_placement_day.keys() if pk == platform_key]
            if not keys:
                return None
            keys_sorted = sorted(keys, key=lambda k: totals_by_placement[k][0], reverse=True)
            placements_out: list[dict[str, Any]] = []
            for pk, pos_k in keys_sorted:
                t_spend, t_conv = totals_by_placement[(pk, pos_k)]
                period_cpl_val = (t_spend / t_conv) if t_conv > 0 else 0.0
                day_map = by_placement_day[(pk, pos_k)]
                cpl_daily: list[float] = []
                spend_daily: list[float] = []
                leads_daily: list[int] = []
                for date_str in chart_date_order:
                    cell = day_map.get(date_str, {"spend": 0.0, "conv": 0})
                    s = float(cell["spend"])
                    c = int(cell["conv"])
                    cpl_d = (s / c) if c > 0 else 0.0
                    cpl_daily.append(round(cpl_d, 2))
                    spend_daily.append(round(s, 2))
                    leads_daily.append(c)
                pos_ui = placement_day_pos_labels.get((pk, pos_k)) or pos_k or "unknown"
                placements_out.append(
                    {
                        "position": pos_ui,
                        "period_cpl": round(period_cpl_val, 2),
                        "period_spend": round(t_spend, 2),
                        "period_leads": int(t_conv),
                        "cpl_daily": cpl_daily,
                        "spend_daily": spend_daily,
                        "leads_daily": leads_daily,
                    }
                )
            pt = platform_totals.get(platform_key) or {}
            period_avg_cpl = float(pt.get("global_cpl") or 0.0)
            return {
                "dates": chart_date_order,
                "placements": placements_out,
                "period_avg_cpl": round(period_avg_cpl, 2),
            }

        placement_cpl_by_platform: dict[str, Any] = {
            "facebook": _build_platform_placement_chart("facebook"),
            "instagram": _build_platform_placement_chart("instagram"),
        }

        analysis_filter_hierarchy: dict[str, Any] = {
            "accounts": [
                {"account_id": str(a.account_id or "").strip(), "name": (a.name or "").strip()}
                for a in accounts
            ],
            "campaigns": [
                {
                    "campaign_id": str(c.campaign_id or "").strip(),
                    "name": (c.name or "").strip(),
                    "account_id": str(c.account.account_id or "").strip() if c.account else "",
                }
                for c in campaigns
            ],
            "adsets": [
                {
                    "id": int(ad.id),
                    "name": (ad.name or "").strip(),
                    "campaign_id": str(ad.campaign.campaign_id or "").strip() if ad.campaign else "",
                    "account_id": str(ad.campaign.account.account_id or "").strip()
                    if ad.campaign and ad.campaign.account
                    else "",
                }
                for ad in adsets
            ],
        }

        return templates.TemplateResponse(
            request,
            "marketing_analysis.html",
            {
                "request": request,
                "title": "Marketing Analysis",
                "user": user,
                "accounts": accounts,
                "campaigns": campaigns,
                "adsets": adsets,
                "analysis_filter_hierarchy_json": _htmlsafe_json_for_script(analysis_filter_hierarchy),
                "totals": totals,
                "chart_points": chart_points,
                "distribution_points": distribution_points,
                "platform_totals": platform_totals,
                "platform_chart_points": platform_chart_points,
                "platform_distribution_points": platform_distribution_points,
                "placement_insights_by_platform": placement_insights_by_platform,
                "placement_creative_by_platform": placement_creative_by_platform,
                "placement_cpl_by_platform": placement_cpl_by_platform,
                "selected_pc_position_facebook": selected_pc_position_facebook,
                "selected_pc_position_instagram": selected_pc_position_instagram,
                "placement_position_options_facebook": placement_position_options_facebook,
                "placement_position_options_instagram": placement_position_options_instagram,
                "placement_creative_expand_by_ad": placement_creative_expand_by_ad,
                "selected_account_id": selected_account_id,
                "selected_campaign_id": selected_campaign_id,
                "selected_adset_id": selected_adset_id,
                "selected_campaign_name": campaign_name_q,
                "selected_adset_name": adset_name_q,
                "selected_creative_name": creative_name_q,
                "date_from": date_from.strftime('%Y-%m-%d'),
                "date_to": date_to.strftime('%Y-%m-%d'),
                "active_page": "marketing_analysis",
                "analysis_tab": analysis_tab,
                "lavorazione_filter_ui": lavorazioni_heatmap_lavorazione_filter_ui_payload(),
            },
        )
    except Exception as e:
        logger.error(f"Errore nel route /marketing/analysis: {e}", exc_info=True)
        raise


def _lavorazioni_scope_from_request(request: Request, db: Session) -> dict | None:
    """Stesso scope del Sankey lavorazioni; None se non autenticato."""
    user = request.session.get("user")
    if not user:
        return None
    if not db.query(User).filter(User.email == user.get("email")).first():
        return None

    params = request.query_params
    date_from_s = params.get("date_from") or ""
    date_to_s = params.get("date_to") or ""
    try:
        date_from_obj = datetime.strptime(date_from_s, "%Y-%m-%d") if date_from_s else datetime.now() - timedelta(days=30)
    except ValueError:
        date_from_obj = datetime.now() - timedelta(days=30)
    try:
        if date_to_s:
            date_to_obj = datetime.strptime(date_to_s, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59, microsecond=999999
            )
        else:
            date_to_obj = datetime.now()
    except ValueError:
        date_to_obj = datetime.now()

    meta_account_id = (params.get("account_id") or "").strip() or None
    meta_campaign_id = (params.get("campaign_id") or "").strip() or None
    adset_db_id = _parse_optional_int_param(params, "adset_id")
    ad_db_id = _parse_optional_int_param(params, "ad_db_id")
    campaign_name_q = (params.get("campaign_name") or "").strip()
    adset_name_q = (params.get("adset_name") or "").strip()
    creative_name_q = (params.get("creative_name") or "").strip()

    leads = _leads_for_lavorazioni_sankey(
        db,
        date_from_obj,
        date_to_obj,
        meta_account_id,
        meta_campaign_id,
        adset_db_id,
        ad_db_id,
        campaign_name_q=campaign_name_q,
        adset_name_q=adset_name_q,
        creative_name_q=creative_name_q,
        analysis_status="all",
        analysis_platform="all",
    )
    return {
        "date_from": date_from_obj,
        "date_to": date_to_obj,
        "leads": leads,
        "meta_account_id": meta_account_id,
        "meta_campaign_id": meta_campaign_id,
        "adset_db_id": adset_db_id,
        "ad_db_id": ad_db_id,
        "campaign_name_q": campaign_name_q,
        "adset_name_q": adset_name_q,
        "creative_name_q": creative_name_q,
    }


@router.get("/api/marketing/analysis-lead-lavorazioni-sankey")
async def api_marketing_analysis_lead_lavorazioni_sankey(request: Request, db: Session = Depends(get_db)):
    """
    JSON per Sankey tab Lavorazioni: lead con magellano_subscr_date nel periodo.
    Tre colonne: Meta → ingresso (barra Entrate + barra Doppioni stima) → uscite (firewall, WS rifiutate, invii WS aggregati, …).
    Filtri come il form Analysis: campaign_name, adset_name, creative_name, date_from / date_to
    (nessun filtro stato/piattaforma).
    """
    scope = _lavorazioni_scope_from_request(request, db)
    if scope is None:
        return JSONResponse({"error": "Non autorizzato"}, status_code=401)

    conv_by_campaign = _meta_marketing_conversions_sum_by_campaign(
        db,
        scope["date_from"],
        scope["date_to"],
        meta_account_id=scope["meta_account_id"],
        meta_campaign_id=scope["meta_campaign_id"],
        adset_db_id=scope["adset_db_id"],
        ad_db_id=scope["ad_db_id"],
        campaign_name_q=scope["campaign_name_q"],
        adset_name_q=scope["adset_name_q"],
        creative_name_q=scope["creative_name_q"],
    )
    payload = build_lead_lavorazioni_sankey_data(
        db, scope["leads"], conversions_by_meta_campaign=conv_by_campaign
    )
    return JSONResponse(payload)


@router.get("/api/marketing/analysis-lead-lavorazioni-daily")
async def api_marketing_analysis_lead_lavorazioni_daily(request: Request, db: Session = Depends(get_db)):
    """Serie giornaliere allineate a /marketing: lordo Meta per giorno metrica + serie per-lead per iscrizione Magellano."""
    scope = _lavorazioni_scope_from_request(request, db)
    if scope is None:
        return JSONResponse({"error": "Non autorizzato"}, status_code=401)
    meta_by_day = _meta_marketing_conversions_sum_by_day(
        db,
        scope["date_from"],
        scope["date_to"],
        meta_account_id=scope["meta_account_id"],
        meta_campaign_id=scope["meta_campaign_id"],
        adset_db_id=scope["adset_db_id"],
        ad_db_id=scope["ad_db_id"],
        campaign_name_q=scope["campaign_name_q"],
        adset_name_q=scope["adset_name_q"],
        creative_name_q=scope["creative_name_q"],
    )
    payload = build_lead_lavorazioni_daily_chart_payload(
        scope["leads"],
        scope["date_from"],
        scope["date_to"],
        meta_conversions_by_day=meta_by_day,
    )
    return JSONResponse(payload)


@router.get("/api/marketing/analysis-lead-lavorazioni-heatmap")
async def api_marketing_analysis_lead_lavorazioni_heatmap(request: Request, db: Session = Depends(get_db)):
    """Heatmap giorno × campagna Meta; lavorazione=all|fuori_flusso|scartate_firewall|scartate_ws|ws_inviate."""
    scope = _lavorazioni_scope_from_request(request, db)
    if scope is None:
        return JSONResponse({"error": "Non autorizzato"}, status_code=401)
    lavorazione = (request.query_params.get("lavorazione") or "all").strip()
    payload = build_lead_lavorazioni_heatmap_payload(
        db,
        scope["leads"],
        scope["date_from"],
        scope["date_to"],
        lavorazione_filter=lavorazione,
    )
    return JSONResponse(payload)
