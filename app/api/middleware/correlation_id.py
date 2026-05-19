"""Pure-ASGI correlation-ID middleware.

Reads ``X-Correlation-Id`` from incoming requests when
``settings.TRUST_PROXY_HEADERS`` is true; otherwise generates a fresh UUID4
to prevent log-spoofing in direct-exposure deployments. Binds the value via
``structlog.contextvars`` so every log call inside the request scope carries
``correlation_id`` automatically (the ``merge_contextvars`` processor is
already first in :mod:`app.core.logging`).
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import settings

CORRELATION_ID_HEADER = "x-correlation-id"
_HEADER_BYTES = CORRELATION_ID_HEADER.encode("ascii")


class CorrelationIdMiddleware:
    """Inject correlation_id into structlog contextvars + response headers."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        cid = self._resolve_id(scope)

        # Reset & bind so logs inside this request carry correlation_id.
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(correlation_id=cid)

        async def send_with_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                # Strip any pre-existing header to avoid duplicates
                headers = [h for h in headers if h[0].lower() != _HEADER_BYTES]
                headers.append((_HEADER_BYTES, cid.encode("ascii")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        finally:
            structlog.contextvars.clear_contextvars()

    @staticmethod
    def _resolve_id(scope: Scope) -> str:
        if settings.TRUST_PROXY_HEADERS:
            for name, value in scope.get("headers", []):
                if name.lower() == _HEADER_BYTES:
                    decoded: str = value.decode("ascii", errors="replace").strip()
                    if decoded:
                        return decoded
        return str(uuid.uuid4())


def get_correlation_id() -> str:
    """Return the current request's correlation ID (``"unknown"`` outside a request)."""
    ctx: dict[str, Any] = structlog.contextvars.get_contextvars()
    cid = ctx.get("correlation_id", "unknown")
    if isinstance(cid, str):
        return cid
    return str(cid)


__all__ = [
    "CORRELATION_ID_HEADER",
    "CorrelationIdMiddleware",
    "get_correlation_id",
]
