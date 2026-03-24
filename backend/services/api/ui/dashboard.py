"""Dashboard e Lavorazioni views"""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session, load_only
from sqlalchemy import func, case, and_, or_
from database import get_db
from models import Lead, StatusCategory, TrafficPlatform, MsgTrafficMapping, ManagedCampaign, MetaAd, MetaMarketingData
from datetime import datetime, timedelta
from collections import defaultdict
from .common import templates

router = APIRouter(include_in_schema=False)


def _get_meta_conversions_for_ad_ids_by_key(db, ad_ids_by_key, date_from, date_to):
    """
    Per ogni chiave in ad_ids_by_key, ritorna la somma delle conversioni Meta per quegli ad.
    ad_ids_by_key: dict chiave -> set/list di meta_ad_id (Lead.meta_ad_id)
    """
    date_from_d = date_from.date() if hasattr(date_from, "date") else date_from
    date_to_d = date_to.date() if hasattr(date_to, "date") else date_to
    clean = {k: {str(a) for a in (v or []) if a and str(a).strip()} for k, v in ad_ids_by_key.items()}
    all_ad_ids = set()
    for s in clean.values():
        all_ad_ids.update(s)
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


def _lavorazioni_filters(request, db):
    """Helper: estrae filtri e oggetti date per lavorazioni"""
    status_category_filter = request.query_params.get('status_category')
    date_from = request.query_params.get('date_from')
    date_to = request.query_params.get('date_to')
    campaign_id = request.query_params.get('campaign_id')

    date_from_obj = None
    date_to_obj = None
    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d')
        except Exception:
            pass
    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d')
        except Exception:
            pass
    if not date_from_obj:
        date_from_obj = datetime.now() - timedelta(days=30)
    if not date_to_obj:
        date_to_obj = datetime.now()

    date_from_d = date_from_obj.date() if hasattr(date_from_obj, "date") else date_from_obj
    date_to_d = date_to_obj.date() if hasattr(date_to_obj, "date") else date_to_obj

    # Usa magellano_subscr_date (data iscrizione Magellano) come in marketing/analysis
    base_filters = [
        Lead.status_category.in_([
            StatusCategory.IN_LAVORAZIONE,
            StatusCategory.RIFIUTATO,
            StatusCategory.CRM,
            StatusCategory.FINALE
        ]),
        Lead.magellano_subscr_date.isnot(None),
        Lead.magellano_subscr_date >= date_from_d,
        Lead.magellano_subscr_date <= date_to_d,
    ]
    if status_category_filter:
        try:
            status_cat = StatusCategory(status_category_filter)
            base_filters.append(Lead.status_category == status_cat)
        except ValueError:
            pass
    if campaign_id:
        base_filters.append(Lead.magellano_campaign_id == campaign_id)

    return {
        'base_filters': base_filters,
        'date_from_obj': date_from_obj,
        'date_to_obj': date_to_obj,
        'date_from': date_from or date_from_obj.strftime('%Y-%m-%d'),
        'date_to': date_to or date_to_obj.strftime('%Y-%m-%d'),
        'status_category_filter': status_category_filter,
        'campaign_id': campaign_id,
    }


def _lavorazioni_common(request, db, filters):
    """Dati comuni per le viste lavorazioni - 1 query invece di 5 per stats"""
    base_filters = filters['base_filters']
    base_q = db.query(Lead).filter(*base_filters)
    row = base_q.with_entities(
        func.count(Lead.id).label('total'),
        func.sum(case((Lead.status_category == StatusCategory.IN_LAVORAZIONE, 1), else_=0)).label('in_lavorazione'),
        func.sum(case((Lead.status_category == StatusCategory.RIFIUTATO, 1), else_=0)).label('rifiutati'),
        func.sum(case((Lead.status_category == StatusCategory.CRM, 1), else_=0)).label('crm'),
        func.sum(case((Lead.status_category == StatusCategory.FINALE, 1), else_=0)).label('finale'),
    ).first()
    stats = {
        'total': row.total or 0,
        'in_lavorazione': row.in_lavorazione or 0,
        'rifiutati': row.rifiutati or 0,
        'crm': row.crm or 0,
        'finale': row.finale or 0,
    }
    stats['conversion_rate'] = (stats['finale'] / stats['total'] * 100) if stats['total'] > 0 else 0

    lavorazioni_base_query = db.query(Lead).filter(*base_filters).filter(
        Lead.msg_id.isnot(None),
        Lead.msg_id != '',
        Lead.current_status.isnot(None)
    )

    campaigns = db.query(ManagedCampaign).filter(ManagedCampaign.is_active == True).all()
    status_categories = [
        {"value": "in_lavorazione", "label": "In Lavorazione"},
        {"value": "rifiutato", "label": "Rifiutato"},
        {"value": "crm", "label": "CRM"},
        {"value": "finale", "label": "Finale"}
    ]

    return {
        'stats': stats,
        'lavorazioni_base_query': lavorazioni_base_query,
        'campaigns': campaigns,
        'status_categories': status_categories,
    }


@router.get("/dashboard")
async def dashboard(request: Request, db: Session = Depends(get_db)):
    user = request.session.get('user')
    if not user:
        return RedirectResponse(url='/')

    row = db.query(Lead).with_entities(
        func.count(Lead.id).label('total'),
        func.sum(case((Lead.status_category == StatusCategory.IN_LAVORAZIONE, 1), else_=0)).label('in_processing'),
        func.sum(case((Lead.status_category == StatusCategory.FINALE, 1), else_=0)).label('converted'),
    ).first()
    stats = {
        "total_leads": row.total or 0,
        "in_processing": row.in_processing or 0,
        "converted": row.converted or 0,
    }

    managed_campaigns = db.query(ManagedCampaign).filter(ManagedCampaign.is_active == True).all()

    return templates.TemplateResponse(request, "dashboard.html", {
        "request": request,
        "title": "Dashboard",
        "user": user,
        "stats": stats,
        "managed_campaigns": managed_campaigns,
        "active_page": "dashboard"
    })


@router.get("/lavorazioni")
async def lavorazioni_redirect(request: Request):
    """Redirect alla prima tab lavorazioni"""
    return RedirectResponse(url='/lavorazioni/ulixe')


@router.get("/lavorazioni/ulixe")
async def lavorazioni_ulixe(request: Request, db: Session = Depends(get_db)):
    """Tab Ulixe: Lavorazioni per ID Messaggio (Aggregato)"""
    user = request.session.get('user')
    if not user:
        return RedirectResponse(url='/')

    filters = _lavorazioni_filters(request, db)
    common = _lavorazioni_common(request, db, filters)

    # Scartate Firewall: entrate Magellano ma non inviate e non refused (firewall, waiting, ecc.)
    _has_mag = and_(Lead.magellano_campaign_id.isnot(None), Lead.magellano_campaign_id != '')
    _not_sent_refused = or_(
        Lead.magellano_status.is_(None),
        ~Lead.magellano_status.in_(['magellano_sent', 'magellano_refused']),
    )
    msg_id_aggregates = db.query(
        Lead.msg_id,
        func.count(Lead.id).label('total_leads'),
        func.sum(case((and_(Lead.magellano_campaign_id.isnot(None), Lead.magellano_campaign_id != ''), 1), else_=0)).label('entrate_magellano'),
        func.sum(case((and_(_has_mag, _not_sent_refused), 1), else_=0)).label('scartate_firewall'),
        func.sum(case((Lead.status_category == StatusCategory.RIFIUTATO, 1), else_=0)).label('doppioni_ulixe'),
        func.sum(case((Lead.magellano_status == 'magellano_sent', 1), else_=0)).label('inviate'),
        func.sum(case((Lead.status_category == StatusCategory.IN_LAVORAZIONE, 1), else_=0)).label('in_lavorazione'),
        func.sum(case((Lead.status_category == StatusCategory.FINALE, 1), else_=0)).label('approvate'),
        func.max(Lead.last_check).label('last_check'),
        func.max(Lead.brand).label('brand'),
        func.max(Lead.campaign_name).label('campaign_name')
    ).filter(*filters['base_filters']).filter(
        Lead.msg_id.isnot(None),
        Lead.msg_id != '',
        Lead.current_status.isnot(None)
    ).group_by(Lead.msg_id).order_by(func.count(Lead.id).desc()).all()

    # Meta conversioni per msg_id (per colonna "Lead Acquistate Meta")
    ad_ids_by_msg = defaultdict(set)
    for row in db.query(Lead.msg_id, Lead.meta_ad_id).filter(*filters['base_filters']).filter(
        Lead.msg_id.isnot(None), Lead.msg_id != '', Lead.meta_ad_id.isnot(None), Lead.meta_ad_id != ''
    ).distinct().all():
        if row.msg_id and row.meta_ad_id:
            ad_ids_by_msg[row.msg_id].add(row.meta_ad_id)
    meta_conv_by_msg = _get_meta_conversions_for_ad_ids_by_key(
        db, ad_ids_by_msg, filters['date_from_obj'], filters['date_to_obj']
    )

    lavorazioni_aggregate = []
    for agg in msg_id_aggregates:
        total = agg.total_leads or 0
        entrate = agg.entrate_magellano or 0
        lead_acquistate_meta = meta_conv_by_msg.get(agg.msg_id, 0)
        doppioni = max(0, lead_acquistate_meta - total) if lead_acquistate_meta else 0
        inviate = agg.inviate or 0
        scartate_fw = agg.scartate_firewall or 0
        doppioni_ulixe = agg.doppioni_ulixe or 0
        in_lavorazione = agg.in_lavorazione or 0
        approvate = agg.approvate or 0
        # % Scarto Ingresso: doppioni / lead_acquistate_meta
        scarto_pct_ingresso = round((doppioni / lead_acquistate_meta * 100), 1) if lead_acquistate_meta else 0
        # % Scarto Uscita: scartate_firewall / inviate
        scarto_pct_uscita = round((scartate_fw / inviate * 100), 1) if inviate else 0
        lavorazioni_aggregate.append({
            'msg_id': agg.msg_id,
            'lead_acquistate_meta': lead_acquistate_meta,
            'entrate_magellano': entrate,
            'doppioni': doppioni,
            'scarto_pct_ingresso': scarto_pct_ingresso,
            'scartate_firewall': scartate_fw,
            'inviate': inviate,
            'scarto_pct_uscita': scarto_pct_uscita,
            'in_lavorazione': in_lavorazione,
            'doppioni_ulixe': doppioni_ulixe,
            'approvate': approvate,
            'last_check': agg.last_check,
            'brand': agg.brand,
            'campaign_name': agg.campaign_name
        })

    return templates.TemplateResponse(request, "lavorazioni_ulixe.html", {
        "request": request,
        "title": "Lavorazioni - Ulixe",
        "user": user,
        "stats": common['stats'],
        "lavorazioni_aggregate": lavorazioni_aggregate,
        "campaigns": common['campaigns'],
        "status_categories": common['status_categories'],
        "selected_status_category": filters['status_category_filter'],
        "selected_campaign_id": filters['campaign_id'],
        "date_from": filters['date_from'],
        "date_to": filters['date_to'],
        "active_page": "lavorazioni_ulixe"
    })


@router.get("/lavorazioni/utenti")
async def lavorazioni_utenti(request: Request, db: Session = Depends(get_db)):
    """Tab Utenti: Dettaglio Singole Lead"""
    user = request.session.get('user')
    if not user:
        return RedirectResponse(url='/')

    filters = _lavorazioni_filters(request, db)
    common = _lavorazioni_common(request, db, filters)

    lavorazioni_leads = common['lavorazioni_base_query'].order_by(
        Lead.last_check.desc().nullslast(),
        Lead.created_at.desc()
    ).limit(1000).all()

    return templates.TemplateResponse(request, "lavorazioni_utenti.html", {
        "request": request,
        "title": "Lavorazioni - Utenti",
        "user": user,
        "stats": common['stats'],
        "lavorazioni_leads": lavorazioni_leads,
        "campaigns": common['campaigns'],
        "status_categories": common['status_categories'],
        "selected_status_category": filters['status_category_filter'],
        "selected_campaign_id": filters['campaign_id'],
        "date_from": filters['date_from'],
        "date_to": filters['date_to'],
        "active_page": "lavorazioni_utenti"
    })


def _get_platform_for_lead(lead, msg_to_platform, facebook_platform_to_slug):
    """Determina piattaforma per una lead: mapping msg_id > facebook_piattaforma > Non mappato"""
    if lead.msg_id and str(lead.msg_id) in msg_to_platform:
        return msg_to_platform[str(lead.msg_id)]
    if lead.facebook_piattaforma:
        slug = (lead.facebook_piattaforma or '').lower().strip()
        for k, v in facebook_platform_to_slug.items():
            if k in slug:
                return v
        if slug in ('facebook', 'instagram', 'messenger', 'audience network'):
            return 'meta'
    return 'non_mappato'


@router.get("/lavorazioni/canali")
async def lavorazioni_canali(request: Request, db: Session = Depends(get_db)):
    """Tab Canali: Riepilogo per fonti di traffico"""
    user = request.session.get('user')
    if not user:
        return RedirectResponse(url='/')

    filters = _lavorazioni_filters(request, db)
    common = _lavorazioni_common(request, db, filters)

    # Mapping msg_id -> slug piattaforma
    mappings = db.query(MsgTrafficMapping).join(TrafficPlatform).filter(
        TrafficPlatform.is_active == True
    ).all()
    msg_to_platform = {m.msg_id: m.traffic_platform.slug for m in mappings}

    # Fallback: facebook_piattaforma -> slug (Facebook/Instagram -> meta)
    platforms = db.query(TrafficPlatform).filter(TrafficPlatform.is_active == True).order_by(
        TrafficPlatform.display_order.asc(),
        TrafficPlatform.name.asc()
    ).all()
    platform_by_slug = {p.slug: p for p in platforms}
    facebook_platform_to_slug = {
        'facebook': 'meta', 'instagram': 'meta', 'messenger': 'meta', 'audience network': 'meta'
    }

    # Solo colonne necessarie per aggregazione (evita caricare 20+ colonne)
    leads = (
        common['lavorazioni_base_query']
        .options(load_only(
            Lead.msg_id, Lead.magellano_campaign_id, Lead.magellano_status,
            Lead.status_category, Lead.meta_ad_id, Lead.facebook_piattaforma
        ))
        .all()
    )

    # Aggregazione per piattaforma (slug) - colonne come marketing/analysis
    platform_stats = {}
    ad_ids_by_plat = defaultdict(set)
    for lead in leads:
        plat = _get_platform_for_lead(lead, msg_to_platform, facebook_platform_to_slug)
        if plat not in platform_stats:
            platform_stats[plat] = {
                'total': 0, 'entrate_magellano': 0, 'scartate_firewall': 0, 'doppioni_ulixe': 0,
                'inviate': 0, 'in_lavorazione': 0, 'approvate': 0
            }
        platform_stats[plat]['total'] += 1
        if lead.magellano_campaign_id and str(lead.magellano_campaign_id).strip():
            platform_stats[plat]['entrate_magellano'] += 1
        # Scartate Firewall: entrate Magellano, non inviate e non refused
        if lead.magellano_campaign_id and lead.magellano_status not in ('magellano_sent', 'magellano_refused'):
            platform_stats[plat]['scartate_firewall'] += 1
        if lead.status_category == StatusCategory.RIFIUTATO:
            platform_stats[plat]['doppioni_ulixe'] += 1
        if lead.magellano_status == 'magellano_sent':
            platform_stats[plat]['inviate'] += 1
        if lead.status_category == StatusCategory.IN_LAVORAZIONE:
            platform_stats[plat]['in_lavorazione'] += 1
        if lead.status_category == StatusCategory.FINALE:
            platform_stats[plat]['approvate'] += 1
        if lead.meta_ad_id and str(lead.meta_ad_id).strip():
            ad_ids_by_plat[plat].add(lead.meta_ad_id)

    meta_conv_by_plat = _get_meta_conversions_for_ad_ids_by_key(
        db, ad_ids_by_plat, filters['date_from_obj'], filters['date_to_obj']
    )

    # Build canali data - colonne come marketing/analysis
    canali_data = []
    for slug in sorted(platform_stats.keys()):
        stats = platform_stats[slug]
        total = stats['total']
        lead_acquistate_meta = meta_conv_by_plat.get(slug, 0)
        doppioni = max(0, lead_acquistate_meta - total) if lead_acquistate_meta else 0

        p = platform_by_slug.get(slug)
        name = p.name if p else (slug.replace('_', ' ').title() if slug != 'non_mappato' else 'Non mappato')
        inviate = stats['inviate']
        scartate_fw = stats['scartate_firewall']
        scarto_pct_ingresso = round((doppioni / lead_acquistate_meta * 100), 1) if lead_acquistate_meta else 0
        scarto_pct_uscita = round((scartate_fw / inviate * 100), 1) if inviate else 0
        canali_data.append({
            'slug': slug,
            'name': name,
            'lead_acquistate_meta': lead_acquistate_meta,
            'entrate_magellano': stats['entrate_magellano'],
            'doppioni': doppioni,
            'scarto_pct_ingresso': scarto_pct_ingresso,
            'scartate_firewall': scartate_fw,
            'inviate': inviate,
            'scarto_pct_uscita': scarto_pct_uscita,
            'in_lavorazione': stats['in_lavorazione'],
            'doppioni_ulixe': stats['doppioni_ulixe'],
            'approvate': stats['approvate'],
        })

    return templates.TemplateResponse(request, "lavorazioni_canali.html", {
        "request": request,
        "title": "Lavorazioni - Canali",
        "user": user,
        "stats": common['stats'],
        "canali_data": canali_data,
        "campaigns": common['campaigns'],
        "status_categories": common['status_categories'],
        "selected_status_category": filters['status_category_filter'],
        "selected_campaign_id": filters['campaign_id'],
        "date_from": filters['date_from'],
        "date_to": filters['date_to'],
        "active_page": "lavorazioni_canali"
    })
