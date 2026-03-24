"""Settings: Gestione Alert Email"""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from database import get_db
from models import AlertConfig, User, CronJob
from datetime import datetime
import logging
from ..common import templates

logger = logging.getLogger('services.api.ui')

router = APIRouter(include_in_schema=False)

@router.get("/settings/alerts")
async def settings_alerts(request: Request, db: Session = Depends(get_db)):
    """Pagina gestione configurazioni alert email"""
    user = request.session.get('user')
    if not user:
        return RedirectResponse(url='/')
    
    # Utenti configurabili per gli alert (solo admin/super-admin)
    users = (
        db.query(User)
        .filter(User.role.in_(["admin", "super-admin"]))
        .order_by(User.email)
        .all()
    )

    alert_configs = db.query(AlertConfig).all()
    
    # Crea dict per tipo
    configs_by_type = {}
    for config in alert_configs:
        configs_by_type[config.alert_type] = config
    
    # Costruisci dinamicamente i "canali di alert" a partire dai cron jobs
    cron_jobs = db.query(CronJob).order_by(CronJob.job_name).all()
    alert_types: list[dict] = []

    # Mappa tra job_name dei cron e label più leggibili
    job_label_overrides = {
        "magellano_export_pipeline": "Magellano – Pipeline automatica",
        "ulixe_sync": "Ulixe – Sync stati",
        "ulixe_rcrm_google_sync": "Ulixe – RCRM da Google Sheet",
        "meta_marketing_sync": "Meta – Marketing",
        "meta_conversion_marker": "Meta – Conversion marker",
        "meta_conversion_sync": "Meta – Conversion API",
        "meta_campaigns_incremental": "Meta – Campagne (incrementale)",
    }

    # Usiamo il job_name come chiave alert_type per tutti i job "moderni" (no orchestrator)
    for cron in cron_jobs:
        if cron.job_type in ("orchestrator",) or cron.job_name == "magellano_sync":
            continue
        value = cron.job_name
        label = job_label_overrides.get(value, cron.job_name.replace("_", " ").title())
        alert_types.append(
            {
                "value": value,
                "label": label,
                "source": "cron",
                "job_type": cron.job_type,
            }
        )

    # Aggiungi canali extra non legati a cron ma a fasi distinte (es. Magellano export/ingest, bootstrap campagne Meta)
    extra_channels = [
        {
            "value": "magellano_export",
            "label": "Magellano – Export richiesto (STEP 1)",
            "source": "manual",
            "job_type": "magellano",
        },
        {
            "value": "magellano_ingest",
            "label": "Magellano – Fetch & ingest (STEP 2)",
            "source": "manual",
            "job_type": "magellano",
        },
        {
            "value": "meta_campaigns_bootstrap",
            "label": "Meta – Campagne (bootstrap)",
            "source": "manual",
            "job_type": "meta_campaigns",
        },
    ]

    # Evita duplicati se in futuro i nomi coincidono
    existing_values = {a["value"] for a in alert_types}
    for ch in extra_channels:
        if ch["value"] not in existing_values:
            alert_types.append(ch)

    from services.utils.email import EmailService
    smtp_configured = EmailService().is_configured()
    
    return templates.TemplateResponse("settings_alerts.html", {
        "request": request,
        "title": "Alert Email",
        "user": user,
        "users": users,
        "alert_types": alert_types,
        "configs_by_type": configs_by_type,
        "active_page": "alerts",
        "smtp_configured": smtp_configured
    })

@router.post("/api/alerts")
async def save_alert_config(request: Request, db: Session = Depends(get_db)):
    """Salva/aggiorna configurazione alert"""
    user = request.session.get('user')
    if not user:
        return JSONResponse({"error": "Non autorizzato"}, status_code=401)
    
    current_user = db.query(User).filter(User.email == user.get('email')).first()
    if not current_user or current_user.role not in ['admin', 'super-admin']:
        return JSONResponse({"error": "Non autorizzato"}, status_code=403)
    
    try:
        data = await request.json()
        alert_type = data.get('alert_type')
        enabled = data.get('enabled', True)
        recipients = data.get('recipients', [])
        on_success = data.get('on_success', False)
        on_error = data.get('on_error', True)
        
        if not alert_type:
            return JSONResponse({"error": "alert_type richiesto"}, status_code=400)
        
        # Valida recipients
        if not isinstance(recipients, list):
            return JSONResponse({"error": "recipients deve essere una lista"}, status_code=400)
        
        # Cerca configurazione esistente
        config = db.query(AlertConfig).filter(AlertConfig.alert_type == alert_type).first()
        
        if config:
            # Update
            config.enabled = enabled
            config.recipients = recipients
            config.on_success = on_success
            config.on_error = on_error
            config.updated_at = datetime.utcnow()
        else:
            # Create
            config = AlertConfig(
                alert_type=alert_type,
                enabled=enabled,
                recipients=recipients,
                on_success=on_success,
                on_error=on_error
            )
            db.add(config)
        
        db.commit()
        return JSONResponse({"success": True, "message": "Configurazione salvata"})
        
    except Exception as e:
        logger.error(f"Errore salvataggio alert config: {e}", exc_info=True)
        db.rollback()
        return JSONResponse({"error": str(e)}, status_code=500)

@router.post("/api/alerts/test")
async def test_alert_email(request: Request, db: Session = Depends(get_db)):
    """Test invio email alert"""
    user = request.session.get('user')
    if not user:
        return JSONResponse({"error": "Non autorizzato"}, status_code=401)
    
    current_user = db.query(User).filter(User.email == user.get('email')).first()
    if not current_user or current_user.role not in ['admin', 'super-admin']:
        return JSONResponse({"error": "Non autorizzato"}, status_code=403)
    
    try:
        data = await request.json()
        recipients = data.get('recipients', [])
        
        if not recipients:
            return JSONResponse({"error": "Destinatari richiesti"}, status_code=400)
        
        from services.utils.email import EmailService
        email_service = EmailService()
        
        if not email_service.is_configured():
            return JSONResponse({"error": "SMTP non configurato"}, status_code=400)
        
        # Invia email di test
        success = email_service.send_alert(
            recipients=recipients,
            subject="Test Alert Email - Insight Magellano",
            body_html=f"""
            <html>
            <body>
                <h2>Test Email Alert</h2>
                <p>Questa è una email di test per verificare la configurazione SMTP.</p>
                <p>Se ricevi questa email, la configurazione è corretta!</p>
                <p><strong>Timestamp:</strong> {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}</p>
            </body>
            </html>
            """
        )
        
        if success:
            return JSONResponse({"success": True, "message": "Email di test inviata con successo"})
        else:
            return JSONResponse({"error": "Errore durante l'invio dell'email"}, status_code=500)
            
    except Exception as e:
        logger.error(f"Errore test email: {e}", exc_info=True)
        return JSONResponse({"error": str(e)}, status_code=500)
