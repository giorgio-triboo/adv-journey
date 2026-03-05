from sqlalchemy import Column, Integer, String, Boolean, DateTime, Date, ForeignKey, Enum, JSON, UniqueConstraint, Numeric
from sqlalchemy.orm import relationship, declarative_base
from datetime import datetime, timezone
import enum

# Funzione helper per datetime con timezone Europe/Rome
def now_rome():
    """Restituisce datetime corrente nel timezone Europe/Rome (come naive datetime per SQLAlchemy)"""
    from services.utils.timezone import now_rome_naive
    return now_rome_naive()

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
    magellano_id = Column(String, unique=True, index=True) # ID da Magellano (senza prefisso)
    external_user_id = Column(String, index=True) # ID interno con prefisso MAG- (used as Ulixe UserId)
    
    email = Column(String)  # Hash SHA256 normalizzato secondo specifiche Meta
    phone = Column(String)  # Hash SHA256 normalizzato secondo specifiche Meta
    
    brand = Column(String) # "gruppocepu_serviziobrand" (Nome Cliente, es. ecampus)
    msg_id = Column(String, index=True) # "gruppocepu_idmessaggio" (Id Messaggio = corso)
    form_id = Column(String) # "gruppocepu_formid"
    source = Column(String)
    campaign_name = Column(String)
    magellano_campaign_id = Column(String, index=True)
    
    # Payout/Status da Magellano (sent = pagata, blocked/altri = scartata)
    payout_status = Column(String, nullable=True) # "sent", "blocked", etc. (deprecated, usa magellano_status)
    is_paid = Column(Boolean, default=False) # True se "sent", False altrimenti
    
    # Stato Magellano standardizzato
    magellano_status = Column(String, nullable=True, index=True) # "magellano_sent", "magellano_firewall", "magellano_refused", etc.
    magellano_status_raw = Column(String, nullable=True) # Stato originale esatto da Magellano: "Sent (accept from WS or by email)", etc.
    magellano_status_category = Column(Enum(StatusCategory), nullable=True) # Categoria normalizzata Magellano (IN_LAVORAZIONE per sent, RIFIUTATO per altri)
    
    # Stato Ulixe
    ulixe_status = Column(String, nullable=True) # Stato originale esatto da Ulixe: "In Lavorazione NV", "NO CRM", etc.
    ulixe_status_category = Column(Enum(StatusCategory), nullable=True) # Categoria normalizzata Ulixe
    
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

    # Data di iscrizione/ingresso lead in Magellano (colonna \"Subscr. date\" dell'export)
    magellano_subscr_date = Column(Date, nullable=True, index=True)

    current_status = Column(String)
    status_category = Column(Enum(StatusCategory), default=StatusCategory.IN_LAVORAZIONE)
    last_check = Column(DateTime)
    
    # Meta Conversion API sync fields
    to_sync_meta = Column(Boolean, default=False, index=True) # Flag per indicare se la lead deve essere sincronizzata con Meta CAPI
    last_meta_event_status = Column(String, nullable=True) # Ultimo status_category per cui è stato inviato evento Meta
    meta_correlation_status = Column(String, nullable=True) # Stato correlazione: "found", "not_found", "error"
    
    created_at = Column(DateTime, default=now_rome)
    updated_at = Column(DateTime, default=now_rome, onupdate=now_rome)
    
    history = relationship("LeadHistory", back_populates="lead")
    marketing_data = relationship("MetaMarketingData", back_populates="lead")

class LeadHistory(Base):
    __tablename__ = "lead_history"
    
    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"))
    
    status = Column(String)
    status_category = Column(Enum(StatusCategory))
    raw_response = Column(JSON) # Store full raw response for debug
    
    checked_at = Column(DateTime, default=now_rome)
    
    lead = relationship("Lead", back_populates="history")

class SyncLog(Base):
    __tablename__ = "sync_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    started_at = Column(DateTime, default=now_rome)
    completed_at = Column(DateTime)
    status = Column(String) # SUCCESS, ERROR
    details = Column(JSON)


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=now_rome, index=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # Tipo di job: magellano, ulixe, meta_marketing, orchestrator, ecc.
    job_type = Column(String, index=True)

    # Stato corrente del job: PENDING, QUEUED, RUNNING, SUCCESS, ERROR
    status = Column(String, index=True)

    # ID della task Celery associata (se presente)
    celery_task_id = Column(String, nullable=True, index=True)

    # Parametri di lancio (date, campagne, ecc.)
    params = Column(JSON, nullable=True)

    # Messaggio riassuntivo / errore
    message = Column(String, nullable=True)

class AlertConfig(Base):
    __tablename__ = "alert_configs"
    
    id = Column(Integer, primary_key=True, index=True)
    alert_type = Column(String, index=True)  # 'magellano', 'ulixe', 'meta_marketing', 'meta_conversion'
    enabled = Column(Boolean, default=True)
    recipients = Column(JSON, default=list)  # Lista email ["email1@example.com", "email2@example.com"]
    on_success = Column(Boolean, default=False)  # Invia email anche su successo
    on_error = Column(Boolean, default=True)  # Invia email su errore
    created_at = Column(DateTime, default=now_rome)
    updated_at = Column(DateTime, default=now_rome, onupdate=now_rome)

class SMTPConfig(Base):
    __tablename__ = "smtp_configs"
    
    id = Column(Integer, primary_key=True, index=True)
    host = Column(String)  # Encrypted
    port = Column(Integer, default=587)
    user = Column(String)  # Encrypted
    password = Column(String)  # Encrypted
    from_email = Column(String)  # Encrypted
    use_tls = Column(Boolean, default=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=now_rome)
    updated_at = Column(DateTime, default=now_rome, onupdate=now_rome)

class CronJob(Base):
    __tablename__ = "cron_jobs"
    
    id = Column(Integer, primary_key=True, index=True)
    job_name = Column(String, unique=True, index=True)  # 'nightly_sync', 'magellano_sync', 'ulixe_sync', etc.
    job_type = Column(String)  # 'orchestrator', 'magellano', 'ulixe', 'meta_marketing', 'meta_conversion'
    enabled = Column(Boolean, default=True)
    hour = Column(Integer, default=0)  # 0-23
    minute = Column(Integer, default=30)  # 0-59
    day_of_week = Column(String, default='*')  # '*', '0-6' (0=Monday), 'mon-fri', etc.
    day_of_month = Column(String, default='*')  # '*', '1-31'
    month = Column(String, default='*')  # '*', '1-12', 'jan-dec'
    description = Column(String, nullable=True)
    config = Column(JSON, nullable=True)  # Job-specific config, es. magellano: {"managed_campaign_ids": [1,2,3]}
    created_at = Column(DateTime, default=now_rome)
    updated_at = Column(DateTime, default=now_rome, onupdate=now_rome)

class ManagedCampaign(Base):
    __tablename__ = "managed_campaigns"
    id = Column(Integer, primary_key=True, index=True)
    
    # Identificatore principale: nome cliente/attività (unique)
    cliente_name = Column(String, unique=True, index=True) # Nome cliente/attività (es. CEPU, ECAMPUS, GS)
    name = Column(String) # Nome descrittivo (opzionale, può essere uguale a cliente_name)
    
    # Array di ID Magellano e ID Messaggio
    magellano_ids = Column(JSON, default=list) # Lista di ID Magellano (es. [183] o [188,200,872,889,909])
    msg_ids = Column(JSON, default=list) # Lista di oggetti con id e name (es. [{"id": "117410", "name": "CEPU"}, ...])
    
    pay_level = Column(String, nullable=True) # Livello Pay (es. 80, 40, 60)
    
    ulixe_ids = Column(JSON, default=list) # List of Ulixe IDs for matching
    meta_dataset_id = Column(String, nullable=True) # Meta Dataset ID per mapping campagna Magellano -> Dataset Meta (per Conversion API)
    
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=now_rome)

# Meta Marketing Models
class MetaAccount(Base):
    __tablename__ = "meta_accounts"
    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(String, index=True) # Meta Ad Account ID (non più unique, può essere condiviso)
    name = Column(String)
    access_token = Column(String) # Encrypted or stored securely
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True) # NULL = condiviso, user_id = specifico utente
    is_active = Column(Boolean, default=True)
    sync_enabled = Column(Boolean, default=True)
    sync_frequency = Column(String, default="daily") # daily, hourly, weekly
    created_at = Column(DateTime, default=now_rome)
    updated_at = Column(DateTime, default=now_rome, onupdate=now_rome)
    
    campaigns = relationship("MetaCampaign", back_populates="account")
    user = relationship("User", backref="meta_accounts")
    
    # Unique constraint su (account_id, user_id) per permettere stesso account a utenti diversi
    __table_args__ = (
        UniqueConstraint('account_id', 'user_id', name='uq_meta_account_user'),
    )

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
    created_at = Column(DateTime, default=now_rome)
    updated_at = Column(DateTime, default=now_rome, onupdate=now_rome)
    
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
    created_at = Column(DateTime, default=now_rome)
    updated_at = Column(DateTime, default=now_rome, onupdate=now_rome)
    
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
    created_at = Column(DateTime, default=now_rome)
    updated_at = Column(DateTime, default=now_rome, onupdate=now_rome)
    
    adset = relationship("MetaAdSet", back_populates="ads")
    marketing_data = relationship("MetaMarketingData", back_populates="ad")

class MetaMarketingData(Base):
    __tablename__ = "meta_marketing_data"
    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=True) # Optional correlation
    ad_id = Column(Integer, ForeignKey("meta_ads.id"), nullable=True)
    date = Column(DateTime, index=True) # Date of the metrics
    
    # Metrics - store numeric values (DECIMAL) for reliability
    spend = Column(Numeric(18, 4), default=0)
    impressions = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
    conversions = Column(Integer, default=0)
    ctr = Column(Numeric(10, 4), default=0) # Click-through rate (percentuale come numero)
    cpc = Column(Numeric(18, 4), default=0) # Cost per click
    cpm = Column(Numeric(18, 4), default=0) # Cost per mille
    cpa = Column(Numeric(18, 4), default=0) # Cost per acquisition
    
    # Additional metrics (JSON for flexibility)
    additional_metrics = Column(JSON, nullable=True)
    
    created_at = Column(DateTime, default=now_rome)
    updated_at = Column(DateTime, default=now_rome, onupdate=now_rome)
    
    lead = relationship("Lead", back_populates="marketing_data")
    ad = relationship("MetaAd", back_populates="marketing_data")

class MetaDataset(Base):
    __tablename__ = "meta_datasets"
    id = Column(Integer, primary_key=True, index=True)
    dataset_id = Column(String, unique=True, index=True) # Meta Dataset/Pixel ID
    name = Column(String)
    account_id = Column(Integer, ForeignKey("meta_accounts.id"), nullable=True) # Collegato all'account Meta
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=now_rome)
    updated_at = Column(DateTime, default=now_rome, onupdate=now_rome)
    
    account = relationship("MetaAccount", backref="datasets")

class MetaDatasetFetchJob(Base):
    __tablename__ = "meta_dataset_fetch_jobs"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    status = Column(String, default="pending") # pending, processing, completed, error
    datasets = Column(JSON, nullable=True) # Lista di dataset recuperati
    account_map = Column(JSON, nullable=True) # Mappa account
    error_message = Column(String, nullable=True)
    created_at = Column(DateTime, default=now_rome)
    completed_at = Column(DateTime, nullable=True)
    
    user = relationship("User", backref="dataset_fetch_jobs")

class MarketingThresholdConfig(Base):
    """Soglie per colorazione margine e % scarto nella vista Marketing (rosso/arancione/verde)"""
    __tablename__ = "marketing_threshold_config"
    id = Column(Integer, primary_key=True, index=True)

    # Margine %: higher = better → rosso fino a X, arancione tra X e Y, verde sopra Y
    margine_rosso_fino = Column(Numeric(10, 2), default=0)   # <= questo = rosso
    margine_verde_da = Column(Numeric(10, 2), default=15)   # >= questo = verde

    # % Scarto: lower = better → verde fino a X, arancione tra X e Y, rosso sopra Y
    scarto_verde_fino = Column(Numeric(10, 2), default=5)   # <= questo = verde
    scarto_rosso_da = Column(Numeric(10, 2), default=20)    # >= questo = rosso

    # Checkbox per ogni soglia: se True, applica il colore per quella banda
    colori_margine_rosso = Column(Boolean, default=True, nullable=False)   # rosso margine
    colori_margine_verde = Column(Boolean, default=True, nullable=False)   # verde margine
    colori_scarto_verde = Column(Boolean, default=True, nullable=False)    # verde scarto
    colori_scarto_rosso = Column(Boolean, default=True, nullable=False)    # rosso scarto

    created_at = Column(DateTime, default=now_rome)
    updated_at = Column(DateTime, default=now_rome, onupdate=now_rome)


class TrafficPlatform(Base):
    """Piattaforme di traffico configurabili da frontend (Meta, Google, TikTok, Organico, ecc.)"""
    __tablename__ = "traffic_platforms"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False, index=True)  # es. "Meta", "Google Ads"
    slug = Column(String, unique=True, nullable=False, index=True)  # es. "meta", "google"
    display_order = Column(Integer, default=0)  # Ordine visualizzazione
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=now_rome)
    updated_at = Column(DateTime, default=now_rome, onupdate=now_rome)

    msg_mappings = relationship("MsgTrafficMapping", back_populates="traffic_platform")


class MsgTrafficMapping(Base):
    """Mapping ID Messaggio (msg_id) -> piattaforma traffico per aggregazione per canale"""
    __tablename__ = "msg_traffic_mapping"

    id = Column(Integer, primary_key=True, index=True)
    msg_id = Column(String, nullable=False, index=True)
    traffic_platform_id = Column(Integer, ForeignKey("traffic_platforms.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, default=now_rome)

    traffic_platform = relationship("TrafficPlatform", back_populates="msg_mappings")

    __table_args__ = (UniqueConstraint("msg_id", name="uq_msg_traffic_mapping_msg_id"),)


class UlixeRcrmTemp(Base):
    """Tabella provvisoria: dati RCRM da export Ulixe (approvate per msg_id e periodo).
    Sostituita in futuro da collegamento API per singola lead."""
    __tablename__ = "ulixe_rcrm_temp"

    id = Column(Integer, primary_key=True, index=True)
    msg_id = Column(String, nullable=False, index=True)  # IDMessaggio (gruppocepu_idmessaggio)
    period = Column(String, nullable=False, index=True)   # YYYY-MM (es. 2026-01, 2026-02)
    rcrm_count = Column(Integer, nullable=False, default=0)  # Colonna RCRM dall'export
    source_file = Column(String, nullable=True)           # File origine (es. rcrm-0126.csv)
    created_at = Column(DateTime, default=now_rome)

    __table_args__ = (UniqueConstraint("msg_id", "period", name="uq_ulixe_rcrm_temp_msg_period"),)


class Session(Base):
    __tablename__ = "sessions"
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, unique=True, index=True) # Token univoco per la sessione
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    session_data = Column(JSON, default=dict) # Dati della sessione (user, meta_oauth_token, etc.)
    is_active = Column(Boolean, default=True) # Flag per invalidare manualmente la sessione
    created_at = Column(DateTime, default=now_rome)
    expires_at = Column(DateTime, nullable=False, index=True) # Scadenza sessione
    last_activity = Column(DateTime, default=now_rome) # Ultima attività
    
    user = relationship("User", backref="sessions")
