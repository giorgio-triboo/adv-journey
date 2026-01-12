from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Enum, JSON
from sqlalchemy.orm import relationship, declarative_base
from datetime import datetime
import enum

Base = declarative_base()

class StatusCategory(enum.Enum):
    IN_LAVORAZIONE = "in_lavorazione"
    RIFIUTATO = "rifiutato"
    CRM = "crm"
    FINALE = "finale"
    UNKNOWN = "unknown"

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    is_active = Column(Boolean, default=True)
    role = Column(String, default="viewer") # viewer, admin

class Lead(Base):
    __tablename__ = "leads"
    
    id = Column(Integer, primary_key=True, index=True)
    magellano_id = Column(String, unique=True, index=True) # ID external ref
    user_id = Column(String, unique=True, index=True) # Our internal unique key
    
    first_name = Column(String)
    last_name = Column(String)
    email = Column(String)
    phone = Column(String)
    province = Column(String)
    
    current_status = Column(String)
    status_category = Column(Enum(StatusCategory), default=StatusCategory.IN_LAVORAZIONE)
    last_check = Column(DateTime)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    history = relationship("LeadHistory", back_populates="lead")

class LeadHistory(Base):
    __tablename__ = "lead_history"
    
    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"))
    
    status = Column(String)
    status_category = Column(Enum(StatusCategory))
    raw_response = Column(JSON) # Store full raw response for debug
    
    checked_at = Column(DateTime, default=datetime.utcnow)
    
    lead = relationship("Lead", back_populates="history")

class SyncLog(Base):
    __tablename__ = "sync_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)
    status = Column(String) # SUCCESS, ERROR
    details = Column(JSON)
