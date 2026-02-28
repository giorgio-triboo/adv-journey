from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    # App Settings
    APP_NAME: str = "Magellano Lead Automation"
    DEBUG: bool = False
    SECRET_KEY: str = "SUPER_SECRET_KEY_CHANGE_ME"
    
    # DATABASE
    DATABASE_URL: str = "postgresql://user:password@db:5432/cepudb"
    
    # GOOGLE OAUTH
    GOOGLE_CLIENT_ID: str
    GOOGLE_CLIENT_SECRET: str
    
    # MAGELLANO
    MAGELLANO_USER: str = "giorgio"
    MAGELLANO_PASSWORD: str = "Magellano2025!"
    
    # ULIXE - DISABILITATO: credenziali impostate a None per prevenire sync accidentale
    ULIXE_USER: Optional[str] = None  # "Triboo2025"
    ULIXE_PASSWORD: Optional[str] = None  # "9Nb6!*HsH812*m7m*"
    ULIXE_WSDL: Optional[str] = None  # "https://tmkprows2.cepu.it/Triboo2025.asmx?WSDL"
    
    # META
    META_ACCESS_TOKEN: Optional[str] = None
    META_PIXEL_ID: Optional[str] = None
    META_APP_ID: Optional[str] = None
    META_APP_SECRET: Optional[str] = None
    # Config per OAuth Meta (login/collegamento account)
    META_CONFIG_ID: Optional[str] = None
    META_SCOPES: Optional[str] = None  # es. "public_profile,email,ads_read,ads_management,business_management"
    
    # EMAIL ALERTS
    SMTP_HOST: Optional[str] = None
    SMTP_PORT: Optional[int] = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_FROM_EMAIL: Optional[str] = None
    SMTP_USE_TLS: bool = True
    
    # CELERY / TASK QUEUE
    CELERY_BROKER_URL: str = "redis://redis:6379/0"
    CELERY_RESULT_BACKEND: Optional[str] = "redis://redis:6379/1"
    
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
