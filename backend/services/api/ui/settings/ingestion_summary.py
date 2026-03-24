"""Riepilogo Ingestion - Storico sync e alert"""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from database import get_db
from models import SyncLog, User, IngestionJob, Lead
from datetime import datetime, timedelta
import logging
from ..common import templates

logger = logging.getLogger('services.api.ui')

router = APIRouter(include_in_schema=False)

# Nomi job per display
JOB_LABELS = {
    'magellano': 'Magellano',
    'ulixe': 'Ulixe',
    'ulixe_rcrm_google': 'RCRM Ulixe (Google Sheet)',
    'meta_marketing': 'Meta Marketing',
    'meta_conversion_marker': 'Meta Conversion Marker',
    'meta_conversion': 'Meta Conversion API',
}


@router.get("/settings/alerts/ingestion")
async def ingestion_summary(request: Request, db: Session = Depends(get_db)):
    """Pagina riepilogo ingestion - ultimi sync con stato e dettagli"""
    user = request.session.get('user')
    if not user:
        return RedirectResponse(url='/')

    # Ultimi 50 sync
    sync_logs = db.query(SyncLog).order_by(desc(SyncLog.started_at)).limit(50).all()

    # Formatta per template
    logs_formatted = []
    for log in sync_logs:
        details = log.details or {}
        jobs_summary = []
        if isinstance(details, dict):
            stats = details.get('stats') if 'error' in details else details
            if isinstance(stats, dict):
                for job_name, job_data in stats.items():
                    if isinstance(job_data, dict):
                        has_errors = job_data.get('errors', 0) > 0
                        status = 'error' if has_errors else 'success'
                        label = JOB_LABELS.get(job_name, job_name)
                        jobs_summary.append({
                            'name': label,
                            'status': status,
                            'detail': job_data
                        })
                    else:
                        jobs_summary.append({
                            'name': JOB_LABELS.get(job_name, job_name),
                            'status': 'success',
                            'detail': {'value': job_data}
                        })
            # Errore orchestrator generale (non per-job)
            if 'error' in details and not jobs_summary:
                jobs_summary.append({
                    'name': 'Errore',
                    'status': 'error',
                    'detail': details.get('error', '')
                })

        logs_formatted.append({
            'id': log.id,
            'started_at': log.started_at,
            'completed_at': log.completed_at,
            'status': log.status,
            'jobs_summary': jobs_summary,
            'details_raw': details
        })

    # Job di ingestion recenti (in particolare PENDING/QUEUED/RUNNING)
    recent_jobs = (
        db.query(IngestionJob)
        .order_by(desc(IngestionJob.created_at))
        .limit(50)
        .all()
    )

    jobs_formatted = []
    for job in recent_jobs:
        # Statistiche aggiuntive per UI (es. campagne Meta aggiornate, lead per campagna Magellano)
        stats = None

        # Meta marketing / bootstrap: stats salvate nei params del job (se presenti)
        if job.params and isinstance(job.params, dict) and job.job_type in (
            "meta_marketing",
            "meta_campaigns_bootstrap",
        ):
            stats = (job.params or {}).get("stats")

        # Magellano: calcola numero di lead per campagna nel periodo indicato
        if job.job_type == "magellano":
            params = job.params or {}
            campaigns = params.get("campaigns") or []
            start_date = params.get("start_date")
            end_date = params.get("end_date")
            if campaigns and start_date and end_date:
                try:
                    q = (
                        db.query(Lead.magellano_campaign_id, func.count(Lead.id))
                        .filter(Lead.magellano_campaign_id.in_([str(c) for c in campaigns]))
                        .filter(Lead.magellano_subscr_date >= start_date)
                        .filter(Lead.magellano_subscr_date <= end_date)
                        .group_by(Lead.magellano_campaign_id)
                    )
                    per_campaign = {str(row[0]): row[1] for row in q.all()}
                    stats = {"per_campaign_leads": per_campaign}
                except Exception as e:
                    logger.warning(f"Errore calcolo stats Magellano per job {job.id}: {e}")

        jobs_formatted.append(
            {
                "id": job.id,
                "created_at": job.created_at,
                "started_at": job.started_at,
                "completed_at": job.completed_at,
                "job_type": job.job_type,
                "status": job.status,
                "celery_task_id": job.celery_task_id,
                "params": job.params or {},
                "message": job.message,
                "stats": stats,
            }
        )

    return templates.TemplateResponse(
        "settings_ingestion_summary.html",
        {
            "request": request,
            "title": "Riepilogo Ingestion",
            "user": user,
            "sync_logs": logs_formatted,
            "ingestion_jobs": jobs_formatted,
            "active_page": "ingestion_summary",
        },
    )
