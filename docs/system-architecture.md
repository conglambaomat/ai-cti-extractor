# System Architecture

**Project:** AI-Assisted CTI Extractor
**Last updated:** 2026-05-18
**Source:** Distilled from [`AI-assisted_CTI_extractor.md`](./AI-assisted_CTI_extractor.md)

---

## 1. Architectural pattern

**Hybrid neuro-symbolic pipeline with evidence-grounded outputs.**

```
+-----------------------------------------------------------+
|  Ingestion  ->  Chunking  ->  Extraction  ->  RAG Judge   |
|                                                           |
|     |             |             |              |         |
|     v             v             v              v         |
|  Provenance   Chunk store   Candidates    Grounded refs   |
+----------------------------+------------------------------+
                             |
                             v
+-----------------------------------------------------------+
|  Entity resolution  ->  Confidence  ->  STIX build        |
|  Knowledge graph        scoring         + validation      |
+----------------------------+------------------------------+
                             |
                             v
+-----------------------------------------------------------+
|        Human review  ->  Audit log  ->  Export            |
|                                          OpenCTI / MISP   |
|                                          TAXII / SIEM     |
+-----------------------------------------------------------+
```

Design choice rationale: rules are precise but semantically narrow; LLMs are flexible but hallucinate; supervised encoders are robust on repetitive tasks but rigid on novel patterns. The pipeline composes their strengths and constrains their weaknesses with retrieval, validation, and human review.

## 2. Component map

### 2.1 Ingestion layer (`app/ingestion/`)

| Module | Responsibility |
|---|---|
| `pdf_parser.py` | Layout-aware PDF parse (pdfplumber / pdfminer.six). Preserve page, char_start, char_end. |
| `html_parser.py` | HTML to structured text with section heuristics. Strip nav/footer. |
| `markdown_parser.py` | MD parse with header/section tracking. |
| `txt_parser.py` | Plain text passthrough with paragraph segmentation. |
| `url_fetcher.py` | URL → HTML; respect robots.txt; user-agent identifies tool. |
| `ocr.py` | Tesseract; only when page has no text layer. Output offsets reconciled to page geometry. |
| `language.py` | Language gate. langdetect/fasttext detects non-English; rejects with clear error. NO translation. English-only corpus is intentional scope. |
| `chunking.py` | Semantic chunking with section/page/offset preservation. Configurable chunk size (default 512 tokens, overlap 64). |

### 2.2 Extraction layer (`app/extractors/`)

| Module | Type | Responsibility |
|---|---|---|
| `regex_ioc.py` | Rules | IPv4/v6, domain, URL, hash (MD5/SHA1/256/512), email, CVE, ASN, file path, registry key, mutex. Defang/refang aware. |
| `ner_model.py` | Encoder | SecureBERT-based NER. Entity types: malware, tool, threat-actor, intrusion-set, campaign, vulnerability, infrastructure, identity, location. |
| `relation_model.py` | Encoder | Relation extraction. Outputs typed pairs with evidence span reference. |
| `event_model.py` | Encoder | Event/trigger extraction (e.g., `delivers`, `executes`, `communicates_with`). |
| `attack_mapper.py` | Encoder + RAG + LLM | 3-stage: (1) candidate top-k from SecRoBERTa, (2) RAG over ATT&CK descriptions + procedure examples + validated past mappings, (3) LLM grounded reranker / abstainer. |
| `llm_judge.py` | LLM | Function-calling LLM for cross-sentence linking, relation normalization, STIX property completion. ALWAYS evidence-required. |

### 2.3 RAG layer (`app/rag/`)

Typed, not generic. Four corpora, four retrievers.

| Index | Backing store | Content |
|---|---|---|
| `attack_index` | Chroma collection `attack_techniques` | ATT&CK techniques + sub-techniques + tactics + procedure examples + software/group cross-refs |
| `stix_index` | Chroma collection `stix_docs` | STIX 2.1 object semantics, required fields, relationship constraints |
| `ontology_index` | Chroma collection `local_ontology` | Project-local canonical aliases, FP patterns, custom taxonomies |
| `validated_examples` | Chroma collection `validated_examples` | Analyst-accepted prior mappings (memory of "what humans agreed with") |

`retriever.py` orchestrates parallel queries and dedup, returns typed `RetrievedContext` with provenance per snippet.

### 2.4 STIX layer (`app/stix/`)

| Module | Responsibility |
|---|---|
| `builders.py` | Build STIX 2.1 objects from intermediate CTI JSON. Phase 1 subset: `report`, `indicator`, `relationship`. |
| `validators.py` | Layered validation: Pydantic (internal schema) → `stix2.parse()` (library) → semantic checks (refs, required fields, ATT&CK pattern refs). |
| `exporters.py` | Bundle assembly + serialization. Generates external_references with proper kill_chain_phases. |

### 2.5 Review layer (`app/review/`)

| Module | Responsibility |
|---|---|
| `queue.py` | Triage queue. Sort by confidence asc, novelty desc, operational priority. |
| `diff.py` | Auto-output vs analyst-edited diff. JSONPatch-style. |
| `acceptance.py` | Accept/reject/edit with reason. Feeds `validated_examples` corpus. |

### 2.6 Database layer (`app/db/`)

PostgreSQL via SQLAlchemy 2.0 async. Repository pattern.

### 2.7 Jobs (`app/jobs/`)

| Module | Responsibility |
|---|---|
| `worker.py` | Worker process (RQ or Celery — decide Phase 1) |
| `pipelines.py` | `process_document(doc_id)` orchestrator. Idempotent. |

### 2.8 API (`app/api/`)

FastAPI. See § 5 for endpoints.

### 2.9 Core (`app/core/`)

| Module | Responsibility |
|---|---|
| `config.py` | Pydantic Settings from env. Single source of truth for runtime config. |
| `logging.py` | Structured JSON logging. Correlation IDs. |
| `security.py` | JWT auth, redaction utilities, secret-masking. |
| `telemetry.py` | OpenTelemetry traces + metrics. |

## 3. Data flow

### 3.1 Single-document ingestion → STIX bundle

```
1. POST /ingest (multipart or URL)
   -> persist raw to S3, hash, document row
   -> enqueue extract job
2. Worker picks up doc_id
   -> parse_and_chunk (layout-aware)
   -> regex_ioc_extract  (rules)
   -> ner_extract        (encoder)
   -> relation_extract   (encoder)
   -> event_extract      (encoder)
   -> attack_prerank     (encoder top-k)
   -> rag_fetch          (typed retrieval over 4 corpora)
   -> llm_grounded_judge (evidence-required)
   -> entity_resolution  (KG canonicalization)
   -> confidence_scoring (5-signal composite)
   -> build_stix_bundle  (Phase 1 subset)
   -> validate_stix      (layered)
   -> persist_all        (Postgres + Chroma + ES + S3)
   -> enqueue_human_review_if_needed (low confidence OR novel entities)
3. Analyst opens review queue
   -> diff and edit
   -> accept -> writes validated_examples
4. Optional export
   -> POST /export/opencti | /export/misp | /export/taxii
   -> audit log entry
```

### 3.2 Confidence scoring formula

```
final_confidence
  = 0.25 * extractor_confidence       # model probability / rule strictness
  + 0.20 * evidence_coverage          # # supporting spans, span quality
  + 0.20 * ensemble_agreement         # agreement between rule/encoder/LLM
  + 0.20 * ontology_consistency       # passes ATT&CK + STIX schema rules
  + 0.15 * stix_validation_score      # passes layered STIX validator
```

Threshold: < 0.55 → human review. < 0.30 → reject without review.

## 4. Internal data model — `intermediate_cti_json`

Canonical internal representation. STIX is built FROM this, not directly from text.

```json
{
  "document": {
    "id": "doc-uuid",
    "source_uri": "internal-id",
    "ingested_at": "2026-05-18T12:00:00Z",
    "language": "en",
    "title": "Example threat report",
    "sha256": "..."
  },
  "chunks": [
    {
      "chunk_id": "c12",
      "section": "Execution",
      "page": 4,
      "text": "The actors used PowerShell to download...",
      "char_start": 10432,
      "char_end": 10528
    }
  ],
  "candidates": {
    "iocs":           [{ "type": "domain", "value": "...", "evidence_ids": ["e1"] }],
    "entities":       [{ "type": "malware", "name": "...", "aliases": [], "evidence_ids": [] }],
    "relations":      [{ "subject_id": "...", "predicate": "delivers", "object_id": "...", "evidence_ids": [] }],
    "events":         [{ "trigger": "execute", "args": {}, "evidence_ids": [] }],
    "attack_mappings":[{ "technique_id": "T1059.001", "confidence": 0.82, "evidence_ids": [] }]
  },
  "evidence": [
    {
      "evidence_id": "e91",
      "chunk_id": "c12",
      "text_span": "used PowerShell to download",
      "char_start": 10451,
      "char_end": 10480
    }
  ],
  "provenance": {
    "extractors": ["regex_ioc@1.2", "securebert_ner@2026.04", "llm_judge@gpt-4o-mini"],
    "prompts":    [{"id": "judge_v3", "hash": "..."}],
    "retrieval":  [{"corpus": "attack", "query_hash": "...", "doc_ids": []}],
    "version": "2026.05.18"
  },
  "scores": {
    "claim_id_to_confidence": {}
  }
}
```

Invariants:
- Every item in `candidates.*` MUST reference at least one `evidence_id`.
- Every `evidence_id` MUST resolve to a chunk with valid char offsets.
- `provenance` is append-only — re-extraction creates a new version, never mutates.

## 5. API surface

```
POST   /ingest                          multipart or { url }
POST   /documents/{id}/extract          trigger pipeline (idempotent)
GET    /documents/{id}                  doc metadata + extraction status
GET    /documents/{id}/chunks           paginated chunks
GET    /extractions/{id}                intermediate_cti_json
POST   /extractions/{id}/rerun          re-run with new model versions
GET    /reviews                         queue (filter, sort, paginate)
POST   /reviews/{id}/accept             accept auto-output as-is
POST   /reviews/{id}/edit               edit + reason; appends to validated_examples
POST   /reviews/{id}/reject             reject + reason
POST   /stix/validate                   accept STIX bundle, return validation report
POST   /export/opencti                  push validated bundle
POST   /export/misp                     push validated bundle
POST   /export/taxii                    push to configured collection
GET    /search                          unified search (lexical + vector + KG)
GET    /metrics                         Prometheus metrics
GET    /health                          liveness + readiness
```

All endpoints require JWT auth except `/health`.

## 6. Database schema (PostgreSQL)

```
documents              (id, source_uri, sha256, title, language, ingested_at, status)
document_sources       (id, document_id, type, raw_uri, raw_hash, fetched_at)
chunks                 (id, document_id, section, page, text, char_start, char_end)
evidence_spans         (id, chunk_id, char_start, char_end, text_span)
ioc_candidates         (id, document_id, type, value, normalized, evidence_ids[])
entities               (id, document_id, type, name, aliases[], evidence_ids[])
relations              (id, subject_entity_id, predicate, object_entity_id, evidence_ids[])
events                 (id, document_id, trigger, args jsonb, evidence_ids[])
attack_mappings        (id, document_id, technique_id, sub_technique_id, confidence, evidence_ids[])
canonical_entities     (id, name, type, aliases[], stix_object_id, attack_id)
stix_objects           (id, type, stix_id, document_id, json jsonb, hash, version)
stix_relationships     (id, source_ref, target_ref, relationship_type, document_id)
reviews                (id, target_type, target_id, reviewer_id, status, edits jsonb, reason, created_at)
exports                (id, target_system, bundle_hash, response jsonb, exported_at, exported_by)
audit_logs             (id, actor, action, target_type, target_id, payload_hash, created_at)
model_runs             (id, document_id, model, version, prompt_hash, input_hash, output_hash, started_at, ended_at)
feedback_examples      (id, source_review_id, claim_type, payload jsonb, accepted_at)
```

`audit_logs` is append-only with hash-chain (each row references previous row's hash) for tamper-evidence.

## 7. Storage allocation

| Store | Use |
|---|---|
| **PostgreSQL** | Authoritative records: documents, chunks, candidates, entities, reviews, exports, audit |
| **Elasticsearch** | Lexical search over chunks, IOC strings, analyst comments. Triage queue index. |
| **ChromaDB** | Vector retrieval. 4 typed collections (see §2.3). |
| **MinIO/S3** | Raw report files, OCR output, original attachments |
| **Redis** | Job queue + transient caches (embedding, LLM response cache) |

## 8. Module dependency graph

```
api ─┐
     v
core ◄─── all modules (config, logging, security, telemetry)
     ^
jobs ┘
     │
     v
ingestion ──> chunks ──┐
                       v
extractors ──> candidates ──┐
                            v
           rag ──> retrieved_context ──┐
                                       v
                           llm_judge / attack_mapper ──┐
                                                       v
                                       review ──> stix.builders ──> stix.validators ──> stix.exporters
                                                       │
                                                       v
                                                       db (Postgres + ES + Chroma)
```

## 9. Security architecture

### Trust boundaries
1. **Untrusted:** Ingested report content. Treated as hostile prompt.
2. **Semi-trusted:** Analyst input (rate-limited, audit-logged).
3. **Trusted:** Service-internal modules.

### Controls
- Input report text NEVER directly drives tool calls. Always wrapped in evidence-required schema.
- `REDACT_BEFORE_LLM=true` strips emails, internal IPs, customer IDs from any external LLM call.
- `ALLOW_EXTERNAL_LLM=false` default in prod; flip with explicit env override.
- All raw reports preserved for forensics. Hash + ingest timestamp immutable.
- JWT for analyst auth. Roles: `analyst`, `reviewer`, `exporter`, `admin`.
- Audit log hash chain. Every export action records bundle hash + destination + actor.
- Secret masking in logs (regex on common API key patterns).
- Container-level secrets via Docker secrets or Vault, NOT env files in prod.

## 10. Observability

- **Logs:** Structured JSON, correlation_id per request, span_id per pipeline step.
- **Traces:** OpenTelemetry → OTLP. Critical spans: `ingest`, `parse_chunk`, `extract.*`, `rag.fetch`, `llm.judge`, `validate_stix`, `export.*`.
- **Metrics:**
  - Latency p50/p95/p99 per pipeline step
  - Extraction counts by type
  - Confidence histogram
  - STIX validation pass rate
  - Review queue depth + age
  - Export success rate
- **Dashboards:** Grafana (recommended). Pre-built panels in `docker/grafana/`.

## 11. Deployment

### Local (development)
`docker compose up` brings up Postgres, Elasticsearch, ChromaDB, Redis, MinIO, app, worker, OpenCTI dev instance.

### Staging / Production
- Containerized; Kubernetes-ready.
- Persistent volumes for Postgres + ES + Chroma + MinIO.
- Worker autoscale on queue depth.
- LLM provider configurable: external API or self-hosted vLLM/Ollama.

## 12. Versioning + reproducibility

- Pinned `pyproject.toml` + `uv.lock` (or `poetry.lock`).
- Model checkpoints version-tagged with `MODEL_VERSION` in `model_runs` table.
- Prompt templates versioned in `app/extractors/prompts/v{n}.md`. Prompt hash captured per run.
- Evaluation reports include: dataset version, model version, prompt version, retrieval version.

## 13. Phase-aligned scope

| Component | Phase 1 | Phase 2 | Phase 3 | Phase 4 |
|---|---|---|---|---|
| Ingest PDF/HTML/TXT/MD | ✓ | | | |
| OCR | | ✓ | | |
| Translation | | | — — | (out of scope: English-only corpus) |
| Regex IOC | ✓ | | | |
| NER + RE + Event | | ✓ | | |
| ATT&CK mapping | | ✓ | | |
| RAG + LLM judge | | | ✓ | |
| STIX (report/indicator/relationship) | ✓ | | | |
| STIX full subset | | ✓ | | |
| Knowledge graph + entity resolution | | | ✓ | |
| Human review UI | | ✓ | | |
| OpenCTI export | ✓ (test) | ✓ (full) | | |
| MISP export | | ✓ | | |
| TAXII export | | | ✓ | |
| SIEM artifacts (Sigma/Splunk) | | | | ✓ |
| Eval harness layered metrics | ✓ (basic) | ✓ (per-task) | ✓ (end-to-end) | ✓ (downstream) |

## 14. References

- OASIS STIX 2.1 — https://docs.oasis-open.org/cti/stix/v2.1/
- OASIS TAXII 2.1 — https://docs.oasis-open.org/cti/taxii/v2.1/
- MITRE ATT&CK — https://attack.mitre.org/
- NIST SP 800-150 — Guide to Cyber Threat Information Sharing
- OpenCTI — https://docs.opencti.io/
- MISP — https://www.misp-project.org/

---

## Unresolved questions

1. RQ vs Celery vs Arq — pending Phase 1 spike.
2. ChromaDB vs Qdrant vs pgvector — ops simplicity vs scale ceiling.
3. Custom KG store: Neo4j embedded or graph queries on PostgreSQL with `recursive` CTEs?
4. ~~Translation provider~~ — out of scope. Public CTI reports are English-only.
5. Whether `audit_logs` hash-chain should integrate with Sigstore / transparency log for thesis-grade tamper evidence.
