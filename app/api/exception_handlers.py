"""FastAPI exception handlers — every error path emits RFC 7807 problem+json.

Registration order: specific subclasses first, ``AppError`` catch-all next,
generic ``Exception`` last. A single :func:`register_exception_handlers` call
wires everything in :mod:`app.main`.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.middleware.correlation_id import get_correlation_id
from app.api.problem import PROBLEM_CONTENT_TYPE, make_problem
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
from app.core.logging import get_logger
from app.storage.backend import StorageError

log = get_logger(__name__)

# (status, title, slug). Order matters — first match in MRO wins.
_APP_ERROR_MAP: list[tuple[type[AppError], int, str, str]] = [
    (UnsupportedFormatError, 415, "Unsupported Media Type", "unsupported-format"),
    (UnsupportedLanguageError, 422, "Unprocessable Content", "unsupported-language"),
    (OCRFailedError, 502, "OCR Dependency Failure", "ocr-failed"),
    (EvidenceMissingError, 422, "Unprocessable Content", "evidence-missing"),
    (OpenCTIError, 502, "Export Dependency Failure", "opencti-error"),
    (MISPError, 502, "Export Dependency Failure", "misp-error"),
    (TAXIIError, 502, "Export Dependency Failure", "taxii-error"),
    (ExportError, 502, "Export Dependency Failure", "export-error"),
    (StorageError, 500, "Storage Failure", "storage-error"),
    (StixError, 500, "STIX Pipeline Error", "stix-error"),
    (AuditChainError, 500, "Audit Chain Integrity Violation", "audit-chain-error"),
    (AppError, 500, "Internal Server Error", "internal-error"),
]


def _instance(request: Request) -> str:
    return f"{request.url.path}#{get_correlation_id()}"


def _problem_response(
    *,
    title: str,
    status: int,
    detail: str,
    instance: str,
    error_code: str,
    type_slug: str | None,
) -> JSONResponse:
    p = make_problem(
        title=title,
        status=status,
        detail=detail,
        instance=instance,
        correlation_id=get_correlation_id(),
        error_code=error_code,
        type_slug=type_slug,
    )
    return JSONResponse(
        content=p.model_dump(),
        status_code=status,
        media_type=PROBLEM_CONTENT_TYPE,
    )


async def handle_request_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    log.warning("request_validation_error", path=request.url.path)
    detail = "; ".join(
        f"{'.'.join(str(part) for part in e['loc'])}: {e['msg']}"
        for e in exc.errors()
    ) or "request validation failed"
    return _problem_response(
        title="Unprocessable Content",
        status=422,
        detail=detail,
        instance=_instance(request),
        error_code="RequestValidationError",
        type_slug="validation",
    )


async def handle_http_exception(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    status = exc.status_code
    title = exc.detail if status < 500 else "Internal Server Error"
    detail = exc.detail if status < 500 else "An unexpected error occurred."
    if status >= 500:
        log.error("http_exception", status=status, path=request.url.path)
    else:
        log.warning("http_exception", status=status, path=request.url.path)
    return _problem_response(
        title=str(title),
        status=status,
        detail=str(detail),
        instance=_instance(request),
        error_code="HTTPException",
        type_slug=None,
    )


async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
    if isinstance(exc, AuditChainError):
        log.critical(
            "audit_chain_integrity_violation",
            path=request.url.path,
            alert=True,
            exc_info=exc,
        )
    elif isinstance(exc, AbstentionRequired):
        log.error("abstention_reached_api_boundary", exc_info=exc)

    status, title, slug = 500, "Internal Server Error", "internal-error"
    for exc_type, st, tl, sl in _APP_ERROR_MAP:
        if isinstance(exc, exc_type):
            status, title, slug = st, tl, sl
            break

    if status >= 500:
        log.error(
            "app_error",
            error_code=type(exc).__name__,
            path=request.url.path,
            exc_info=exc,
        )
        detail = str(exc) if settings.DEBUG else "An unexpected error occurred."
    else:
        log.warning(
            "app_error",
            error_code=type(exc).__name__,
            path=request.url.path,
            detail=str(exc),
        )
        detail = str(exc)

    return _problem_response(
        title=title,
        status=status,
        detail=detail,
        instance=_instance(request),
        error_code=type(exc).__name__,
        type_slug=slug,
    )


async def handle_unhandled_exception(
    request: Request, exc: Exception
) -> JSONResponse:
    log.error(
        "unhandled_exception",
        path=request.url.path,
        exc_info=exc,
    )
    detail = (
        f"{type(exc).__name__}: {exc}" if settings.DEBUG
        else "An unexpected error occurred."
    )
    return _problem_response(
        title="Internal Server Error",
        status=500,
        detail=detail,
        instance=_instance(request),
        error_code="InternalError",
        type_slug="internal-error",
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register all handlers on ``app``. Call once during create_app."""
    app.add_exception_handler(
        RequestValidationError,
        handle_request_validation_error,  # type: ignore[arg-type]
    )
    app.add_exception_handler(
        StarletteHTTPException,
        handle_http_exception,  # type: ignore[arg-type]
    )
    app.add_exception_handler(AppError, handle_app_error)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, handle_unhandled_exception)


__all__ = ["register_exception_handlers"]
