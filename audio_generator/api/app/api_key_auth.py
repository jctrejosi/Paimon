"""Autenticación por clave de API para las APIs públicas.

Toda petición (salvo los healthchecks) debe presentar una de las claves definidas
en `API_KEYS`, ya sea como cabecera `X-API-Key` o como `Authorization: Bearer
<clave>`.

Variables de entorno
--------------------
API_KEYS
    Claves aceptadas, separadas por comas. Es la fuente principal.
API_AUTH_REQUIRED
    `1` (defecto) exige clave. `0` desactiva la comprobación; solo para desarrollo
    local.
API_ALLOW_QUERY_TOKEN
    `1` acepta también `?token=` / `?api_key=` en la URL (útil para SSE/WS).
API_PUBLIC_DOCS
    `1` deja abiertos `/docs`, `/redoc` y `/openapi.json`.

Si la autenticación está activa y `API_KEYS` está vacío, se responde 503 en lugar
de dejar la API abierta (fail-closed).
"""

from __future__ import annotations

import hmac
import logging
import os
from urllib.parse import parse_qs

from starlette.responses import JSONResponse

logger = logging.getLogger("api_key_auth")

# Clave heredada aceptada además de API_KEYS. Se ajusta por servicio.
LEGACY_TOKEN_ENV: str | None = "TTS_API_TOKEN"

PUBLIC_PATHS = frozenset({"/health", "/healthz", "/live", "/ready"})
DOC_PATHS = frozenset({"/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"})


def _flag(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def auth_required() -> bool:
    """Indica si la comprobación de clave está activa."""
    return _flag("API_AUTH_REQUIRED", "1")


def expected_keys() -> list[str]:
    """Claves válidas: `API_KEYS` (coma) más la heredada del servicio, si hay."""
    keys = [k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()]
    if LEGACY_TOKEN_ENV:
        legacy = (os.getenv(LEGACY_TOKEN_ENV) or "").strip()
        if legacy and legacy not in keys:
            keys.append(legacy)
    return keys


def is_valid_token(token: str) -> bool:
    """Compara en tiempo constante contra todas las claves configuradas."""
    if not token:
        return False
    candidate = token.encode("utf-8")
    return any(hmac.compare_digest(candidate, key.encode("utf-8")) for key in expected_keys())


def _header(scope, name: bytes) -> str:
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            return value.decode("latin-1").strip()
    return ""


def token_from_request(scope) -> str:
    """Extrae la clave de `X-API-Key`, `Authorization: Bearer` o la query."""
    token = _header(scope, b"x-api-key")
    if token:
        return token

    scheme, _, value = _header(scope, b"authorization").partition(" ")
    if scheme.lower() == "bearer" and value.strip():
        return value.strip()

    if _flag("API_ALLOW_QUERY_TOKEN"):
        params = parse_qs(scope.get("query_string", b"").decode("latin-1"))
        token = (params.get("token") or params.get("api_key") or [""])[0].strip()
        if token:
            return token

    return ""


class APIKeyMiddleware:
    """Middleware ASGI (no intercepta el cuerpo: compatible con streaming/SSE)."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not _flag("API_AUTH_REQUIRED", "1"):
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path in PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return
        if _flag("API_PUBLIC_DOCS") and path in DOC_PATHS:
            await self.app(scope, receive, send)
            return

        if not expected_keys():
            logger.error(
                "API_KEYS vacío con API_AUTH_REQUIRED=1: se rechazan las peticiones."
            )
            await JSONResponse(
                {"detail": "API sin claves configuradas (define API_KEYS)."},
                status_code=503,
            )(scope, receive, send)
            return

        if not is_valid_token(token_from_request(scope)):
            await JSONResponse(
                {"detail": "Clave de API inválida o ausente."},
                status_code=401,
                headers={"WWW-Authenticate": 'Bearer realm="api"'},
            )(scope, receive, send)
            return

        await self.app(scope, receive, send)
