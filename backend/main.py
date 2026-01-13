from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from services.auth import router as auth_router
from services.leads import router as leads_router
from services.ui import router as ui_router
from config import settings
import os

app = FastAPI(title=settings.APP_NAME)

# Session Middleware
app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY)

# Mount Static Files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Templates Configuration
templates = Jinja2Templates(directory="templates")

# Include Routers
app.include_router(auth_router)
app.include_router(leads_router)
app.include_router(ui_router)

@app.on_event("startup")
def startup_event():
    from database import engine
    from models import Base
    Base.metadata.create_all(bind=engine)
    
    from services.scheduler import start_scheduler
    start_scheduler()

@app.get("/")
async def root(request: Request):
    user = request.session.get('user')
    if user:
         return RedirectResponse(url='/dashboard')
    return templates.TemplateResponse("login.html", {"request": request, "title": "Login", "user": None})

@app.get("/health")
async def health_check():
    return {"status": "ok"}
