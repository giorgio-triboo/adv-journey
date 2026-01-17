"""Funzioni comuni condivise tra i moduli UI"""
from fastapi import Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from models import User
from typing import Tuple, Optional
import os
import logging

logger = logging.getLogger('services.api.ui')

def translate_error(error_code: str) -> str:
    """Traduce i codici di errore in messaggi italiani"""
    error_translations = {
        'not_found': 'Elemento non trovato',
        'missing_fields': 'Campi obbligatori mancanti',
        'missing_account_id': 'ID account mancante',
        'missing_token': 'Token di accesso mancante',
        'oauth_not_configured': 'OAuth non configurato',
        'invalid_state': 'Stato OAuth non valido',
        'no_code': 'Codice di autorizzazione mancante',
        'no_token': 'Token di accesso non ricevuto',
        'no_accounts': 'Nessun account disponibile',
        'session_expired': 'Sessione scaduta',
        'no_accounts_selected': 'Nessun account selezionato',
        'unauthorized': 'Non autorizzato',
        'inactive': 'Account inattivo',
        'Permissions error': 'Errore di permessi',
        'permissions_error': 'Errore di permessi',
        'Connection successful': 'Connessione riuscita',
        'Access token not configured': 'Token di accesso non configurato'
    }
    # Se il codice è già tradotto o contiene spazi, restituiscilo così com'è
    if error_code in error_translations:
        return error_translations[error_code]
    # Altrimenti prova a tradurre parti comuni
    if 'Permissions' in error_code or 'permissions' in error_code.lower():
        return 'Errore di permessi'
    if 'Access token' in error_code or 'access token' in error_code.lower():
        return 'Token di accesso non configurato'
    return error_code

# Setup templates directory
# In Docker: frontend è montato in /app/frontend
# In sviluppo locale: calcola percorso relativo alla root del progetto
if os.path.exists("frontend"):
    FRONTEND_DIR = "frontend"  # Docker container
else:
    # Da services/api/ui/common.py -> services/api/ui -> services/api -> services -> backend -> root
    FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))), "frontend")

templates = Jinja2Templates(directory=os.path.join(FRONTEND_DIR, "templates"))

# Aggiungi filtro personalizzato per formattare numeri con separatori di migliaia
def format_number_with_separator(value):
    """Formatta un numero con separatori di migliaia usando il punto come separatore"""
    if value is None:
        return "0"
    try:
        num = int(value)
        # Formatta con separatori di migliaia usando il punto
        return f"{num:,}".replace(',', '.')
    except (ValueError, TypeError):
        return str(value)

# Registra il filtro personalizzato
templates.env.filters['format_number'] = format_number_with_separator

def require_super_admin(request: Request, db: Session) -> Tuple[Optional[User], Optional[RedirectResponse]]:
    """
    Verifica che l'utente sia super-admin.
    Returns: (current_user, None) se autorizzato, (None, RedirectResponse) se non autorizzato
    """
    user_session = request.session.get('user')
    if not user_session:
        return None, RedirectResponse(url='/')
    
    current_user = db.query(User).filter(User.email == user_session.get('email')).first()
    if not current_user:
        return None, RedirectResponse(url='/')
    
    if current_user.role != 'super-admin':
        return None, RedirectResponse(url='/dashboard?error=Non autorizzato - accesso riservato a super-admin')
    
    return current_user, None
