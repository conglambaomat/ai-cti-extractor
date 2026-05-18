---
phase: 3
title: "Ingestion layer: parsers, OCR, chunking"
status: pending
priority: P1
effort: "5d"
dependencies: [02]
file_ownership:
  create:
    - app/ingestion/__init__.py
    - app/ingestion/types.py
    - app/ingestion/dispatcher.py
    - app/ingestion/pdf_parser.py
    - app/ingestion/html_parser.py
    - app/ingestion/markdown_parser.py
    - app/ingestion/txt_parser.py
    - app/ingestion/url_fetcher.py
    - app/ingestion/ocr.py
    - app/ingestion/language.py
    - app/ingestion/chunking.py
    - app/ingestion/offset_map.py
    - tests/unit/ingestion/test_pdf_parser.py
    - tests/unit/ingestion/test_html_parser.py
    - tests/unit/ingestion/test_markdown_parser.py
    - tests/unit/ingestion/test_chunking.py
    - tests/unit/ingestion/test_language.py
    - tests/fixtures/reports/sample-mandiant-style.pdf
    - tests/fixtures/reports/sample-vendor-blog.html
    - tests/fixtures/reports/sample-report.md
    - tests/fixtures/reports/sample-image-only.pdf
---

# Phase 03 — Ingestion layer

## Overview

Convert any supported input (PDF, HTML, Markdown, TXT, URL) into a list of `Chunk` records with **char-offset preservation** so downstream extractors can ground every claim in exact source positions. Reject non-English inputs at ingestion. OCR only when a page has no text layer.

This phase is the most error-prone in Phase 1 because offset fidelity drives every other phase. Get the contract right; everything else cascades.

## Requirements

### Functional
- `dispatch(uri_or_path) -> ParsedDocument` routes to the right parser by MIME type / extension / URL scheme
- Each parser returns `ParsedDocument(text, sections[], offset_map, metadata)` where every char in `text` resolves to source position via `offset_map`
- `chunk(parsed) -> list[Chunk]` segments by section + size, never splits headings, code blocks, or tables
- `language.detect(text)` returns ISO-639-1; non-`en` raises `UnsupportedLanguageError`
- OCR triggers only on page with `len(text.strip()) < 50` AND ≥1 image

### Non-functional
- 10-page Mandiant-style PDF parses in ≤ 2s
- Property test: every chunk's `(char_start, char_end)` resolves to exact source span
- Offsets stable across re-runs
- OCR confidence < 60 → word dropped + logged; counted in `model_runs.ocr_words_dropped`
- Coverage ≥ 80% on `app/ingestion/`

## Architecture

### Type contract (`app/ingestion/types.py`)
```python
class OffsetEntry(BaseModel):
    char_idx: int
    page: int | None
    line: int | None
    x: float | None = None
    y: float | None = None

class Section(BaseModel):
    name: str          # e.g., "Initial Access"
    char_start: int
    char_end: int
    level: int = 1     # heading depth

class ParsedDocument(BaseModel):
    text: str
    sections: list[Section]
    offset_map: list[OffsetEntry]   # sparse, every N chars
    metadata: dict[str, Any]        # title, author, mime_type, etc.
    source_format: Literal["pdf","html","md","txt","url"]
    language: str                   # ISO-639-1

class Chunk(BaseModel):
    chunk_id: str
    document_id: UUID
    section: str | None
    page: int | None
    text: str
    char_start: int        # in ParsedDocument.text
    char_end: int
    token_count: int
```

### Dispatcher
- File extension → parser
- URL → `url_fetcher` → HTML/PDF based on Content-Type
- Unknown extension → MIME sniff via `python-magic` (or fallback content inspection)

### PDF parser (primary)
- `pdfplumber.open(path)`
- For each page: `page.extract_words(use_text_flow=True, keep_blank_chars=False)`
- Build `text` by concatenating words in reading order with single spaces
- Build `offset_map` entries every 256 chars referencing page + (x,y) of nearest word
- Heading detection: word with font size > 1.2 × document median size
- Section bounds: heading char_start to next heading - 1
- Fallback to `pdfminer.six.high_level.extract_text()` on `pdfplumber` exception, log degradation

### HTML parser
- `trafilatura.extract(html, output_format='xml', include_tables=True, with_metadata=True)`
- Walk XML tree to build text + section list
- Reject if extracted text < 200 chars (likely paywall / nav-only)

### Markdown parser
- `markdown_it.MarkdownIt().parse(source)`
- Walk tokens; for each `heading_open`, record section start; for paragraph/code/inline, append text
- Source line → char offset via line-prefix table

### URL fetcher
- `httpx.AsyncClient(timeout=30, follow_redirects=True)`
- Respect `robots.txt` (best effort; log if denied)
- User-Agent: `cti-extractor/0.1 (+https://github.com/conglambaomat/ai-cti-extractor)`
- Detect Content-Type, dispatch to PDF or HTML parser
- Raise `UnsupportedFormatError` for non-text content types

### OCR
- For PDFs: per page, if `extract_text(layout=True)` returns < 50 chars AND `page.images`, render page to PIL Image at 300 DPI, run `pytesseract.image_to_data(img, lang='eng', output_type=Output.DICT)`
- Reconstruct word stream sorted by `(top, left)` (Y-major)
- Drop words with `conf < 60`
- Append OCR text to page text; offset map references OCR-derived word boxes

### Language gate
- `langdetect.detect(text[:5000])` (sample first 5K chars)
- If `lang != 'en'`, raise `UnsupportedLanguageError(detected=lang)`
- Override flag `force_english: bool = False` in API for analyst manual override

### Chunking
- Walk `parsed.text`; respect `parsed.sections` boundaries
- Target 800 chars/chunk with 200 overlap
- Never split inside heading (use `sections` list)
- Never split inside code fence (detect ``` in MD; fixed-pitch font cluster in PDF)
- Never split inside Markdown table row
- Compute `token_count` lazily via `tiktoken.encoding_for_model('gpt-4o-mini').encode(text)` (only if downstream Phase 3 needs it; defer if expensive)

### Defang detection (preserve original)
Ingestion does **not** refang. Refang happens in regex IOC extractor (Phase 5). Reason: chunks store original text for evidence integrity.

## Implementation steps

1. Define `app/ingestion/types.py` Pydantic models per spec.
2. Implement `app/ingestion/offset_map.py` helper: `OffsetMap` class with `lookup(char_idx) -> OffsetEntry | None` + `build_from_words(words)`.
3. Implement `app/ingestion/pdf_parser.py`:
   - Open PDF with pdfplumber
   - Iterate pages, extract words, detect headings via font size
   - Build text + sections + offset map
   - Catch exceptions, fall back to pdfminer.six
4. Implement `app/ingestion/html_parser.py`: trafilatura primary, BeautifulSoup fallback for empty extraction.
5. Implement `app/ingestion/markdown_parser.py`: markdown-it-py with token map → char offsets.
6. Implement `app/ingestion/txt_parser.py`: trivial, but still build offset map (line-based).
7. Implement `app/ingestion/url_fetcher.py`: async fetch + dispatch.
8. Implement `app/ingestion/ocr.py`: page-level OCR gate + word extraction + offset reconciliation.
9. Implement `app/ingestion/language.py`: langdetect wrapper, raise typed exception.
10. Implement `app/ingestion/chunking.py`: section-aware chunking respecting boundaries.
11. Implement `app/ingestion/dispatcher.py`: route by extension/MIME/URL.
12. Add fixtures in `tests/fixtures/reports/`:
    - `sample-mandiant-style.pdf` — 5-page PDF with sections (Executive Summary, Initial Access, Impact)
    - `sample-vendor-blog.html` — saved Talos blog with nav/footer noise
    - `sample-report.md` — markdown with code fences + table
    - `sample-image-only.pdf` — single page scanned image
13. Write unit tests:
    - `test_pdf_parser.py`: text non-empty, sections detected, every chunk's (start,end) round-trips
    - `test_html_parser.py`: nav/footer stripped, main article preserved
    - `test_markdown_parser.py`: code fence not split; table not split
    - `test_chunking.py`: 800-char target ± 100, no split inside headings, sections preserved
    - `test_language.py`: `en` passes, `vi` raises `UnsupportedLanguageError`
14. Property test (Hypothesis) in `test_chunking.py`: for any generated `ParsedDocument`, every chunk's `text == parsed.text[chunk.char_start:chunk.char_end]`.
15. `make test && make types && make lint && make security` green.
16. Commit: `feat(p03): ingestion layer with offset preservation`. Push.

## Success criteria

- [ ] Mandiant-style PDF ingests, produces ≥3 sections, ≥10 chunks, all offsets resolve
- [ ] Vendor blog HTML strips nav/footer; main article ≥90% of original word count
- [ ] Markdown with table + code fence: chunks never split inside either
- [ ] Image-only PDF: OCR triggers; ≥80% words have conf ≥ 60
- [ ] Vietnamese sample raises `UnsupportedLanguageError`
- [ ] Property test: 100 random chunks all round-trip char_start..char_end == chunk.text
- [ ] Coverage ≥ 80% on `app/ingestion/`

## Risk assessment

| Risk | Mitigation |
|---|---|
| pdfplumber returns words out of reading order on multi-column | Sort words by `(top // line_height, left)` to enforce reading order |
| Section detection false positives (large word in body) | Combine font-size + bold + line position heuristic; allow analyst manual section override in Phase 2 |
| Trafilatura strips legitimate content | Track `extraction_ratio = len(extracted) / len(raw_html)`; if < 0.05, fallback to BeautifulSoup with main-content selector heuristic |
| Tesseract Windows path | Document `TESSERACT_CMD` env var in `.env.example`; CI uses `apt install tesseract-ocr` |
| `tiktoken` dep heavy for Phase 1 | Compute token_count lazily; default 0 in Phase 1; populate when LLM phase needs it |
| Language detect on heavily-truncated PDF (e.g., title page only) | Detect on full text not first 5K if doc < 5K chars; lower confidence threshold |
| MD parser with mixed YAML frontmatter | markdown-it-py with `frontmatter` plugin; otherwise strip lines until blank |
