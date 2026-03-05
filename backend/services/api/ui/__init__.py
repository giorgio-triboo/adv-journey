"""UI Router - Combina tutti i moduli UI"""
from fastapi import APIRouter
from .dashboard import router as dashboard_router
from .marketing import router as marketing_router
from .sync import router as sync_router
from .leads import router as leads_router
from .settings import users, campaigns, smtp, alerts, ingestion_summary, cron_jobs, meta_accounts, meta_campaigns, sessions, marketing_thresholds, traffic_platforms

# Crea router principale
router = APIRouter(include_in_schema=False)

# Include tutti i sub-router
router.include_router(dashboard_router)
router.include_router(marketing_router)
router.include_router(sync_router)
router.include_router(leads_router)
router.include_router(users.router)
router.include_router(campaigns.router)
router.include_router(smtp.router)
router.include_router(alerts.router)
router.include_router(ingestion_summary.router)
router.include_router(cron_jobs.router)
router.include_router(meta_accounts.router)
router.include_router(meta_campaigns.router)
router.include_router(sessions.router)
router.include_router(marketing_thresholds.router)
router.include_router(traffic_platforms.router)