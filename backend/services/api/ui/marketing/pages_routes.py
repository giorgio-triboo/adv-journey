"""Pagine HTML Marketing e Prediction."""
import logging

from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from database import get_db
from models import MetaAccount, MetaCampaign, User

from ..common import templates

logger = logging.getLogger('services.api.ui')
router = APIRouter(include_in_schema=False)

@router.get("/marketing/prediction")
async def marketing_prediction(request: Request, db: Session = Depends(get_db)):
    """
    Vista Marketing Prediction (WIP) con sola documentazione e layout base.
    """
    try:
        user = request.session.get('user')
        if not user:
            return RedirectResponse(url='/')

        # Manteniamo controllo utente coerente con le altre viste
        current_user = db.query(User).filter(User.email == user.get('email')).first()
        if not current_user:
            return RedirectResponse(url='/')

        return templates.TemplateResponse(
            request,
            "marketing_prediction.html",
            {
                "request": request,
                "title": "Marketing Prediction",
                "user": user,
                "active_page": "marketing_prediction",
            },
        )
    except Exception as e:
        logger.error(f"Errore nel route /marketing/prediction: {e}", exc_info=True)
        raise

@router.get("/marketing")
async def marketing(request: Request, db: Session = Depends(get_db)):
    """Maschera Marketing - Vista unificata con tab gerarchica e dati"""
    try:
        logger.debug(f"Accesso a /marketing - verifica sessione")
        user = request.session.get('user')
        logger.debug(f"Sessione user: {user is not None}")
        if not user:
            logger.warning(f"Accesso a /marketing negato: sessione user non trovata")
            return RedirectResponse(url='/')
        
        logger.debug(f"Email utente dalla sessione: {user.get('email')}")
        current_user = db.query(User).filter(User.email == user.get('email')).first()
        if not current_user:
            logger.warning(f"Accesso a /marketing negato: utente non trovato nel DB per email {user.get('email')}")
            return RedirectResponse(url='/')
        
        logger.debug(f"Utente trovato: {current_user.id}, recupero accounts e campaigns")
        # Get user's accessible accounts
        accounts = db.query(MetaAccount).filter(
            MetaAccount.is_active == True,
        ).all()
        logger.debug(f"Trovati {len(accounts)} accounts")
        
        # Get all campaigns from accessible accounts
        campaigns = db.query(MetaCampaign).join(MetaAccount).filter(
            MetaAccount.is_active == True,
        ).order_by(MetaCampaign.name).all()
        logger.debug(f"Trovate {len(campaigns)} campaigns")
        
        logger.debug(f"Rendering template marketing.html")
        return templates.TemplateResponse(request, "marketing.html", {
            "request": request,
            "title": "Marketing ADV",
            "user": user,
            "campaigns": campaigns,
            "accounts": accounts,
            "active_page": "marketing"
        })
    except Exception as e:
        # Logga tutti gli errori del route marketing
        import traceback
        logger.error(f"Errore nel route /marketing: {e}")
        logger.error(traceback.format_exc())
        # Re-solleva l'eccezione per essere gestita dall'exception handler globale
        raise
