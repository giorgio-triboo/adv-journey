from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    # App Settings
    APP_NAME: str = "Magellano Lead Automation"
    DEBUG: bool = False
    # URL base app (per link nelle email, es. https://app.example.com)
    APP_BASE_URL: Optional[str] = None
    # SECRET_KEY obbligatoria in produzione - non usare default
    SECRET_KEY: str = "SUPER_SECRET_KEY_CHANGE_ME"
    # Cookie Secure flag: True in produzione con HTTPS
    SECURE_COOKIES: bool = False
    
    # DATABASE - usare variabili env in produzione
    DATABASE_URL: str = "postgresql://user:password@db:5432/cepudb"
    
    # GOOGLE OAUTH
    GOOGLE_CLIENT_ID: str
    GOOGLE_CLIENT_SECRET: str
    
    # MAGELLANO - da .env
    MAGELLANO_USER: Optional[str] = None
    MAGELLANO_PASSWORD: Optional[str] = None
    
    # ULIXE - da .env
    ULIXE_USER: Optional[str] = None
    ULIXE_PASSWORD: Optional[str] = None
    ULIXE_WSDL: Optional[str] = None
    # RCRM Ulixe: Google Sheet via service account (solo variabili .env, nessun file JSON)
    ULIXE_RCRM_GOOGLE_SA_TYPE: str = "service_account"
    ULIXE_RCRM_GOOGLE_SA_PROJECT_ID: Optional[str] = None
    ULIXE_RCRM_GOOGLE_SA_PRIVATE_KEY_ID: Optional[str] = None
    ULIXE_RCRM_GOOGLE_SA_PRIVATE_KEY: Optional[str] = None
    ULIXE_RCRM_GOOGLE_SA_CLIENT_EMAIL: Optional[str] = None
    ULIXE_RCRM_GOOGLE_SA_CLIENT_ID: Optional[str] = None
    ULIXE_RCRM_GOOGLE_SA_AUTH_URI: str = "https://accounts.google.com/o/oauth2/auth"
    ULIXE_RCRM_GOOGLE_SA_TOKEN_URI: str = "https://oauth2.googleapis.com/token"
    ULIXE_RCRM_GOOGLE_SA_AUTH_PROVIDER_X509_CERT_URL: str = "https://www.googleapis.com/oauth2/v1/certs"
    ULIXE_RCRM_GOOGLE_SA_CLIENT_X509_CERT_URL: Optional[str] = None
    ULIXE_RCRM_GOOGLE_SPREADSHEET_ID: Optional[str] = "19pQMgXp9IqzDxFsE7lBIiLZig5bMYCIOvbRJcZGfGtc"
    # Tab per mese: da periodo YYYY-MM → es. 03-ulixe-rcrm. Vuoto = usa solo GID (legacy).
    ULIXE_RCRM_GOOGLE_SHEET_NAME_TEMPLATE: str = "{mm}-ulixe-rcrm"
    ULIXE_RCRM_GOOGLE_SHEET_GID: Optional[int] = None
    # Range che include IDMessaggio e RCRM (colonna L nel layout Ulixe esteso)
    ULIXE_RCRM_GOOGLE_COLUMN_RANGE: str = "A1:Q"
    
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
