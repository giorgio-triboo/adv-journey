"""Cache in-RAM e proxy immagini creatività Meta."""
import base64
import hashlib
import logging
import time
from threading import Lock

import httpx
from fastapi import APIRouter, Request, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from database import get_db
from models import MetaAd
from services.utils.crypto import decrypt_token

logger = logging.getLogger('services.api.ui')
router = APIRouter(include_in_schema=False)

# PNG 1×1 trasparente: niente 404/502 in <img> se Meta/token/creatività non disponibili
_PLACEHOLDER_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
_PLACEHOLDER_ETAG = f'"{hashlib.md5(_PLACEHOLDER_PNG).hexdigest()}"'

# Cache in-memory per immagini proxy (riduce richieste duplicate a Meta/CDN)
PROXY_IMAGE_CACHE_TTL_SECONDS = 1800  # 30 minuti
PROXY_IMAGE_CACHE_MAX_ITEMS = 500
_proxy_image_cache: dict[int, dict] = {}
_proxy_image_cache_lock = Lock()


def _cleanup_proxy_image_cache_if_needed():
    now_ts = time.time()
    expired_keys = []
    for key, item in _proxy_image_cache.items():
        expires_at = float(item.get("expires_at", 0))
        if expires_at <= now_ts:
            expired_keys.append(key)
    for key in expired_keys:
        _proxy_image_cache.pop(key, None)

    if len(_proxy_image_cache) <= PROXY_IMAGE_CACHE_MAX_ITEMS:
        return

    # Rimuove gli elementi meno recentemente usati.
    sorted_items = sorted(
        _proxy_image_cache.items(),
        key=lambda x: float(x[1].get("last_access", 0)),
    )
    to_remove = len(_proxy_image_cache) - PROXY_IMAGE_CACHE_MAX_ITEMS
    for key, _ in sorted_items[:to_remove]:
        _proxy_image_cache.pop(key, None)


def _get_cached_proxy_image(ad_id: int):
    now_ts = time.time()
    with _proxy_image_cache_lock:
        item = _proxy_image_cache.get(ad_id)
        if not item:
            return None
        if float(item.get("expires_at", 0)) <= now_ts:
            _proxy_image_cache.pop(ad_id, None)
            return None
        item["last_access"] = now_ts
        return item


def _set_cached_proxy_image(ad_id: int, image_bytes: bytes, content_type: str, etag: str):
    now_ts = time.time()
    with _proxy_image_cache_lock:
        _proxy_image_cache[ad_id] = {
            "content": image_bytes,
            "content_type": content_type,
            "etag": etag,
            "expires_at": now_ts + PROXY_IMAGE_CACHE_TTL_SECONDS,
            "last_access": now_ts,
        }
        _cleanup_proxy_image_cache_if_needed()


def _fallback_thumbnail_response(request: Request) -> Response:
    """200 + pixel trasparente: le thumb non bloccano la pagina né generano errori in rete."""
    if request.headers.get("if-none-match") == _PLACEHOLDER_ETAG:
        return Response(
            status_code=304,
            headers={
                "ETag": _PLACEHOLDER_ETAG,
                "Cache-Control": "private, max-age=120",
            },
        )
    return Response(
        content=_PLACEHOLDER_PNG,
        media_type="image/png",
        headers={
            "ETag": _PLACEHOLDER_ETAG,
            "Cache-Control": "private, max-age=120",
        },
    )


@router.get("/api/marketing/proxy-image")
async def proxy_creative_image(request: Request, db: Session = Depends(get_db)):
    """
    Proxy per le thumbnail delle creatività Meta.
    Ottiene un URL fresco dalla Graph API (con token) poi scarica l'immagine.
    Se l'anteprima non è disponibile, risponde 200 con PNG trasparente (no 404 in tabella).
    """
    ad_id_param = request.query_params.get("ad_id")
    if not ad_id_param:
        return _fallback_thumbnail_response(request)
    try:
        ad_id_int = int(ad_id_param)
    except ValueError:
        return _fallback_thumbnail_response(request)

    cached_image = _get_cached_proxy_image(ad_id_int)
    if cached_image:
        etag = cached_image.get("etag", "")
        if request.headers.get("if-none-match") == etag:
            return Response(
                status_code=304,
                headers={
                    "ETag": etag,
                    "Cache-Control": "private, max-age=300",
                },
            )
        return Response(
            content=cached_image.get("content", b""),
            media_type=cached_image.get("content_type", "image/jpeg"),
            headers={
                "ETag": etag,
                "Cache-Control": "private, max-age=300",
            },
        )

    ad = db.query(MetaAd).filter(MetaAd.id == ad_id_int).first()
    if not ad or not ad.creative_id:
        return _fallback_thumbnail_response(request)
    account = None
    if ad.adset and ad.adset.campaign:
        account = ad.adset.campaign.account
    if not account or not account.access_token:
        return _fallback_thumbnail_response(request)
    try:
        access_token = decrypt_token(account.access_token)
    except Exception:
        logger.debug("Proxy image: decrypt token failed, fallback thumbnail")
        return _fallback_thumbnail_response(request)

    # Ottieni URL fresco dalla Graph API (evita URL scaduti/signed)
    graph_url = f"https://graph.facebook.com/v21.0/{ad.creative_id}/?fields=thumbnail_url,image_url&access_token={access_token}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(graph_url)
            r.raise_for_status()
            data = r.json()
            thumbnail_url = data.get("thumbnail_url") or data.get("image_url")
            if not thumbnail_url:
                return _fallback_thumbnail_response(request)
            # Scarica l'immagine (URL dalla Graph API è valido)
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            r2 = await client.get(thumbnail_url, headers=headers, follow_redirects=True)
            r2.raise_for_status()
            content_type = r2.headers.get("content-type", "image/jpeg")
            image_bytes = r2.content
            etag = hashlib.md5(image_bytes).hexdigest()
            _set_cached_proxy_image(
                ad_id=ad_id_int,
                image_bytes=image_bytes,
                content_type=content_type,
                etag=etag,
            )
            if request.headers.get("if-none-match") == etag:
                return Response(
                    status_code=304,
                    headers={
                        "ETag": etag,
                        "Cache-Control": "private, max-age=300",
                    },
                )
            return Response(
                content=image_bytes,
                media_type=content_type,
                headers={
                    "ETag": etag,
                    "Cache-Control": "private, max-age=300",
                },
            )
    except httpx.HTTPStatusError as e:
        logger.debug(f"Proxy image HTTP error: {e}")
        return _fallback_thumbnail_response(request)
    except Exception as e:
        logger.debug(f"Proxy image failed: {e}")
        return _fallback_thumbnail_response(request)
