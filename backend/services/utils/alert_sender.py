"""
Helper per inviare alert email dopo sync job.
"""
from sqlalchemy.orm import Session
from models import AlertConfig
from services.utils.email import EmailService
import logging

logger = logging.getLogger(__name__)

def send_sync_alert_if_needed(
    db: Session,
    sync_type: str,
    success: bool,
    stats: dict,
    error_message: str = None
):
    """
    Invia alert email se configurato per questo tipo di sync.
    
    Args:
        db: Sessione database
        sync_type: Tipo sync ('magellano', 'ulixe', 'meta_marketing', 'meta_conversion')
        success: True se successo, False se errore
        stats: Dizionario con statistiche
        error_message: Messaggio errore (se success=False)
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
        
        # Verifica se deve inviare (solo su errore o anche su successo)
        if not success and not alert_config.on_error:
            logger.debug(f"Alert configurato per non inviare su errore per {sync_type}")
            return
        
        if success and not alert_config.on_success:
            logger.debug(f"Alert configurato per non inviare su successo per {sync_type}")
            return
        
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
