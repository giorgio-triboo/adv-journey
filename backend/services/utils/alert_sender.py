"""
Helper per inviare alert email dopo sync job.
"""
from sqlalchemy.orm import Session
from models import AlertConfig
from services.utils.email import EmailService
import logging

logger = logging.getLogger(__name__)


def should_alert_ulixe_rcrm_google_api(source: str) -> bool:
    """
    True se la richiesta API sync RCRM riguarda il flusso Google Sheet
    (source esplicito o auto con credenziali configurate).
    """
    s = (source or "auto").strip().lower()
    if s == "google_sheet":
        return True
    if s == "auto":
        from services.integrations.google_sheets_rcrm import is_rcrm_google_sheet_configured

        return is_rcrm_google_sheet_configured()
    return False


def notify_ulixe_rcrm_google_after_api(
    db: Session,
    *,
    source: str,
    period: str,
    success: bool,
    stats: dict | None = None,
    error_message: str | None = None,
) -> None:
    """
    Alert canale ulixe_rcrm_google_sync dopo POST /api/ulixe/rcrm/sync.
    Successo solo se import da Google Sheet; errori solo se il flusso era Google-related.
    """
    if success:
        if not stats or stats.get("mode") != "google_sheet":
            return
    elif not should_alert_ulixe_rcrm_google_api(source):
        return

    payload = dict(stats) if stats else {"period": period, "source": source}
    payload.setdefault("period", period)
    payload.setdefault("source", source)
    payload["trigger"] = "api"

    try:
        send_sync_alert_if_needed(
            db,
            "ulixe_rcrm_google_sync",
            success,
            payload,
            error_message,
        )
    except Exception as e:
        logger.error("Errore invio alert RCRM Google Sheet (API): %s", e, exc_info=True)

def send_sync_alert_if_needed(
    db: Session,
    sync_type: str,
    success: bool,
    stats: dict,
    error_message: str = None
):
    """
    Invia alert email se il canale è abilitato e ha destinatari.
    L'email parte sia in caso di successo sia in caso di errore (il subject/body riflettono l'esito).
    """
    try:
        # Cerca configurazione alert per questo tipo
        alert_config = db.query(AlertConfig).filter(
            AlertConfig.alert_type == sync_type,
            AlertConfig.enabled == True
        ).first()
        
        if not alert_config:
            logger.debug(f"Nessuna configurazione alert per {sync_type}")
            return
        
        # Canale attivo + destinatari: invia sempre, sia su successo sia su errore
        # (i flag on_success/on_error in DB non filtrano più l'invio).
        if not alert_config.recipients:
            logger.warning(f"Configurazione alert per {sync_type} senza destinatari")
            return
        
        email_service = EmailService()
        if not email_service.is_configured():
            logger.warning("SMTP non configurato. Alert non inviato.")
            return
        
        email_service.send_sync_alert(
            sync_type=sync_type,
            success=success,
            stats=stats,
            recipients=alert_config.recipients,
            error_message=error_message
        )
        
    except Exception as e:
        logger.error(f"Errore invio alert per {sync_type}: {e}", exc_info=True)
