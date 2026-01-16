from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, JSONResponse
from starlette.middleware.sessions import SessionMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from services.api.auth import router as auth_router
from services.api.leads import router as leads_router
from services.api.ui import router as ui_router
from config import settings
import os
import time
import logging
import traceback

# Configura logging all'avvio
from logging_config import setup_logging
log_file = setup_logging(logging.INFO if not settings.DEBUG else logging.DEBUG)

logger = logging.getLogger(__name__)

app = FastAPI(title=settings.APP_NAME)

# Exception handler globale per loggare tutti gli errori
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Handler globale per catturare e loggare tutti gli errori non gestiti.
    """
    import traceback
    
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
    """
    logger.warning(
        f"HTTP {exc.status_code} su {request.method} {request.url.path}: {exc.detail}"
    )
    # Re-solleva per il comportamento di default
    raise exc

# Session Middleware con timeout esplicito (14 giorni)
app.add_middleware(
    SessionMiddleware, 
    secret_key=settings.SECRET_KEY,
    max_age=3600 * 24 * 14,  # 14 giorni in secondi
    same_site='lax'
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

# Include Routers
app.include_router(auth_router)
app.include_router(leads_router)
app.include_router(ui_router)

@app.on_event("startup")
def startup_event():
    from database import engine
    from models import Base
    Base.metadata.create_all(bind=engine)
    
    # Seed campaigns
    from seeders.campaigns_seeder import seed_campaigns
    seed_campaigns()
    
    # Start scheduler - DISABILITATO
    # from services.scheduler import start_scheduler
    # start_scheduler()
    logger.info("Scheduler disabilitato - le schedulazioni non verranno eseguite")

@app.middleware("http")
async def refresh_session_middleware(request: Request, call_next):
    """Refresh session su ogni richiesta autenticata per prevenire session_expired"""
    response = await call_next(request)
    if request.session.get('user'):
        # Aggiorna timestamp ultima attività
        request.session['last_activity'] = time.time()
        # Refresh anche token OAuth Meta se presente
        if 'meta_oauth_token_expires' in request.session:
            # Estendi scadenza token OAuth se ancora valido
            current_expires = request.session.get('meta_oauth_token_expires', 0)
            if current_expires > time.time():
                # Estendi di altri 5 minuti se mancano meno di 5 minuti
                if current_expires - time.time() < 300:
                    request.session['meta_oauth_token_expires'] = time.time() + 600
    return response

@app.get("/")
async def root(request: Request):
    user = request.session.get('user')
    if user:
         return RedirectResponse(url='/dashboard')
    return templates.TemplateResponse("login.html", {"request": request, "title": "Login", "user": None})

@app.get("/health")
async def health_check():
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
