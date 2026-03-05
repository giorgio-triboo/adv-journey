"""Settings: Piattaforme traffico"""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from database import get_db
from models import TrafficPlatform, User
from ..common import templates
import re
import logging

logger = logging.getLogger("services.api.ui")

router = APIRouter(include_in_schema=False)


def _slugify(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[-\s]+", "-", s)
    return s or "platform"


@router.get("/settings/traffic-platforms")
async def settings_traffic_platforms(request: Request, db: Session = Depends(get_db)):
    """Pagina configurazione piattaforme traffico"""
    user = request.session.get("user")
    if not user:
        return RedirectResponse(url="/")

    current_user = db.query(User).filter(User.email == user.get("email")).first()
    if not current_user:
        return RedirectResponse(url="/")

    platforms = db.query(TrafficPlatform).order_by(
        TrafficPlatform.display_order.asc(),
        TrafficPlatform.name.asc()
    ).all()

    return templates.TemplateResponse(
        "settings_traffic_platforms.html",
        {
            "request": request,
            "title": "Piattaforme Traffico",
            "user": user,
            "platforms": platforms,
            "active_page": "traffic_platforms",
        },
    )


@router.get("/api/traffic-platforms")
async def api_list_traffic_platforms(db: Session = Depends(get_db)):
    """API: lista piattaforme attive"""
    platforms = db.query(TrafficPlatform).filter(TrafficPlatform.is_active == True).order_by(
        TrafficPlatform.display_order.asc(),
        TrafficPlatform.name.asc()
    ).all()
    return [{"id": p.id, "name": p.name, "slug": p.slug, "display_order": p.display_order} for p in platforms]


@router.post("/api/traffic-platforms")
async def api_create_traffic_platform(request: Request, db: Session = Depends(get_db)):
    """API: crea piattaforma"""
    user = request.session.get("user")
    if not user:
        return JSONResponse({"error": "Non autorizzato"}, status_code=401)

    current_user = db.query(User).filter(User.email == user.get("email")).first()
    if not current_user or current_user.role not in ("admin", "super-admin"):
        return JSONResponse({"error": "Non autorizzato"}, status_code=403)

    try:
        data = await request.json()
        name = (data.get("name") or "").strip()
        if not name:
            return JSONResponse({"error": "Nome obbligatorio"}, status_code=400)

        slug = (data.get("slug") or _slugify(name)).strip() or _slugify(name)
        display_order = int(data.get("display_order", 0))

        existing = db.query(TrafficPlatform).filter(
            (TrafficPlatform.name == name) | (TrafficPlatform.slug == slug)
        ).first()
        if existing:
            return JSONResponse({"error": "Piattaforma già esistente"}, status_code=400)

        platform = TrafficPlatform(name=name, slug=slug, display_order=display_order)
        db.add(platform)
        db.commit()
        db.refresh(platform)
        return {"id": platform.id, "name": platform.name, "slug": platform.slug, "display_order": platform.display_order}
    except Exception as e:
        logger.exception("Errore creazione piattaforma: %s", e)
        return JSONResponse({"error": str(e)}, status_code=500)


@router.put("/api/traffic-platforms/{platform_id}")
async def api_update_traffic_platform(platform_id: int, request: Request, db: Session = Depends(get_db)):
    """API: aggiorna piattaforma"""
    user = request.session.get("user")
    if not user:
        return JSONResponse({"error": "Non autorizzato"}, status_code=401)

    current_user = db.query(User).filter(User.email == user.get("email")).first()
    if not current_user or current_user.role not in ("admin", "super-admin"):
        return JSONResponse({"error": "Non autorizzato"}, status_code=403)

    platform = db.query(TrafficPlatform).filter(TrafficPlatform.id == platform_id).first()
    if not platform:
        return JSONResponse({"error": "Piattaforma non trovata"}, status_code=404)

    try:
        data = await request.json()
        if "name" in data:
            platform.name = (data["name"] or "").strip() or platform.name
        if "slug" in data:
            platform.slug = (data["slug"] or _slugify(platform.name)).strip() or platform.slug
        if "display_order" in data:
            platform.display_order = int(data["display_order"])
        if "is_active" in data:
            platform.is_active = bool(data["is_active"])
        db.commit()
        db.refresh(platform)
        return {"id": platform.id, "name": platform.name, "slug": platform.slug, "display_order": platform.display_order, "is_active": platform.is_active}
    except Exception as e:
        logger.exception("Errore aggiornamento piattaforma: %s", e)
        return JSONResponse({"error": str(e)}, status_code=500)


@router.delete("/api/traffic-platforms/{platform_id}")
async def api_delete_traffic_platform(platform_id: int, request: Request, db: Session = Depends(get_db)):
    """API: elimina piattaforma"""
    user = request.session.get("user")
    if not user:
        return JSONResponse({"error": "Non autorizzato"}, status_code=401)

    current_user = db.query(User).filter(User.email == user.get("email")).first()
    if not current_user or current_user.role not in ("admin", "super-admin"):
        return JSONResponse({"error": "Non autorizzato"}, status_code=403)

    platform = db.query(TrafficPlatform).filter(TrafficPlatform.id == platform_id).first()
    if not platform:
        return JSONResponse({"error": "Piattaforma non trovata"}, status_code=404)

    db.delete(platform)
    db.commit()
    return {"ok": True}
