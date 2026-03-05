"""Settings: Gestione Utenti Platform"""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from database import get_db
from models import User
from ..common import templates, require_super_admin

router = APIRouter(include_in_schema=False)

VALID_ROLES = {"viewer", "admin", "super-admin"}

@router.get("/settings/platform/users")
async def settings_platform_users(request: Request, db: Session = Depends(get_db)):
    """Gestione Utenti - Solo super-admin"""
    current_user, redirect = require_super_admin(request, db)
    if redirect:
        return redirect
        
    users = db.query(User).all()
    
    return templates.TemplateResponse("settings_platform_users.html", {
        "request": request,
        "title": "Gestione Utenti",
        "user": current_user,
        "users": users,
        "active_page": "platform_users"
    })

# Manteniamo il vecchio endpoint per compatibilità (redirect)
@router.get("/settings/users")
async def settings_users_redirect(request: Request, db: Session = Depends(get_db)):
    """Redirect al nuovo endpoint platform"""
    return RedirectResponse(url='/settings/platform/users', status_code=301)

@router.post("/settings/platform/users")
async def add_platform_user(request: Request, db: Session = Depends(get_db)):
    """Aggiungi utente - Solo super-admin"""
    current_user, redirect = require_super_admin(request, db)
    if redirect:
        return redirect
    
    form = getattr(request.state, "_parsed_form", None) or await request.form()
    email = form.get("email")
    role = form.get("role", "viewer")
    if role not in VALID_ROLES:
        role = "viewer"
    if email:
        new_user = User(email=email, is_active=True, role=role)
        db.add(new_user)
        db.commit()
    return RedirectResponse(url='/settings/platform/users', status_code=303)

@router.post("/settings/platform/users/role")
async def update_platform_user_role(request: Request, db: Session = Depends(get_db)):
    """Aggiorna ruolo utente - Solo super-admin"""
    current_user, redirect = require_super_admin(request, db)
    if redirect:
        return redirect
    
    form = getattr(request.state, "_parsed_form", None) or await request.form()
    user_id = form.get("user_id")
    new_role = form.get("role")
    if new_role not in VALID_ROLES:
        return RedirectResponse(url='/settings/platform/users?error=ruolo_non_valido', status_code=303)

    target_user = db.query(User).filter(User.id == user_id).first()
    if target_user:
        # Prevent self-role modification
        if target_user.id == current_user.id:
            return RedirectResponse(url='/settings/platform/users', status_code=303)

        target_user.role = new_role
        db.commit()
        
    return RedirectResponse(url='/settings/platform/users', status_code=303)

@router.post("/settings/platform/users/delete")
async def delete_platform_user(request: Request, db: Session = Depends(get_db)):
    """Elimina utente - Solo super-admin"""
    current_user, redirect = require_super_admin(request, db)
    if redirect:
        return redirect
    
    form = getattr(request.state, "_parsed_form", None) or await request.form()
    user_id = form.get("user_id")
    if user_id:
        # Prevent self-deletion
        if current_user and str(current_user.id) == str(user_id):
            return RedirectResponse(url='/settings/platform/users', status_code=303)
            
        db.query(User).filter(User.id == user_id).delete()
        db.commit()
    return RedirectResponse(url='/settings/platform/users', status_code=303)

# Manteniamo i vecchi endpoint per compatibilità (redirect)
@router.post("/settings/users")
async def add_user_redirect(request: Request, db: Session = Depends(get_db)):
    return RedirectResponse(url='/settings/platform/users', status_code=301)

@router.post("/settings/users/role")
async def update_user_role_redirect(request: Request, db: Session = Depends(get_db)):
    return RedirectResponse(url='/settings/platform/users', status_code=301)

@router.post("/settings/users/delete")
async def delete_user_redirect(request: Request, db: Session = Depends(get_db)):
    return RedirectResponse(url='/settings/platform/users', status_code=301)

@router.get("/settings")
async def settings_redirect(request: Request, db: Session = Depends(get_db)):
    """Redirect a settings appropriato in base al ruolo"""
    user_session = request.session.get('user')
    if not user_session:
        return RedirectResponse(url='/')
    
    current_user = db.query(User).filter(User.email == user_session.get('email')).first()
    if current_user and current_user.role == 'super-admin':
        return RedirectResponse(url='/settings/platform/users')
    else:
        return RedirectResponse(url='/settings/campaigns')
