"""Tests for CorrelationIdMiddleware via a stub ASGI app.

Avoids spinning up a full FastAPI app — middleware is pure ASGI so we can
exercise it directly with a contrived scope/receive/send.
"""

from __future__ import annotations

import os
import uuid

import pytest
import structlog

from app.api.middleware.correlation_id import (
    CORRELATION_ID_HEADER,
    CorrelationIdMiddleware,
    get_correlation_id,
)


async def _stub_app(scope, receive, send) -> None:  # type: ignore[no-untyped-def]
    # Capture the bound correlation_id INSIDE the request scope
    cid_inside = get_correlation_id()
    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [(b"x-cid-inside", cid_inside.encode())],
    })
    await send({"type": "http.response.body", "body": b""})


def _scope(headers: list[tuple[bytes, bytes]] | None = None) -> dict:  # type: ignore[type-arg]
    return {
        "type": "http",
        "method": "GET",
        "path": "/test",
        "headers": headers or [],
    }


class _Sink:
    def __init__(self) -> None:
        self.messages: list[dict] = []  # type: ignore[type-arg]

    async def send(self, message: dict) -> None:  # type: ignore[type-arg]
        self.messages.append(message)


async def _noop_receive() -> dict:  # type: ignore[type-arg]
    return {"type": "http.request"}


@pytest.fixture(autouse=True)
def _reset_env(monkeypatch: pytest.MonkeyPatch) -> None:
    structlog.contextvars.clear_contextvars()
    yield
    structlog.contextvars.clear_contextvars()


async def test_generates_uuid_when_no_trust(monkeypatch: pytest.MonkeyPatch) -> None:
    # Default: TRUST_PROXY_HEADERS=False -> ignore incoming, generate fresh
    from app.core import config

    monkeypatch.setattr(config.settings, "TRUST_PROXY_HEADERS", False)

    middleware = CorrelationIdMiddleware(_stub_app)
    sink = _Sink()
    incoming = "spoofed-cid-from-attacker"
    await middleware(
        _scope(headers=[(CORRELATION_ID_HEADER.encode(), incoming.encode())]),
        _noop_receive,
        sink.send,
    )

    start = next(m for m in sink.messages if m["type"] == "http.response.start")
    headers = dict(start["headers"])
    cid = headers[CORRELATION_ID_HEADER.encode()].decode()
    assert cid != incoming
    # Validate UUID4
    uuid.UUID(cid, version=4)


async def test_echoes_incoming_when_trusted(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import config

    monkeypatch.setattr(config.settings, "TRUST_PROXY_HEADERS", True)

    middleware = CorrelationIdMiddleware(_stub_app)
    sink = _Sink()
    incoming = "trusted-upstream-cid"
    await middleware(
        _scope(headers=[(CORRELATION_ID_HEADER.encode(), incoming.encode())]),
        _noop_receive,
        sink.send,
    )

    start = next(m for m in sink.messages if m["type"] == "http.response.start")
    headers = dict(start["headers"])
    assert headers[CORRELATION_ID_HEADER.encode()].decode() == incoming


async def test_skips_non_http_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    middleware = CorrelationIdMiddleware(_stub_app)
    sink = _Sink()
    await middleware({"type": "lifespan"}, _noop_receive, sink.send)
    # Stub app would have tried to send http messages; lifespan path should not raise
    # We just assert no exception raised.


async def test_clears_contextvars_after_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import config

    monkeypatch.setattr(config.settings, "TRUST_PROXY_HEADERS", False)

    middleware = CorrelationIdMiddleware(_stub_app)
    sink = _Sink()
    await middleware(_scope(), _noop_receive, sink.send)
    assert get_correlation_id() == "unknown"  # cleared
