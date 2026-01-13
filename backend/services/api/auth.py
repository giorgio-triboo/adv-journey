from fastapi import APIRouter, Request, Depends
from starlette.config import Config
from starlette.requests import Request
from starlette.responses import RedirectResponse
from authlib.integrations.starlette_client import OAuth
from sqlalchemy.orm import Session
from database import get_db
from models import User
from config import settings

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
    # The redirect_uri must be whitelisted in your Google Cloud Console.
    # Based on the provided client_secret.json, you might need to add:
    # http://localhost:8000/auth
    # to your "Authorized redirect URIs" in the Google Cloud Console.
    redirect_uri = request.url_for('auth_callback')
    return await oauth.google.authorize_redirect(request, redirect_uri)

@router.get('/auth')
async def auth_callback(request: Request, db: Session = Depends(get_db)):
    token = await oauth.google.authorize_access_token(request)
    user_info = token.get('userinfo')
    
    if not user_info:
        return RedirectResponse(url='/')

    email = user_info.get('email')
    
    # Check whitelist
    user = db.query(User).filter(User.email == email).first()
    if not user:
         # Auto-reject or create as inactive? 
         # Plan says "whitelist enforcement", so imply rejection if not exists or not specific logic.
         # For MVP, let's create inactive viewer if not found, or reject.
         # Let's reject for now if strict whitelist. 
         # Actually, implementation plan said "Implement Auth System (Google OAuth + Whitelist)"
         # Let's assume we need to manually add users to DB to whitelist them.
         return RedirectResponse(url='/?error=unauthorized')

    if not user.is_active:
        return RedirectResponse(url='/?error=inactive')

    # Set session
    request.session['user'] = dict(user_info)
    return RedirectResponse(url='/dashboard')

@router.get('/logout')
async def logout(request: Request):
    request.session.pop('user', None)
    return RedirectResponse(url='/')
