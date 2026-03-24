import logging
import threading
import time

from logging_config import setup_logging
from config import settings
from services.cron_scheduler_reload_signal import CRON_SCHEDULER_RELOAD_CHANNEL
from services.scheduler import start_scheduler


def _redis_reload_listener_loop() -> None:
    """Ascolta Redis e richiama start_scheduler() quando l'UI salva i cron job."""
    logger = logging.getLogger("services.scheduler_runner")
    import redis

    backoff = 5
    while True:
        client = None
        pubsub = None
        try:
            client = redis.from_url(settings.CELERY_BROKER_URL, decode_responses=True)
            pubsub = client.pubsub(ignore_subscribe_messages=True)
            pubsub.subscribe(CRON_SCHEDULER_RELOAD_CHANNEL)
            logger.info(
                "In ascolto su Redis (canale=%s) per reload job cron senza riavvio.",
                CRON_SCHEDULER_RELOAD_CHANNEL,
            )
            backoff = 5
            for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                logger.info("Segnale reload cron ricevuto: riallineo i job da database.")
                try:
                    start_scheduler()
                except Exception:
                    logger.exception("Errore durante reload scheduler dopo segnale Redis")
        except Exception:
            logger.exception(
                "Errore listener Redis per reload cron; nuovo tentativo tra %ss",
                backoff,
            )
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)
        finally:
            if pubsub is not None:
                try:
                    pubsub.close()
                except Exception:
                    pass
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass


def main() -> None:
    """
    Entry point per il processo scheduler dedicato.

    Avvia APScheduler (che registra i job in base alla tabella cron_jobs)
    e poi mantiene vivo il processo.
    """
    # Configura logging per questo processo
    log_level = logging.INFO if not settings.DEBUG else logging.DEBUG
    setup_logging(log_level)
    logger = logging.getLogger("services.scheduler_runner")

    logger.info("Avvio processo scheduler dedicato...")
    try:
        start_scheduler()
    except Exception as e:
        logger.error("Errore durante l'avvio dello scheduler: %s", e, exc_info=True)
        # Se non riusciamo ad avviare lo scheduler, non ha senso tenere vivo il processo
        raise

    reload_thread = threading.Thread(
        target=_redis_reload_listener_loop,
        name="cron-scheduler-redis-reload",
        daemon=True,
    )
    reload_thread.start()

    logger.info("Scheduler avviato. Processo in attesa (loop infinito).")
    try:
        while True:
            # Mantiene vivo il processo; APScheduler gira in background
            time.sleep(60)
    except KeyboardInterrupt:
        logger.info("Scheduler interrotto da KeyboardInterrupt, uscita del processo.")


if __name__ == "__main__":
    main()

