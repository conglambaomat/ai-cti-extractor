# Error Handling, Correlation ID Middleware & RFC 7807 — Research Report
**Phase 07 — API Pipeline**
**Date:** 2026-05-19
**Researcher:** researcher agent

---

## 1. Executive Summary

- RFC 7807 `application/problem+json` is the correct envelope for all error responses; it is stable (2016, updated RFC 9457 2023), widely adopted, and maps cleanly onto the existing `AppError` hierarchy via a single Pydantic model.
- Correlation ID must be bound via `structlog.contextvars.bind_contextvars` (already imported in `app/core/logging.py` as `merge_contextvars` processor) — zero new dependencies required.
- ASGI pure middleware (not `BaseHTTPMiddleware`) is preferred for correlation ID injection: avoids double-buffering the request body and has lower overhead on streaming responses.
- Exception handler registration order in FastAPI is last-registered-wins for same type; `AppError` catch-all must be registered BEFORE the generic `Exception` handler; `RequestValidationError` and `HTTPException` handlers must override FastAPI's built-ins explicitly.
- `AuditChainError` is the only exception that warrants a CRITICAL log + out-of-band alert hook; all other 5xx emit ERROR with full traceback server-side but a sanitized generic body client-side.

---

## 2. Problem JSON Schema (RFC 7807 / RFC 9457)

### 2.1 Canonical fields

| Field | Type | Required | Description |
|---|---|---|---|
| `type` | URI string | No (default `"about:blank"`) | Identifies problem type; human-readable doc at URI |
| `title` | string | No | Short human-readable summary; SHOULD NOT change per occurrence |
| `status` | integer | No | HTTP status code (mirrors response status) |
| `detail` | string | No | Human-readable explanation specific to this occurrence |
| `instance` | URI string | No | URI identifying this specific occurrence (use request path + correlation_id) |

RFC 9457 (2023) adds: `errors` array for multi-field validation problems.

Content-Type header: `application/problem+json`

### 2.2 Pydantic v2 model

```python
# app/api/problem.py
from __future__ import annotations

from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class Problem(BaseModel):
    """RFC 7807 / RFC 9457 problem+json envelope.

    Frozen + extra=forbid: prevents accidental field leakage.
    Extensions (correlation_id, error_code) are explicit fields, not **kwargs.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: str = Field(
        default="about:blank",
        description="URI identifying the problem type",
        examples=["https://cti.internal/errors/unsupported-format"],
    )
    title: str = Field(
        description="Short stable summary of the problem type",
        examples=["Unsupported document format"],
    )
    status: int = Field(
        description="HTTP status code",
        ge=400,
        le=599,
    )
    detail: str = Field(
        description="Occurrence-specific explanation (safe for client consumption)",
        examples=["File type application/x-zip is not supported. Accepted: pdf, html, txt, md"],
    )
    instance: str = Field(
        description="URI of this specific occurrence",
        examples=["/ingest#corr-550e8400-e29b-41d4-a716"],
    )
    # --- Extensions ---
    correlation_id: str = Field(
        description="Request-scoped correlation ID; echo from X-Correlation-Id or generated",
    )
    error_code: str = Field(
        description="Machine-readable error code matching AppError subclass name",
        examples=["UnsupportedFormatError", "EvidenceMissingError"],
    )


def make_problem(
    *,
    title: str,
    status: int,
    detail: str,
    instance: str,
    correlation_id: str,
    error_code: str,
    type_slug: str | None = None,
) -> Problem:
    """Factory — keeps call sites clean."""
    type_uri = (
        f"https://cti.internal/errors/{type_slug}"
        if type_slug
        else "about:blank"
    )
    return Problem(
        type=type_uri,
        title=title,
        status=status,
        detail=detail,
        instance=instance,
        correlation_id=correlation_id,
        error_code=error_code,
    )
```

### 2.3 Per-status examples

| Scenario | status | title | error_code |
|---|---|---|---|
| Bad multipart / wrong MIME | 415 | Unsupported Media Type | `UnsupportedFormatError` |
| Non-English document | 422 | Unprocessable Content | `UnsupportedLanguageError` |
| Pydantic / FastAPI validation | 422 | Unprocessable Content | `RequestValidationError` |
| Resource not found | 404 | Not Found | `NotFoundError` |
| Conflict (duplicate ingest) | 409 | Conflict | `ConflictError` |
| Internal pipeline failure | 500 | Internal Server Error | `InternalError` |

---

## 3. Correlation ID Middleware

### 3.1 ASGI pure middleware vs BaseHTTPMiddleware

| Dimension | Pure ASGI middleware | `BaseHTTPMiddleware` |
|---|---|---|
| Request body access | Must buffer manually | Auto-buffered (double memory) |
| Streaming response | No interference | Buffers entire response |
| Exception propagation | Full control | Can swallow exceptions in edge cases |
| Complexity | ~30 LOC | ~15 LOC |
| Recommended for | Header injection, logging | Simple request/response transforms |

**Decision:** Pure ASGI for correlation ID — only touches headers, no body needed.

### 3.2 Implementation sketch

```python
# app/api/middleware/correlation_id.py
from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

import structlog
from starlette.types import ASGIApp, Receive, Scope, Send

HEADER_NAME = b"x-correlation-id"
HEADER_NAME_STR = "x-correlation-id"


class CorrelationIdMiddleware:
    """Pure ASGI middleware.

    - Reads X-Correlation-Id from request headers (trusts upstream proxy).
    - Generates UUID4 if absent.
    - Binds to structlog contextvars for the duration of the request.
    - Echoes value in response headers.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        # --- Extract or generate ---
        headers: dict[bytes, bytes] = dict(scope.get("headers", []))
        raw = headers.get(HEADER_NAME)
        correlation_id = raw.decode() if raw else str(uuid.uuid4())

        # --- Bind to structlog contextvars (async-safe) ---
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(correlation_id=correlation_id)

        # --- Inject into response headers ---
        async def send_with_header(message: dict) -> None:  # type: ignore[type-arg]
            if message["type"] == "http.response.start":
                headers_list: list[tuple[bytes, bytes]] = list(
                    message.get("headers", [])
                )
                headers_list.append(
                    (HEADER_NAME, correlation_id.encode())
                )
                message = {**message, "headers": headers_list}
            await send(message)

        await self.app(scope, receive, send_with_header)
```

### 3.3 Registration

```python
# app/main.py  (registration order matters — outermost first)
app.add_middleware(CorrelationIdMiddleware)
```

### 3.4 Accessing correlation_id in handlers

```python
import structlog

def _get_correlation_id() -> str:
    ctx = structlog.contextvars.get_contextvars()
    return ctx.get("correlation_id", "unknown")
```

`merge_contextvars` is already the first processor in `app/core/logging.py` — every `log.info(...)` call automatically includes `correlation_id` with no extra work.

---

## 4. Exception Handler Registration

### 4.1 FastAPI handler precedence rules

- Handlers are matched by **exact type first**, then MRO walk — FastAPI does NOT do subclass matching automatically for `add_exception_handler`.
- Register handlers from **most specific to most general** (specific first, generic last).
- FastAPI's built-in handlers for `HTTPException` and `RequestValidationError` are registered at app creation; overriding them requires explicit `add_exception_handler` with the same types AFTER app creation, or passing `exception_handlers` dict to `FastAPI()`.
- A handler registered for `AppError` will NOT catch `HTTPException` (different hierarchy) — both must be registered.

### 4.2 Registration table

| Exception type | HTTP status | Response shape | Log level | Notes |
|---|---|---|---|---|
| `RequestValidationError` | 422 | Problem+JSON, `errors` array with field paths | WARNING | FastAPI built-in override; field paths safe to return |
| `HTTPException` / `StarletteHTTPException` | passthrough `.status_code` | Problem+JSON | WARNING (4xx) / ERROR (5xx) | Override FastAPI built-in |
| `UnsupportedFormatError` | 415 | Problem+JSON | WARNING | |
| `UnsupportedLanguageError` | 422 | Problem+JSON | WARNING | |
| `OCRFailedError` | 502 | Problem+JSON | ERROR | Upstream dependency (Tesseract) failed — 502 is correct |
| `EvidenceMissingError` | 422 | Problem+JSON | ERROR | Pipeline invariant violation; safe to surface as 422 |
| `AbstentionRequired` | 200 + `abstained: true` | NOT Problem+JSON — normal response body | INFO | Not an error; pipeline routed to review |
| `StixSchemaError` | 500 | Problem+JSON (generic) | ERROR | |
| `StixSemanticError` | 500 | Problem+JSON (generic) | ERROR | |
| `OpenCTIError` | 502 | Problem+JSON | ERROR | Upstream dependency |
| `MISPError` | 502 | Problem+JSON | ERROR | Upstream dependency |
| `TAXIIError` | 502 | Problem+JSON | ERROR | Upstream dependency |
| `AuditChainError` | 500 | Problem+JSON (generic) | CRITICAL + alert | Hash chain integrity — needs pager/alert hook |
| `AppError` (catch-all) | 500 | Problem+JSON (generic) | ERROR | Catches any unclassified AppError subclass |
| `Exception` (catch-all) | 500 | Problem+JSON (generic) | ERROR | Last resort; never leak traceback |

### 4.3 Implementation sketch

```python
# app/api/exception_handlers.py
from __future__ import annotations

import structlog
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.problem import make_problem
from app.core.config import settings
from app.core.exceptions import (
    AbstentionRequired,
    AppError,
    AuditChainError,
    EvidenceMissingError,
    ExportError,
    MISPError,
    OCRFailedError,
    OpenCTIError,
    StixError,
    TAXIIError,
    UnsupportedFormatError,
    UnsupportedLanguageError,
)

log = structlog.get_logger(__name__)

_PROBLEM_CONTENT_TYPE = "application/problem+json"

# Maps AppError subclass → (status, title, type_slug)
_APP_ERROR_MAP: dict[type[AppError], tuple[int, str, str]] = {
    UnsupportedFormatError: (415, "Unsupported Media Type", "unsupported-format"),
    UnsupportedLanguageError: (422, "Unprocessable Content", "unsupported-language"),
    OCRFailedError: (502, "OCR Dependency Failure", "ocr-failed"),
    EvidenceMissingError: (422, "Unprocessable Content", "evidence-missing"),
    OpenCTIError: (502, "Export Dependency Failure", "opencti-error"),
    MISPError: (502, "Export Dependency Failure", "misp-error"),
    TAXIIError: (502, "Export Dependency Failure", "taxii-error"),
    StixError: (500, "Internal Server Error", "stix-error"),
    AuditChainError: (500, "Internal Server Error", "audit-chain-error"),
}


def _correlation_id() -> str:
    return structlog.contextvars.get_contextvars().get("correlation_id", "unknown")


def _instance(request: Request) -> str:
    cid = _correlation_id()
    return f"{request.url.path}#{cid}"


def _problem_response(problem_kwargs: dict, status: int) -> JSONResponse:
    from app.api.problem import make_problem
    p = make_problem(**problem_kwargs)
    return JSONResponse(
        content=p.model_dump(),
        status_code=status,
        media_type=_PROBLEM_CONTENT_TYPE,
    )


async def handle_request_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    log.warning("request_validation_error", errors=exc.errors())
    detail = "; ".join(
        f"{'.'.join(str(l) for l in e['loc'])}: {e['msg']}"
        for e in exc.errors()
    )
    return _problem_response(
        {
            "title": "Unprocessable Content",
            "status": 422,
            "detail": detail,
            "instance": _instance(request),
            "correlation_id": _correlation_id(),
            "error_code": "RequestValidationError",
        },
        422,
    )


async def handle_http_exception(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    status = exc.status_code
    if status >= 500:
        log.error("http_exception", status=status, detail=exc.detail)
    else:
        log.warning("http_exception", status=status, detail=exc.detail)
    return _problem_response(
        {
            "title": exc.detail if status < 500 else "Internal Server Error",
            "status": status,
            "detail": exc.detail if status < 500 else "An unexpected error occurred.",
            "instance": _instance(request),
            "correlation_id": _correlation_id(),
            "error_code": "HTTPException",
        },
        status,
    )


async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
    if isinstance(exc, AuditChainError):
        log.critical(
            "audit_chain_integrity_violation",
            exc_info=exc,
            alert=True,  # hook: alerting processor reads this key
        )
    elif isinstance(exc, AbstentionRequired):
        # Not an error — should be caught upstream and converted to 200 body.
        # If it bubbles here, treat as 500 (pipeline bug).
        log.error("abstention_reached_api_boundary", exc_info=exc)
    
    # Walk MRO to find most specific mapping
    status, title, slug = 500, "Internal Server Error", "internal-error"
    for exc_type, mapping in _APP_ERROR_MAP.items():
        if isinstance(exc, exc_type):
            status, title, slug = mapping
            break

    is_server_error = status >= 500
    if is_server_error:
        log.error("app_error", error_code=type(exc).__name__, exc_info=exc)
        detail = "An unexpected error occurred." if not settings.DEBUG else str(exc)
    else:
        log.warning("app_error", error_code=type(exc).__name__, detail=str(exc))
        detail = str(exc)  # 4xx: safe to surface

    return _problem_response(
        {
            "title": title,
            "status": status,
            "detail": detail,
            "instance": _instance(request),
            "correlation_id": _correlation_id(),
            "error_code": type(exc).__name__,
            "type_slug": slug,
        },
        status,
    )


async def handle_unhandled_exception(
    request: Request, exc: Exception
) -> JSONResponse:
    log.error("unhandled_exception", exc_info=exc)
    return _problem_response(
        {
            "title": "Internal Server Error",
            "status": 500,
            "detail": "An unexpected error occurred.",
            "instance": _instance(request),
            "correlation_id": _correlation_id(),
            "error_code": "InternalError",
        },
        500,
    )


def register_exception_handlers(app) -> None:  # type: ignore[type-arg]
    """Call once during app factory. Order: specific → general."""
    # Override FastAPI built-ins
    app.add_exception_handler(RequestValidationError, handle_request_validation_error)
    app.add_exception_handler(StarletteHTTPException, handle_http_exception)
    # AppError subclasses — single handler walks MRO internally
    app.add_exception_handler(AppError, handle_app_error)
    # Catch-all — must be last
    app.add_exception_handler(Exception, handle_unhandled_exception)
```

### 4.4 `AbstentionRequired` — not an HTTP error

`AbstentionRequired` signals the LLM judge cannot answer with sufficient confidence. The correct handling is:

- Pipeline layer catches it, sets `abstained=True` in the response body, routes to review queue.
- If it reaches the API boundary (pipeline bug), `handle_app_error` logs ERROR and returns 500.
- Do NOT return 200 from an exception handler — that breaks HTTP semantics and client error detection.

---

## 5. Status Code Mapping Rationale

| Exception | Status | Rationale |
|---|---|---|
| `UnsupportedFormatError` | **415** | Client sent wrong MIME/format. RFC 7231 §6.5.13. Correct. |
| `UnsupportedLanguageError` | **422** | Content is syntactically valid but semantically unprocessable (non-English). 415 would be wrong (MIME is fine). |
| `OCRFailedError` | **502** | Tesseract is an upstream dependency. Its failure is not the client's fault and not an internal logic error — it's a bad gateway. 500 would conflate infra failure with code bugs. |
| `EvidenceMissingError` | **422** | The submitted document produced a claim without evidence — the input is unprocessable per project invariants. Not a 500 (no code bug); the document is the problem. |
| `AbstentionRequired` | **200 (body flag)** | Not an error. Handled in pipeline, never reaches exception handler in normal flow. |
| `StixSchemaError` / `StixSemanticError` | **500** | Internal pipeline invariant — STIX validation should have been caught before this point. Indicates a builder bug. |
| `OpenCTIError` / `MISPError` / `TAXIIError` | **502** | Upstream export targets. Their failure is not the client's fault. |
| `AuditChainError` | **500** | Internal integrity violation. CRITICAL severity. Needs alerting. |

---

## 6. Logging Strategy

### 4xx errors
- Log at **WARNING**.
- Include: `error_code`, `detail` (the user-facing message — already sanitized), `path`, `correlation_id`.
- Do NOT log full traceback (noise, and 4xx are expected operational events).
- Sanitize `detail` before logging: strip newlines to prevent log injection.

### 5xx errors
- Log at **ERROR** (CRITICAL for `AuditChainError`).
- Include: full `exc_info=exc` (traceback), `error_code`, `path`, `correlation_id`.
- Do NOT include traceback in response body (see §7).
- `structlog.processors.format_exc_info` (already in pipeline) formats traceback as structured field, not raw string — safe for JSON log aggregators.

### Log injection prevention

User-controlled strings (document titles, file names, error details from parsing) can contain `\n`, `\r`, ANSI escape codes. Mitigations:

1. structlog's `JSONRenderer` serializes strings as JSON — newlines become `\n` literals, not actual newlines. Safe in production.
2. In dev (`ConsoleRenderer`), add a sanitizer processor:

```python
import re

def _sanitize_strings(
    logger: Any, method: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Strip newlines/ANSI from string values to prevent log injection."""
    _UNSAFE = re.compile(r"[\r\n\x1b]")
    return {
        k: _UNSAFE.sub(" ", v) if isinstance(v, str) else v
        for k, v in event_dict.items()
    }
```

Insert before `ConsoleRenderer` in `_build_processors()`.

---

## 7. Security Pitfalls & Mitigations

| Pitfall | Risk | Mitigation |
|---|---|---|
| Stack trace in 5xx response | Leaks internal paths, library versions, DB schema | Never include `exc_info` in response body. Generic message + `correlation_id` only. |
| `detail` echoing user input | Reflected content injection; path traversal hints | For 5xx, always use static string. For 4xx, use pre-defined messages from exception class, not `str(exc)` directly when exc wraps user input. |
| `instance` URI leaking internal paths | Reveals route structure | Use request path (already public) + correlation_id only. No file paths, no DB IDs in `instance`. |
| Log injection via user-controlled strings | Log forging, SIEM confusion | structlog JSON renderer escapes newlines. Add `_sanitize_strings` processor for dev console. |
| Correlation ID header spoofing | Attacker sets their own ID to confuse logs | Accept from `X-Correlation-Id` only when behind trusted proxy. Add `TRUST_PROXY_HEADERS: bool = False` to Settings; when False, always generate fresh UUID. |
| `DEBUG` mode in production | Full error details exposed | `settings.DEBUG` defaults False. Only set True in development. Gate all `str(exc)` exposure behind this flag. |
| `AuditChainError` silent failure | Integrity violation goes unnoticed | Log at CRITICAL. Add alerting processor that fires on `alert=True` key in event dict (Slack/PagerDuty webhook, or write to separate alert log). |

Add `DEBUG: bool = False` to `app/core/config.py` Settings.

---

## 8. Test Patterns

### 8.1 RFC 7807 shape assertion helper

```python
# tests/unit/api/test_helpers.py
from __future__ import annotations

def assert_problem_json(response, *, status: int, error_code: str) -> dict:
    """Assert RFC 7807 shape and return parsed body."""
    assert response.status_code == status
    assert "application/problem+json" in response.headers["content-type"]
    body = response.json()
    assert body["status"] == status
    assert body["error_code"] == error_code
    assert "correlation_id" in body
    assert "instance" in body
    assert "title" in body
    assert "detail" in body
    # Security: no stack trace
    assert "traceback" not in body
    assert "Traceback" not in body.get("detail", "")
    return body
```

### 8.2 Correlation ID round-trip

```python
# tests/unit/api/test_correlation_id.py
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_correlation_id_echoed(client: AsyncClient) -> None:
    cid = "test-corr-id-12345"
    resp = await client.get("/health", headers={"X-Correlation-Id": cid})
    assert resp.headers["x-correlation-id"] == cid

@pytest.mark.asyncio
async def test_correlation_id_generated_when_absent(client: AsyncClient) -> None:
    resp = await client.get("/health")
    cid = resp.headers.get("x-correlation-id", "")
    assert len(cid) == 36  # UUID4 format
    # Validate UUID4 shape
    import uuid
    uuid.UUID(cid, version=4)  # raises if invalid
```

### 8.3 Exception handler tests

```python
# tests/unit/api/test_exception_handlers.py
import pytest
from httpx import AsyncClient
from app.core.exceptions import UnsupportedFormatError, AuditChainError

@pytest.mark.asyncio
async def test_unsupported_format_returns_415(client: AsyncClient) -> None:
    # Route that raises UnsupportedFormatError
    resp = await client.post("/ingest", content=b"fake", headers={"content-type": "application/x-zip"})
    body = assert_problem_json(resp, status=415, error_code="UnsupportedFormatError")
    assert body["type"] != "about:blank"  # has specific type URI

@pytest.mark.asyncio
async def test_500_does_not_leak_traceback(client: AsyncClient, monkeypatch) -> None:
    # Force an internal error
    from app.api import routes
    monkeypatch.setattr(routes, "some_handler", lambda: (_ for _ in ()).throw(RuntimeError("secret path /internal/db")))
    resp = await client.get("/trigger-error")
    assert resp.status_code == 500
    body = resp.json()
    assert "/internal/db" not in body["detail"]
    assert "RuntimeError" not in body["detail"]
    assert "correlation_id" in body

@pytest.mark.asyncio
async def test_correlation_id_in_problem_response(client: AsyncClient) -> None:
    cid = "my-trace-id"
    resp = await client.post(
        "/ingest",
        content=b"bad",
        headers={"X-Correlation-Id": cid, "content-type": "application/x-zip"},
    )
    body = resp.json()
    assert body["correlation_id"] == cid
    assert resp.headers["x-correlation-id"] == cid
```

### 8.4 Hypothesis — Problem model never leaks extra fields

```python
from hypothesis import given, strategies as st
from app.api.problem import Problem

@given(
    title=st.text(max_size=200),
    detail=st.text(max_size=500),
    status=st.integers(min_value=400, max_value=599),
)
def test_problem_model_extra_forbid(title: str, detail: str, status: int) -> None:
    p = Problem(
        title=title,
        status=status,
        detail=detail,
        instance="/test",
        correlation_id="abc",
        error_code="TestError",
    )
    dumped = p.model_dump()
    # extra=forbid means no surprise keys
    allowed = {"type", "title", "status", "detail", "instance", "correlation_id", "error_code"}
    assert set(dumped.keys()) == allowed
```

---

## 9. Open Questions

1. **`TRUST_PROXY_HEADERS` policy** — is the app always behind a reverse proxy (nginx/traefik) in all envs? If yes, accepting `X-Correlation-Id` from upstream is safe. If not (direct exposure), always generate fresh UUID to prevent spoofing. Needs deployment topology confirmation.

2. **`AuditChainError` alert hook** — what is the alerting target? Slack webhook, PagerDuty, or just a separate `CRITICAL` log stream that ops monitors? The `alert=True` key in the structlog event dict is a placeholder; the actual processor needs a concrete destination.

3. **`AbstentionRequired` at API boundary** — the current exception hierarchy has `AbstentionRequired` as an `ExtractionError` subclass. If it can legitimately surface at the API layer (e.g., a synchronous `/stix/validate` endpoint that runs the judge inline), the pipeline layer must catch it and convert to a structured response before returning. Confirm whether any Phase 07 endpoints run the judge synchronously.

4. **`EvidenceMissingError` as 422 vs 500** — mapped to 422 (client's document is unprocessable). If this error can also be raised by a pipeline bug (extractor forgot to attach evidence), it should be 500. Recommend adding a `source: Literal["input", "pipeline"]` field to `EvidenceMissingError` to disambiguate at the handler level.

5. **`type` URI namespace** — `https://cti.internal/errors/{slug}` is a placeholder. For a thesis-grade build, these URIs should resolve to human-readable documentation pages. Decide whether to host a static error catalog or use `about:blank` with `title` as the sole discriminator.
