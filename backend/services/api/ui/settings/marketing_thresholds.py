"""Settings: Soglie Margine e % Scarto per colorazione vista Marketing"""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from database import get_db
from models import MarketingThresholdConfig, User
from ..common import templates
from decimal import Decimal
import logging

logger = logging.getLogger("services.api.ui")

router = APIRouter(include_in_schema=False)


def _get_or_create_config(db: Session) -> MarketingThresholdConfig:
    config = db.query(MarketingThresholdConfig).first()
    if not config:
        config = MarketingThresholdConfig(
            margine_rosso_fino=Decimal("0"),
            margine_verde_da=Decimal("15"),
            scarto_verde_fino=Decimal("5"),
            scarto_rosso_da=Decimal("20"),
            colori_margine_rosso=True,
            colori_margine_verde=True,
            colori_scarto_verde=True,
            colori_scarto_rosso=True,
        )
        db.add(config)
        db.commit()
        db.refresh(config)
    return config


@router.get("/settings/marketing-thresholds")
async def settings_marketing_thresholds(request: Request, db: Session = Depends(get_db)):
    """Pagina configurazione soglie margine e scarto per colorazione Marketing"""
    user = request.session.get("user")
    if not user:
        return RedirectResponse(url="/")

    current_user = db.query(User).filter(User.email == user.get("email")).first()
    if not current_user:
        return RedirectResponse(url="/")

    config = _get_or_create_config(db)
    return templates.TemplateResponse(
        request,
        "settings_marketing_thresholds.html",
        {
            "request": request,
            "title": "Soglie Margine e Scarto",
            "user": user,
            "config": config,
            "active_page": "marketing_thresholds",
        },
    )


@router.get("/api/marketing/thresholds")
async def api_marketing_thresholds(db: Session = Depends(get_db)):
    """API: restituisce le soglie per la colorazione margine/scarto (usa dalla vista Marketing)"""
    config = _get_or_create_config(db)
    return {
        "margine_rosso_fino": float(config.margine_rosso_fino or 0),
        "margine_verde_da": float(config.margine_verde_da or 15),
        "scarto_verde_fino": float(config.scarto_verde_fino or 5),
        "scarto_rosso_da": float(config.scarto_rosso_da or 20),
        "colori_margine_rosso": bool(getattr(config, "colori_margine_rosso", True)),
        "colori_margine_verde": bool(getattr(config, "colori_margine_verde", True)),
        "colori_scarto_verde": bool(getattr(config, "colori_scarto_verde", True)),
        "colori_scarto_rosso": bool(getattr(config, "colori_scarto_rosso", True)),
    }


@router.post("/api/marketing/thresholds")
async def api_save_marketing_thresholds(request: Request, db: Session = Depends(get_db)):
    """API: salva le soglie margine e scarto"""
    user = request.session.get("user")
    if not user:
        return JSONResponse({"error": "Non autorizzato"}, status_code=401)

    current_user = db.query(User).filter(User.email == user.get("email")).first()
    if not current_user or current_user.role not in ("admin", "super-admin"):
        return JSONResponse({"error": "Non autorizzato"}, status_code=403)

    try:
        data = await request.json()
        config = _get_or_create_config(db)

        colori_margine_rosso = data.get("colori_margine_rosso")
        colori_margine_verde = data.get("colori_margine_verde")
        colori_scarto_verde = data.get("colori_scarto_verde")
        colori_scarto_rosso = data.get("colori_scarto_rosso")
        margine_rosso = data.get("margine_rosso_fino")
        margine_verde = data.get("margine_verde_da")
        scarto_verde = data.get("scarto_verde_fino")
        scarto_rosso = data.get("scarto_rosso_da")

        if colori_margine_rosso is not None:
            config.colori_margine_rosso = bool(colori_margine_rosso)
        if colori_margine_verde is not None:
            config.colori_margine_verde = bool(colori_margine_verde)
        if colori_scarto_verde is not None:
            config.colori_scarto_verde = bool(colori_scarto_verde)
        if colori_scarto_rosso is not None:
            config.colori_scarto_rosso = bool(colori_scarto_rosso)
        if margine_rosso is not None:
            config.margine_rosso_fino = Decimal(str(margine_rosso))
        if margine_verde is not None:
            config.margine_verde_da = Decimal(str(margine_verde))
        if scarto_verde is not None:
            config.scarto_verde_fino = Decimal(str(scarto_verde))
        if scarto_rosso is not None:
            config.scarto_rosso_da = Decimal(str(scarto_rosso))

        db.commit()
        db.refresh(config)
        return {
            "margine_rosso_fino": float(config.margine_rosso_fino or 0),
            "margine_verde_da": float(config.margine_verde_da or 15),
            "scarto_verde_fino": float(config.scarto_verde_fino or 5),
            "scarto_rosso_da": float(config.scarto_rosso_da or 20),
            "colori_margine_rosso": bool(config.colori_margine_rosso),
            "colori_margine_verde": bool(config.colori_margine_verde),
            "colori_scarto_verde": bool(config.colori_scarto_verde),
            "colori_scarto_rosso": bool(config.colori_scarto_rosso),
        }
    except Exception as e:
        logger.exception("Errore salvataggio soglie marketing: %s", e)
        return JSONResponse({"error": str(e)}, status_code=500)
