from fastapi import APIRouter, Request, Depends
from starlette.config import Config
from starlette.requests import Request
from starlette.responses import RedirectResponse
from authlib.integrations.starlette_client import OAuth
from sqlalchemy.orm import Session
from database import get_db
from models import User
from config import settings
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

# Initialize OAuth
oauth = OAuth()
oauth.register(
    name='google',
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_id=settings.GOOGLE_CLIENT_ID,
    client_secret=settings.GOOGLE_CLIENT_SECRET,
    client_kwargs={
        'scope': 'openid email profile'
    }
)

@router.get('/login')
async def login(request: Request):
    """
    Endpoint per avviare il processo di login OAuth con Google.
    Il redirect_uri deve essere whitelisted nel Google Cloud Console.
    """
    try:
        # Costruisci l'URL di callback basato sulla richiesta corrente
        # Usa l'URL base della richiesta per costruire il redirect_uri
        base_url = str(request.base_url).rstrip('/')
        redirect_uri = f"{base_url}/auth"
        
        logger.info(f"Avvio login OAuth - redirect_uri: {redirect_uri}")
        return await oauth.google.authorize_redirect(request, redirect_uri)
    except Exception as e:
        logger.error(f"Errore durante il login OAuth: {e}", exc_info=True)
        return RedirectResponse(url='/?error=Errore durante il login')

@router.get('/auth')
async def auth_callback(request: Request, db: Session = Depends(get_db)):
    """
    Callback OAuth dopo l'autenticazione con Google.
    Verifica che l'utente sia nella whitelist e crea la sessione.
    """
    try:
        logger.info("Callback OAuth ricevuto")
        token = await oauth.google.authorize_access_token(request)
        user_info = token.get('userinfo')
        
        if not user_info:
            logger.warning("Callback OAuth: user_info non disponibile nel token")
            return RedirectResponse(url='/?error=Autenticazione fallita')
        
        email = user_info.get('email')
        if not email:
            logger.warning("Callback OAuth: email non disponibile in user_info")
            return RedirectResponse(url='/?error=Email non disponibile')
        
        logger.info(f"Callback OAuth: verifica utente con email {email}")
        
        # Check whitelist
        user = db.query(User).filter(User.email == email).first()
        if not user:
            logger.warning(f"Accesso negato: utente {email} non presente nella whitelist")
            return RedirectResponse(url='/?error=Non autorizzato')
        
        if not user.is_active:
            logger.warning(f"Accesso negato: account {email} non attivo")
            return RedirectResponse(url='/?error=Account inattivo')
        
        # Set session - include user role from database
        session_user = dict(user_info)
        session_user['role'] = user.role
        request.session['user'] = session_user
        
        logger.info(f"Login riuscito per utente {email} con ruolo {user.role}")
        return RedirectResponse(url='/dashboard')
        
    except Exception as e:
        logger.error(f"Errore durante il callback OAuth: {e}", exc_info=True)
        return RedirectResponse(url='/?error=Errore durante autenticazione')

@router.get('/logout')
async def logout(request: Request):
    request.session.pop('user', None)
    return RedirectResponse(url='/')
