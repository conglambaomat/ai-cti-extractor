"""Structured logging via structlog.

Dev: ConsoleRenderer with colors. Production (``APP_ENV=production``): JSON
renderer for log aggregators (Loki, ELK, Datadog).

Always returns a bound logger so a single ``log.info("msg", key=value)`` call
gets the right format with no caller-side branching.
"""

from __future__ import annotations

import logging
import sys

import structlog
from structlog.types import Processor

from app.core.config import settings


def _build_processors() -> list[Processor]:
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    if settings.APP_ENV == "production":
        shared.append(structlog.processors.JSONRenderer())
    else:
        shared.append(structlog.dev.ConsoleRenderer(colors=True))
    return shared


def configure_logging() -> None:
    """Idempotent: safe to call multiple times."""
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL),
        format="%(message)s",
        stream=sys.stdout,
    )
    structlog.configure(
        processors=_build_processors(),
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, settings.LOG_LEVEL)),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


_configured = False


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a logger bound to ``name``. First call configures the global pipeline."""
    global _configured
    if not _configured:
        configure_logging()
        _configured = True
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger


__all__ = ["configure_logging", "get_logger"]
