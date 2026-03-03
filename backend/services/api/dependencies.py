"""Dipendenze condivise per API - autenticazione OAuth + utenti DB"""
from fastapi import Request, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import User


def require_api_user(request: Request, db: Session = Depends(get_db)) -> User:
    """
    Richiede utente autenticato via OAuth Google e presente nel database.
    Usare per tutte le API che devono essere protette.
    """
    user_session = request.session.get("user")
    if not user_session:
        raise HTTPException(status_code=401, detail="Autenticazione richiesta")
    
    email = user_session.get("email")
    if not email:
        raise HTTPException(status_code=401, detail="Sessione non valida")
    
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Utente non autorizzato")
    
    if not user.is_active:
        raise HTTPException(status_code=401, detail="Account inattivo")
    
    return user
