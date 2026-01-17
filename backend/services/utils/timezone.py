"""
Utility per gestire il timezone dell'applicazione.
Tutte le funzioni restituiscono datetime con timezone Europe/Rome (CET/CEST).
"""
from datetime import datetime, timezone
from typing import Optional

try:
    # Python 3.9+ ha zoneinfo built-in
    from zoneinfo import ZoneInfo
    ROME_TZ = ZoneInfo("Europe/Rome")
except ImportError:
    # Fallback per Python < 3.9 (usa pytz se disponibile)
    try:
        import pytz
        ROME_TZ = pytz.timezone("Europe/Rome")
    except ImportError:
        # Ultimo fallback: usa UTC offset (non gestisce ora legale)
        from datetime import timedelta
        ROME_TZ = timezone(timedelta(hours=1))

def now() -> datetime:
    """
    Restituisce la data/ora corrente nel timezone Europe/Rome.
    
    Returns:
        datetime con timezone Europe/Rome
    """
    return datetime.now(ROME_TZ)

def utc_to_rome(utc_dt: datetime) -> datetime:
    """
    Converte un datetime UTC in Europe/Rome.
    
    Args:
        utc_dt: datetime UTC (senza timezone o con UTC timezone)
        
    Returns:
        datetime con timezone Europe/Rome
    """
    if utc_dt.tzinfo is None:
        # Assume UTC se non ha timezone
        utc_dt = utc_dt.replace(tzinfo=timezone.utc)
    elif utc_dt.tzinfo != timezone.utc:
        # Converti al timezone UTC prima
        utc_dt = utc_dt.astimezone(timezone.utc)
    
    # Converti da UTC a Rome
    return utc_dt.astimezone(ROME_TZ)

def rome_to_utc(rome_dt: datetime) -> datetime:
    """
    Converte un datetime Europe/Rome in UTC.
    
    Args:
        rome_dt: datetime Europe/Rome
        
    Returns:
        datetime UTC
    """
    if rome_dt.tzinfo is None:
        # Assume Rome timezone se non ha timezone
        rome_dt = rome_dt.replace(tzinfo=ROME_TZ)
    elif rome_dt.tzinfo != ROME_TZ:
        # Converti al timezone Rome prima
        rome_dt = rome_dt.astimezone(ROME_TZ)
    
    # Converti da Rome a UTC
    return rome_dt.astimezone(timezone.utc)

def now_utc() -> datetime:
    """
    Restituisce la data/ora corrente in UTC.
    Utile per compatibilità con codice esistente che usa UTC.
    
    Returns:
        datetime UTC
    """
    return datetime.now(timezone.utc)

def now_rome_naive() -> datetime:
    """
    Restituisce la data/ora corrente nel timezone Europe/Rome come datetime naive.
    Utile per SQLAlchemy che preferisce datetime naive.
    
    Returns:
        datetime naive con ora corretta per Europe/Rome
    """
    dt = now()
    return dt.replace(tzinfo=None)
