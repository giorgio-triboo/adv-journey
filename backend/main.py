from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded


def _get_client_ip(request: Request) -> str:
    """IP client per rate limiting - supporta proxy (Docker/nginx)."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware
from services.api.auth import router as auth_router
from services.middleware.csrf import CSRFMiddleware
from services.api.leads import router as leads_router
from services.api.ui import router as ui_router
from config import settings
import os
import time
import logging
import traceback
import sys

# Configura logging all'avvio
from logging_config import setup_logging
log_file = setup_logging(logging.INFO if not settings.DEBUG else logging.DEBUG)

# Logger per questo modulo - eredita gli handler dal root logger
logger = logging.getLogger(__name__)
# Assicurati che il logger propaga al root logger (default, ma esplicito)
logger.propagate = True

limiter = Limiter(key_func=_get_client_ip, default_limits=["200/minute"])
app = FastAPI(title=settings.APP_NAME)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Exception handler globale per loggare tutti gli errori non gestiti
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Handler globale per catturare e loggare tutti gli errori non gestiti.
    Non logga gli HTTPException che sono già gestiti dall'handler specifico.
    """
    import traceback
    
    # Non loggare gli HTTPException - sono già gestiti dall'handler specifico
    if isinstance(exc, StarletteHTTPException):
        raise exc
    
    # Logga l'errore completo con traceback
    error_traceback = traceback.format_exc()
    logger.error(
        f"Errore non gestito su {request.method} {request.url.path}: {str(exc)}\n"
        f"Traceback:\n{error_traceback}"
    )
    
    # Se è una richiesta API (JSON), restituisci JSON
    if request.url.path.startswith('/api/'):
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal Server Error",
                "detail": str(exc) if settings.DEBUG else "Si è verificato un errore interno"
            }
        )
    
    # Altrimenti, re-solleva l'eccezione per il comportamento di default di FastAPI
    # (che mostrerà la pagina di errore appropriata)
    raise exc

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """
    Handler per errori HTTP (404, 500, etc.) per loggarli.
    Filtra i 404 su richieste comuni che sono normali e non necessitano di log.
    """
    # Non loggare i 404 su richieste comuni - sono normali richieste del browser/bot
    if exc.status_code == 404:
        common_404_paths = [
            '/favicon.ico',
            '/robots.txt',
            '/apple-touch-icon.png',
            '/apple-touch-icon-precomposed.png',
            '/favicon.png',
            '/favicon-16x16.png',
            '/favicon-32x32.png',
        ]
        if request.url.path in common_404_paths:
            # Non loggare e non sollevare eccezione - sono normali
            return JSONResponse({"detail": "Not Found"}, status_code=404)
    
    # Raccogli informazioni dettagliate sulla richiesta
    url_info = {
        "method": request.method,
        "path": request.url.path,
        "query_string": str(request.url.query) if request.url.query else None,
        "full_url": str(request.url),
        "referer": request.headers.get("referer"),
        "user_agent": request.headers.get("user-agent"),
    }
    
    # Prova a ottenere il traceback completo
    exc_type, exc_value, exc_traceback = sys.exc_info()
    if exc_traceback:
        error_traceback = ''.join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    else:
        # Se non c'è traceback disponibile, prova a formattare l'eccezione corrente
        try:
            error_traceback = ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        except:
            error_traceback = traceback.format_exc()
    
    # Per i 404, logga a livello INFO (non DEBUG) così vengono scritti nei file
    if exc.status_code == 404:
        logger.info(f"HTTP 404 su {request.method} {request.url.path}")
    else:
        # Per altri errori HTTP, logga informazioni dettagliate
        log_message = (
            f"HTTP {exc.status_code} su {request.method} {request.url.path}\n"
            f"URL completo: {url_info['full_url']}\n"
            f"Query string: {url_info['query_string']}\n"
            f"Referer: {url_info['referer']}\n"
            f"Dettaglio errore: {exc.detail}\n"
            f"Traceback:\n{error_traceback}"
        )
        logger.error(log_message)  # Cambiato da WARNING a ERROR per assicurarsi che venga scritto
    # Re-solleva per il comportamento di default
    raise exc

# Security headers (innermost - ultimo a processare request)
from starlette.middleware.base import BaseHTTPMiddleware
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # CSP: consenti CDN Tailwind, Google Fonts, jsDelivr (flatpickr, moment, datetimerange-picker), img da https
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.tailwindcss.com https://cdn.jsdelivr.net; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https:; "
            "connect-src 'self'; "
            "frame-ancestors 'self'"
        )
        if settings.SECURE_COOKIES:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

# Ordine add_middleware: l'ultimo aggiunto è il più esterno (eseguito per primo sulla request).
# SessionMiddleware DEVE essere il più esterno perché CSRF accede a request.session.
# Ordine (request in entrata): Session -> CORS -> SlowAPI -> CSRF -> SecurityHeaders -> App
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(CSRFMiddleware)
from slowapi.middleware import SlowAPIMiddleware
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[],  # Solo same-origin; aggiungere origini se serve (es. frontend separato)
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SECRET_KEY,
    https_only=settings.SECURE_COOKIES,
    same_site="lax",
)

# Mount Static Files
# In Docker: frontend è montato in /app/frontend
# In sviluppo locale: calcola percorso relativo alla root del progetto
if os.path.exists("frontend"):
    FRONTEND_DIR = "frontend"  # Docker container
else:
    FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")  # Local dev

app.mount("/static", StaticFiles(directory=os.path.join(FRONTEND_DIR, "static")), name="static")

# Templates Configuration
templates = Jinja2Templates(directory=os.path.join(FRONTEND_DIR, "templates"))
# Starlette passa globals dict a get_template; la cache LRU di Jinja2 usa una chiave non hashabile → TypeError in prod (Python 3.13).
templates.env.cache = None

# Include Routers
app.include_router(auth_router)
app.include_router(leads_router)
app.include_router(ui_router)

@app.on_event("startup")
def startup_event():
    if not settings.DEBUG and settings.SECRET_KEY == "SUPER_SECRET_KEY_CHANGE_ME":
        logger.warning(
            "ATTENZIONE: SECRET_KEY non configurata (usa default). "
            "In produzione imposta SECRET_KEY nel file .env"
        )
    # NOTA: Le tabelle vengono create da Alembic migrations, NON da create_all()
    # Questo evita conflitti tra create_all() e le migrazioni Alembic
    
    # Seed campaigns
    from seeders.campaigns_seeder import seed_campaigns
    seed_campaigns()

    # Seed traffic platforms
    from seeders.traffic_platforms_seeder import seed_traffic_platforms
    seed_traffic_platforms()

    # Seed msg_id -> traffic platform mapping (dipende da traffic_platforms)
    from seeders.msg_traffic_mapping_seeder import seed_msg_traffic_mapping
    seed_msg_traffic_mapping()

    # Seed users
    from seeders.users_seeder import seed_users
    seed_users()

    # Seed marketing thresholds e alert config
    from seeders.marketing_threshold_config_seeder import seed_marketing_threshold_config
    from seeders.alert_config_seeder import seed_alert_configs
    seed_marketing_threshold_config()
    seed_alert_configs()

@app.middleware("http")
async def error_logging_middleware(request: Request, call_next):
    """
    Middleware per loggare tutti gli errori prima che vengano gestiti.
    Non logga gli HTTPException che verranno già loggati dall'handler specifico.
    """
    try:
        response = await call_next(request)
        return response
    except StarletteHTTPException:
        # Non loggare gli HTTPException qui - saranno loggati dall'handler specifico
        # Re-solleva per la gestione normale
        raise
    except Exception as exc:
        # Logga solo gli errori non-HTTP con traceback completo
        exc_type, exc_value, exc_traceback = sys.exc_info()
        if exc_traceback:
            error_traceback = ''.join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        else:
            # Se non c'è traceback disponibile, prova a formattare l'eccezione corrente
            try:
                error_traceback = ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            except:
                error_traceback = traceback.format_exc()
        
        # Usa logger.error per assicurarsi che venga scritto nei file di log
        logger.error(
            f"Errore durante la richiesta {request.method} {request.url.path}:\n"
            f"Tipo: {type(exc).__name__}\n"
            f"Messaggio: {str(exc)}\n"
            f"Traceback completo:\n{error_traceback}"
        )
        # Re-solleva l'eccezione per la gestione normale
        raise

@app.middleware("http")
async def refresh_session_middleware(request: Request, call_next):
    """
    Refresh session su ogni richiesta autenticata per prevenire session_expired.
    Gestisce l'estensione del token OAuth Meta se necessario.
    """
    response = await call_next(request)
    if request.session.get('user'):
        # Refresh anche token OAuth Meta se presente
        if 'meta_oauth_token_expires' in request.session:
            # Estendi scadenza token OAuth se ancora valido
            current_expires = request.session.get('meta_oauth_token_expires', 0)
            if current_expires > time.time():
                # Estendi di altri 5 minuti se mancano meno di 5 minuti
                if current_expires - time.time() < 300:
                    request.session['meta_oauth_token_expires'] = time.time() + 600
    return response

# Proxy Adminer: in dev (senza nginx) le richieste /adminer vanno al backend che le inoltra al container adminer
ADMINER_UPSTREAM = "http://adminer:8080"

@app.api_route("/adminer", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
@app.api_route("/adminer/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
@limiter.exempt
async def adminer_proxy(request: Request, path: str = ""):
    """
    Proxy verso Adminer. Richiede super-admin OAuth (stesso check di nginx auth_request in prod).
    In sviluppo senza nginx, /adminer funziona tramite questo proxy.
    """
    from fastapi.responses import Response as FastAPIResponse
    from database import SessionLocal
    from models import User

    # Auth: solo super-admin (come adminer-check)
    user_session = request.session.get("user")
    if not user_session or not user_session.get("email"):
        return RedirectResponse(url="/login?next=/adminer/")
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == user_session["email"]).first()
        if not user or not user.is_active or user.role != "super-admin":
            return RedirectResponse(url="/dashboard")
    finally:
        db.close()

    # Costruisci path verso adminer: /adminer/foo -> /foo, /adminer -> /
    upstream_path = f"/{path}" if path else "/"
    if request.url.query:
        upstream_path = f"{upstream_path}?{request.url.query}"
    url = f"{ADMINER_UPSTREAM}{upstream_path}"

    # Forward request
    import httpx
    headers = {k: v for k, v in request.headers.items() if k.lower() not in ("host", "connection")}
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            if request.method == "GET":
                resp = await client.get(url, headers=headers)
            elif request.method == "POST":
                body = await request.body()
                resp = await client.post(url, content=body, headers=headers)
            elif request.method == "PUT":
                body = await request.body()
                resp = await client.put(url, content=body, headers=headers)
            elif request.method == "DELETE":
                resp = await client.delete(url, headers=headers)
            elif request.method == "PATCH":
                body = await request.body()
                resp = await client.patch(url, content=body, headers=headers)
            elif request.method == "HEAD":
                resp = await client.head(url, headers=headers)
            elif request.method == "OPTIONS":
                resp = await client.request("OPTIONS", url, headers=headers)
            else:
                return FastAPIResponse(content="Method Not Allowed", status_code=405)

        # Restituisci risposta proxy. httpx decompressa automaticamente gzip/deflate,
        # quindi resp.content è già in chiaro: NON inoltrare content-encoding/content-length
        # (causerebbe ERR_CONTENT_DECODING_FAILED nel browser).
        response_headers = {}
        for k, v in resp.headers.items():
            if k.lower() in ("transfer-encoding", "connection", "content-encoding", "content-length"):
                continue
            if k.lower() == "location" and v.startswith("/") and not v.startswith("/adminer"):
                v = f"/adminer{v}" if v != "/" else "/adminer/"
            response_headers[k] = v
        return FastAPIResponse(content=resp.content, status_code=resp.status_code, headers=response_headers)
    except httpx.ConnectError as e:
        logger.error(f"Adminer proxy: impossibile connettersi a {ADMINER_UPSTREAM}: {e}")
        return FastAPIResponse(
            content="Adminer non disponibile. Verifica che il container adminer sia avviato (docker compose up -d).",
            status_code=503,
        )
    except Exception as e:
        logger.error(f"Adminer proxy errore: {e}", exc_info=True)
        raise

@app.get("/")
async def root(request: Request):
    user = request.session.get('user')
    if user:
         return RedirectResponse(url='/dashboard')
    return templates.TemplateResponse(request, "login.html", {"request": request, "title": "Login", "user": None})

@app.get("/health")
@limiter.exempt
async def health_check(request: Request):
    """
    Healthcheck endpoint per monitoraggio applicazione.
    Verifica connessione DB e stato generale dell'applicazione.
    """
    from datetime import datetime
    from database import engine
    
    health_status = {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "checks": {}
    }
    
    # Check database connection
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        health_status["checks"]["database"] = "ok"
    except Exception as e:
        health_status["status"] = "degraded"
        health_status["checks"]["database"] = f"error: {str(e)}"
    
    # Se il database non risponde, lo status diventa "error"
    if health_status["checks"]["database"] != "ok":
        health_status["status"] = "error"
    
    return health_status
