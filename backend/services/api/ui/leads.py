"""Lead detail view"""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from database import get_db
from models import (
    LeadHistory, Lead, StatusCategory
)
from sqlalchemy import func, case, desc
from .common import templates

router = APIRouter(include_in_schema=False)

@router.get("/leads/{lead_id}")
async def lead_detail(request: Request, lead_id: int, db: Session = Depends(get_db)):
    """Vista dettaglio lead estesa con due livelli di analisi"""
    user = request.session.get('user')
    if not user:
        return RedirectResponse(url='/')
    
    # Get lead
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        return RedirectResponse(url='/dashboard')
    
    # Get history
    history = db.query(LeadHistory).filter(
        LeadHistory.lead_id == lead_id
    ).order_by(desc(LeadHistory.checked_at)).all()
    
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
    
    return templates.TemplateResponse(request, "lead_detail.html", {
        "request": request,
        "title": f"Lead #{lead.id}",
        "user": user,
        "lead": lead,
        "history": history,
        "msg_id_overview": msg_id_overview
    })
