"""Health probe — no DB hit."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import AppSettings
from app.api.schemas import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health(cfg: AppSettings) -> HealthResponse:
    return HealthResponse(env=cfg.APP_ENV)
