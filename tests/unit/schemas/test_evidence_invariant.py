"""Property-based tests on the ``IocCandidate.evidence_ids`` invariant.

Hypothesis fuzzes valid + invalid shapes; the only contract under test is
"every IocCandidate has at least one evidence_id". Stronger invariants live
in ``test_intermediate_cti``.
"""

from __future__ import annotations

import string

import pytest
from app.schemas import IocCandidate, IocType
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

_HEX = st.text(alphabet=string.hexdigits.lower(), min_size=16, max_size=32)


@st.composite
def _evidence_id(draw: st.DrawFn) -> str:
    return "e-" + draw(_HEX)


@st.composite
def _ioc_value(draw: st.DrawFn) -> str:
    return draw(st.text(min_size=1, max_size=128).filter(lambda s: s.strip()))


@given(
    eids=st.lists(_evidence_id(), min_size=1, max_size=5, unique=True),
    value=_ioc_value(),
    confidence=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
)
@settings(max_examples=100, deadline=500)
def test_valid_ioc_with_evidence_passes(eids: list[str], value: str, confidence: float) -> None:
    ioc = IocCandidate(
        type=IocType.DOMAIN,
        value=value,
        normalized=value.lower(),
        evidence_ids=eids,
        confidence=confidence,
        extractor="regex_ioc@1.0.0",
    )
    assert ioc.evidence_ids == eids
    assert 0.0 <= ioc.confidence <= 1.0


@given(value=_ioc_value(), confidence=st.floats(min_value=0.0, max_value=1.0))
@settings(max_examples=20)
def test_empty_evidence_always_fails(value: str, confidence: float) -> None:
    with pytest.raises(ValidationError):
        IocCandidate(
            type=IocType.DOMAIN,
            value=value,
            normalized=value.lower(),
            evidence_ids=[],
            confidence=confidence,
            extractor="regex_ioc@1.0.0",
        )
