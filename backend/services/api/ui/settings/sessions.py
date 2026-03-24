"""Settings: Gestione Sessioni Utenti"""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from database import get_db
from models import User, Session as SessionModel
from services.utils.session_manager import invalidate_session, invalidate_user_sessions
from ..common import templates, require_super_admin
from datetime import datetime

router = APIRouter(include_in_schema=False)

@router.get("/settings/platform/sessions")
async def settings_platform_sessions(request: Request, db: Session = Depends(get_db)):
    """Gestione Sessioni - Solo super-admin"""
    current_user, redirect = require_super_admin(request, db)
    if redirect:
        return redirect
    
    # Recupera tutte le sessioni attive con informazioni utente
    sessions = db.query(SessionModel).filter(
        SessionModel.is_active == True
    ).join(User).order_by(SessionModel.last_activity.desc()).all()
    
    # Formatta i dati per la visualizzazione
    sessions_data = []
    for session in sessions:
        user = session.user
        sessions_data.append({
            'id': session.id,
            'session_id': session.session_id[:16] + '...',  # Mostra solo primi caratteri
            'user_email': user.email,
            'user_role': user.role,
            'created_at': session.created_at,
            'last_activity': session.last_activity,
            'expires_at': session.expires_at,
            'is_expired': session.expires_at < datetime.utcnow()
        })
    
    return templates.TemplateResponse(request, "settings_platform_sessions.html", {
        "request": request,
        "title": "Gestione Sessioni",
        "user": current_user,
        "sessions": sessions_data,
        "active_page": "platform_sessions"
    })

@router.post("/settings/platform/sessions/invalidate")
async def invalidate_user_session(request: Request, db: Session = Depends(get_db)):
    """Invalida una sessione specifica - Solo super-admin"""
    current_user, redirect = require_super_admin(request, db)
    if redirect:
        return redirect
    
    form = await request.form()
    session_id = form.get("session_id")
    
    if session_id:
        # Recupera la sessione completa dal database
        session = db.query(SessionModel).filter(
            SessionModel.session_id == session_id
        ).first()
        
        if session:
            invalidate_session(db, session_id)
    
    return RedirectResponse(url='/settings/platform/sessions', status_code=303)

@router.post("/settings/platform/sessions/invalidate-user")
async def invalidate_all_user_sessions(request: Request, db: Session = Depends(get_db)):
    """Invalida tutte le sessioni di un utente - Solo super-admin"""
    current_user, redirect = require_super_admin(request, db)
    if redirect:
        return redirect
    
    form = await request.form()
    user_id = form.get("user_id")
    
    if user_id:
        try:
            user_id = int(user_id)
            invalidate_user_sessions(db, user_id)
        except ValueError:
            pass
    
    return RedirectResponse(url='/settings/platform/sessions', status_code=303)
