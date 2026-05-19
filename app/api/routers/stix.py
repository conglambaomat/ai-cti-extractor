"""STIX bundle access + ad-hoc validation."""

from __future__ import annotations

from typing import Any

import stix2
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.api.deps import DbSession
from app.api.schemas import (
    StixValidateRequest,
    StixValidateResponse,
    StixValidationIssue,
)
from app.db.models.document import Document
from app.db.models.stix_object import StixObject

router = APIRouter()

_STIX_MEDIA_TYPE = "application/stix+json;version=2.1"


@router.get("/{doc_id}")
async def get_bundle(doc_id: str, db: DbSession) -> JSONResponse:
    doc = await db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    rows = (
        await db.execute(
            select(StixObject).where(StixObject.document_id == doc_id)
        )
    ).scalars().all()
    if not rows:
        raise HTTPException(status_code=404, detail="no STIX objects for document")
    bundle = {
        "type": "bundle",
        "id": f"bundle--{doc.id}",
        "objects": [r.json for r in rows],
    }
    return JSONResponse(content=bundle, media_type=_STIX_MEDIA_TYPE)


@router.post("/validate", response_model=StixValidateResponse)
async def validate_bundle(payload: StixValidateRequest) -> StixValidateResponse:
    """Run library + semantic validation on a user-supplied bundle.

    Pydantic-layer (Layer 1) is skipped because the inbound dict has no
    intermediate CTI to bind to; we still surface that explicitly.
    """
    issues: list[StixValidationIssue] = []
    parse_ok = True
    try:
        stix2.parse(payload.bundle, allow_custom=False)
    except (stix2.exceptions.STIXError, ValueError) as exc:
        parse_ok = False
        issues.append(
            StixValidationIssue(
                layer="parse", code="stix_parse_error", message=str(exc)
            )
        )

    semantic_ok = _check_semantics_dict(payload.bundle, issues)

    return StixValidateResponse(
        is_valid=parse_ok and semantic_ok,
        parse_ok=parse_ok,
        semantic_ok=semantic_ok,
        issues=issues,
    )


def _check_semantics_dict(
    bundle: dict[str, Any], issues: list[StixValidationIssue]
) -> bool:
    """Lightweight semantic check on a dict-shaped bundle."""
    if bundle.get("type") != "bundle":
        issues.append(
            StixValidationIssue(
                layer="semantic", code="not_a_bundle", message="root type != bundle"
            )
        )
        return False
    objs = bundle.get("objects") or []
    if not isinstance(objs, list) or not objs:
        issues.append(
            StixValidationIssue(
                layer="semantic", code="empty_bundle", message="bundle.objects is empty"
            )
        )
        return False
    by_id = {o.get("id"): o for o in objs if isinstance(o, dict)}
    ok = True
    for obj in objs:
        if obj.get("type") == "relationship":
            for ref_field in ("source_ref", "target_ref"):
                ref = obj.get(ref_field)
                if ref and ref not in by_id:
                    issues.append(
                        StixValidationIssue(
                            layer="semantic",
                            code=f"dangling_{ref_field}",
                            message=f"relationship {obj.get('id')} -> unknown {ref}",
                            target_id=obj.get("id"),
                        )
                    )
                    ok = False
        if obj.get("type") == "report":
            for ref in obj.get("object_refs", []) or []:
                if ref not in by_id:
                    issues.append(
                        StixValidationIssue(
                            layer="semantic",
                            code="dangling_report_ref",
                            message=f"report {obj.get('id')} -> unknown {ref}",
                            target_id=obj.get("id"),
                        )
                    )
                    ok = False
    return ok
