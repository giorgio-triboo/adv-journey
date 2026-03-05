"""Dipendenze condivise per API - autenticazione OAuth + utenti DB"""
from fastapi import Request, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import User
from typing import Optional


def get_effective_user(request: Request, db: Session) -> Optional[User]:
    """
    Ritorna l'utente "effettivo" (quello con cui stiamo agendo).
    Durante impersonazione: l'utente impersonato.
    Altrimenti: l'utente reale dalla sessione.
    """
    user_session = request.session.get("user")
    if not user_session:
        return None
    email = user_session.get("email")
    if not email:
        return None
    user = db.query(User).filter(User.email == email).first()
    return user if user and user.is_active else None


def get_real_user(request: Request, db: Session) -> Optional[User]:
    """
    Ritorna l'utente "reale" (chi ha fatto login con OAuth).
    Durante impersonazione: l'utente originale (super-admin che ha avviato impersonazione).
    Altrimenti: l'utente effettivo.
    """
    original_id = request.session.get("_impersonate_original_user_id")
    if original_id is not None:
        user = db.query(User).filter(User.id == original_id).first()
        return user if user and user.is_active else None
    return get_effective_user(request, db)


def is_impersonating(request: Request) -> bool:
    """True se la sessione è in modalità impersonazione."""
    return request.session.get("_impersonate_original_user_id") is not None


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
