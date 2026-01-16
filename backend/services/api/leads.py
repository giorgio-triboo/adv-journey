from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from database import get_db
from models import Lead, User, StatusCategory, LeadHistory
from pydantic import BaseModel
from datetime import datetime

router = APIRouter(prefix="/api/leads", tags=["leads"])

# Pydantic models for response/request
class LeadBase(BaseModel):
    first_name: str
    last_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    province: Optional[str] = None
    city: Optional[str] = None
    region: Optional[str] = None
    brand: Optional[str] = None
    msg_id: Optional[str] = None
    source: Optional[str] = None
    campaign_name: Optional[str] = None

class LeadOut(LeadBase):
    id: int
    magellano_id: Optional[str]
    external_user_id: Optional[str]
    magellano_campaign_id: Optional[str]
    current_status: Optional[str]
    status_category: str
    last_check: Optional[datetime]
    created_at: datetime
    
    class Config:
        from_attributes = True

@router.get("/", response_model=List[LeadOut])
def get_leads(
    skip: int = 0, 
    limit: int = 100, 
    status_category: Optional[str] = None,
    db: Session = Depends(get_db)
):
    query = db.query(Lead)
    
    if status_category:
        query = query.filter(Lead.status_category == status_category)
        
    leads = query.order_by(Lead.created_at.desc()).offset(skip).limit(limit).all()
    return leads

@router.get("/{lead_id}", response_model=LeadOut)
def get_lead(lead_id: int, db: Session = Depends(get_db)):
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead

class LeadCreate(LeadBase):
    magellano_id: Optional[str] = None
    external_user_id: Optional[str] = None
    magellano_campaign_id: Optional[str] = None
    status_category: str = "in_lavorazione"

class LeadUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    province: Optional[str] = None
    city: Optional[str] = None
    region: Optional[str] = None
    brand: Optional[str] = None
    msg_id: Optional[str] = None
    source: Optional[str] = None
    status_category: Optional[str] = None

@router.post("/", response_model=LeadOut)
def create_lead(lead: LeadCreate, db: Session = Depends(get_db)):
    db_lead = Lead(**lead.dict())
    if not db_lead.magellano_id:
         db_lead.magellano_id = f"MAN-{datetime.utcnow().timestamp()}"
    
    db.add(db_lead)
    db.commit()
    db.refresh(db_lead)
    return db_lead

@router.patch("/{lead_id}", response_model=LeadOut)
def update_lead(lead_id: int, lead_update: LeadUpdate, db: Session = Depends(get_db)):
    db_lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not db_lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    old_category = db_lead.status_category.value if hasattr(db_lead.status_category, 'value') else db_lead.status_category
    
    update_data = lead_update.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_lead, key, value)
        
    db.commit()
    db.refresh(db_lead)
    
    # Trigger Meta Event if category changed
    new_category = db_lead.status_category.value if hasattr(db_lead.status_category, 'value') else db_lead.status_category
    
    if old_category != new_category:
        try:
            from services.integrations.meta import MetaService
            meta = MetaService()
            meta.send_custom_event(
                event_name=f"LeadStatusChange_{new_category}",
                lead_data={
                    "email": db_lead.email,
                    "phone": db_lead.phone,
                    "first_name": db_lead.first_name,
                    "last_name": db_lead.last_name,
                    "province": db_lead.province
                },
                additional_data={"old_status": old_category, "new_status": new_category}
            )
        except Exception as e:
            print(f"Meta trigger failed: {e}")

    return db_lead

@router.post("/{lead_id}/check-ulixe", response_model=LeadOut)
def check_lead_ulixe(lead_id: int, db: Session = Depends(get_db)):
    db_lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not db_lead:
        raise HTTPException(status_code=404, detail="Lead not found")
        
    if not db_lead.external_user_id:
        raise HTTPException(status_code=400, detail="Lead has no external_user_id for Ulixe")
    
    # Verifica che le credenziali Ulixe siano configurate
    from config import settings
    if not settings.ULIXE_USER or not settings.ULIXE_PASSWORD or not settings.ULIXE_WSDL:
        raise HTTPException(status_code=503, detail="Ulixe sync is disabled: credentials not configured")
        
    try:
        from services.integrations.ulixe import UlixeClient
        client = UlixeClient()
        status_info = client.get_lead_status(db_lead.external_user_id)
        
        db_lead.current_status = status_info.status
        try:
            db_lead.status_category = StatusCategory(status_info.category)
        except ValueError:
            db_lead.status_category = StatusCategory.UNKNOWN

        db_lead.last_check = status_info.checked_at
        
        history = LeadHistory(
            lead_id=db_lead.id,
            status=status_info.status,
            status_category=db_lead.status_category,
            raw_response={"raw": status_info.raw_response},
            checked_at=status_info.checked_at
        )
        db.add(history)
        db.commit()
        db.refresh(db_lead)
        
        return db_lead
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ulixe check failed: {e}")
