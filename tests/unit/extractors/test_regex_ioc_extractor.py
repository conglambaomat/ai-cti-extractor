"""End-to-end tests for ``app.extractors.regex_ioc.extract``.

These exercise the integration of patterns + defang offset map + normalize
+ deduplication. Per-type precision/recall benchmark lives in
``test_patterns_per_type.py`` (Phase 5 acceptance gate).
"""

from __future__ import annotations

from app.extractors.regex_ioc import extract
from app.ingestion.types import Chunk
from app.schemas.ioc import IocType


def _chunk(text: str, *, char_start: int = 0) -> Chunk:
    return Chunk(
        chunk_id="c-test",
        document_id="00000000-0000-0000-0000-000000000001",
        text=text,
        char_start=char_start,
        char_end=char_start + len(text),
    )


def test_extract_ipv4() -> None:
    result = extract(_chunk("Saw connections from 8.8.8.8 yesterday."))
    types = [ioc.type for ioc in result.iocs]
    assert IocType.IPV4 in types


def test_extract_defanged_domain_resolves_to_original_span() -> None:
    chunk_text = "C2 at evil[.]example.com today."
    chunk = _chunk(chunk_text, char_start=1000)
    result = extract(chunk)

    domain_iocs = [ioc for ioc in result.iocs if ioc.type is IocType.DOMAIN]
    assert len(domain_iocs) == 1
    assert domain_iocs[0].normalized == "evil.example.com"
    # `value` retains the original (still defanged)
    assert "evil[.]example.com" in domain_iocs[0].value

    # Evidence must point to absolute offset; window covers original defanged span
    evid_id = domain_iocs[0].evidence_ids[0]
    evidence = next(e for e in result.evidence if e.evidence_id == evid_id)
    assert evidence.text_span == "evil[.]example.com"
    assert evidence.char_start == chunk.char_start + chunk_text.index("evil[.]example.com")
    assert evidence.char_end == evidence.char_start + len("evil[.]example.com")


def test_dedup_same_value_two_locations_merges_evidence() -> None:
    chunk = _chunk("evil.example.com seen, then evil.example.com again.")
    result = extract(chunk)

    domain_iocs = [ioc for ioc in result.iocs if ioc.type is IocType.DOMAIN]
    assert len(domain_iocs) == 1
    assert len(domain_iocs[0].evidence_ids) == 2  # two evidences, one candidate


def test_extract_hxxps_url_normalizes_scheme() -> None:
    result = extract(_chunk("Visit hxxps://bad.example.com/x for details."))
    url_iocs = [ioc for ioc in result.iocs if ioc.type is IocType.URL]
    assert len(url_iocs) == 1
    assert url_iocs[0].normalized.startswith("https://")


def test_extract_cve_uppercased() -> None:
    result = extract(_chunk("Patched cve-2024-1234 last week."))
    cve_iocs = [ioc for ioc in result.iocs if ioc.type is IocType.CVE]
    assert len(cve_iocs) == 1
    assert cve_iocs[0].normalized == "CVE-2024-1234"


def test_extract_md5_only_when_word_bounded() -> None:
    digest = "d41d8cd98f00b204e9800998ecf8427e"
    text = f"hash is {digest} confirmed"
    result = extract(_chunk(text))
    md5_iocs = [ioc for ioc in result.iocs if ioc.type is IocType.MD5]
    assert len(md5_iocs) == 1
    assert md5_iocs[0].normalized == digest


def test_reserved_ip_rejected() -> None:
    result = extract(_chunk("internal at 192.168.1.1 only"))
    ipv4_iocs = [ioc for ioc in result.iocs if ioc.type is IocType.IPV4]
    assert ipv4_iocs == []


def test_invalid_tld_domain_rejected() -> None:
    result = extract(_chunk("see README.txt for notes"))
    domain_iocs = [ioc for ioc in result.iocs if ioc.type is IocType.DOMAIN]
    assert domain_iocs == []


def test_empty_text_yields_no_iocs() -> None:
    # Cannot construct empty chunk via Chunk model (min_length=1), use single non-IOC char
    result = extract(_chunk("x"))
    assert result.iocs == []
    assert result.evidence == []


def test_determinism_same_input_same_output() -> None:
    text = "C2 evil[.]example.com hxxps://bad.com 8.8.8.8"
    chunk = _chunk(text)
    a = extract(chunk)
    b = extract(chunk)

    assert [ioc.evidence_ids for ioc in a.iocs] == [ioc.evidence_ids for ioc in b.iocs]
    assert [e.evidence_id for e in a.evidence] == [e.evidence_id for e in b.evidence]


def test_redos_safety_on_pathological_input() -> None:
    # Worst-case "nearly an email" string repeated 5000 times should still
    # finish quickly. Tracking: pytest-timeout pinned for Phase 2; until then
    # this is a smoke check - failure mode is hang, not assertion miss.
    chunk = _chunk("a@a.aa " * 5_000)
    result = extract(chunk)
    # Should find ~1 dedup'd email across all repeats
    email_iocs = [ioc for ioc in result.iocs if ioc.type is IocType.EMAIL]
    assert len(email_iocs) <= 1
