"""Gestione delle sessioni nel database"""
from sqlalchemy.orm import Session
from models import Session as SessionModel, User
from datetime import datetime, timedelta
import secrets
import logging

logger = logging.getLogger('services.utils.session_manager')

# Durata sessione: 14 giorni (come nel middleware originale)
SESSION_DURATION_DAYS = 14

def generate_session_id() -> str:
    """Genera un session_id univoco e sicuro"""
    return secrets.token_urlsafe(32)

def create_session(db: Session, user_id: int, session_data: dict = None) -> SessionModel:
    """
    Crea una nuova sessione nel database
    
    Args:
        db: Database session
        user_id: ID dell'utente
        session_data: Dati da memorizzare nella sessione (default: dict vuoto)
    
    Returns:
        SessionModel: La sessione creata
    """
    if session_data is None:
        session_data = {}
    
    session_id = generate_session_id()
    expires_at = datetime.utcnow() + timedelta(days=SESSION_DURATION_DAYS)
    
    session = SessionModel(
        session_id=session_id,
        user_id=user_id,
        session_data=session_data,
        is_active=True,
        expires_at=expires_at,
        last_activity=datetime.utcnow()
    )
    
    db.add(session)
    db.commit()
    db.refresh(session)
    
    logger.info(f"Sessione creata per user_id={user_id}, session_id={session_id[:8]}...")
    return session

def get_session(db: Session, session_id: str) -> SessionModel | None:
    """
    Recupera una sessione dal database
    
    Args:
        db: Database session
        session_id: ID della sessione da recuperare
    
    Returns:
        SessionModel se trovata e valida, None altrimenti
    """
    if not session_id:
        return None
    
    session = db.query(SessionModel).filter(
        SessionModel.session_id == session_id
    ).first()
    
    if not session:
        return None
    
    # Verifica che la sessione sia attiva e non scaduta
    if not session.is_active:
        logger.debug(f"Sessione {session_id[:8]}... non attiva")
        return None
    
    if session.expires_at < datetime.utcnow():
        logger.debug(f"Sessione {session_id[:8]}... scaduta")
        # Invalida automaticamente le sessioni scadute
        session.is_active = False
        db.commit()
        return None
    
    return session

def update_session_data(db: Session, session_id: str, session_data: dict):
    """
    Aggiorna i dati di una sessione
    
    Args:
        db: Database session
        session_id: ID della sessione
        session_data: Nuovi dati da memorizzare (sostituisce completamente i dati esistenti)
    """
    session = get_session(db, session_id)
    if not session:
        return
    
    session.session_data = session_data
    session.last_activity = datetime.utcnow()
    db.commit()

def update_session_activity(db: Session, session_id: str):
    """
    Aggiorna solo il timestamp di ultima attività
    
    Args:
        db: Database session
        session_id: ID della sessione
    """
    session = get_session(db, session_id)
    if not session:
        return
    
    session.last_activity = datetime.utcnow()
    db.commit()

def update_session_user(db: Session, session_id: str, user_id: int, session_data: dict = None):
    """
    Aggiorna il user_id di una sessione esistente (utile per aggiornare sessioni temporanee OAuth)
    
    Args:
        db: Database session
        session_id: ID della sessione da aggiornare
        user_id: Nuovo user_id da assegnare
        session_data: Dati opzionali da aggiornare (se None, mantiene i dati esistenti)
    """
    session = get_session(db, session_id)
    if not session:
        return None
    
    session.user_id = user_id
    if session_data is not None:
        session.session_data = session_data
    session.last_activity = datetime.utcnow()
    db.commit()
    db.refresh(session)
    
    logger.info(f"Sessione {session_id[:8]}... aggiornata con user_id={user_id}")
    return session

def invalidate_session(db: Session, session_id: str):
    """
    Invalida una sessione (logout o revoca manuale)
    
    Args:
        db: Database session
        session_id: ID della sessione da invalidare
    """
    session = db.query(SessionModel).filter(
        SessionModel.session_id == session_id
    ).first()
    
    if session:
        session.is_active = False
        db.commit()
        logger.info(f"Sessione {session_id[:8]}... invalidata")

def invalidate_user_sessions(db: Session, user_id: int, exclude_session_id: str = None):
    """
    Invalida tutte le sessioni di un utente (utile per logout da tutti i dispositivi)
    
    Args:
        db: Database session
        user_id: ID dell'utente
        exclude_session_id: Session ID da escludere dall'invalidazione (opzionale)
    """
    query = db.query(SessionModel).filter(
        SessionModel.user_id == user_id,
        SessionModel.is_active == True
    )
    
    if exclude_session_id:
        query = query.filter(SessionModel.session_id != exclude_session_id)
    
    sessions = query.all()
    for session in sessions:
        session.is_active = False
    
    db.commit()
    logger.info(f"Invalidate {len(sessions)} sessioni per user_id={user_id}")

def cleanup_expired_sessions(db: Session):
    """
    Pulisce le sessioni scadute dal database
    
    Args:
        db: Database session
    """
    now = datetime.utcnow()
    expired_sessions = db.query(SessionModel).filter(
        SessionModel.is_active == True,
        SessionModel.expires_at < now
    ).all()
    
    count = len(expired_sessions)
    for session in expired_sessions:
        session.is_active = False
    
    db.commit()
    
    if count > 0:
        logger.info(f"Pulite {count} sessioni scadute")

def get_user_from_session(db: Session, session_id: str) -> User | None:
    """
    Recupera l'utente associato a una sessione
    
    Args:
        db: Database session
        session_id: ID della sessione
    
    Returns:
        User se la sessione è valida, None altrimenti
    """
    session = get_session(db, session_id)
    if not session:
        return None
    
    user = db.query(User).filter(User.id == session.user_id).first()
    if not user or not user.is_active:
        return None
    
    return user
