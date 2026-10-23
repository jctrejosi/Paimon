"""Autenticación por clave de API para las APIs públicas.

Toda petición (salvo los healthchecks) debe presentar una de las claves
definidas en `API_KEYS`, ya sea como cabecera `X-API-Key` o como
`Authorization: Bearer <clave>`.

Variables de entorno
--------------------
API_KEYS
    Claves aceptadas, separadas por comas. Es la fuente principal.
API_AUTH_REQUIRED
    `1` (defecto) exige clave. `0` desactiva la comprobación; solo para
    desarrollo local.
API_ALLOW_QUERY_TOKEN
    `1` acepta también `?token=` / `?api_key=` en la URL. Necesario para SSE
    (EventSource no permite cabeceras). Defecto `0`.
API_PUBLIC_DOCS
    `1` deja abiertos `/docs`, `/redoc` y `/openapi.json`. Defecto `0`: el
    esquema de la API también queda detrás de la clave.

Si la autenticación está activa y `API_KEYS` está vacío, se responde 503 en
lugar de dejar la API abierta (fail-closed).
"""

from __future__ import annotations

import hmac
import logging
import os
from urllib.parse import unquote_to_bytes

from starlette.responses import JSONResponse

logger = logging.getLogger("api_key_auth")

# Clave heredada aceptada además de API_KEYS. Se ajusta por servicio.
LEGACY_TOKEN_ENV: str | None = "IMAGE_API_TOKEN"

PUBLIC_PATHS = frozenset({"/health", "/healthz", "/live", "/ready"})
DOC_PATHS = frozenset({"/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"})


def require_valid_token(token: str | bytes | None) -> None:
    """Lanza 401 si la clave dada no es válida (o falta)."""
    from fastapi import HTTPException

    if not auth_required():
        return
    if not is_valid_token(token or ""):
        raise HTTPException(status_code=401, detail="Clave de API inválida o ausente.")


def require_valid_key(authorization: str | None, x_api_key: str | None) -> None:
    """Comprueba la clave en una dependencia de FastAPI.

    Acepta `X-API-Key` o `Authorization: Bearer`; lanza 401 si ninguna vale.
    """
    if not auth_required():
        return

    token = (x_api_key or "").strip()
    if not token:
        scheme, _, value = (authorization or "").partition(" ")
        token = value.strip() if scheme.lower() == "bearer" else ""

    require_valid_token(token)


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


def is_valid_token(token: str | bytes) -> bool:
    """Compara en tiempo constante contra todas las claves configuradas.

    Se comparan bytes: las cabeceras HTTP no son UTF-8, así que una clave con
    acentos llega como bytes. Al recibir un `str` (ya decodificado como latin-1
    por Starlette) se re-codifica a latin-1 para recuperar los bytes originales.
    """
    if not token:
        return False
    if isinstance(token, str):
        try:
            candidate = token.encode("latin-1")
        except UnicodeEncodeError:
            candidate = token.encode("utf-8")
    else:
        candidate = token
    return any(hmac.compare_digest(candidate, key.encode("utf-8")) for key in expected_keys())


def _header(scope, name: bytes) -> bytes:
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            return value.strip()
    return b""


def token_from_request(scope) -> bytes:
    """Extrae la clave de `X-API-Key`, `Authorization: Bearer` o la query."""
    token = _header(scope, b"x-api-key")
    if token:
        return token

    scheme, _, value = _header(scope, b"authorization").partition(b" ")
    if scheme.lower() == b"bearer" and value.strip():
        return value.strip()

    if _flag("API_ALLOW_QUERY_TOKEN"):
        for pair in scope.get("query_string", b"").split(b"&"):
            key, _, value = pair.partition(b"=")
            if key in (b"token", b"api_key") and value:
                return unquote_to_bytes(value)

    return b""


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
