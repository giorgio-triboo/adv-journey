from fastapi import APIRouter, Request, Depends
from fastapi.responses import PlainTextResponse
from starlette.config import Config
from starlette.requests import Request
from starlette.responses import RedirectResponse
from authlib.integrations.starlette_client import OAuth
from sqlalchemy.orm import Session
from database import get_db
from models import User
from config import settings
import logging

logger = logging.getLogger('services.api.auth')

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
        # Costruisci l'URL di callback. In produzione usa APP_BASE_URL per evitare
        # redirect_uri_mismatch quando il proxy restituisce http:// o host interno.
        if settings.APP_BASE_URL:
            base_url = settings.APP_BASE_URL.rstrip('/')
        else:
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
        query_params = dict(request.query_params)
        logger.info(f"Callback OAuth ricevuto - Query params keys: {list(query_params.keys())}")
        
        # Verifica se ci sono errori nei parametri della richiesta (da Google)
        if 'error' in query_params:
            error = query_params.get('error')
            error_description = query_params.get('error_description', 'Nessuna descrizione')
            logger.error(f"Errore OAuth da Google: {error} - {error_description}")
            return RedirectResponse(url=f'/?error=Errore OAuth: {error}')
        
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
        
        # Salva i dati dell'utente nella sessione (lato server)
        session_user = dict(user_info)
        session_user['role'] = user.role
        request.session['user'] = session_user
        request.session['user_id'] = user.id
        
        logger.info(f"Login riuscito per utente {email} con ruolo {user.role}")
        
        # Crea la risposta di redirect
        return RedirectResponse(url='/dashboard')
        
    except Exception as e:
        logger.error(f"Errore durante il callback OAuth: {type(e).__name__}: {str(e)}", exc_info=True)
        return RedirectResponse(url='/?error=Errore durante autenticazione')

@router.get("/api/auth/adminer-check")
async def adminer_check(request: Request, db: Session = Depends(get_db)):
    """
    Endpoint usato da nginx auth_request per proteggere Adminer.
    Restituisce 200 solo se l'utente è autenticato via OAuth e ha ruolo super-admin.
    """
    user_session = request.session.get("user")
    if not user_session:
        return PlainTextResponse("Unauthorized", status_code=401)
    email = user_session.get("email")
    if not email:
        return PlainTextResponse("Unauthorized", status_code=401)
    user = db.query(User).filter(User.email == email).first()
    if not user or not user.is_active or user.role != "super-admin":
        return PlainTextResponse("Unauthorized", status_code=401)
    return PlainTextResponse("OK", status_code=200)


@router.get('/logout')
async def logout(request: Request):
    """
    Logout: pulisce la sessione lato server
    """
    # Pulisci la sessione
    request.session.clear()
    logger.info("Logout: sessione pulita")
    
    return RedirectResponse(url='/')


@router.post('/api/auth/impersonate')
async def impersonate(request: Request, db: Session = Depends(get_db)):
    """
    Impersona un utente (solo super-admin).
    Permette di vedere l'app come la vedrebbe l'utente target.
    """
    from services.api.dependencies import get_real_user, is_impersonating
    real_user = get_real_user(request, db)
    if not real_user or real_user.role != "super-admin":
        return RedirectResponse(url='/dashboard?error=Impersonazione consentita solo a super-admin', status_code=303)
    if is_impersonating(request):
        return RedirectResponse(url='/dashboard?error=Esci prima dalla impersonazione attuale', status_code=303)
    form = await request.form()
    user_id_str = form.get("user_id") or request.query_params.get("user_id")
    if not user_id_str:
        return RedirectResponse(url='/settings/platform/users?error=user_id mancante', status_code=303)
    try:
        target_user_id = int(user_id_str)
    except ValueError:
        return RedirectResponse(url='/settings/platform/users?error=user_id non valido', status_code=303)
    target_user = db.query(User).filter(User.id == target_user_id).first()
    if not target_user or not target_user.is_active:
        return RedirectResponse(url='/settings/platform/users?error=Utente non trovato', status_code=303)
    if target_user.id == real_user.id:
        return RedirectResponse(url='/settings/platform/users?error=Non puoi impersonare te stesso', status_code=303)
    # Salva utente originale per restore
    request.session["_impersonate_original_user_id"] = real_user.id
    request.session["_impersonate_original_email"] = real_user.email
    # Sostituisci sessione con dati utente target
    session_user = {
        "email": target_user.email,
        "name": target_user.email.split("@")[0],
        "role": target_user.role,
    }
    request.session["user"] = session_user
    request.session["user_id"] = target_user.id
    logger.info(f"Impersonazione: {real_user.email} ora impersona {target_user.email}")
    return RedirectResponse(url='/dashboard', status_code=303)


@router.get('/api/auth/stop-impersonate')
@router.post('/api/auth/stop-impersonate')
async def stop_impersonate(request: Request, db: Session = Depends(get_db)):
    """
    Termina la impersonazione e ripristina la sessione dell'utente originale.
    """
    from services.api.dependencies import is_impersonating
    if not is_impersonating(request):
        return RedirectResponse(url='/dashboard', status_code=303)
    original_id = request.session.pop("_impersonate_original_user_id", None)
    original_email = request.session.pop("_impersonate_original_email", None)
    if not original_id or not original_email:
        request.session.clear()
        return RedirectResponse(url='/', status_code=303)
    original_user = db.query(User).filter(User.id == original_id).first()
    if not original_user or not original_user.is_active:
        request.session.clear()
        return RedirectResponse(url='/', status_code=303)
    # Ripristina sessione originale
    session_user = {
        "email": original_user.email,
        "name": original_user.email.split("@")[0],
        "role": original_user.role,
    }
    request.session["user"] = session_user
    request.session["user_id"] = original_user.id
    logger.info(f"Impersonazione terminata: ripristinato {original_user.email}")
    return RedirectResponse(url='/settings/platform/users', status_code=303)
