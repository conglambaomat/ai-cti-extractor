---
phase: 3
title: "Problem+JSON envelope, correlation_id middleware, exception handlers"
status: pending
priority: P1
effort: "2h"
dependencies: [1]
---

# Phase 03: Error handling + correlation ID

## Overview

RFC 7807 problem+json envelope. Pure ASGI correlation_id middleware (no body buffering). Exception handler that walks `AppError` MRO → status/title/slug.

## Files

```
app/api/
├── __init__.py
├── problem.py                       # Problem model + make_problem
├── middleware/
│   ├── __init__.py
│   └── correlation_id.py            # Pure ASGI middleware
└── exception_handlers.py            # All handlers + register_exception_handlers
```

## Architecture

### `app/api/problem.py`
- `Problem` Pydantic v2 model: `type, title, status, detail, instance, correlation_id, error_code`
- `ConfigDict(frozen=True, extra="forbid")`
- `make_problem(...)` factory; `type_uri = "https://cti.local/errors/{slug}"` or `about:blank`

### `app/api/middleware/correlation_id.py`
- Pure ASGI: reads `X-Correlation-Id` only when `settings.TRUST_PROXY_HEADERS` is True; else generates UUID4
- Calls `structlog.contextvars.clear_contextvars()` then `bind_contextvars(correlation_id=...)`
- Wraps `send` to inject `x-correlation-id` response header

### `app/api/exception_handlers.py`

Status mapping table (from researcher report):

| Exception | Status | Slug |
|---|---|---|
| `UnsupportedFormatError` | 415 | unsupported-format |
| `UnsupportedLanguageError` | 422 | unsupported-language |
| `OCRFailedError` | 502 | ocr-failed |
| `EvidenceMissingError` | 422 | evidence-missing |
| `StorageError` | 500 | storage-error |
| `StixError` | 500 | stix-error |
| `ExportError` | 502 | export-error |
| `AuditChainError` | 500 | audit-chain-error (CRITICAL log + alert=True) |
| `AppError` (catch-all) | 500 | internal-error |

Handlers:
- `handle_request_validation_error` → 422 + flattened field paths in `detail`
- `handle_http_exception` → passthrough status, sanitize 5xx detail
- `handle_app_error` → walks `_APP_ERROR_MAP` MRO, gates `str(exc)` on `settings.DEBUG`
- `handle_unhandled_exception` → 500 + generic body, ERROR log with `exc_info`
- `register_exception_handlers(app)` registers all four (specific → general)

## Related Code Files

- Create: `app/api/__init__.py`
- Create: `app/api/problem.py` (~80 LOC)
- Create: `app/api/middleware/__init__.py`
- Create: `app/api/middleware/correlation_id.py` (~70 LOC)
- Create: `app/api/exception_handlers.py` (~150 LOC)
- Create: `tests/unit/api/test_problem.py`
- Create: `tests/unit/api/test_correlation_id.py`
- Create: `tests/unit/api/test_exception_handlers.py`

## Implementation Steps

1. `Problem` model + `make_problem` factory. Hypothesis test: `extra=forbid` no surprise keys.
2. Correlation ID middleware. Tests:
   - When `TRUST_PROXY_HEADERS=False`: incoming header ignored, fresh UUID generated
   - When `TRUST_PROXY_HEADERS=True`: incoming header echoed
   - Response always carries `x-correlation-id`
   - structlog contextvars bound (assert via `get_contextvars()`)
3. Exception handlers + `_APP_ERROR_MAP`. Tests:
   - `UnsupportedFormatError` → 415, content-type `application/problem+json`, `error_code` matches class name
   - `OCRFailedError` → 502
   - `AuditChainError` → 500 + CRITICAL log assertion (caplog)
   - generic `RuntimeError` → 500, no traceback in body, no internal paths leaked
   - Validation error → 422 with field paths
4. `register_exception_handlers(app)` invocation order verified.

## Success Criteria

- [ ] Problem model has 7 fields, frozen, extra=forbid
- [ ] All 5xx response bodies have NO traceback / NO file paths
- [ ] Correlation ID round-trips when trust enabled, else generated
- [ ] All handler tests green (≥ 8 tests)
- [ ] mypy --strict clean
