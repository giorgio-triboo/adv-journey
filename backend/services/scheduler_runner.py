import logging
import time

from logging_config import setup_logging
from config import settings
from services.scheduler import start_scheduler


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

    logger.info("Scheduler avviato. Processo in attesa (loop infinito).")
    try:
        while True:
            # Mantiene vivo il processo; APScheduler gira in background
            time.sleep(60)
    except KeyboardInterrupt:
        logger.info("Scheduler interrotto da KeyboardInterrupt, uscita del processo.")


if __name__ == "__main__":
    main()

