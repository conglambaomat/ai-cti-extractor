"""Tests for FastAPI exception handlers (RFC 7807 envelope)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.exception_handlers import register_exception_handlers
from app.api.middleware.correlation_id import CorrelationIdMiddleware
from app.api.problem import PROBLEM_CONTENT_TYPE
from app.core.exceptions import (
    AuditChainError,
    EvidenceMissingError,
    OCRFailedError,
    OpenCTIError,
    UnsupportedFormatError,
    UnsupportedLanguageError,
)


def _make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)
    register_exception_handlers(app)

    @app.get("/raise/{which}")
    async def raise_route(which: str) -> dict[str, str]:  # type: ignore[no-untyped-def]
        if which == "format":
            raise UnsupportedFormatError("zip not supported")
        if which == "lang":
            raise UnsupportedLanguageError("vi not supported")
        if which == "ocr":
            raise OCRFailedError("tesseract crashed")
        if which == "evidence":
            raise EvidenceMissingError("missing")
        if which == "opencti":
            raise OpenCTIError("connection refused")
        if which == "audit":
            raise AuditChainError("hash mismatch row 42")
        if which == "boom":
            raise RuntimeError("internal /etc/secret leak")
        return {"ok": "true"}

    return app


@pytest.fixture()
async def client() -> AsyncClient:
    app = _make_app()
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _assert_problem_shape(body: dict, *, status: int, error_code: str) -> None:  # type: ignore[type-arg]
    assert body["status"] == status
    assert body["error_code"] == error_code
    assert "correlation_id" in body
    assert "instance" in body
    assert "title" in body
    assert "detail" in body


async def test_unsupported_format_returns_415(client: AsyncClient) -> None:
    r = await client.get("/raise/format")
    assert r.status_code == 415
    assert PROBLEM_CONTENT_TYPE in r.headers["content-type"]
    body = r.json()
    _assert_problem_shape(body, status=415, error_code="UnsupportedFormatError")
    assert body["type"].endswith("/errors/unsupported-format")


async def test_unsupported_language_returns_422(client: AsyncClient) -> None:
    r = await client.get("/raise/lang")
    assert r.status_code == 422
    body = r.json()
    _assert_problem_shape(body, status=422, error_code="UnsupportedLanguageError")


async def test_ocr_failure_returns_502(client: AsyncClient) -> None:
    r = await client.get("/raise/ocr")
    assert r.status_code == 502
    body = r.json()
    _assert_problem_shape(body, status=502, error_code="OCRFailedError")


async def test_evidence_missing_returns_422(client: AsyncClient) -> None:
    r = await client.get("/raise/evidence")
    assert r.status_code == 422
    body = r.json()
    _assert_problem_shape(body, status=422, error_code="EvidenceMissingError")


async def test_opencti_error_returns_502(client: AsyncClient) -> None:
    r = await client.get("/raise/opencti")
    assert r.status_code == 502
    body = r.json()
    _assert_problem_shape(body, status=502, error_code="OpenCTIError")


async def test_audit_chain_error_is_500(client: AsyncClient) -> None:
    r = await client.get("/raise/audit")
    assert r.status_code == 500
    body = r.json()
    _assert_problem_shape(body, status=500, error_code="AuditChainError")
    # AuditChainError is a 5xx — must NOT leak hash details unless DEBUG
    assert "hash mismatch" not in body["detail"]


async def test_unhandled_exception_does_not_leak_traceback(
    client: AsyncClient,
) -> None:
    r = await client.get("/raise/boom")
    assert r.status_code == 500
    body = r.json()
    _assert_problem_shape(body, status=500, error_code="InternalError")
    # No internal paths or class names leaked
    assert "/etc/secret" not in body["detail"]
    assert "RuntimeError" not in body["detail"]
    assert "Traceback" not in body["detail"]


async def test_validation_error_returns_422(client: AsyncClient) -> None:
    # Missing path param triggers 404 not validation; use a body validation route
    app = _make_app()

    from pydantic import BaseModel

    class Item(BaseModel):
        name: str
        count: int

    @app.post("/echo")
    async def echo(item: Item) -> Item:  # type: ignore[no-untyped-def]
        return item

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/echo", json={"name": "x"})
    assert r.status_code == 422
    body = r.json()
    _assert_problem_shape(body, status=422, error_code="RequestValidationError")


async def test_correlation_id_in_problem_body(client: AsyncClient) -> None:
    r = await client.get("/raise/format")
    body = r.json()
    cid = r.headers["x-correlation-id"]
    assert body["correlation_id"] == cid
    assert cid in body["instance"]
