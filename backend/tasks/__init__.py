# Celery tasks package - import task modules so they are registered with the app
from tasks.sync_pipeline import run_full_sync_task  # noqa: F401
from tasks.meta_marketing import (  # noqa: F401
    meta_manual_sync_task,
    meta_graph_leads_sync_task,
    meta_sync_accounts_sequentially_task,
    meta_sync_single_account_task,
)
from tasks.magellano import magellano_export_request_task, magellano_export_fetch_task  # noqa: F401
from tasks.meta_datasets import fetch_datasets_task  # noqa: F401
from tasks.exports import generate_and_email_csv_task  # noqa: F401
