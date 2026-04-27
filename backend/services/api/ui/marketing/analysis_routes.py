"""Marketing Analysis + API Sankey lavorazioni."""
import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Request, Depends
from markupsafe import Markup
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import func, desc, and_, or_
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
    _get_mag_to_pay,
    default_marketing_filter_date_range,
)
from .hierarchy_routes import (
    _bulk_leads_by_meta_adset,
    _bulk_leads_by_meta_ad_id,
    _bulk_marketing_by_adset_pk,
    _bulk_marketing_by_ad_pk,
    _marketing_metrics_block,
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


def _extract_interests_from_targeting(targeting: Any) -> list[tuple[str, str]]:
    """
    (chiave_stabile, nome_display) dagli interessi nel JSON targeting Meta (ad set).
    flexible_spec[].interests e interests top-level.
    """
    if not targeting or not isinstance(targeting, dict):
        return []

    by_key: dict[str, str] = {}

    def absorb_interest_list(items: Any) -> None:
        if not items or not isinstance(items, list):
            return
        for it in items:
            if not isinstance(it, dict):
                continue
            raw_id = it.get("id")
            iid = str(raw_id).strip() if raw_id is not None else ""
            name = (it.get("name") or "").strip()
            if not iid and not name:
                continue
            key = iid if iid else f"name:{name.lower()}"
            if key not in by_key:
                by_key[key] = name if name else (iid or key)

    absorb_interest_list(targeting.get("interests"))
    flex = targeting.get("flexible_spec")
    if isinstance(flex, list):
        for block in flex:
            if isinstance(block, dict):
                absorb_interest_list(block.get("interests"))

    return list(by_key.items())


def _names_from_targeting_objects(items: Any, *, max_items: int = 25) -> list[str]:
    """Estrae etichette testuali da liste di dict Meta (id/name o name solo)."""
    if not items or not isinstance(items, list):
        return []
    out: list[str] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        name = (it.get("name") or "").strip()
        raw_id = it.get("id")
        sid = str(raw_id).strip() if raw_id is not None else ""
        if name:
            label = name if not sid else f"{name} ({sid})"
        elif sid:
            label = sid
        else:
            continue
        if label not in out:
            out.append(label)
        if len(out) >= max_items:
            break
    return out


def _geo_locations_summary(geo: Any, *, max_items: int = 12) -> str:
    """Sintesi geo_locations / excluded_geo_locations (countries, regions, cities, custom_locations)."""
    if not geo or not isinstance(geo, dict):
        return ""
    parts: list[str] = []
    countries = geo.get("countries")
    if isinstance(countries, list) and countries:
        parts.append("Paesi: " + ", ".join(str(c) for c in countries[:max_items]))
    regions = geo.get("regions")
    if isinstance(regions, list) and regions:
        reg_bits = []
        for r in regions[:max_items]:
            if isinstance(r, dict):
                reg_bits.append((r.get("name") or r.get("key") or str(r.get("country", ""))).strip() or "?")
            else:
                reg_bits.append(str(r))
        if reg_bits:
            parts.append("Regioni: " + ", ".join(reg_bits))
    cities = geo.get("cities")
    if isinstance(cities, list) and cities:
        c_bits = []
        for c in cities[:max_items]:
            if isinstance(c, dict):
                c_bits.append((c.get("name") or c.get("key") or "").strip() or "?")
            else:
                c_bits.append(str(c))
        if c_bits:
            parts.append("Città: " + ", ".join(c_bits))
    zips = geo.get("zips")
    if isinstance(zips, list) and zips:
        parts.append("CAP/ZIP: " + ", ".join(str(z) for z in zips[:8]))
    loc_types = geo.get("location_types")
    if isinstance(loc_types, list) and loc_types:
        parts.append("Tipo luogo: " + ", ".join(str(x) for x in loc_types))
    custom = geo.get("custom_locations")
    if isinstance(custom, list) and custom:
        parts.append(f"Custom locations: {len(custom)} area/i")
    return " · ".join(parts) if parts else ""


def _flexible_spec_collect_specs(targeting: dict) -> dict[str, list[str]]:
    """
    Da flexible_spec[], raccoglie etichette per behaviors, work_*, education_*, ecc.
    Chiavi interne: behaviors, work_employers, industries, education_schools, education_majors,
    college_years, income, family_statuses, life_events, relationship_statuses, user_adclusters.
    """
    keys = (
        "behaviors",
        "work_employers",
        "work_positions",
        "industries",
        "education_schools",
        "education_majors",
        "education_statuses",
        "college_years",
        "income",
        "family_statuses",
        "life_events",
        "relationship_statuses",
        "user_adclusters",
    )
    acc: dict[str, list[str]] = {k: [] for k in keys}
    flex = targeting.get("flexible_spec")
    if not isinstance(flex, list):
        return acc
    for block in flex:
        if not isinstance(block, dict):
            continue
        for k in keys:
            acc[k].extend(_names_from_targeting_objects(block.get(k), max_items=40))
    # dedupe mantenendo ordine
    for k in keys:
        seen: set[str] = set()
        deduped: list[str] = []
        for x in acc[k]:
            if x not in seen:
                seen.add(x)
                deduped.append(x)
        acc[k] = deduped[:25]
    return acc


def _extract_excluded_interests_from_targeting(targeting: dict) -> list[str]:
    """Interessi esclusi: chiavi note + flexible_spec[].exclusions (se presenti)."""
    names: list[str] = []
    top = targeting.get("excluded_interests")
    if isinstance(top, list):
        names.extend(_names_from_targeting_objects(top))
    excl = targeting.get("exclusions")
    if isinstance(excl, dict):
        ei = excl.get("interests")
        if isinstance(ei, list):
            names.extend(_names_from_targeting_objects(ei))
    flex = targeting.get("flexible_spec")
    if isinstance(flex, list):
        for block in flex:
            if not isinstance(block, dict):
                continue
            sub = block.get("exclusions")
            if isinstance(sub, dict):
                ei2 = sub.get("interests")
                if isinstance(ei2, list):
                    names.extend(_names_from_targeting_objects(ei2))
    seen: set[str] = set()
    out: list[str] = []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out[:40]


def _summarize_meta_targeting_detailed(targeting: Any) -> dict[str, Any]:
    """
    Campi leggibili per UI (età, genere, geo, piattaforme, audience, esclusioni, behaviors, ecc.).
    Valori assenti = stringa vuota o lista vuota (mai 0 al posto di mancante per testi).
    """
    empty: dict[str, Any] = {
        "age_range": "",
        "genders": "",
        "locales": "",
        "geo_included": "",
        "geo_excluded": "",
        "publisher_platforms": "",
        "facebook_positions": "",
        "instagram_positions": "",
        "audience_network_positions": "",
        "messenger_positions": "",
        "device_platforms": "",
        "custom_audiences_in": "",
        "custom_audiences_ex": "",
        "interests_included_labels": [],
        "interests_excluded_labels": [],
        "behaviors": "",
        "work_and_industries": "",
        "education": "",
        "demographics_other": "",
        "brand_safety": "",
        "targeting_automation": "",
        "advantage_audience": "",
        "other_notable": "",
    }
    if not targeting or not isinstance(targeting, dict):
        return empty

    t = targeting
    out = dict(empty)

    amin = t.get("age_min")
    amax = t.get("age_max")
    if amin is not None or amax is not None:
        a1 = str(amin).strip() if amin is not None else ""
        a2 = str(amax).strip() if amax is not None else ""
        if a1 and a2:
            out["age_range"] = f"{a1}–{a2}"
        elif a1:
            out["age_range"] = f"min {a1}"
        elif a2:
            out["age_range"] = f"max {a2}"

    genders = t.get("genders")
    if isinstance(genders, list) and genders:
        gl: list[str] = []
        for g in genders:
            if g in (1, "1"):
                gl.append("Maschio")
            elif g in (2, "2"):
                gl.append("Femmina")
            else:
                gl.append(str(g))
        out["genders"] = ", ".join(gl)

    locs = t.get("locales")
    if isinstance(locs, list) and locs:
        out["locales"] = ", ".join(str(x) for x in locs[:20])

    out["geo_included"] = _geo_locations_summary(t.get("geo_locations"))
    out["geo_excluded"] = _geo_locations_summary(t.get("excluded_geo_locations"))

    pp = t.get("publisher_platforms")
    if isinstance(pp, list) and pp:
        out["publisher_platforms"] = ", ".join(str(x) for x in pp)

    for key, label in (
        ("facebook_positions", "facebook_positions"),
        ("instagram_positions", "instagram_positions"),
        ("audience_network_positions", "audience_network_positions"),
        ("messenger_positions", "messenger_positions"),
    ):
        v = t.get(label)
        if isinstance(v, list) and v:
            out[key] = ", ".join(str(x) for x in v[:30])

    dp = t.get("device_platforms")
    if isinstance(dp, list) and dp:
        out["device_platforms"] = ", ".join(str(x) for x in dp)

    ca = t.get("custom_audiences")
    if isinstance(ca, list) and ca:
        out["custom_audiences_in"] = " · ".join(_names_from_targeting_objects(ca, max_items=15))
    ex_ca = t.get("excluded_custom_audiences")
    if isinstance(ex_ca, list) and ex_ca:
        out["custom_audiences_ex"] = " · ".join(_names_from_targeting_objects(ex_ca, max_items=15))

    inc_int = [iname for _k, iname in _extract_interests_from_targeting(t)]
    out["interests_included_labels"] = inc_int[:40]
    out["interests_excluded_labels"] = _extract_excluded_interests_from_targeting(t)

    flex_specs = _flexible_spec_collect_specs(t)
    if flex_specs["behaviors"]:
        out["behaviors"] = " · ".join(flex_specs["behaviors"])
    work_bits = flex_specs["work_employers"] + flex_specs["work_positions"] + flex_specs["industries"]
    if work_bits:
        out["work_and_industries"] = " · ".join(work_bits[:25])
    edu_bits = (
        flex_specs["education_schools"]
        + flex_specs["education_majors"]
        + flex_specs["education_statuses"]
        + flex_specs["college_years"]
    )
    if edu_bits:
        out["education"] = " · ".join(edu_bits[:25])
    demo_rest = (
        flex_specs["income"]
        + flex_specs["family_statuses"]
        + flex_specs["life_events"]
        + flex_specs["relationship_statuses"]
        + flex_specs["user_adclusters"]
    )
    if demo_rest:
        out["demographics_other"] = " · ".join(demo_rest[:25])

    bsf = t.get("brand_safety_content_filter_levels")
    if isinstance(bsf, list) and bsf:
        out["brand_safety"] = ", ".join(str(x) for x in bsf)
    elif isinstance(bsf, str) and bsf.strip():
        out["brand_safety"] = bsf.strip()

    ta = t.get("targeting_automation")
    if isinstance(ta, dict) and ta:
        parts = [f"{k}={ta[k]}" for k in sorted(ta.keys())[:12]]
        out["targeting_automation"] = ", ".join(parts)
    elif isinstance(ta, (str, int, float)):
        out["targeting_automation"] = str(ta)

    aa = t.get("targeting_optimization")
    if isinstance(aa, str) and aa.strip():
        out["advantage_audience"] = aa.strip()
    taa = t.get("targeting_relaxation_types")
    if isinstance(taa, list) and taa:
        out["advantage_audience"] = (
            (out["advantage_audience"] + " · ") if out["advantage_audience"] else ""
        ) + "relaxation: " + ", ".join(str(x) for x in taa)

    # Chiavi “utili” non ancora mappate (brevi)
    skip = {
        "age_min",
        "age_max",
        "genders",
        "locales",
        "geo_locations",
        "excluded_geo_locations",
        "publisher_platforms",
        "facebook_positions",
        "instagram_positions",
        "audience_network_positions",
        "messenger_positions",
        "device_platforms",
        "custom_audiences",
        "excluded_custom_audiences",
        "interests",
        "flexible_spec",
        "excluded_interests",
        "exclusions",
    }
    extra_keys = [k for k in t.keys() if k not in skip and not str(k).startswith("_")]
    if extra_keys:
        out["other_notable"] = ", ".join(sorted(extra_keys)[:18])

    return out


def _interests_adset_metrics_fallback(spend: float, conversions: int) -> dict[str, Any]:
    """Se _marketing_metrics_block segnala _skip ma l'ad set ha spend/conv da aggregato Insights, mostra almeno il blocco Meta coerente."""
    cv = int(conversions or 0)
    sp = float(spend or 0.0)
    cpl = round(sp / cv, 2) if cv else 0.0
    sp_r = round(sp, 2)
    return {
        "total_leads": cv,
        "cpl_meta": cpl,
        "spend": sp_r,
        "conversions": cv,
        "magellano_entrate": 0,
        "magellano_scartate": cv,
        "magellano_scarto_pct_ingresso": round(100.0, 2) if cv else 0.0,
        "cpl_ingresso": round(cpl, 2) if cv else 0.0,
        "magellano_inviate": 0,
        "magellano_rifiutate": 0,
        "magellano_scarto_pct_uscita": 0.0,
        "cpl_uscita": 0.0,
        "ulixe_lavorazione": 0,
        "ulixe_rifiutate": 0,
        "ulixe_approvate": 0,
        "revenue": 0.0,
        "margine_singola_lead": None,
        "margine_lordo": None,
        "margine_pct": None,
        "scarto_totale_pct": round(100.0, 2) if cv else 0.0,
    }


def _story_spec_strings_for_search(spec: Any) -> list[str]:
    """Estrae testi noti da object_story_spec (minuscolo) per filtro copy."""
    out: list[str] = []

    def _from_cta(cta: Any) -> None:
        if not isinstance(cta, dict):
            return
        cv = cta.get("value")
        if isinstance(cv, dict):
            for ck in ("link", "link_caption", "link_title"):
                s = cv.get(ck)
                if isinstance(s, str) and s.strip():
                    out.append(s.strip().lower())
        elif isinstance(cv, str) and cv.strip():
            out.append(cv.strip().lower())

    def _from_link_data(ld: Any) -> None:
        if not isinstance(ld, dict):
            return
        for k in ("name", "message", "description", "caption", "link"):
            v = ld.get(k)
            if isinstance(v, str) and v.strip():
                out.append(v.strip().lower())
        _from_cta(ld.get("call_to_action"))

    def _walk(n: Any) -> None:
        if not isinstance(n, dict):
            return
        ld = n.get("link_data")
        if isinstance(ld, dict):
            _from_link_data(ld)
        vd = n.get("video_data")
        if isinstance(vd, dict):
            for k in ("title", "message"):
                v = vd.get(k)
                if isinstance(v, str) and v.strip():
                    out.append(v.strip().lower())
            _from_cta(vd.get("call_to_action"))
        pd = n.get("photo_data")
        if isinstance(pd, dict):
            v = pd.get("caption")
            if isinstance(v, str) and v.strip():
                out.append(v.strip().lower())
        kids = n.get("child_attachments")
        if isinstance(kids, list):
            for ch in kids:
                _walk(ch)

    _walk(spec if isinstance(spec, dict) else {})
    return out


def _object_story_spec_to_search_blob(spec: Any, ad_name: str = "") -> str:
    parts = _story_spec_strings_for_search(spec)
    an = (ad_name or "").strip()
    if an:
        parts.append(an.lower())
    return " ".join(parts)


def _summarize_creative_copy_for_display(spec: Any) -> dict[str, Any]:
    """Riepilogo copy per UI (liste deduplicate; campi vuoti come stringhe vuote)."""
    headlines: list[str] = []
    bodies: list[str] = []
    descriptions: list[str] = []
    captions: list[str] = []
    urls: list[str] = []
    ctas: list[str] = []

    def _add(bucket: list[str], s: Any) -> None:
        if not isinstance(s, str):
            return
        t = s.strip()
        if not t or t in bucket:
            return
        bucket.append(t)

    def _from_cta(cta: Any) -> None:
        if not isinstance(cta, dict):
            return
        cv = cta.get("value")
        if isinstance(cv, dict):
            t = cv.get("link_title") or cv.get("link_caption") or ""
            if isinstance(t, str) and t.strip():
                _add(ctas, t)
            act = cv.get("lead_gen_form_id") or cv.get("app_link")
            if act:
                _add(ctas, str(act))
        t = cta.get("type")
        if isinstance(t, str) and t.strip():
            _add(ctas, t)

    def _from_link_data(ld: Any) -> None:
        if not isinstance(ld, dict):
            return
        _add(headlines, ld.get("name", ""))
        _add(bodies, ld.get("message", ""))
        _add(descriptions, ld.get("description", ""))
        _add(captions, ld.get("caption", ""))
        _add(urls, ld.get("link", ""))
        _from_cta(ld.get("call_to_action"))

    def _walk(n: Any) -> None:
        if not isinstance(n, dict):
            return
        ld = n.get("link_data")
        if isinstance(ld, dict):
            _from_link_data(ld)
        vd = n.get("video_data")
        if isinstance(vd, dict):
            _add(headlines, vd.get("title", ""))
            _add(bodies, vd.get("message", ""))
            _from_cta(vd.get("call_to_action"))
        pd = n.get("photo_data")
        if isinstance(pd, dict):
            _add(bodies, pd.get("caption", ""))
        kids = n.get("child_attachments")
        if isinstance(kids, list):
            for ch in kids:
                _walk(ch)

    _walk(spec if isinstance(spec, dict) else {})
    return {
        "headlines": headlines,
        "bodies": bodies,
        "descriptions": descriptions,
        "captions": captions,
        "urls": urls,
        "ctas": ctas,
    }


def _build_copy_marketing_analysis(
    db: Session,
    date_from,
    date_to,
    af: dict[str, Any],
    *,
    analysis_platform: str = "all",
    copy_q: str = "",
    page: int = 1,
    page_size: int = 10,
) -> dict[str, Any]:
    """
    Annunci (MetaAd) con metriche nel periodo e copy da creative_object_story_spec.
    Filtro opzionale copy_q: sottostringa nel testo copy o nel nome ad.
    """
    ad_agg = (
        db.query(
            MetaAd.id.label("ad_internal_id"),
            func.coalesce(func.sum(MetaMarketingData.spend), 0).label("tot_spend"),
            func.coalesce(func.sum(MetaMarketingData.conversions), 0).label("tot_conv"),
        )
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
    ad_agg = _apply_analysis_entity_filters(ad_agg, **af)
    ad_agg = _apply_analysis_platform_meta_marketing_data(ad_agg, analysis_platform)
    ad_agg = ad_agg.group_by(MetaAd.id)
    agg_rows = ad_agg.all()

    empty = {
        "ad_detail_rows": [],
        "ad_page": 1,
        "ad_page_size": max(1, min(int(page_size), 50)),
        "ad_total_count": 0,
        "ad_total_pages": 0,
        "unique_ad_count": 0,
        "unique_total_spend": 0.0,
        "unique_total_conversions": 0,
        "unique_cpl": 0.0,
    }

    if not agg_rows:
        return empty

    ids_initial = [int(r.ad_internal_id) for r in agg_rows]
    name_map: dict[int, str] = {}
    spec_map: dict[int, dict[str, Any]] = {}
    for aid, aname, spec in (
        db.query(MetaAd.id, MetaAd.name, MetaAd.creative_object_story_spec).filter(MetaAd.id.in_(ids_initial)).all()
    ):
        name_map[int(aid)] = (aname or "").strip()
        spec_map[int(aid)] = spec if isinstance(spec, dict) else {}

    cq = (copy_q or "").strip().lower()

    def _ad_matches_copy_filter(aid_int: int) -> bool:
        if not cq:
            return True
        blob = _object_story_spec_to_search_blob(spec_map.get(aid_int, {}), name_map.get(aid_int, ""))
        return cq in blob

    agg_rows = [r for r in agg_rows if _ad_matches_copy_filter(int(r.ad_internal_id))]
    if not agg_rows:
        return empty

    agg_by_ad: dict[int, tuple[float, int]] = {}
    unique_spend = 0.0
    unique_conv = 0
    for r in agg_rows:
        aid = int(r.ad_internal_id)
        sp = float(_parse_amount(r.tot_spend) if r.tot_spend is not None else 0.0)
        cv = int(r.tot_conv or 0)
        agg_by_ad[aid] = (sp, cv)
        unique_spend += sp
        unique_conv += cv

    unique_cpl = (unique_spend / unique_conv) if unique_conv > 0 else 0.0
    ids = [int(r.ad_internal_id) for r in agg_rows]

    ad_triples = (
        db.query(MetaAd, MetaAdSet.name, MetaCampaign.name)
        .join(MetaAdSet, MetaAd.adset_id == MetaAdSet.id)
        .join(MetaCampaign, MetaAdSet.campaign_id == MetaCampaign.id)
        .filter(MetaAd.id.in_(ids))
        .all()
    )
    ad_triples.sort(
        key=lambda t: (agg_by_ad.get(t[0].id, (0.0, 0))[0], agg_by_ad.get(t[0].id, (0.0, 0))[1]),
        reverse=True,
    )

    meta_ad_ids_ordered: list[str] = []
    for ad, _, _ in ad_triples:
        if ad.ad_id:
            s = str(ad.ad_id).strip()
            if s:
                meta_ad_ids_ordered.append(s)
    meta_ad_ids_unique = list(dict.fromkeys(meta_ad_ids_ordered))
    mag_to_pay = _get_mag_to_pay(db)
    plat = (analysis_platform or "all").strip().lower()
    leads_by_ad = _bulk_leads_by_meta_ad_id(db, meta_ad_ids_unique, date_from, date_to, plat)
    md_by_ad = _bulk_marketing_by_ad_pk(db, ids, date_from, date_to, plat)

    ad_detail_rows: list[dict[str, Any]] = []
    for ad, adset_name, campaign_name in ad_triples:
        meta_aid = str(ad.ad_id).strip() if ad.ad_id else ""
        leads = leads_by_ad.get(meta_aid, []) if meta_aid else []
        marketing_data = md_by_ad.get(ad.id, [])
        m = _marketing_metrics_block(leads, marketing_data, mag_to_pay, db)
        if m.pop("_skip"):
            sp_fb, cv_fb = agg_by_ad.get(ad.id, (0.0, 0))
            m = _interests_adset_metrics_fallback(sp_fb, cv_fb)
        raw_spec = ad.creative_object_story_spec if isinstance(ad.creative_object_story_spec, dict) else {}
        row: dict[str, Any] = {
            "ad_internal_id": ad.id,
            "ad_meta_id": meta_aid,
            "ad_name": (ad.name or "").strip(),
            "adset_name": (adset_name or "").strip(),
            "campaign_name": (campaign_name or "").strip(),
            "status": (ad.status or "").strip(),
            "creative_id": (ad.creative_id or "").strip(),
            "show_thumbnail": bool((ad.creative_id or "").strip() and ad.id),
            "creative_copy_detail": _summarize_creative_copy_for_display(raw_spec),
            "creative_object_story_spec": raw_spec,
        }
        row.update(m)
        row["total_spend"] = m["spend"]
        row["total_conversions"] = m["total_leads"]
        row["cpl"] = m["cpl_meta"]
        ad_detail_rows.append(row)

    ps = max(1, min(int(page_size), 50))
    pg = max(1, int(page))
    total_ads = len(ad_detail_rows)
    total_pages = max(1, (total_ads + ps - 1) // ps) if total_ads else 1
    if pg > total_pages:
        pg = total_pages
    start = (pg - 1) * ps
    page_rows = ad_detail_rows[start : start + ps]

    return {
        "ad_detail_rows": page_rows,
        "ad_page": pg,
        "ad_page_size": ps,
        "ad_total_count": total_ads,
        "ad_total_pages": total_pages,
        "unique_ad_count": len(agg_rows),
        "unique_total_spend": round(unique_spend, 2),
        "unique_total_conversions": unique_conv,
        "unique_cpl": round(unique_cpl, 2),
    }


def _build_interests_marketing_analysis(
    db: Session,
    date_from,
    date_to,
    af: dict[str, Any],
    *,
    analysis_platform: str = "all",
    interest_name_q: str = "",
    page: int = 1,
    page_size: int = 10,
) -> dict[str, Any]:
    """
    Ad set con metriche nel periodo e targeting Meta completo (JSON + riepilogo).
    Filtro opzionale interest_name: solo ad set il cui targeting contiene almeno un interesse che matcha il testo.
    Paginazione sugli ad set.
    """
    adset_agg = (
        db.query(
            MetaAdSet.id.label("adset_internal_id"),
            func.coalesce(func.sum(MetaMarketingData.spend), 0).label("tot_spend"),
            func.coalesce(func.sum(MetaMarketingData.conversions), 0).label("tot_conv"),
        )
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
    adset_agg = _apply_analysis_entity_filters(adset_agg, **af)
    adset_agg = _apply_analysis_platform_meta_marketing_data(adset_agg, analysis_platform)
    adset_agg = adset_agg.group_by(MetaAdSet.id)
    agg_rows = adset_agg.all()

    if not agg_rows:
        return {
            "adset_detail_rows": [],
            "adset_page": 1,
            "adset_page_size": max(1, min(int(page_size), 50)),
            "adset_total_count": 0,
            "adset_total_pages": 0,
            "unique_adset_count": 0,
            "unique_total_spend": 0.0,
            "unique_total_conversions": 0,
            "unique_cpl": 0.0,
        }

    ids = [int(r.adset_internal_id) for r in agg_rows]
    targeting_map = dict(db.query(MetaAdSet.id, MetaAdSet.targeting).filter(MetaAdSet.id.in_(ids)).all())

    iq = (interest_name_q or "").strip().lower()

    def _adset_matches_interest_filter(aid: int) -> bool:
        if not iq:
            return True
        interests = _extract_interests_from_targeting(targeting_map.get(aid))
        if not interests:
            interests = [("__no_interests__", "Senza interessi nel targeting")]
        for ikey, iname in interests:
            if iq in (str(ikey) or "").lower() or iq in (str(iname) or "").lower():
                return True
        return False

    agg_rows = [r for r in agg_rows if _adset_matches_interest_filter(int(r.adset_internal_id))]
    if not agg_rows:
        return {
            "adset_detail_rows": [],
            "adset_page": 1,
            "adset_page_size": max(1, min(int(page_size), 50)),
            "adset_total_count": 0,
            "adset_total_pages": 0,
            "unique_adset_count": 0,
            "unique_total_spend": 0.0,
            "unique_total_conversions": 0,
            "unique_cpl": 0.0,
        }

    ids = [int(r.adset_internal_id) for r in agg_rows]

    agg_by_adset: dict[int, tuple[float, int]] = {}
    for r in agg_rows:
        aid = int(r.adset_internal_id)
        sp = float(_parse_amount(r.tot_spend) if r.tot_spend is not None else 0.0)
        cv = int(r.tot_conv or 0)
        agg_by_adset[aid] = (sp, cv)

    unique_spend = 0.0
    unique_conv = 0
    for r in agg_rows:
        unique_spend += float(_parse_amount(r.tot_spend) if r.tot_spend is not None else 0.0)
        unique_conv += int(r.tot_conv or 0)

    unique_cpl = (unique_spend / unique_conv) if unique_conv > 0 else 0.0

    plat = (analysis_platform or "all").strip().lower()
    adset_pairs = (
        db.query(MetaAdSet, MetaCampaign.name)
        .join(MetaCampaign, MetaAdSet.campaign_id == MetaCampaign.id)
        .filter(MetaAdSet.id.in_(ids))
        .all()
    )
    meta_adset_ids_ordered: list[str] = []
    for a, _ in adset_pairs:
        if a.adset_id:
            s = str(a.adset_id).strip()
            if s:
                meta_adset_ids_ordered.append(s)
    meta_adset_ids_unique = list(dict.fromkeys(meta_adset_ids_ordered))
    mag_to_pay = _get_mag_to_pay(db)
    leads_by_as = _bulk_leads_by_meta_adset(db, meta_adset_ids_unique, date_from, date_to, plat)
    md_by_as = _bulk_marketing_by_adset_pk(db, ids, date_from, date_to, plat)

    adset_detail_rows: list[dict[str, Any]] = []
    for adset, campaign_name in adset_pairs:
        aid_meta = str(adset.adset_id).strip() if adset.adset_id else ""
        leads = leads_by_as.get(aid_meta, []) if aid_meta else []
        marketing_data = md_by_as.get(adset.id, [])
        m = _marketing_metrics_block(leads, marketing_data, mag_to_pay, db)
        if m.pop("_skip"):
            sp_fb, cv_fb = agg_by_adset.get(adset.id, (0.0, 0))
            m = _interests_adset_metrics_fallback(sp_fb, cv_fb)
        raw_t = targeting_map.get(adset.id)
        raw_dict = raw_t if isinstance(raw_t, dict) else {}
        row: dict[str, Any] = {
            "adset_internal_id": adset.id,
            "adset_meta_id": aid_meta,
            "adset_name": (adset.name or "").strip(),
            "campaign_name": (campaign_name or "").strip(),
            "status": (adset.status or "").strip(),
            "targeting_detail": _summarize_meta_targeting_detailed(raw_dict),
            "targeting_raw": raw_dict,
        }
        row.update(m)
        row["total_spend"] = m["spend"]
        row["total_conversions"] = m["total_leads"]
        row["cpl"] = m["cpl_meta"]
        adset_detail_rows.append(row)
    adset_detail_rows.sort(key=lambda x: (x["total_spend"], x["total_conversions"]), reverse=True)

    ps = max(1, min(int(page_size), 50))
    pg = max(1, int(page))
    total_adsets = len(adset_detail_rows)
    total_pages = max(1, (total_adsets + ps - 1) // ps) if total_adsets else 1
    if pg > total_pages:
        pg = total_pages
    start = (pg - 1) * ps
    page_rows = adset_detail_rows[start : start + ps]

    return {
        "adset_detail_rows": page_rows,
        "adset_page": pg,
        "adset_page_size": ps,
        "adset_total_count": total_adsets,
        "adset_total_pages": total_pages,
        "unique_adset_count": len(agg_rows),
        "unique_total_spend": round(unique_spend, 2),
        "unique_total_conversions": unique_conv,
        "unique_cpl": round(unique_cpl, 2),
    }


def _marketing_redirect_preserve_query(path: str, request: Request, tab: str | None = None) -> RedirectResponse:
    """Redirect con stessi query param; opzionalmente imposta/sostituisce tab=."""
    pairs: list[tuple[str, str]] = [(k, v) for k, v in request.query_params.multi_items() if k != "tab"]
    if tab is not None:
        pairs.append(("tab", tab))
    qs = urlencode(pairs)
    url = f"{path}?{qs}" if qs else path
    return RedirectResponse(url=url, status_code=302)


def _empty_totals_for_analysis_template() -> dict[str, Any]:
    """Totale KPI vuoti: usato quando si salta il calcolo completo (tab placement_creative)."""
    return {
        "total_spend": 0.0,
        "total_impressions": 0,
        "total_clicks": 0,
        "total_conversions": 0,
        "global_cpl": 0.0,
        "avg_ctr": 0.0,
        "avg_cpc": 0.0,
        "avg_cpm": 0.0,
        "pay_level": None,
        "total_magellano_entrate": 0,
        "total_magellano_inviate": 0,
        "total_magellano_doppioni": 0,
        "total_magellano_scartate": 0,
        "total_ulixe_scartate": 0,
        "total_ulixe_approvate": 0,
        "ulixe_approvate_from_rcrm": False,
        "total_ricavo": 0.0,
        "total_margine": 0.0,
        "total_margine_pct": None,
        "leads_count": 0,
        "magellano_doppioni_pct": 0,
        "magellano_scartate_pct": 0,
        "ulixe_scartate_pct": 0,
    }


def _compute_placement_creative_tab_data(
    db: Session,
    date_from,
    date_to,
    af: dict,
    placement_creative_expand_by_ad: bool,
    params,
) -> tuple[
    dict[str, list[dict[str, Any]]],
    list[dict[str, str]],
    list[dict[str, str]],
    str,
    str,
]:
    """
    Dati solo per il tab «Creatività per posizionamento».
    Evita le query aggregate dell'analisi completa che fanno scadere il timeout proxy.
    """
    placement_creative_by_platform: dict[str, list[dict[str, Any]]] = {
        "facebook": [],
        "instagram": [],
    }
    _mpp_pos_key = func.lower(func.trim(func.coalesce(MetaMarketingPlacement.platform_position, "")))

    def _placement_creative_base_for_platform(pub: str):
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

    return (
        placement_creative_by_platform,
        placement_position_options_facebook,
        placement_position_options_instagram,
        selected_pc_position_facebook,
        selected_pc_position_instagram,
    )


def _mmd_filtered_base_query(db: Session, date_from, date_to, af: dict, analysis_platform: str):
    """Query MetaMarketingData con join account e filtri entity/piattaforma (layer A)."""
    q = (
        db.query(MetaMarketingData)
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
    q = _apply_analysis_entity_filters(q, **af)
    q = _apply_analysis_platform_meta_marketing_data(q, analysis_platform)
    return q


def _compute_mmd_kpis_from_aggregate(db: Session, date_from, date_to, af: dict, analysis_platform: str) -> dict:
    """Somme e medie SQL su meta_marketing_data nello scope filtri (evita .all() su milioni di righe)."""
    base = _mmd_filtered_base_query(db, date_from, date_to, af, analysis_platform)
    row = (
        base.with_entities(
            func.coalesce(func.sum(MetaMarketingData.spend), 0).label("total_spend"),
            func.coalesce(func.sum(MetaMarketingData.impressions), 0).label("total_impressions"),
            func.coalesce(func.sum(MetaMarketingData.clicks), 0).label("total_clicks"),
            func.coalesce(func.sum(MetaMarketingData.conversions), 0).label("total_conversions"),
            func.avg(MetaMarketingData.ctr).label("avg_ctr"),
            func.avg(MetaMarketingData.cpc).label("avg_cpc"),
            func.avg(MetaMarketingData.cpm).label("avg_cpm"),
        ).first()
    )
    if not row:
        return {
            "total_spend": 0.0,
            "total_impressions": 0,
            "total_clicks": 0,
            "total_conversions": 0,
            "avg_ctr": 0.0,
            "avg_cpc": 0.0,
            "avg_cpm": 0.0,
        }
    return {
        "total_spend": _parse_amount(row.total_spend),
        "total_impressions": int(row.total_impressions or 0),
        "total_clicks": int(row.total_clicks or 0),
        "total_conversions": int(row.total_conversions or 0),
        "avg_ctr": float(row.avg_ctr) if row.avg_ctr is not None else 0.0,
        "avg_cpc": float(row.avg_cpc) if row.avg_cpc is not None else 0.0,
        "avg_cpm": float(row.avg_cpm) if row.avg_cpm is not None else 0.0,
    }


def _mmd_scope_campaign_adset_ids(
    db: Session, date_from, date_to, af: dict, analysis_platform: str
) -> tuple[set[str], set[str]]:
    """campaign_id e adset_id Meta distinti nello scope (per correlazione Lead)."""
    base = _mmd_filtered_base_query(db, date_from, date_to, af, analysis_platform)
    c_rows = base.with_entities(MetaCampaign.campaign_id).distinct().all()
    a_rows = base.with_entities(MetaAdSet.adset_id).distinct().all()
    campaign_ids = {str(r[0]).strip() for r in c_rows if r[0]}
    adset_ids = {str(r[0]).strip() for r in a_rows if r[0]}
    return campaign_ids, adset_ids


def _mpp_filtered_base_query(db: Session, date_from, date_to, af: dict, platform_key: str):
    """Layer B: placement per publisher_platform (facebook / instagram)."""
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
            _placement_publisher_platform_eq(MetaMarketingPlacement.publisher_platform, platform_key),
        )
    )
    q = _apply_analysis_entity_filters(q, **af)
    return q


def _compute_mpp_kpis_from_aggregate(
    db: Session, date_from, date_to, af: dict, platform_key: str
) -> dict:
    base = _mpp_filtered_base_query(db, date_from, date_to, af, platform_key)
    row = (
        base.with_entities(
            func.coalesce(func.sum(MetaMarketingPlacement.spend), 0).label("total_spend"),
            func.coalesce(func.sum(MetaMarketingPlacement.impressions), 0).label("total_impressions"),
            func.coalesce(func.sum(MetaMarketingPlacement.clicks), 0).label("total_clicks"),
            func.coalesce(func.sum(MetaMarketingPlacement.conversions), 0).label("total_conversions"),
            func.avg(MetaMarketingPlacement.ctr).label("avg_ctr"),
            func.avg(MetaMarketingPlacement.cpc).label("avg_cpc"),
            func.avg(MetaMarketingPlacement.cpm).label("avg_cpm"),
        ).first()
    )
    if not row:
        return {
            "total_spend": 0.0,
            "total_impressions": 0,
            "total_clicks": 0,
            "total_conversions": 0,
            "avg_ctr": 0.0,
            "avg_cpc": 0.0,
            "avg_cpm": 0.0,
        }
    return {
        "total_spend": _parse_amount(row.total_spend),
        "total_impressions": int(row.total_impressions or 0),
        "total_clicks": int(row.total_clicks or 0),
        "total_conversions": int(row.total_conversions or 0),
        "avg_ctr": float(row.avg_ctr) if row.avg_ctr is not None else 0.0,
        "avg_cpc": float(row.avg_cpc) if row.avg_cpc is not None else 0.0,
        "avg_cpm": float(row.avg_cpm) if row.avg_cpm is not None else 0.0,
    }


def _mpp_scope_campaign_ids(db: Session, date_from, date_to, af: dict, platform_key: str) -> set[str]:
    base = _mpp_filtered_base_query(db, date_from, date_to, af, platform_key)
    rows = base.with_entities(MetaCampaign.campaign_id).distinct().all()
    return {str(r[0]).strip() for r in rows if r[0]}


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


async def _marketing_analysis_page(request: Request, db: Session, *, layout: str):
    """
    layout='main': tab Analisi + Lavorazioni lead (/marketing/analysis).
    layout='posizionamenti': tab Breakdown + Creatività per posizionamenti.
    """
    user = request.session.get('user')
    if not user:
        return RedirectResponse(url='/')

    current_user = db.query(User).filter(User.email == user.get('email')).first()
    if not current_user:
        return RedirectResponse(url='/')

    params = request.query_params
    _tab_raw = (params.get("tab") or "").strip().lower()

    if layout == "main":
        if _tab_raw in ("breakdown", "placement_creative"):
            return _marketing_redirect_preserve_query("/marketing/analysis-posizionamenti", request, _tab_raw)
        analysis_tab = _tab_raw if _tab_raw in ("analysis", "lead_wip") else "analysis"
    else:
        if _tab_raw in ("analysis", "lead_wip"):
            return _marketing_redirect_preserve_query("/marketing/analysis", request, _tab_raw)
        analysis_tab = _tab_raw if _tab_raw in ("breakdown", "placement_creative") else "breakdown"

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

    # Date range: default inizio mese corrente → ieri (allineato a /marketing)
    date_from_str = params.get('date_from')
    date_to_str = params.get('date_to')
    _def_from, _def_to = default_marketing_filter_date_range()

    try:
        date_from = datetime.strptime(date_from_str, '%Y-%m-%d') if date_from_str else _def_from
    except Exception:
        date_from = _def_from

    try:
        if date_to_str:
            date_to = datetime.strptime(date_to_str, '%Y-%m-%d').replace(
                hour=23, minute=59, second=59, microsecond=999999
            )
        else:
            date_to = _def_to
    except Exception:
        date_to = _def_to

    # Dati per JSON gerarchia (filtri combobox / export lato client se presenti)
    accounts = (
        db.query(MetaAccount).filter(MetaAccount.is_active == True).order_by(MetaAccount.name).all()
    )
    campaigns = (
        db.query(MetaCampaign)
        .join(MetaAccount)
        .filter(MetaAccount.is_active == True)
        .options(joinedload(MetaCampaign.account))
        .order_by(MetaCampaign.name)
        .all()
    )
    adsets = (
        db.query(MetaAdSet)
        .join(MetaCampaign)
        .join(MetaAccount)
        .filter(MetaAccount.is_active == True)
        .options(joinedload(MetaAdSet.campaign).joinedload(MetaCampaign.account))
        .order_by(MetaAdSet.name)
        .all()
    )

    if layout == "main":
        # KPI principali: una query aggregata (niente .all() su tutte le righe giornaliere)
        mmd_kpis = _compute_mmd_kpis_from_aggregate(db, date_from, date_to, af, analysis_platform)
        total_spend = mmd_kpis["total_spend"]
        total_impressions = mmd_kpis["total_impressions"]
        total_clicks = mmd_kpis["total_clicks"]
        total_conversions = mmd_kpis["total_conversions"]
        global_cpl = (total_spend / total_conversions) if total_conversions > 0 else 0.0

        totals = {
            "total_spend": round(total_spend, 2),
            "total_impressions": total_impressions,
            "total_clicks": total_clicks,
            "total_conversions": total_conversions,
            "global_cpl": round(global_cpl, 2),
            "avg_ctr": round(mmd_kpis["avg_ctr"], 2),
            "avg_cpc": round(mmd_kpis["avg_cpc"], 4),
            "avg_cpm": round(mmd_kpis["avg_cpm"], 2),
        }

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

        # Metriche Magellano/Ulixe: scope = campagne/adset presenti nello stesso filtro layer A
        campaign_ids, adset_ids = _mmd_scope_campaign_adset_ids(
            db, date_from, date_to, af, analysis_platform
        )

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
    else:
        mmd_kpis = _compute_mmd_kpis_from_aggregate(db, date_from, date_to, af, analysis_platform)
        totals = _empty_totals_for_analysis_template()
        ts = mmd_kpis["total_spend"]
        tcv = mmd_kpis["total_conversions"]
        g_cpl = (ts / tcv) if tcv > 0 else 0.0
        totals.update(
            {
                "total_spend": round(ts, 2),
                "total_impressions": mmd_kpis["total_impressions"],
                "total_clicks": mmd_kpis["total_clicks"],
                "total_conversions": tcv,
                "global_cpl": round(g_cpl, 2),
                "avg_ctr": round(mmd_kpis["avg_ctr"], 2),
                "avg_cpc": round(mmd_kpis["avg_cpc"], 4),
                "avg_cpm": round(mmd_kpis["avg_cpm"], 2),
            }
        )
        chart_points = []
        distribution_points = []


    if layout == "posizionamenti":
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
        # Breakdown per piattaforma: aggregate SQL su meta_marketing_placement (layer B)
        for platform_key in ("facebook", "instagram"):
            p_kpis = _compute_mpp_kpis_from_aggregate(db, date_from, date_to, af, platform_key)
            p_spend = p_kpis["total_spend"]
            p_impr = p_kpis["total_impressions"]
            p_clicks = p_kpis["total_clicks"]
            p_convs = p_kpis["total_conversions"]
            p_cpl = (p_spend / p_convs) if p_convs > 0 else 0.0
            p_campaign_ids = _mpp_scope_campaign_ids(db, date_from, date_to, af, platform_key)

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
                "avg_ctr": round(p_kpis["avg_ctr"], 2),
                "avg_cpc": round(p_kpis["avg_cpc"], 4),
                "avg_cpm": round(p_kpis["avg_cpm"], 2),
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

        # Posizionamento × creatività (stessa logica del tab dedicato; funzione condivisa).
        (
            placement_creative_by_platform,
            placement_position_options_facebook,
            placement_position_options_instagram,
            selected_pc_position_facebook,
            selected_pc_position_instagram,
        ) = _compute_placement_creative_tab_data(
            db, date_from, date_to, af, placement_creative_expand_by_ad, params
        )

        # CPL giornaliero per posizionamento: asse X = sempre l'intervallo filtro (non solo i giorni con righe in MetaMarketingData).
        d0 = date_from.date() if hasattr(date_from, "date") else date_from
        d1 = date_to.date() if hasattr(date_to, "date") else date_to
        chart_date_order: list[str] = []
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
    else:
        platform_totals = {"facebook": {}, "instagram": {}}
        platform_chart_points = {"facebook": [], "instagram": []}
        platform_distribution_points = {"facebook": [], "instagram": []}
        placement_insights_by_platform = {"facebook": [], "instagram": []}
        placement_creative_by_platform = {"facebook": [], "instagram": []}
        placement_position_options_facebook = []
        placement_position_options_instagram = []
        selected_pc_position_facebook = (params.get("pc_position_facebook") or "").strip()
        selected_pc_position_instagram = (params.get("pc_position_instagram") or "").strip()
        placement_cpl_by_platform = {"facebook": None, "instagram": None}


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

    page_title = "Marketing Analysis" if layout == "main" else "Analisi Posizionamenti"
    active_pg = "marketing_analysis" if layout == "main" else "marketing_analysis_posizionamenti"
    analysis_allowed_tabs = ["analysis", "lead_wip"] if layout == "main" else ["breakdown", "placement_creative"]
    analysis_default_tab = "analysis" if layout == "main" else "breakdown"
    filters_reset_path = "/marketing/analysis" if layout == "main" else "/marketing/analysis-posizionamenti"

    return templates.TemplateResponse(
        request,
        "marketing_analysis.html",
        {
            "request": request,
            "title": page_title,
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
            "active_page": active_pg,
            "analysis_tab": analysis_tab,
            "analysis_layout": layout,
            "analysis_allowed_tabs": analysis_allowed_tabs,
            "analysis_default_tab": analysis_default_tab,
            "analysis_filters_reset_path": filters_reset_path,
            "lavorazione_filter_ui": lavorazioni_heatmap_lavorazione_filter_ui_payload(),
        },
    )


@router.get("/marketing/analysis")
async def marketing_analysis(request: Request, db: Session = Depends(get_db)):
    try:
        return await _marketing_analysis_page(request, db, layout="main")
    except Exception as e:
        logger.error(f"Errore nel route /marketing/analysis: {e}", exc_info=True)
        raise


@router.get("/marketing/analysis-posizionamenti")
async def marketing_analysis_posizionamenti(request: Request, db: Session = Depends(get_db)):
    try:
        return await _marketing_analysis_page(request, db, layout="posizionamenti")
    except Exception as e:
        logger.error(f"Errore nel route /marketing/analysis-posizionamenti: {e}", exc_info=True)
        raise


def _interessi_pagination_urls(request: Request, total_pages: int, current_page: int) -> dict[str, Any]:
    """Link prev/next per GET /marketing/analysis-interessi preservando i query param."""
    base = "/marketing/analysis-interessi"
    pairs = [(k, v) for k, v in request.query_params.multi_items() if k not in ("page", "tab")]

    def _url(p: int) -> str:
        q = list(pairs)
        if p > 1:
            q.append(("page", str(p)))
        return f"{base}?{urlencode(q)}" if q else base

    return {
        "prev_url": _url(current_page - 1) if current_page > 1 else None,
        "next_url": _url(current_page + 1) if current_page < total_pages else None,
        "first_url": _url(1),
    }


def _copy_pagination_urls(request: Request, total_pages: int, current_page: int) -> dict[str, Any]:
    """Link prev/next per GET /marketing/analysis-copy preservando i query param."""
    base = "/marketing/analysis-copy"
    pairs = [(k, v) for k, v in request.query_params.multi_items() if k not in ("page", "tab")]

    def _url(p: int) -> str:
        q = list(pairs)
        if p > 1:
            q.append(("page", str(p)))
        return f"{base}?{urlencode(q)}" if q else base

    return {
        "prev_url": _url(current_page - 1) if current_page > 1 else None,
        "next_url": _url(current_page + 1) if current_page < total_pages else None,
        "first_url": _url(1),
    }


@router.get("/marketing/analysis-interessi")
async def marketing_analysis_interessi(request: Request, db: Session = Depends(get_db)):
    """Ad set con metriche Meta nel periodo e targeting completo (stessi filtri Analysis; filtro opzionale su interessi nel targeting)."""
    try:
        user = request.session.get("user")
        if not user:
            return RedirectResponse(url="/")
        if not db.query(User).filter(User.email == user.get("email")).first():
            return RedirectResponse(url="/")

        params = request.query_params
        selected_account_id = params.get("account_id") or ""
        selected_campaign_id = params.get("campaign_id") or ""
        selected_adset_id_param = params.get("adset_id") or ""
        try:
            selected_adset_id = int(selected_adset_id_param) if selected_adset_id_param else None
        except ValueError:
            selected_adset_id = None

        campaign_name_q = (params.get("campaign_name") or "").strip()
        adset_name_q = (params.get("adset_name") or "").strip()
        interest_name_q = (params.get("interest_name") or "").strip()
        analysis_status = "all"
        analysis_platform = "all"

        try:
            page = int(params.get("page") or "1")
        except ValueError:
            page = 1
        try:
            page_size = int(params.get("page_size") or "10")
        except ValueError:
            page_size = 10

        af = dict(
            selected_account_id=selected_account_id,
            selected_campaign_id=selected_campaign_id,
            selected_adset_id=selected_adset_id,
            campaign_name_q=campaign_name_q,
            adset_name_q=adset_name_q,
            creative_name_q="",
            analysis_status=analysis_status,
        )

        date_from_str = params.get("date_from")
        date_to_str = params.get("date_to")
        _def_from_i, _def_to_i = default_marketing_filter_date_range()
        try:
            date_from = datetime.strptime(date_from_str, "%Y-%m-%d") if date_from_str else _def_from_i
        except Exception:
            date_from = _def_from_i
        try:
            if date_to_str:
                date_to = datetime.strptime(date_to_str, "%Y-%m-%d").replace(
                    hour=23, minute=59, second=59, microsecond=999999
                )
            else:
                date_to = _def_to_i
        except Exception:
            date_to = _def_to_i

        interest_payload = _build_interests_marketing_analysis(
            db,
            date_from,
            date_to,
            af,
            analysis_platform=analysis_platform,
            interest_name_q=interest_name_q,
            page=page,
            page_size=page_size,
        )

        tp = int(interest_payload.get("adset_total_pages") or 1)
        cp = int(interest_payload.get("adset_page") or 1)
        interessi_pagination = _interessi_pagination_urls(request, tp, cp)

        return templates.TemplateResponse(
            request,
            "marketing_analysis_interessi.html",
            {
                "request": request,
                "title": "Targeting ad set",
                "user": user,
                "active_page": "marketing_analysis_interessi",
                "date_from": date_from.strftime("%Y-%m-%d"),
                "date_to": date_to.strftime("%Y-%m-%d"),
                "selected_account_id": selected_account_id,
                "selected_campaign_id": selected_campaign_id,
                "selected_adset_id": selected_adset_id,
                "selected_campaign_name": campaign_name_q,
                "selected_adset_name": adset_name_q,
                "selected_interest_name": interest_name_q,
                "interest_payload": interest_payload,
                "interessi_pagination": interessi_pagination,
            },
        )
    except Exception as e:
        logger.error(f"Errore nel route /marketing/analysis-interessi: {e}", exc_info=True)
        raise


@router.get("/marketing/analysis-copy")
async def marketing_analysis_copy(request: Request, db: Session = Depends(get_db)):
    """Annunci con metriche nel periodo e copy creatività (object_story_spec da sync Meta)."""
    try:
        user = request.session.get("user")
        if not user:
            return RedirectResponse(url="/")
        if not db.query(User).filter(User.email == user.get("email")).first():
            return RedirectResponse(url="/")

        params = request.query_params
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
        copy_q = (params.get("copy_q") or "").strip()
        analysis_status = "all"
        analysis_platform = "all"

        try:
            page = int(params.get("page") or "1")
        except ValueError:
            page = 1
        try:
            page_size = int(params.get("page_size") or "10")
        except ValueError:
            page_size = 10

        af = dict(
            selected_account_id=selected_account_id,
            selected_campaign_id=selected_campaign_id,
            selected_adset_id=selected_adset_id,
            campaign_name_q=campaign_name_q,
            adset_name_q=adset_name_q,
            creative_name_q=creative_name_q,
            analysis_status=analysis_status,
        )

        date_from_str = params.get("date_from")
        date_to_str = params.get("date_to")
        _def_from_c, _def_to_c = default_marketing_filter_date_range()
        try:
            date_from = datetime.strptime(date_from_str, "%Y-%m-%d") if date_from_str else _def_from_c
        except Exception:
            date_from = _def_from_c
        try:
            if date_to_str:
                date_to = datetime.strptime(date_to_str, "%Y-%m-%d").replace(
                    hour=23, minute=59, second=59, microsecond=999999
                )
            else:
                date_to = _def_to_c
        except Exception:
            date_to = _def_to_c

        copy_payload = _build_copy_marketing_analysis(
            db,
            date_from,
            date_to,
            af,
            analysis_platform=analysis_platform,
            copy_q=copy_q,
            page=page,
            page_size=page_size,
        )

        tp = int(copy_payload.get("ad_total_pages") or 1)
        cp = int(copy_payload.get("ad_page") or 1)
        copy_pagination = _copy_pagination_urls(request, tp, cp)

        return templates.TemplateResponse(
            request,
            "marketing_analysis_copy.html",
            {
                "request": request,
                "title": "Analisi copy",
                "user": user,
                "active_page": "marketing_analysis_copy",
                "date_from": date_from.strftime("%Y-%m-%d"),
                "date_to": date_to.strftime("%Y-%m-%d"),
                "selected_account_id": selected_account_id,
                "selected_campaign_id": selected_campaign_id,
                "selected_adset_id": selected_adset_id,
                "selected_campaign_name": campaign_name_q,
                "selected_adset_name": adset_name_q,
                "selected_creative_name": creative_name_q,
                "selected_copy_q": copy_q,
                "copy_payload": copy_payload,
                "copy_pagination": copy_pagination,
            },
        )
    except Exception as e:
        logger.error(f"Errore nel route /marketing/analysis-copy: {e}", exc_info=True)
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
    _def_from_l, _def_to_l = default_marketing_filter_date_range()
    try:
        date_from_obj = datetime.strptime(date_from_s, "%Y-%m-%d") if date_from_s else _def_from_l
    except ValueError:
        date_from_obj = _def_from_l
    try:
        if date_to_s:
            date_to_obj = datetime.strptime(date_to_s, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59, microsecond=999999
            )
        else:
            date_to_obj = _def_to_l
    except ValueError:
        date_to_obj = _def_to_l

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
