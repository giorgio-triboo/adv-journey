from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    # App Settings
    APP_NAME: str = "Magellano Lead Automation"
    DEBUG: bool = False
    SECRET_KEY: str = "SUPER_SECRET_KEY_CHANGE_ME"
    
    # DATABASE
    DATABASE_URL: str = "postgresql://postgres:postgres@db:5432/cepu"
    
    # GOOGLE OAUTH
    GOOGLE_CLIENT_ID: str
    GOOGLE_CLIENT_SECRET: str
    
    # MAGELLANO
    MAGELLANO_USER: str = "giorgio"
    MAGELLANO_PASSWORD: str = "Magellano2025!"
    
    # ULIXE
    ULIXE_USER: str = "Triboo2025"
    ULIXE_PASSWORD: str = "9Nb6!*HsH812*m7m*"
    ULIXE_WSDL: str = "https://tmkprows2.cepu.it/Triboo2025.asmx?WSDL"
    
    # META
    META_ACCESS_TOKEN: Optional[str] = None
    META_PIXEL_ID: Optional[str] = None
    
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
