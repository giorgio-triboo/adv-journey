"""Dashboard e Lavorazioni views"""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, case
from database import get_db
from models import Lead, StatusCategory
from datetime import datetime, timedelta
from .common import templates

router = APIRouter(include_in_schema=False)

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

    from models import ManagedCampaign
    managed_campaigns = db.query(ManagedCampaign).filter(ManagedCampaign.is_active == True).all()

    return templates.TemplateResponse("dashboard.html", {
        "request": request, 
        "title": "Dashboard",
        "user": user,
        "stats": stats,
        "managed_campaigns": managed_campaigns,
        "active_page": "dashboard"
    })

@router.get("/lavorazioni")
async def lavorazioni(request: Request, db: Session = Depends(get_db)):
    """Maschera Lavorazioni - Vista dedicata per dati sulle lavorazioni (stati Ulixe)"""
    user = request.session.get('user')
    if not user:
        return RedirectResponse(url='/')
    
    from models import ManagedCampaign
    
    # Get filter parameters
    status_category_filter = request.query_params.get('status_category')
    date_from = request.query_params.get('date_from')
    date_to = request.query_params.get('date_to')
    campaign_id = request.query_params.get('campaign_id')
    
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
    
    # Base query filters: solo lead con stati lavorazione (escludi UNKNOWN se non esplicitamente richiesto)
    base_filters = [
        Lead.status_category.in_([
            StatusCategory.IN_LAVORAZIONE,
            StatusCategory.RIFIUTATO,
            StatusCategory.CRM,
            StatusCategory.FINALE
        ]),
        Lead.created_at >= date_from_obj,
        Lead.created_at <= date_to_obj
    ]
    
    # Apply status filter
    if status_category_filter:
        try:
            status_cat = StatusCategory(status_category_filter)
            base_filters.append(Lead.status_category == status_cat)
        except ValueError:
            pass  # Invalid status, ignore filter
    
    # Apply campaign filter
    if campaign_id:
        base_filters.append(Lead.magellano_campaign_id == campaign_id)
    
    # Calculate statistics by category (macrocategorie)
    # Create base query with common filters
    def get_base_query():
        return db.query(Lead).filter(*base_filters)
    
    total_leads = get_base_query().count()
    
    # Calculate stats for each category (create new query for each to avoid filter conflicts)
    stats = {
        'total': total_leads,
        'in_lavorazione': get_base_query().filter(Lead.status_category == StatusCategory.IN_LAVORAZIONE).count(),
        'rifiutati': get_base_query().filter(Lead.status_category == StatusCategory.RIFIUTATO).count(),
        'crm': get_base_query().filter(Lead.status_category == StatusCategory.CRM).count(),
        'finale': get_base_query().filter(Lead.status_category == StatusCategory.FINALE).count()
    }
    
    # Calculate conversion rate (finale / total)
    stats['conversion_rate'] = (stats['finale'] / stats['total'] * 100) if stats['total'] > 0 else 0
    
    # Get leads with Ulixe data (only leads with msg_id and Ulixe status)
    lavorazioni_base_query = get_base_query().filter(
        Lead.msg_id.isnot(None),
        Lead.msg_id != '',
        Lead.current_status.isnot(None)
    )
    
    # Aggregate by msg_id - get statistics per message ID
    msg_id_aggregates = db.query(
        Lead.msg_id,
        func.count(Lead.id).label('total_leads'),
        func.sum(case(
            (Lead.status_category == StatusCategory.IN_LAVORAZIONE, 1),
            else_=0
        )).label('in_lavorazione'),
        func.sum(case(
            (Lead.status_category == StatusCategory.RIFIUTATO, 1),
            else_=0
        )).label('rifiutati'),
        func.sum(case(
            (Lead.status_category == StatusCategory.CRM, 1),
            else_=0
        )).label('crm'),
        func.sum(case(
            (Lead.status_category == StatusCategory.FINALE, 1),
            else_=0
        )).label('finale'),
        func.max(Lead.last_check).label('last_check'),
        func.max(Lead.brand).label('brand'),
        func.max(Lead.campaign_name).label('campaign_name')
    ).filter(*base_filters).filter(
        Lead.msg_id.isnot(None),
        Lead.msg_id != '',
        Lead.current_status.isnot(None)
    ).group_by(Lead.msg_id).order_by(func.count(Lead.id).desc()).all()
    
    # Build lavorazioni aggregate list
    lavorazioni_aggregate = []
    for agg in msg_id_aggregates:
        total = agg.total_leads or 0
        finale = agg.finale or 0
        conversion_rate = (finale / total * 100) if total > 0 else 0
        
        lavorazioni_aggregate.append({
            'msg_id': agg.msg_id,
            'total_leads': total,
            'in_lavorazione': agg.in_lavorazione or 0,
            'rifiutati': agg.rifiutati or 0,
            'crm': agg.crm or 0,
            'finale': finale,
            'conversion_rate': round(conversion_rate, 1),
            'last_check': agg.last_check,
            'brand': agg.brand,
            'campaign_name': agg.campaign_name
        })
    
    # Get all individual leads for detail section (with Ulixe data)
    lavorazioni_leads = lavorazioni_base_query.order_by(
        Lead.last_check.desc().nullslast(), 
        Lead.created_at.desc()
    ).limit(1000).all()
    
    # Get available campaigns for filter
    campaigns = db.query(ManagedCampaign).filter(ManagedCampaign.is_active == True).all()
    
    return templates.TemplateResponse("lavorazioni.html", {
        "request": request,
        "title": "Lavorazioni",
        "user": user,
        "stats": stats,
        "lavorazioni_aggregate": lavorazioni_aggregate,
        "lavorazioni_leads": lavorazioni_leads,
        "campaigns": campaigns,
        "status_categories": [
            {"value": "in_lavorazione", "label": "In Lavorazione"},
            {"value": "rifiutato", "label": "Rifiutato"},
            {"value": "crm", "label": "CRM"},
            {"value": "finale", "label": "Finale"}
        ],
        "selected_status_category": status_category_filter,
        "selected_campaign_id": campaign_id,
        "date_from": date_from or date_from_obj.strftime('%Y-%m-%d'),
        "date_to": date_to or date_to_obj.strftime('%Y-%m-%d'),
        "active_page": "lavorazioni"
    })
