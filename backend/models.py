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
    role = Column(String, default="viewer") # viewer, admin, super-admin
    id_sede = Column(String, nullable=True) # Optional link to a specific location/brand

class Lead(Base):
    __tablename__ = "leads"
    
    id = Column(Integer, primary_key=True, index=True)
    magellano_id = Column(String, unique=True, index=True) # Our internal unique key (e.g. MAG-user_id)
    external_user_id = Column(String, index=True) # "Id user" from Magellano (used as Ulixe UserId)
    
    first_name = Column(String)
    last_name = Column(String)
    email = Column(String)
    phone = Column(String)
    province = Column(String) # "County"
    city = Column(String)
    region = Column(String)
    
    brand = Column(String) # "gruppocepu_serviziobrand" (Nome Cliente, es. ecampus)
    msg_id = Column(String, index=True) # "gruppocepu_idmessaggio" (Id Messaggio = corso)
    form_id = Column(String) # "gruppocepu_formid"
    source = Column(String)
    campaign_name = Column(String)
    magellano_campaign_id = Column(String, index=True)
    
    # Payout/Status da Magellano (sent = pagata, blocked/altri = scartata)
    payout_status = Column(String, nullable=True) # "sent", "blocked", etc.
    is_paid = Column(Boolean, default=False) # True se "sent", False altrimenti
    
    # Facebook/Meta fields from Magellano
    facebook_ad_name = Column(String, index=True, nullable=True)
    facebook_ad_set = Column(String, index=True, nullable=True)
    facebook_campaign_name = Column(String, index=True, nullable=True)
    facebook_id = Column(String, index=True, nullable=True) # ID utente Facebook (non ID ad)
    facebook_piattaforma = Column(String, nullable=True)
    
    # Meta Marketing correlation (from Meta API)
    meta_campaign_id = Column(String, index=True, nullable=True) # Meta Campaign ID
    meta_adset_id = Column(String, index=True, nullable=True) # Meta AdSet ID
    meta_ad_id = Column(String, index=True, nullable=True) # Meta Ad ID

    current_status = Column(String)
    status_category = Column(Enum(StatusCategory), default=StatusCategory.IN_LAVORAZIONE)
    last_check = Column(DateTime)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    history = relationship("LeadHistory", back_populates="lead")
    marketing_data = relationship("MetaMarketingData", back_populates="lead")

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

class ManagedCampaign(Base):
    __tablename__ = "managed_campaigns"
    id = Column(Integer, primary_key=True, index=True)
    campaign_id = Column(String, unique=True, index=True) # Magellano Campaign ID
    name = Column(String)
    
    # Gerarchia: Nome Cliente > Pay > Id Messaggio
    cliente_name = Column(String, index=True, nullable=True) # Nome cliente (es. ecampus, cepu)
    pay_level = Column(String, nullable=True) # Livello Pay (se applicabile)
    msg_id_pattern = Column(String, nullable=True) # Pattern o valore msg_id associato
    
    ulixe_ids = Column(JSON, default=list) # List of Ulixe IDs for matching
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

# Meta Marketing Models
class MetaAccount(Base):
    __tablename__ = "meta_accounts"
    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(String, unique=True, index=True) # Meta Ad Account ID
    name = Column(String)
    access_token = Column(String) # Encrypted or stored securely
    is_active = Column(Boolean, default=True)
    sync_enabled = Column(Boolean, default=True)
    sync_frequency = Column(String, default="daily") # daily, hourly, weekly
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    campaigns = relationship("MetaCampaign", back_populates="account")

class MetaCampaign(Base):
    __tablename__ = "meta_campaigns"
    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("meta_accounts.id"))
    campaign_id = Column(String, unique=True, index=True) # Meta Campaign ID
    name = Column(String)
    status = Column(String) # ACTIVE, PAUSED, etc.
    objective = Column(String)
    daily_budget = Column(String, nullable=True)
    lifetime_budget = Column(String, nullable=True)
    tags = Column(JSON, default=list) # List of tags for filtering
    is_synced = Column(Boolean, default=False) # Whether to sync this campaign
    sync_filters = Column(JSON, default=dict) # Filter config: {"tag": "value", "name_pattern": "pattern"}
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    account = relationship("MetaAccount", back_populates="campaigns")
    adsets = relationship("MetaAdSet", back_populates="campaign")

class MetaAdSet(Base):
    __tablename__ = "meta_adsets"
    id = Column(Integer, primary_key=True, index=True)
    campaign_id = Column(Integer, ForeignKey("meta_campaigns.id"))
    adset_id = Column(String, unique=True, index=True) # Meta AdSet ID
    name = Column(String)
    status = Column(String)
    optimization_goal = Column(String)
    targeting = Column(JSON, nullable=True) # Targeting details
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    campaign = relationship("MetaCampaign", back_populates="adsets")
    ads = relationship("MetaAd", back_populates="adset")

class MetaAd(Base):
    __tablename__ = "meta_ads"
    id = Column(Integer, primary_key=True, index=True)
    adset_id = Column(Integer, ForeignKey("meta_adsets.id"))
    ad_id = Column(String, unique=True, index=True) # Meta Ad ID
    name = Column(String)
    status = Column(String)
    creative_id = Column(String, nullable=True)
    creative_thumbnail_url = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    adset = relationship("MetaAdSet", back_populates="ads")
    marketing_data = relationship("MetaMarketingData", back_populates="ad")

class MetaMarketingData(Base):
    __tablename__ = "meta_marketing_data"
    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=True) # Optional correlation
    ad_id = Column(Integer, ForeignKey("meta_ads.id"), nullable=True)
    date = Column(DateTime, index=True) # Date of the metrics
    
    # Metrics
    spend = Column(String, default="0,00") # Using comma as decimal separator
    impressions = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
    conversions = Column(Integer, default=0)
    ctr = Column(String, default="0,00") # Click-through rate
    cpc = Column(String, default="0,00") # Cost per click
    cpm = Column(String, default="0,00") # Cost per mille
    cpa = Column(String, default="0,00") # Cost per acquisition
    
    # Additional metrics (JSON for flexibility)
    additional_metrics = Column(JSON, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    lead = relationship("Lead", back_populates="marketing_data")
    ad = relationship("MetaAd", back_populates="marketing_data")
