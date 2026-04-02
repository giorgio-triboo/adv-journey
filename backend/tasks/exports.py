"""Celery task per export CSV asincroni e invio email al richiedente."""
from __future__ import annotations

import csv
import logging
import os
import tempfile
from datetime import datetime, timedelta
from email.message import EmailMessage
from typing import Any

import smtplib
from sqlalchemy import and_, case, func

from celery_app import celery_app
from config import settings
from database import SessionLocal
from models import (
    Lead,
    MetaAccount,
    MetaAd,
    MetaAdSet,
    MetaCampaign,
    MetaMarketingData,
    MetaMarketingPlacement,
    MsgTrafficMapping,
    StatusCategory,
    TrafficPlatform,
)

logger = logging.getLogger("tasks.exports")


def _get_meta_conversions_for_ad_ids_by_key(db, ad_ids_by_key, date_from, date_to):
    """
    Per ogni chiave in ad_ids_by_key, ritorna la somma conversioni Meta per quei meta_ad_id.
    Duplicata localmente per evitare circular import con services.api.ui.dashboard.
    """
    date_from_d = date_from.date() if hasattr(date_from, "date") else date_from
    date_to_d = date_to.date() if hasattr(date_to, "date") else date_to
    clean = {k: {str(a) for a in (v or []) if a and str(a).strip()} for k, v in ad_ids_by_key.items()}
    all_ad_ids = set()
    for ad_id_set in clean.values():
        all_ad_ids.update(ad_id_set)
    if not all_ad_ids:
        return {k: 0 for k in ad_ids_by_key}
    rows = (
        db.query(MetaAd.ad_id, func.sum(MetaMarketingData.conversions).label("total"))
        .join(MetaMarketingData, MetaMarketingData.ad_id == MetaAd.id)
        .filter(
            MetaAd.ad_id.in_(list(all_ad_ids)),
            MetaMarketingData.date >= date_from_d,
            MetaMarketingData.date <= date_to_d,
        )
        .group_by(MetaAd.ad_id)
        .all()
    )
    ad_to_conv = {str(r.ad_id): int(r.total or 0) for r in rows}
    result = {}
    for key, ad_ids in clean.items():
        result[key] = sum(ad_to_conv.get(aid, 0) for aid in ad_ids)
    for key in ad_ids_by_key:
        if key not in result:
            result[key] = 0
    return result


def _get_platform_for_lead(lead, msg_to_platform, facebook_platform_to_slug):
    """
    Determina piattaforma lead con fallback su facebook_piattaforma.
    Duplicata localmente per evitare circular import con services.api.ui.dashboard.
    """
    if lead.msg_id and str(lead.msg_id) in msg_to_platform:
        return msg_to_platform[str(lead.msg_id)]
    if lead.facebook_piattaforma:
        slug = (lead.facebook_piattaforma or "").lower().strip()
        for key, value in facebook_platform_to_slug.items():
            if key in slug:
                return value
        if slug in ("facebook", "instagram", "messenger", "audience network"):
            return "meta"
    return "non_mappato"


def _lead_date_filter(date_from_obj, date_to_obj):
    """
    Filtra lead per data iscrizione Magellano.
    Duplicata localmente per evitare circular import con services.api.ui.marketing.
    """
    date_from_d = date_from_obj.date() if hasattr(date_from_obj, "date") else date_from_obj
    date_to_d = date_to_obj.date() if hasattr(date_to_obj, "date") else date_to_obj
    return and_(
        Lead.magellano_subscr_date.isnot(None),
        Lead.magellano_subscr_date >= date_from_d,
        Lead.magellano_subscr_date <= date_to_d,
    )


def _parse_amount(val) -> float:
    """
    Normalizza importi provenienti da MetaMarketingData in float.
    Duplicata localmente per evitare circular import con services.api.ui.marketing.
    """
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    try:
        from decimal import Decimal
        if isinstance(val, Decimal):
            return float(val)
    except ImportError:
        pass
    raw = str(val).strip()
    if not raw:
        return 0.0
    if "." in raw and "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    elif "," in raw:
        raw = raw.replace(",", ".")
    return float(raw)


def _fmt_decimal(value: Any, decimals: int = 2) -> str:
    if value is None:
        return ""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return ""
    return f"{numeric:.{decimals}f}".replace(".", ",")


def _safe(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _parse_date_range(
    filters: dict[str, Any], *, marketing_defaults: bool = False
) -> tuple[datetime, datetime]:
    date_from = filters.get("date_from")
    date_to = filters.get("date_to")
    if marketing_defaults:
        from services.api.ui.marketing.helpers import default_marketing_filter_date_range

        def_from, def_to = default_marketing_filter_date_range()
    else:
        def_from = datetime.now() - timedelta(days=30)
        def_to = datetime.now()
    try:
        from_obj = datetime.strptime(date_from, "%Y-%m-%d") if date_from else def_from
    except Exception:
        from_obj = def_from
    try:
        to_obj = datetime.strptime(date_to, "%Y-%m-%d") if date_to else def_to
    except Exception:
        to_obj = def_to
    return from_obj, to_obj


def _send_export_email_with_attachment(recipient: str, subject: str, body: str, file_path: str, filename: str) -> None:
    if not (settings.SMTP_HOST and settings.SMTP_USER and settings.SMTP_PASSWORD):
        raise RuntimeError("SMTP non configurato")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_FROM_EMAIL or settings.SMTP_USER
    msg["To"] = recipient
    msg.set_content(body)

    with open(file_path, "rb") as fp:
        msg.add_attachment(fp.read(), maintype="text", subtype="csv", filename=filename)

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT or 587) as server:
        if settings.SMTP_USE_TLS:
            server.starttls()
        server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.send_message(msg)


def _write_csv(path: str, headers: list[str], rows: list[dict[str, Any]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: _safe(v) for k, v in row.items()})


def _export_lavorazioni(db, subsection: str, filters: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]]]:
    date_from_obj, date_to_obj = _parse_date_range(filters)
    date_from_d = date_from_obj.date()
    date_to_d = date_to_obj.date()

    base_filters = [
        Lead.status_category.in_([
            StatusCategory.IN_LAVORAZIONE,
            StatusCategory.RIFIUTATO,
            StatusCategory.CRM,
            StatusCategory.FINALE,
        ]),
        Lead.magellano_subscr_date.isnot(None),
        Lead.magellano_subscr_date >= date_from_d,
        Lead.magellano_subscr_date <= date_to_d,
    ]
    status_category_filter = filters.get("status_category")
    campaign_id = filters.get("campaign_id")
    if status_category_filter:
        try:
            base_filters.append(Lead.status_category == StatusCategory(status_category_filter))
        except ValueError:
            pass
    if campaign_id:
        base_filters.append(Lead.magellano_campaign_id == campaign_id)

    if subsection == "utenti":
        headers = [
            "msg_id", "external_user_id", "brand", "campaign_name", "magellano_campaign_id",
            "ulixe_status", "magellano_status_raw", "current_status", "status_category", "last_check",
        ]
        leads = (
            db.query(Lead)
            .filter(*base_filters)
            .order_by(Lead.last_check.desc().nullslast(), Lead.created_at.desc())
            .all()
        )
        rows = []
        for lead in leads:
            rows.append({
                "msg_id": lead.msg_id or "",
                "external_user_id": lead.external_user_id or "",
                "brand": lead.brand or "",
                "campaign_name": lead.campaign_name or "",
                "magellano_campaign_id": lead.magellano_campaign_id or "",
                "ulixe_status": lead.ulixe_status or "",
                "magellano_status_raw": lead.magellano_status_raw or "",
                "current_status": lead.current_status or "",
                "status_category": lead.status_category.value if lead.status_category else "",
                "last_check": lead.last_check.isoformat(sep=" ") if lead.last_check else "",
            })
        return headers, rows

    if subsection == "canali":
        headers = [
            "channel", "lead_acquistate_meta", "entrate_magellano", "doppioni", "scarto_pct_ingresso",
            "scartate_firewall", "inviate", "scarto_pct_uscita", "in_lavorazione", "doppioni_ulixe", "approvate",
        ]
        mappings = db.query(MsgTrafficMapping).join(TrafficPlatform).filter(TrafficPlatform.is_active == True).all()
        msg_to_platform = {m.msg_id: m.traffic_platform.slug for m in mappings}
        platforms = db.query(TrafficPlatform).filter(TrafficPlatform.is_active == True).all()
        platform_by_slug = {p.slug: p for p in platforms}
        facebook_platform_to_slug = {"facebook": "meta", "instagram": "meta", "messenger": "meta", "audience network": "meta"}
        leads = db.query(Lead).filter(*base_filters).all()

        stats: dict[str, dict[str, int]] = {}
        ad_ids_by_plat: dict[str, set[str]] = {}
        for lead in leads:
            plat = _get_platform_for_lead(lead, msg_to_platform, facebook_platform_to_slug)
            stats.setdefault(plat, {
                "total": 0, "entrate_magellano": 0, "scartate_firewall": 0, "doppioni_ulixe": 0,
                "inviate": 0, "in_lavorazione": 0, "approvate": 0,
            })
            ad_ids_by_plat.setdefault(plat, set())
            stats[plat]["total"] += 1
            if lead.magellano_campaign_id and str(lead.magellano_campaign_id).strip():
                stats[plat]["entrate_magellano"] += 1
            if lead.magellano_campaign_id and lead.magellano_status not in ("magellano_sent", "magellano_refused"):
                stats[plat]["scartate_firewall"] += 1
            if lead.status_category == StatusCategory.RIFIUTATO:
                stats[plat]["doppioni_ulixe"] += 1
            if lead.magellano_status == "magellano_sent":
                stats[plat]["inviate"] += 1
            if lead.status_category == StatusCategory.IN_LAVORAZIONE:
                stats[plat]["in_lavorazione"] += 1
            if lead.status_category == StatusCategory.FINALE:
                stats[plat]["approvate"] += 1
            if lead.meta_ad_id:
                ad_ids_by_plat[plat].add(lead.meta_ad_id)

        meta_conv_by_plat = _get_meta_conversions_for_ad_ids_by_key(db, ad_ids_by_plat, date_from_obj, date_to_obj)
        rows = []
        for slug in sorted(stats.keys()):
            row = stats[slug]
            lead_acquistate_meta = int(meta_conv_by_plat.get(slug, 0) or 0)
            doppioni = max(0, lead_acquistate_meta - row["total"]) if lead_acquistate_meta else 0
            inviate = row["inviate"]
            scartate_fw = row["scartate_firewall"]
            scarto_in = (doppioni / lead_acquistate_meta * 100) if lead_acquistate_meta else 0
            uscita_totale = inviate + scartate_fw
            scarto_out = (scartate_fw / uscita_totale * 100) if uscita_totale else 0
            p = platform_by_slug.get(slug)
            channel_name = p.name if p else slug
            rows.append({
                "channel": channel_name,
                "lead_acquistate_meta": lead_acquistate_meta,
                "entrate_magellano": row["entrate_magellano"],
                "doppioni": doppioni,
                "scarto_pct_ingresso": _fmt_decimal(scarto_in, 2),
                "scartate_firewall": scartate_fw,
                "inviate": inviate,
                "scarto_pct_uscita": _fmt_decimal(scarto_out, 2),
                "in_lavorazione": row["in_lavorazione"],
                "doppioni_ulixe": row["doppioni_ulixe"],
                "approvate": row["approvate"],
            })
        return headers, rows

    # subsection default: ulixe
    headers = [
        "msg_id", "brand", "campaign_name", "lead_acquistate_meta", "entrate_magellano", "doppioni",
        "scarto_pct_ingresso", "scartate_firewall", "inviate", "scarto_pct_uscita",
        "in_lavorazione", "doppioni_ulixe", "approvate", "last_check",
    ]
    has_mag = and_(Lead.magellano_campaign_id.isnot(None), Lead.magellano_campaign_id != "")
    not_sent_refused = (~Lead.magellano_status.in_(["magellano_sent", "magellano_refused"]))
    aggregates = (
        db.query(
            Lead.msg_id,
            func.count(Lead.id).label("total_leads"),
            func.sum(case((and_(Lead.magellano_campaign_id.isnot(None), Lead.magellano_campaign_id != ""), 1), else_=0)).label("entrate_magellano"),
            func.sum(case((and_(has_mag, not_sent_refused), 1), else_=0)).label("scartate_firewall"),
            func.sum(case((Lead.status_category == StatusCategory.RIFIUTATO, 1), else_=0)).label("doppioni_ulixe"),
            func.sum(case((Lead.magellano_status == "magellano_sent", 1), else_=0)).label("inviate"),
            func.sum(case((Lead.status_category == StatusCategory.IN_LAVORAZIONE, 1), else_=0)).label("in_lavorazione"),
            func.sum(case((Lead.status_category == StatusCategory.FINALE, 1), else_=0)).label("approvate"),
            func.max(Lead.last_check).label("last_check"),
            func.max(Lead.brand).label("brand"),
            func.max(Lead.campaign_name).label("campaign_name"),
        )
        .filter(*base_filters)
        .filter(Lead.msg_id.isnot(None), Lead.msg_id != "", Lead.current_status.isnot(None))
        .group_by(Lead.msg_id)
        .order_by(func.count(Lead.id).desc())
        .all()
    )
    ad_ids_by_msg: dict[str, set[str]] = {}
    msg_rows = (
        db.query(Lead.msg_id, Lead.meta_ad_id)
        .filter(*base_filters)
        .filter(Lead.msg_id.isnot(None), Lead.msg_id != "", Lead.meta_ad_id.isnot(None), Lead.meta_ad_id != "")
        .distinct()
        .all()
    )
    for msg_id, meta_ad_id in msg_rows:
        ad_ids_by_msg.setdefault(msg_id, set()).add(meta_ad_id)
    meta_conv_by_msg = _get_meta_conversions_for_ad_ids_by_key(db, ad_ids_by_msg, date_from_obj, date_to_obj)

    rows = []
    for agg in aggregates:
        lead_acquistate_meta = int(meta_conv_by_msg.get(agg.msg_id, 0) or 0)
        total = int(agg.total_leads or 0)
        doppioni = max(0, lead_acquistate_meta - total) if lead_acquistate_meta else 0
        inviate = int(agg.inviate or 0)
        scartate_fw = int(agg.scartate_firewall or 0)
        rows.append({
            "msg_id": agg.msg_id or "",
            "brand": agg.brand or "",
            "campaign_name": agg.campaign_name or "",
            "lead_acquistate_meta": lead_acquistate_meta,
            "entrate_magellano": int(agg.entrate_magellano or 0),
            "doppioni": doppioni,
            "scarto_pct_ingresso": _fmt_decimal((doppioni / lead_acquistate_meta * 100) if lead_acquistate_meta else 0, 2),
            "scartate_firewall": scartate_fw,
            "inviate": inviate,
            "scarto_pct_uscita": _fmt_decimal((scartate_fw / (inviate + scartate_fw) * 100) if (inviate + scartate_fw) else 0, 2),
            "in_lavorazione": int(agg.in_lavorazione or 0),
            "doppioni_ulixe": int(agg.doppioni_ulixe or 0),
            "approvate": int(agg.approvate or 0),
            "last_check": agg.last_check.isoformat(sep=" ") if agg.last_check else "",
        })
    return headers, rows


def _export_marketing(db, filters: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]], str]:
    date_from_obj, date_to_obj = _parse_date_range(filters, marketing_defaults=True)
    # Requisito utente: per Marketing usare SOLO il filtro data.
    # Export sempre completo su 3 livelli: campagna, adset, ad.
    campaigns_query = db.query(MetaCampaign).join(MetaAccount).filter(MetaAccount.is_active == True)

    rows: list[dict[str, Any]] = []
    headers = [
        "Livello",
        "Account",
        "Campagna",
        "AdSet",
        "Ad",
        "Stato",
        "Lead",
        "CPL Meta",
        "Speso",
        "Entrate Magellano",
        "CPL Ingresso",
        "Scartate Ingresso",
        "% Scarto Ingresso",
        "Inviate Magellano",
        "CPL Uscita",
        "Rifiutate Uscita",
        "% Scarto Uscita",
        "Margine",
        "Scarto Totale",
        "Lavorazione Ulixe",
        "Rifiutate Ulixe",
        "Approvate Ulixe",
    ]

    campaigns = campaigns_query.all()

    def _append_row(
        level_label: str,
        campaign: MetaCampaign,
        adset: MetaAdSet | None,
        ad: MetaAd | None,
        leads: list[Lead],
        marketing_data: list[MetaMarketingData],
    ) -> None:
        spend = sum(_parse_amount(md.spend) for md in marketing_data)
        conversions = int(sum(md.conversions or 0 for md in marketing_data))
        total_leads = conversions
        if total_leads == 0 and spend == 0:
            return

        mag_entrate = len([l for l in leads if l.magellano_campaign_id])
        mag_scartate = total_leads - mag_entrate
        mag_inviate = len([l for l in leads if l.magellano_status == "magellano_sent"])
        mag_rifiutate = len([l for l in leads if l.magellano_status in ["magellano_firewall", "magellano_refused"]])
        ul_lavorazione = len([l for l in leads if l.status_category == StatusCategory.IN_LAVORAZIONE])
        ul_rifiutate = len([l for l in leads if l.status_category == StatusCategory.RIFIUTATO])
        ul_approvate = len([l for l in leads if l.status_category == StatusCategory.FINALE])
        cpl_meta = (spend / total_leads) if total_leads > 0 else 0
        cpl_ingresso = (spend / mag_entrate) if mag_entrate > 0 else 0
        cpl_uscita = (spend / mag_inviate) if mag_inviate > 0 else 0
        scarto_in = (mag_scartate / total_leads * 100) if total_leads > 0 else 0
        uscita_totale = mag_inviate + mag_rifiutate
        scarto_out = (mag_rifiutate / uscita_totale * 100) if uscita_totale > 0 else 0
        scarto_tot = ((total_leads - mag_inviate) / total_leads * 100) if total_leads > 0 else 0

        rows.append({
            "Livello": level_label,
            "Account": campaign.account.name if campaign.account else "",
            "Campagna": campaign.name or "",
            "AdSet": adset.name if adset else "",
            "Ad": ad.name if ad else "",
            "Stato": (ad.status if ad else (adset.status if adset else campaign.status)) or "",
            "Lead": total_leads,
            "CPL Meta": _fmt_decimal(cpl_meta, 2),
            "Speso": _fmt_decimal(spend, 2),
            "Entrate Magellano": mag_entrate,
            "CPL Ingresso": _fmt_decimal(cpl_ingresso, 2),
            "Scartate Ingresso": mag_scartate,
            "% Scarto Ingresso": _fmt_decimal(scarto_in, 2),
            "Inviate Magellano": mag_inviate,
            "CPL Uscita": _fmt_decimal(cpl_uscita, 2),
            "Rifiutate Uscita": mag_rifiutate,
            "% Scarto Uscita": _fmt_decimal(scarto_out, 2),
            "Margine": "N/D",
            "Scarto Totale": _fmt_decimal(scarto_tot, 2),
            "Lavorazione Ulixe": ul_lavorazione,
            "Rifiutate Ulixe": ul_rifiutate,
            "Approvate Ulixe": ul_approvate,
        })

    for campaign in campaigns:
        # Campagna (sempre)
        lead_query = db.query(Lead).filter(
            Lead.meta_campaign_id == campaign.campaign_id,
            _lead_date_filter(date_from_obj, date_to_obj),
        )
        marketing_query = (
            db.query(MetaMarketingData)
            .join(MetaAd)
            .join(MetaAdSet)
            .filter(
                MetaAdSet.campaign_id == campaign.id,
                MetaMarketingData.date >= date_from_obj,
                MetaMarketingData.date <= date_to_obj,
            )
        )
        _append_row("Campagna", campaign, None, None, lead_query.all(), marketing_query.all())

        # AdSet (sempre)
        adsets = db.query(MetaAdSet).filter(MetaAdSet.campaign_id == campaign.id).all()
        if not adsets:
            continue

        for adset in adsets:
            lead_query = db.query(Lead).filter(
                Lead.meta_adset_id == adset.adset_id,
                _lead_date_filter(date_from_obj, date_to_obj),
            )
            marketing_query = (
                db.query(MetaMarketingData)
                .join(MetaAd)
                .filter(
                    MetaAd.adset_id == adset.id,
                    MetaMarketingData.date >= date_from_obj,
                    MetaMarketingData.date <= date_to_obj,
                )
            )
            _append_row("AdSet", campaign, adset, None, lead_query.all(), marketing_query.all())

            # Ad (sempre)
            ads = db.query(MetaAd).filter(MetaAd.adset_id == adset.id).all()
            if not ads:
                continue
            for ad in ads:
                lead_query = db.query(Lead).filter(
                    Lead.meta_ad_id == ad.ad_id,
                    _lead_date_filter(date_from_obj, date_to_obj),
                )
                marketing_query = db.query(MetaMarketingData).filter(
                    MetaMarketingData.ad_id == ad.id,
                    MetaMarketingData.date >= date_from_obj,
                    MetaMarketingData.date <= date_to_obj,
                )
                _append_row("Ad", campaign, adset, ad, lead_query.all(), marketing_query.all())

    return headers, rows, "full"


def _export_marketing_analysis_placement(db, filters: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]]]:
    """
    Export righe giornaliere da meta_marketing_placement (breakdown publisher_platform + platform_position),
    con gli stessi filtri della pagina /marketing/analysis (account / campagna / adset / periodo).
    """
    date_from_obj, date_to_obj = _parse_date_range(filters, marketing_defaults=True)

    q = (
        db.query(
            MetaMarketingPlacement,
            MetaAd,
            MetaAdSet,
            MetaCampaign,
            MetaAccount,
        )
        .join(MetaAd, MetaMarketingPlacement.ad_id == MetaAd.id)
        .join(MetaAdSet, MetaAd.adset_id == MetaAdSet.id)
        .join(MetaCampaign, MetaAdSet.campaign_id == MetaCampaign.id)
        .join(MetaAccount, MetaCampaign.account_id == MetaAccount.id)
        .filter(
            MetaAccount.is_active == True,
            MetaMarketingPlacement.date >= date_from_obj,
            MetaMarketingPlacement.date <= date_to_obj,
        )
    )

    account_id = (filters.get("account_id") or "").strip()
    if account_id:
        q = q.filter(MetaAccount.account_id == account_id)

    campaign_name = (filters.get("campaign_name") or "").strip()
    campaign_id = (filters.get("campaign_id") or "").strip()
    if campaign_name:
        q = q.filter(MetaCampaign.name.ilike(f"%{campaign_name}%"))
    elif campaign_id:
        q = q.filter(MetaCampaign.campaign_id == campaign_id)

    adset_name = (filters.get("adset_name") or "").strip()
    adset_raw = filters.get("adset_id") or ""
    if adset_name:
        q = q.filter(MetaAdSet.name.ilike(f"%{adset_name}%"))
    elif adset_raw:
        try:
            adset_pk = int(str(adset_raw).strip())
            q = q.filter(MetaAdSet.id == adset_pk)
        except ValueError:
            pass

    creative_name = (filters.get("creative_name") or "").strip()
    if creative_name:
        q = q.filter(MetaAd.name.ilike(f"%{creative_name}%"))

    status_f = (filters.get("status") or "all").strip().lower()
    if status_f == "active":
        q = q.filter(MetaCampaign.status == "ACTIVE")
    elif status_f == "inactive":
        q = q.filter(MetaCampaign.status != "ACTIVE")

    platform_f = (filters.get("platform") or "all").strip().lower()
    if platform_f in ("facebook", "instagram"):
        q = q.filter(
            func.lower(func.coalesce(MetaMarketingPlacement.publisher_platform, "")) == platform_f
        )

    q = q.order_by(
        MetaMarketingPlacement.date,
        MetaAccount.name,
        MetaCampaign.name,
        MetaAdSet.name,
        MetaAd.name,
        MetaMarketingPlacement.publisher_platform,
        MetaMarketingPlacement.platform_position,
    )

    headers = [
        "Data",
        "Account Meta ID",
        "Account",
        "Campagna ID",
        "Campagna",
        "AdSet Meta ID",
        "AdSet",
        "Ad Meta ID",
        "Ad",
        "Publisher platform",
        "Posizione",
        "Speso",
        "Impression",
        "Click",
        "Lead Meta",
        "CPL giorno",
        "CTR",
        "CPC",
        "CPM",
        "CPA",
    ]

    rows: list[dict[str, Any]] = []
    for mp, ad, adset, campaign, account in q.all():
        d = mp.date
        date_str = d.strftime("%Y-%m-%d") if d else ""
        spend = _parse_amount(mp.spend)
        conv = int(mp.conversions or 0)
        cpl = (spend / conv) if conv > 0 else 0.0
        rows.append({
            "Data": date_str,
            "Account Meta ID": account.account_id or "",
            "Account": account.name or "",
            "Campagna ID": campaign.campaign_id or "",
            "Campagna": campaign.name or "",
            "AdSet Meta ID": adset.adset_id or "",
            "AdSet": adset.name or "",
            "Ad Meta ID": ad.ad_id or "",
            "Ad": ad.name or "",
            "Publisher platform": mp.publisher_platform or "",
            "Posizione": mp.platform_position or "",
            "Speso": _fmt_decimal(spend, 2),
            "Impression": str(int(mp.impressions or 0)),
            "Click": str(int(mp.clicks or 0)),
            "Lead Meta": str(conv),
            "CPL giorno": _fmt_decimal(cpl, 2),
            "CTR": _fmt_decimal(_parse_amount(mp.ctr), 4),
            "CPC": _fmt_decimal(_parse_amount(mp.cpc), 4),
            "CPM": _fmt_decimal(_parse_amount(mp.cpm), 4),
            "CPA": _fmt_decimal(_parse_amount(mp.cpa), 4),
        })

    return headers, rows


@celery_app.task(name="tasks.exports.generate_and_email_csv")
def generate_and_email_csv_task(export_type: str, requester_email: str, filters: dict[str, Any], subsection: str = ""):
    """Genera il CSV in background e lo invia via mail al richiedente."""
    db = SessionLocal()
    temp_file = None
    try:
        if export_type == "lavorazioni":
            headers, rows = _export_lavorazioni(db, subsection or "ulixe", filters)
            filename = f"lavorazioni_{subsection or 'ulixe'}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            subject = f"Export Lavorazioni ({subsection or 'ulixe'}) pronto"
            body = f"In allegato trovi il CSV richiesto per Lavorazioni ({subsection or 'ulixe'})."
        elif export_type == "marketing":
            headers, rows, mode = _export_marketing(db, filters)
            filename = f"marketing_{mode}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            subject = f"Export Marketing ({mode}) pronto"
            body = f"In allegato trovi il CSV richiesto per Marketing ({mode})."
        elif export_type == "marketing_analysis_placement":
            headers, rows = _export_marketing_analysis_placement(db, filters)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"marketing_analysis_breakdown_{ts}.csv"
            subject = "Export Marketing Analysis (breakdown placement) pronto"
            body = (
                "In allegato il CSV con le righe giornaliere da meta_marketing_placement "
                "(publisher_platform, platform_position), filtrate come in Marketing Analysis."
            )
        else:
            raise ValueError(f"Tipo export non supportato: {export_type}")

        fd, temp_file = tempfile.mkstemp(prefix="export_", suffix=".csv")
        os.close(fd)
        _write_csv(temp_file, headers, rows)
        _send_export_email_with_attachment(requester_email, subject, body, temp_file, filename)
        logger.info("Export %s completato e inviato a %s (rows=%s)", export_type, requester_email, len(rows))
        return {"ok": True, "rows": len(rows), "filename": filename}
    except Exception as exc:
        logger.error("Errore export %s per %s: %s", export_type, requester_email, exc, exc_info=True)
        raise
    finally:
        db.close()
        if temp_file and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except OSError:
                pass
