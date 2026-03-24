"""Segnale Redis: il processo scheduler_runner si riallinea ai CronJob a database senza riavvio."""
import logging

from config import settings

logger = logging.getLogger(__name__)

# Canale dedicato (non interferisce con le code Celery sullo stesso broker).
CRON_SCHEDULER_RELOAD_CHANNEL = "cepulavorazioni:cron_scheduler_reload"


def notify_cron_scheduler_reload() -> None:
    """Pubblica su Redis; lo scheduler in ascolto richiama start_scheduler()."""
    try:
        import redis
    except ImportError:
        logger.warning("redis non installato: impossibile notificare il reload dello scheduler")
        return

    try:
        client = redis.from_url(settings.CELERY_BROKER_URL, decode_responses=True)
        try:
            subscribers = client.publish(CRON_SCHEDULER_RELOAD_CHANNEL, "reload")
            logger.info(
                "Segnale reload cron scheduler pubblicato (canale=%s, subscriber=%s)",
                CRON_SCHEDULER_RELOAD_CHANNEL,
                subscribers,
            )
        finally:
            client.close()
    except Exception as exc:
        # Non fallire il salvataggio UI se Redis è giù o lo scheduler non è deployato.
        logger.warning("Notifica reload scheduler non inviata: %s", exc, exc_info=True)
