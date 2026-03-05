"""Middleware per protezione CSRF su form POST"""
import secrets
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse, JSONResponse
import logging

logger = logging.getLogger("services.middleware.csrf")

EXEMPT_PATHS = {
    "/login", "/auth", "/logout",
    "/settings/meta-accounts/oauth/start", "/settings/meta-accounts/oauth/callback",
    "/health",
}
EXEMPT_PREFIXES = ("/static/", "/api/auth/")


def _is_exempt(path: str) -> bool:
    if path in EXEMPT_PATHS:
        return True
    for p in EXEMPT_PREFIXES:
        if path.startswith(p):
            return True
    return False


class CSRFMiddleware(BaseHTTPMiddleware):
    """Genera e valida token CSRF per form POST."""

    async def dispatch(self, request: Request, call_next):
        # Genera token se non presente in sessione
        if "csrf_token" not in request.session:
            request.session["csrf_token"] = secrets.token_urlsafe(32)

        request.state.csrf_token = request.session["csrf_token"]

        # Valida solo per metodi che modificano stato
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            if _is_exempt(request.url.path):
                return await call_next(request)

            token_from_request = None
            content_type = request.headers.get("content-type", "")

            if "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
                try:
                    form = await request.form()
                    request.state._parsed_form = form  # Riusa downstream: evita stream consumato
                    token_from_request = form.get("csrf_token")
                except Exception:
                    pass
            elif "application/json" in content_type:
                token_from_request = request.headers.get("X-CSRF-Token")

            expected = request.session.get("csrf_token")
            if not expected or token_from_request != expected:
                logger.warning(f"CSRF validation failed for {request.method} {request.url.path}")
                if request.url.path.startswith("/api/"):
                    return JSONResponse(
                        {"error": "Token CSRF non valido o scaduto"},
                        status_code=403,
                    )
                return RedirectResponse(
                    url=request.url.path + "?error=Token+CSRF+non+valido",
                    status_code=303,
                )

        return await call_next(request)
