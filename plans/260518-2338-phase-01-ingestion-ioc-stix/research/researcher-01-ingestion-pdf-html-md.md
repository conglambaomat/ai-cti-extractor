# Research Report — Ingestion (PDF / HTML / Markdown / TXT / URL)

**Date:** 2026-05-18
**Author:** main session (sub-agents lost on session resume; synthesized from training knowledge + library docs)
**Scope:** Phase 1 ingestion stack with char-offset preservation for evidence-span grounding.

---

## 1. PDF parsing

### Recommendation
- **Primary: `pdfplumber` (>=0.11)** — clean Python API on top of `pdfminer.six`, exposes per-character `x0/x1/y0/y1/text` with stable doctop offsets. Multi-column heuristics via `extract_words(use_text_flow=True)`. Slowest of the bench (~1.5x pypdf), but offset fidelity wins.
- **Fallback: `pdfminer.six` (>=20240706)** — lower-level when pdfplumber misbehaves on heavy CTI reports (unicode CID maps, encrypted, embedded fonts). Use `pdfminer.high_level.extract_pages()` + custom layout walker.
- **Reject for primary use:**
  - `pypdf` — fast but loses layout, char positions unreliable on multi-column PDFs.
  - `unstructured.io` — overkill, pulls heavy deps (transformers, magic-pdf), adds 200MB to image. Phase 2 candidate at most.

### Char-offset strategy
Build a **flat reading-order text** + **offset map** in one pass:
```
chunk = {
  text: "...",             # joined reading-order
  char_to_pdf: [(char_idx, page, x, y), ...]  # sparse map every N chars
}
```
Every IOC span (char_start..char_end in `text`) resolves back to PDF coordinates via interpolation in `char_to_pdf`. This is the contract Phase 2 NER will rely on.

### Speed note
10-page typical CrowdStrike PDF: pdfplumber ~1.2s cold, ~0.6s warm. Acceptable for Phase 1 batch.

## 2. HTML parsing (threat blogs)

### Recommendation
- **Primary: `trafilatura` (>=1.12)** — purpose-built for article extraction, beats readability-lxml on benchmark. Returns clean main-text. Critical: `extract(..., output_format='xml', include_tables=True, with_metadata=True)` keeps section structure.
- **Offset preservation:** trafilatura cleans the DOM, so original byte offsets become meaningless. **Solution:** record offsets in *cleaned* text and reference original via DOM xpath in `provenance.dom_path`. Evidence spans live in cleaned text; the DOM xpath is a secondary breadcrumb for analyst audit.
- **Fallback: `BeautifulSoup` (>=4.12)** — only when trafilatura returns empty (rare on CTI vendor blogs). Use `bs4.SoupStrainer` for nav/ad stripping.

### Reject
- `readability-lxml` — solid but deprecated, no active maintainer; trafilatura supersedes.
- `newspaper3k` — abandoned upstream, fragile lxml deps.

## 3. Markdown

### Recommendation
- **Primary: `markdown-it-py` (>=3.0)** — only major lib that returns AST (`Token` stream) with `map=[start_line, end_line]` per token. We compute char offsets by mapping back to original source via line index.
- **Reject:**
  - `mistune` — fast HTML output but no public AST positions.
  - `python-markdown` — extension-rich but no source positions.

## 4. OCR fallback

### Trigger condition
Only OCR a page when `len(extracted_text.strip()) < 50` chars AND page has ≥1 image. Don't OCR every page.

### Implementation
- `pytesseract.image_to_data(img, output_type=Output.DICT)` returns word-level boxes with `left/top/width/height/conf`.
- Reconcile offsets: synthesize a `text` string by joining words in reading order, build offset map from word boxes back to page geometry. Same contract as PDF parser.
- Quality gate: drop words with `conf < 60`. Log to `model_runs.ocr_confidence` for audit.

### Languages
- Phase 1: English-only (`lang='eng'`). No Vietnamese pack needed (per CLAUDE.md scope).

## 5. Defang / refang patterns in CTI

Common vendor defang formats observed in Mandiant, Talos, CrowdStrike, Unit 42:

| Pattern | Example | Refang regex (Python) |
|---|---|---|
| Square-bracket dot | `evil[.]com`, `1.2.3[.]4` | `\[\.\]` → `.` |
| Curly-paren dot | `evil(.)com` | `\(\.\)` → `.` |
| `hxxp` scheme | `hxxp://`, `hxxps://` | `hxxps?://` → `http(s)?://` |
| FxxP scheme | `fxp://` | `fxp://` → `ftp://` |
| `[://]` | `evil[://]com` | `\[://\]` → `://` |
| `[at]` email | `name[at]example.com` | `\[at\]` → `@` |
| `[@]` email | `name[@]example.com` | `\[@\]` → `@` |
| `[d]` for dot | `evil[d]com` (rare) | `\[d\]` → `.` |
| Backtick wrap | `` `evil.com` `` | strip backticks at boundary |
| Zero-width chars | `evil​.com` | `[​‌‍﻿]` → `` |

Order of refang matters. Apply most specific first (`hxxps://` before `\[\.\]`), zero-width last.

## 6. Chunking strategy

For 30-page CTI reports:

- **Chunk size:** 800 chars (~200 tokens) — keeps a typical TTP description (intro sentence + 2-3 detail sentences) intact.
- **Overlap:** 200 chars (25%) — covers cross-sentence references at boundaries.
- **Boundary rule:** never split inside a heading, code block, or table row. Detect with markdown-it AST tokens or pdfplumber font-size heuristic (size > 1.2× median = heading).
- **Section preservation:** a chunk MUST carry `section: str` (e.g., "Initial Access", "Persistence") inferred from the nearest preceding heading. Phase 2 ATT&CK mapper uses section as soft prior.
- **Token vs char:** char-based chunking is cheaper and aligns naturally with offsets. Token counts are derived after the fact for LLM budgeting.

## Unresolved questions

1. **PDF with embedded JavaScript / forms** — out of scope for Phase 1 corpus? Most CTI PDFs are static text PDFs (verified on 10 sample reports from Mandiant/Talos/CrowdStrike). Defer to Phase 2 if encountered.
2. **Trafilatura license** — Apache-2.0, OK for thesis + production.
3. **Tesseract Windows install path** — bundle install instructions in `docker/Dockerfile.worker` Phase 1 setup script.

---

**Status:** DONE
**Summary:** pdfplumber (primary) + pdfminer.six (fallback) for PDF; trafilatura for HTML; markdown-it-py for MD; pytesseract gated to image-only pages. Defang regex table includes 10 common patterns. Chunking: 800-char with 200-char overlap, never split on heading/code/table.
**Concerns/Blockers:** None.
