"""Settings: Configurazione SMTP"""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from database import get_db
from models import SMTPConfig
from services.utils.crypto import encrypt_token, decrypt_token
from datetime import datetime
import logging
import smtplib
from email.mime.text import MIMEText
from ..common import templates, require_super_admin

logger = logging.getLogger('services.api.ui')

router = APIRouter(include_in_schema=False)

@router.get("/settings/smtp")
async def settings_smtp(request: Request, db: Session = Depends(get_db)):
    """Pagina gestione configurazione SMTP - Solo super-admin"""
    current_user, redirect = require_super_admin(request, db)
    if redirect:
        return redirect
    
    # Recupera configurazione esistente (solo una configurazione attiva)
    smtp_config = db.query(SMTPConfig).filter(SMTPConfig.is_active == True).first()
    
    # Decripta i dati se presenti
    config_data = None
    if smtp_config:
        try:
            config_data = {
                "id": smtp_config.id,
                "host": decrypt_token(smtp_config.host) if smtp_config.host else "",
                "port": smtp_config.port or 587,
                "user": decrypt_token(smtp_config.user) if smtp_config.user else "",
                "password": "",  # Non mostrare la password
                "from_email": decrypt_token(smtp_config.from_email) if smtp_config.from_email else "",
                "use_tls": smtp_config.use_tls if smtp_config.use_tls is not None else True,
                "is_active": smtp_config.is_active
            }
        except Exception as e:
            logger.error(f"Errore decriptazione SMTP config: {e}")
            config_data = None
    
    return templates.TemplateResponse("settings_smtp.html", {
        "request": request,
        "title": "Configurazione SMTP",
        "user": current_user,
        "smtp_config": config_data,
        "active_page": "smtp"
    })

@router.post("/settings/smtp")
async def save_smtp_config(request: Request, db: Session = Depends(get_db)):
    """Salva configurazione SMTP - Solo super-admin"""
    current_user, redirect = require_super_admin(request, db)
    if redirect:
        return redirect
    
    try:
        form = await request.form()
        
        host = form.get("host", "").strip()
        port = int(form.get("port", 587) or 587)
        user = form.get("user", "").strip()
        password = form.get("password", "").strip()
        from_email = form.get("from_email", "").strip()
        use_tls = form.get("use_tls") == "on"
        is_active = form.get("is_active") == "on"
        
        # Validazione
        if not host or not user:
            return RedirectResponse(url='/settings/smtp?error=Host e User sono obbligatori', status_code=303)
        
        # Recupera configurazione esistente
        smtp_config = db.query(SMTPConfig).filter(SMTPConfig.is_active == True).first()
        
        if smtp_config:
            # Update configurazione esistente
            smtp_config.host = encrypt_token(host)
            smtp_config.port = port
            smtp_config.user = encrypt_token(user)
            if password:  # Aggiorna password solo se fornita
                smtp_config.password = encrypt_token(password)
            smtp_config.from_email = encrypt_token(from_email) if from_email else None
            smtp_config.use_tls = use_tls
            smtp_config.is_active = is_active
            smtp_config.updated_at = datetime.utcnow()
        else:
            # Crea nuova configurazione
            if not password:
                return RedirectResponse(url='/settings/smtp?error=Password obbligatoria per nuova configurazione', status_code=303)
            
            smtp_config = SMTPConfig(
                host=encrypt_token(host),
                port=port,
                user=encrypt_token(user),
                password=encrypt_token(password),
                from_email=encrypt_token(from_email) if from_email else None,
                use_tls=use_tls,
                is_active=is_active
            )
            db.add(smtp_config)
        
        db.commit()
        return RedirectResponse(url='/settings/smtp?success=Configurazione SMTP salvata con successo', status_code=303)
        
    except Exception as e:
        logger.error(f"Errore salvataggio SMTP config: {e}", exc_info=True)
        db.rollback()
        return RedirectResponse(url=f'/settings/smtp?error=Errore nel salvataggio: {str(e)}', status_code=303)

@router.post("/api/smtp/test")
async def test_smtp_config(request: Request, db: Session = Depends(get_db)):
    """Test configurazione SMTP - Solo super-admin"""
    current_user, redirect = require_super_admin(request, db)
    if redirect:
        return JSONResponse({"error": "Non autorizzato"}, status_code=401)
    
    try:
        # Recupera configurazione attiva
        smtp_config = db.query(SMTPConfig).filter(SMTPConfig.is_active == True).first()
        
        if not smtp_config:
            return JSONResponse({"error": "Configurazione SMTP non trovata"}, status_code=400)
        
        # Decripta credenziali
        host = decrypt_token(smtp_config.host)
        user = decrypt_token(smtp_config.user)
        password = decrypt_token(smtp_config.password)
        from_email = decrypt_token(smtp_config.from_email) if smtp_config.from_email else user
        
        # Test connessione SMTP
        test_email = current_user.email
        
        msg = MIMEText("Questa è una email di test per verificare la configurazione SMTP.")
        msg['From'] = from_email
        msg['To'] = test_email
        msg['Subject'] = "Test SMTP - Cepu Lavorazioni"
        
        with smtplib.SMTP(host, smtp_config.port or 587) as server:
            if smtp_config.use_tls:
                server.starttls()
            server.login(user, password)
            server.send_message(msg)
        
        return JSONResponse({"success": True, "message": f"Email di test inviata con successo a {test_email}"})
        
    except Exception as e:
        logger.error(f"Errore test SMTP: {e}", exc_info=True)
        return JSONResponse({"error": f"Errore test SMTP: {str(e)}"}, status_code=500)
