from celery import Celery
from config import settings
from logging_config import setup_logging

# Configura logging anche nel processo Celery worker,
# in modo che scriva nei file sotto backend/logs
setup_logging()


celery_app = Celery(
    "cepulavorazioni",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Europe/Rome",
    enable_utc=False,
)

# Import esplicito dei moduli di task per registrarli con l'app Celery
# (evita problemi di autodiscovery in ambienti Dockerizzati)
import tasks.sync_pipeline  # noqa: F401
import tasks.meta_marketing  # noqa: F401
import tasks.magellano  # noqa: F401
import tasks.meta_datasets  # noqa: F401
import tasks.exports  # noqa: F401

