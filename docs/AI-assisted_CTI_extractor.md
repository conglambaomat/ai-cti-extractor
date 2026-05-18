# AI-Assisted Cyber Threat Intelligence Extractor for STIX, ATT&CK, and SOC Operations

## Problem framing

An AI-assisted CTI extractor is a high-value project because it sits at the intersection of three things that security teams actually need in production: converting unstructured threat reports into machine-readable intelligence, mapping narrative descriptions to attacker behavior frameworks, and pushing usable outputs into analyst workflows and security platforms. NIST defines cyber threat information broadly to include indicators, TTPs, security alerts, threat intelligence reports, and tool configurations; OASIS defines STIX as the language and serialization format for exchanging CTI and TAXII as the application-layer protocol for sharing it; ENISA’s current threat-landscape methodology explicitly highlights translating information into STIX 2.1 and structuring TTPs according to MITRE ATT&CK. citeturn23view2turn23view3turn23view4

The research consensus is that the bottleneck is not “finding more CTI” but turning noisy prose, PDFs, blog posts, screenshots, and heterogeneous report layouts into grounded, standardized, queryable knowledge. A recent SoK reviewing 80 peer-reviewed studies on ATT&CK mapping from CTI reports found that the field still leans heavily on narrow single-label document classification and under-serves cross-sentence, multi-technique, and analyst-centric workflows; a separate multi-report study showed that aggregating related reports improved ATT&CK identification by 26% and push the best method to 78.6% F1, underscoring that single-report extraction is structurally limited. citeturn15view6turn15view7

The strongest practical conclusion from the literature is that **pure rule-based systems do not scale semantically, pure LLM systems are too brittle and hallucination-prone, and the best production architecture is a hybrid neuro-symbolic pipeline**: deterministic IOC extraction where exactness matters, smaller fine-tuned encoders for frequent structured subtasks, LLMs only where cross-sentence synthesis and schema reasoning are needed, retrieval against ATT&CK/STIX/ontology sources to constrain outputs, and a human review layer before operational export. That pattern is consistent across STIX extraction, ATT&CK technique classification, KG construction, and downstream detection-rule generation. citeturn15view0turn24view3turn31academia11turn27view0turn30view0turn36view0

## Research taxonomy

The literature can be organized into six streams. The earliest stream focused on **IOC extraction and automation of structured indicators**. The classic iACE work at CCS 2016 showed that open-source security articles could be converted into machine-readable OpenIOC-style outputs and correlated at scale; this line established that regular expressions, entity typing, and provenance capture are operationally useful, but it mostly targeted low-level indicators rather than richer behavioral abstractions. citeturn31search0turn31search4

A second stream moved from IoCs to **attack behavior and ATT&CK-oriented extraction**. AttacKG extracts attack behavior graphs from CTI reports, aggregates intelligence across reports, and reported F1 of 0.887 for attack-relevant entities, 0.896 for dependencies, and 0.789 for techniques on manually labeled reports; LADDER explicitly argued that CTI should move “beyond IoCs” toward reusable attack patterns and ATT&CK alignment; CTI-to-MITRE showed that ML can classify unstructured CTI into 188 ATT&CK techniques with F-measure up to 72%, but document-level performance drops and many techniques are still missed. citeturn31academia11turn37search0turn37search7turn33view0turn33view2

A third stream addresses **entity, relation, and STIX object extraction**. STIXnet proposed a modular deep-learning solution for extracting both STIX entities and STIX-specified relationships from CTI reports and reported macro F1 of 0.916 for STIX entities and 0.724 for relations. The newer AZERG work pushes the problem into a clearly STIX-aligned, multi-task setting and provides the largest public dataset of its kind, spanning entity detection, entity typing, related-pair detection, and relationship typing over real-world reports. citeturn15view0turn24view3

A fourth stream focuses on **knowledge-graph construction and ontology alignment**. Open-CyKG uses an attention-based neural Open Information Extraction pipeline plus a cybersecurity NER model to construct CTI knowledge graphs from APT reports; MALOnt proposed an open malware ontology to drive structured extraction and KG generation; TINKER framed open-source CTI as a semi-supervised KG problem; ThreatKG and CTINexus pushed farther toward automated, continuously updated, modular knowledge graphs, with CTINexus explicitly showing that its in-context-learning approach can adapt to the STIX ontology as one of the target schemas. citeturn32search3turn31academia12turn35search0turn35search1turn32search10

A fifth stream covers **LLM-based and RAG-based CTI extraction**. Recent work on actionable CTI with KGs and LLMs found that guidance-style constrained generation and fine-tuning outperform plain prompt engineering for triple extraction. IntelEX targeted a more operational endpoint, extracting attack-level intelligence from CTI and converting it into detection rules for Sigma and Splunk, reporting splunk execution for 99.03% of generated rules. LLMCloudHunter went further for cloud CTI, extracting API calls and IoCs from text and images with 92% precision / 98% recall for API calls, 99% precision / 98% recall for IoCs, and 99.18% compilation/conversion success for rule candidates. citeturn36view0turn2academia16turn27view0

A sixth stream is about **benchmarks, agentic workflows, and downstream SOC usefulness**, not just extraction accuracy. AttackSeqBench measures how well LLMs understand attack sequences in CTI; ExCyTIn-Bench evaluates threat investigation over 57 Microsoft Sentinel-related log tables and 7,542 generated questions with explicit graph-anchored ground truth; CTI-REALM evaluates agent performance on CTI-informed detection rule generation and showed that CTI-specific tools and memory augmentation materially improve outcomes. These benchmarks matter because a system that extracts “correct looking” entities but does not help investigation, detection engineering, or sharing is not enough for a top-tier project. citeturn26view0turn27view1turn26view1

### Representative papers and tools

| Area | Representative work | Core contribution | Practical takeaway |
|---|---|---|---|
| IOC automation | iACE / Acing the IOC Game | Automated IOC extraction and structuring from open-source CTI articles. citeturn31search0turn31search4 | Exact-pattern extraction still belongs in a deterministic rule layer. |
| ATT&CK mapping baseline | CTI-to-MITRE | ML classification of CTI into 188 ATT&CK techniques; best F-measure up to 72%. citeturn33view0turn33view2 | Strong baseline, but not enough alone for production-grade multi-technique reports. |
| Multi-report ATT&CK mapping | Multi-report identification study | Report aggregation improved ATT&CK identification by 26%, best F1 78.6%. citeturn15view7 | Cross-report context is valuable; do not treat reports as isolated documents. |
| Behavior graph extraction | AttacKG | Attack behavior graphs and technique knowledge graphs from CTI; outperformed earlier approaches. citeturn31academia11 | Graph-level consolidation is worth keeping in the architecture. |
| STIX extraction | STIXnet | Direct STIX entity and relation extraction with strong macro F1. citeturn15view0 | STIX can be treated as a first-class extraction target, not only a final serialization. |
| STIX dataset | AZERG | 141 reports, 4,011 STIX entities, 2,075 relationships, vendor-disjoint train/test. citeturn24view3 | Best current public starting point for STIX entity/relation model training. |
| ATT&CK + ontology fusion | MITREtrieval | Fuses deep learning with ontology voting; reported F2 of 58%, 62%, and 69% across three settings. citeturn34search9turn34search11 | Ontology-aware reranking improves neural ATT&CK mapping. |
| Synthetic data for TTP mapping | SynthCTI | LLM-driven augmentation improved SecureBERT from 0.4412 to 0.6558 macro-F1. citeturn33view3 | Use synthetic augmentation for rare techniques and sub-techniques. |
| Joint entity–relation extraction | TIJERE | SecureBERT+-based joint extraction with F1 above 0.93 for NER and 0.98 for RE. citeturn30view0 | Joint extraction is promising, especially when evidence spans are retained. |
| LLM-to-detection bridge | IntelEX / LLMCloudHunter | Converts CTI into executable detection artifacts with high compilation and extraction quality. citeturn2academia16turn27view0 | End-to-end usefulness should be part of evaluation, not an afterthought. |
| Knowledge graph systems | ThreatKG / CTINexus / Open-CyKG | Automated OSCTI gathering, extraction, and KG construction, including STIX adaptation. citeturn35search1turn32search10turn32search3 | A KG layer is most valuable as the normalized internal memory of the system. |
| Operational platforms | OpenCTI / MISP / TRAM | OpenCTI provides a STIX-driven CTI platform; MISP provides sharing, correlation and integrations; TRAM provides ATT&CK mapping workflows. citeturn19view1turn19view5turn18view7 | These are the best reuse points for a capstone-grade implementation. |

## Benchmarks and datasets

For **entity and relation extraction**, the strongest public resources are AnnoCTR and AZERG. AnnoCTR contains 400 commercial-vendor threat reports annotated at full-document level with named entities, temporal expressions, tactics, and techniques linked to Wikipedia and MITRE ATT&CK, which is substantially richer than earlier sentence-only or single-label resources. AZERG is specifically valuable if your stated goal is STIX 2.1 generation: it is built from 141 real-world reports and includes 4,011 STIX entities and 2,075 STIX relationships, with train/test splits designed to evaluate generalization across non-overlapping reports and vendors. citeturn24view0turn24view4turn24view3

For **ATT&CK mapping and TTP classification**, the most useful open resources are CTI-to-MITRE, TRAM, WAVE-27K, and CTI-HAL. CTI-to-MITRE provides code and datasets for reproducing ISSRE 2022 baselines. The MITRE Center for Threat-Informed Defense’s TRAM maps sentences to ATT&CK techniques, works out of the box for up to 50 common ATT&CK techniques, and can be tailored for a user’s own ATT&CK subset. WAVE-27K contains 27 techniques, 22,539 single-technique samples and 5,262 multi-technique samples, with SecRoBERTa reaching 77.52% F1. CTI-HAL is important because it is manually constructed around ATT&CK and explicitly reports inter-annotator agreement using Krippendorff’s alpha, which makes it useful as a reliability-oriented evaluation resource instead of only a weakly supervised benchmark. citeturn33view2turn18view7turn24view2turn25view0

For **reasoning and analyst-workflow evaluation**, AttackSeqBench, ExCyTIn-Bench, and CTI-REALM are the most relevant current benchmarks. AttackSeqBench focuses on tactical, technical, and procedural sequence understanding over CTI. ExCyTIn-Bench builds explainable ground truth from investigation graphs over 57 Microsoft Sentinel-related log tables and reports that the best model reward is still only 0.606, leaving major headroom. CTI-REALM evaluates detection-rule generation directly from CTI reports and shows that CTI-specific tools and seeded memory improve agent performance. citeturn26view0turn27view1turn26view1

The biggest dataset gap is that **no single public benchmark currently covers the full end-to-end problem you want to solve**: ingesting PDF/HTML/TXT/Markdown/URL inputs, extracting entities/events/relations with evidence spans, generating full STIX 2.1 bundles, validating them, mapping to ATT&CK at technique and sub-technique level, and measuring downstream SOC usefulness. The literature repeatedly fragments the problem into one of three narrow targets: ATT&CK classification, entity–relation extraction, or detection-rule generation. That gap is exactly where a strong thesis can contribute: a unified benchmark and evaluation harness for grounded, standardized, operational CTI extraction. citeturn15view6turn24view3turn26view0turn26view1turn27view0

## Recommended architecture

The most defensible architecture for this problem is an **evidence-grounded hybrid pipeline with a normalized intermediate schema, ontology-aware candidate generation, retrieval-constrained LLM reasoning, graph-backed entity resolution, and human review before export**. That recommendation is a synthesis of the best-performing ideas from STIXnet, AZERG, AttacKG, CTINexus, MITREtrieval, SynthCTI, LLMCloudHunter, and the official STIX/TAXII and ATT&CK ecosystem. citeturn15view0turn24view3turn31academia11turn32search10turn34search11turn33view3turn27view0turn23view3turn18view5

```text
Input sources
  -> PDF / HTML / TXT / Markdown / URL / API
  -> layout-aware parsing
  -> OCR only when the page is image-only
  -> language detection + translation cache
  -> report structure segmentation

Segmented report
  -> chunk store with document sections, tables, captions, page/offset spans
  -> deterministic IOC extraction
  -> sentence / paragraph embeddings
  -> domain NER + relation / event extraction
  -> ATT&CK candidate generation
  -> RAG over ATT&CK + STIX + local ontology + analyst memory

Evidence-grounded synthesis
  -> LLM function calling for only:
       cross-sentence linking
       relation normalization
       ATT&CK reranking
       STIX object assembly
  -> confidence scoring
  -> entity resolution / dedup / graph merge
  -> STIX 2.1 bundle build
  -> schema + semantic validation
  -> human review queue

Operational outputs
  -> TAXII
  -> OpenCTI
  -> MISP
  -> SIEM/SOAR / Elastic / Splunk / Sigma
  -> analyst dashboard + audit logs
```

The key design choice is **task routing**. Use **rules first** for exact, low-ambiguity observables such as IPv4/IPv6, domains, URLs, hashes, email addresses, CVEs, ASNs, file paths, registry keys, and common YARA/Sigma/code-block patterns. The reason is simple: these fields care more about precision, format, and provenance than about latent semantics, and the literature consistently shows that operational systems retain strong deterministic components even when they add transformers or LLMs. citeturn31search0turn31academia13turn27view0

Use **small or mid-sized fine-tuned domain encoders** for repetitive structured tasks: CTI NER, relation extraction, event trigger extraction, sentence-level ATT&CK candidate generation, document-section relevance classification, and duplicate detection. SecureBERT, SecRoBERTa, DistilBERT-class models, and joint extraction architectures built on BERT/BiGRU/CRF or set-prediction style decoders are justified by the current results landscape: WAVE-27K found SecRoBERTa strongest on its benchmark; TIJERE reported state-of-the-art NER/RE on DNRTI-JE; the 2025 parallel ensemble model reported absolute F1 gains over sequence-tagging baselines; TIEF reported a fine-tuned DistilBERT classifier over 560 sub-techniques as its core TTP classifier. citeturn24view2turn30view0turn29view1turn38view0

Use **LLMs only where they have a comparative advantage**: cross-sentence coreference, long-range relation normalization, multi-evidence ATT&CK technique justification, STIX property completion from grounded evidence, analyst-facing explanation, and multilingual normalization. The papers most relevant to your target use case do not support an LLM-only design; instead, they show that constrained generation, guidance-style control, fine-tuning, or RAG-like support is materially better than free-form prompting, and that downstream agentic workflows benefit from CTI-specific tools and memory. citeturn36view0turn26view1turn27view1

The **RAG layer** should not be a generic vector database over PDFs. It should be a **typed retrieval layer** with four corpora: ATT&CK techniques and sub-techniques with tactics, procedures, software and group links; STIX 2.1 object semantics and relationship constraints; your local CTI ontology / KG; and internal analyst memory containing previously validated mappings, false-positive patterns, and canonical aliases. MITRE’s ATT&CK data and the ATT&CK STIX/TAXII server give you an official machine-readable representation of ATT&CK, while OASIS STIX/TAXII gives the sharing schema and protocol semantics. citeturn18view5turn18view0turn23view3

The **internal data model** should revolve around an intermediate JSON schema rather than jumping straight from text to STIX. A good intermediate object has at least these groups:

```json
{
  "document": {
    "id": "doc-uuid",
    "source_uri": "redacted-or-internal-id",
    "ingested_at": "2026-05-18T12:00:00Z",
    "language": "en",
    "title": "Example threat report"
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
    "iocs": [],
    "entities": [],
    "relations": [],
    "events": [],
    "attack_mappings": []
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
    "extractors": ["regex_ioc", "securebert_ner", "llm_relation_judge"],
    "version": "2026.05.18"
  }
}
```

Every extracted fact should carry **evidence-span grounding**. That means an ATT&CK mapping is invalid if it cannot point back to one or more report spans, and a STIX relationship is invalid if the system cannot show which spans justified the endpoints and the relation type. This is the single most important anti-hallucination design decision for your thesis, because it turns evaluation from “did the model say something plausible?” into “did the system produce a justified, reviewable claim tied to the report itself?” The current benchmark landscape strongly supports this direction: ExCyTIn-Bench anchors answers to explicit graph nodes and edges for explainable ground truth, and CTI-REALM explicitly rewards trajectory quality rather than only final outputs. citeturn27view1turn26view1

For **ATT&CK mapping**, use a three-stage ensemble. First, a small encoder gives a top-*k* candidate list per sentence or event span. Second, retrieval pulls ATT&CK descriptions, procedure examples, and local examples from validated past reports for those candidates. Third, an LLM acts only as a **grounded re-ranker / judge**, selecting the best technique or abstaining if evidence is insufficient. This is the architecture most likely to beat both TRAM-like fixed-label baselines and unconstrained LLM classification, because it combines the strong recall of neural candidate generation, the ontology consistency of MITREtrieval-style fusion, and the data-balance benefits observed in SynthCTI. citeturn18view7turn34search11turn33view3

For **entity resolution and deduplication**, maintain a knowledge graph plus canonical alias tables. Reports mention the same malware, tool, or intrusion set using variants, vendor-specific labels, or family aliases. OpenCTI’s entity model, source-linking, and confidence handling make it a natural integration target, and ATT&CK’s official relationships also give you a useful normalization backbone for software, groups, and techniques. citeturn19view1turn18view5

For **STIX 2.1 generation**, do not attempt to build the full object universe on day one. Start with a high-value subset: `report`, `indicator`, `malware`, `tool`, `threat-actor`, `intrusion-set`, `campaign`, `vulnerability`, `attack-pattern`, `infrastructure`, `identity`, `observed-data`, and `relationship`. OASIS positions STIX as the standard representation language and TAXII as the exchange protocol; TIEF shows a workable subset for automated generation and documents concrete property mappings for `attack-pattern`, `indicator`, `report`, and `relationship`. citeturn23view3turn38view0

A good final **confidence score** should combine at least five signals: extractor confidence, evidence completeness, ensemble agreement, ontology consistency, and post-generation validation. One practical formula is:

```text
final_confidence
= 0.25 * extractor_confidence
+ 0.20 * evidence_coverage
+ 0.20 * ensemble_agreement
+ 0.20 * ontology_consistency
+ 0.15 * stix_validation_score
```

That weighting is a design recommendation rather than a standard, but it matches the literature’s main lesson: correctness in CTI extraction is multi-dimensional and cannot be reduced to a single model probability. citeturn15view6turn24view3turn36view0

## Implementation blueprint

A production-ready thesis implementation can be built cleanly in Python/FastAPI with the stack you listed. My recommended split is: **FastAPI + Pydantic** for the service layer, **PostgreSQL** for normalized metadata and audit records, **Elasticsearch** for lexical search and reviewer triage, **ChromaDB** for vector retrieval, and **OpenCTI / MISP / TAXII** connectors for export. The official OASIS `cti-python-stix2` library supports STIX 2.1 object serialization, parsing, versioning, and ID/reference handling; the official OASIS TAXII Python client provides client-side interaction with TAXII servers; OpenCTI is an open-source CTI platform built on the STIX 2 standard and offers GraphQL APIs plus dashboards and connector workflows; MISP is an open-source threat-intelligence platform with feeds, sharing, collaboration, and exports for SIEM/NIDS/log-analysis use cases. citeturn19view3turn17view0turn19view1turn19view5

A clean module layout looks like this:

```text
app/
  api/
    ingest.py
    extract.py
    review.py
    export.py
    search.py
    health.py
  core/
    config.py
    logging.py
    security.py
    telemetry.py
  ingestion/
    pdf_parser.py
    html_parser.py
    markdown_parser.py
    ocr.py
    language.py
    chunking.py
  extractors/
    regex_ioc.py
    ner_model.py
    relation_model.py
    event_model.py
    attack_mapper.py
    llm_judge.py
  rag/
    attack_index.py
    stix_index.py
    ontology_index.py
    retriever.py
  stix/
    builders.py
    validators.py
    exporters.py
  review/
    queue.py
    diff.py
    acceptance.py
  db/
    models.py
    repositories.py
  jobs/
    worker.py
    pipelines.py
tests/
scripts/
```

The minimum API surface should include:

```text
POST   /ingest
POST   /documents/{id}/extract
GET    /documents/{id}
GET    /documents/{id}/chunks
GET    /extractions/{id}
POST   /extractions/{id}/rerun
POST   /reviews/{id}/accept
POST   /reviews/{id}/edit
POST   /stix/validate
POST   /export/opencti
POST   /export/misp
POST   /export/taxii
GET    /search
GET    /metrics
```

The **logical database schema** should separate immutable provenance from mutable analyst decisions. At minimum, create tables for `documents`, `document_sources`, `chunks`, `evidence_spans`, `ioc_candidates`, `entities`, `relations`, `events`, `attack_mappings`, `canonical_entities`, `stix_objects`, `stix_relationships`, `reviews`, `exports`, `audit_logs`, `model_runs`, and `feedback_examples`. Store embeddings in ChromaDB keyed by `chunk_id`, `technique_id`, and `artifact_type`; store exact-searchable text, IOC strings, and analyst comments in Elasticsearch; keep the authoritative relational record in PostgreSQL. citeturn19view1turn19view5

The **retrieval indexes** should be typed, not mixed. In ChromaDB, create at least four collections: `report_chunks`, `attack_techniques`, `stix_docs`, and `validated_examples`. In Elasticsearch, create one document index for threat reports/chunks, one event index for extracted CTI objects, and one triage index for analyst-review tasks sorted by confidence, novelty, and operational priority. This design follows the spirit of the recent RAG and KG literature, which argues that symbolic structure and retrieval grounding are necessary to mitigate stale knowledge and hallucination in cyber workflows. citeturn32search16turn36view0

A practical orchestrator looks like this:

```python
def process_document(doc_id: str) -> dict:
    doc = load_document(doc_id)
    chunks = parse_and_chunk(doc)              # layout-aware
    iocs = regex_ioc_extract(chunks)           # high-precision
    entities = ner_extract(chunks)             # fine-tuned encoder
    relations = relation_extract(chunks, entities)
    events = event_extract(chunks, entities, relations)

    attack_candidates = attack_prerank(events, chunks)    # small model top-k
    retrieved = rag_fetch(
        attack_candidates=attack_candidates,
        stix_schema=True,
        ontology=True,
        prior_examples=True
    )

    judged = llm_grounded_judge(
        chunks=chunks,
        entities=entities,
        relations=relations,
        events=events,
        retrieved=retrieved,
        require_evidence=True,
        output_schema="intermediate_cti_json"
    )

    resolved = entity_resolution(judged)
    scored = confidence_scoring(resolved)
    stix_bundle = build_stix_bundle(scored)
    validation = validate_stix(stix_bundle)

    persist_all(doc_id, chunks, scored, stix_bundle, validation)
    enqueue_human_review_if_needed(doc_id, scored, validation)
    return {"doc_id": doc_id, "status": validation.status}
```

For **STIX validation**, use a layered approach rather than one parser call:

```python
def validate_stix(bundle_json: dict) -> ValidationResult:
    pydantic_validate(bundle_json)             # internal schema
    bundle = stix2.parse(bundle_json, allow_custom=False)
    semantic_errors = []

    for obj in bundle.objects:
        check_required_fields(obj, semantic_errors)
        check_external_references(obj, semantic_errors)
        check_relationship_endpoints(obj, bundle, semantic_errors)
        check_attack_pattern_refs(obj, semantic_errors)

    return ValidationResult(
        parse_ok=True,
        semantic_ok=(len(semantic_errors) == 0),
        errors=semantic_errors
    )
```

For **security controls**, assume the input document is untrusted. Treat report text as hostile prompt content, never let it directly dictate tool calls, preserve original documents for forensics, redact secrets before any external-model call, and prefer on-prem or VPC-hosted models for sensitive customer intelligence. Add immutable audit logs for every extraction, review, edit, and export. That matters because NIST emphasizes trust, handling constraints, legal/compliance boundaries, and data-sharing rules in CTI workflows. citeturn23view2

## Evaluation and trade-offs

Your evaluation should be **strictly layered**, because “overall accuracy” hides the real failure modes. For IOC extraction, measure strict exact-match precision/recall/F1 separately by type: IPv4, domain, URL, hash, email, CVE, filesystem path, mutex, registry key, and user-agent. For NER, use span-level and type-level F1. For relation extraction, use labeled and unlabeled relation F1. For events, use trigger F1, argument F1, and event-frame exact match. For ATT&CK mapping, report exact technique F1, parent-technique relaxed F1, top-*k* hit rate, and macro/micro F1; if you support sub-techniques, report sub-technique exactness separately. For STIX, report parse success, semantic validation pass rate, object completeness, relationship consistency, and export success into OpenCTI/MISP/TAXII. For faithfulness, report evidence coverage, unsupported-claim rate, and analyst correction rate. For SOC usefulness, report analyst acceptance, export ingestion success, downstream rule/detection utility, latency, and cost. citeturn24view3turn25view0turn26view1turn27view0

The strongest gold-standard strategy is to build a **new end-to-end benchmark** from a curated threat-report set, then reuse public datasets only for subsystem pretraining and stress testing. I would recommend about 150–250 reports for the thesis gold set, split across APT write-ups, malware analyses, incident posts, and vendor blogs. Use **double annotation** for at least 20–30% of the corpus, compute Krippendorff’s alpha or Cohen’s kappa on entities / ATT&CK techniques / relationships, and require every annotation to point to one or more exact evidence spans. CTI-HAL is particularly useful as a methodological precedent because it explicitly prioritizes human annotation quality and inter-annotator agreement instead of only weak supervision. citeturn25view0

The public datasets should be assigned to roles rather than mixed blindly. Use **AnnoCTR** for whole-document entity and ATT&CK concept detection; **AZERG** for STIX entity/relationship training and testing; **TRAM**, **CTI-to-MITRE**, **WAVE-27K**, and **CTI-HAL** for ATT&CK mapping experiments; **AttackSeqBench** for sequence understanding; and **ExCyTIn-Bench / CTI-REALM** for downstream operational reasoning where you want to show SOC relevance. That would give your evaluation a much stronger story than reporting one macro-F1 number on one dataset. citeturn24view0turn24view3turn18view7turn33view2turn24view2turn25view0turn26view0turn27view1turn26view1

A concise comparison of architecture options looks like this:

| Architecture | Accuracy pattern | Cost / latency | Maintainability | Security / privacy | My judgment |
|---|---|---|---|---|---|
| Rule-based only | Very high precision on exact IoCs, poor semantic recall. citeturn31search0turn31academia13 | Low | High | Strong | Necessary component, not sufficient as the full system. |
| Supervised transformer only | Strong on repeated tasks if labels exist; weak on schema reasoning and cross-sentence inference. citeturn24view2turn30view0turn33view0 | Low–medium | Medium | Strong on-prem | Best backbone for NER/RE/TTP candidate generation. |
| LLM-only | Broad coverage but unstable faithfulness and higher hallucination risk. citeturn36view0turn26view0turn27view1 | High | Medium | Weaker if external | Not recommended for production CTI extraction. |
| RAG + LLM | Better grounding and explanation than LLM-only. citeturn32search16turn36view0 | Medium–high | Medium | Medium | Good for ATT&CK/STIX reasoning and analyst summarization. |
| KG-based pipeline | Excellent normalization, merging, and enrichment. citeturn31academia11turn35search1turn32search10 | Medium | Medium–low initially | Strong | Best as the system’s memory and canonical layer. |
| Hybrid neuro-symbolic + human review | Best precision/recall balance and operational trust. citeturn15view6turn24view3turn27view0turn26view1 | Medium | Medium | Strong | Best overall architecture for your thesis. |

## Milestones, risks, and open questions

A realistic milestone plan is to build the system in four phases. **Phase one** should deliver ingestion, report parsing, deterministic IOC extraction, a minimal STIX subset (`report`, `indicator`, `relationship`), and export to JSON plus OpenCTI/MISP test endpoints. **Phase two** should add ATT&CK mapping, evidence spans, reviewer UI, and an evaluation harness over TRAM / CTI-to-MITRE / WAVE-27K. **Phase three** should add STIX entity–relation extraction from AZERG/AnnoCTR, knowledge-graph resolution, and RAG-constrained LLM judging. **Phase four** should add SOC-facing outputs: TAXII export, Elastic/Splunk-ready artifacts, quality dashboards, and analyst-acceptance studies. That sequencing reduces risk because each phase yields a demonstrable artifact with clear metrics. citeturn24view3turn18view7turn24view2turn19view1turn19view5

The top technical risks are not ordinary software bugs; they are **semantic drift, dataset mismatch, evidence-free hallucinations, STIX-invalid outputs, and operational irrelevance**. Synthetic augmentation can help long-tail ATT&CK labels, but it can also amplify annotation artifacts if not reviewed; SynthCTI and TIEF both suggest augmentation is useful, but they do not eliminate the need for careful gold data. Multi-report aggregation helps, but it complicates provenance and deduplication. LLMs improve cross-sentence reasoning, but recent benchmark work still shows substantial headroom and instability. citeturn33view3turn38view0turn15view7turn26view0turn26view1turn27view1

The best mitigation strategy is to make the system **boringly strict**. Force every operational claim to carry evidence spans. Allow abstention as a valid model output. Serialize nothing into STIX until internal schema checks pass. Keep deterministic extractors for exact observables. Run ontology consistency checks before export. Route low-confidence outputs to analysts. Log every model version, prompt template, retrieval result, and human edit. If you do that, your thesis will not only be “more accurate”; it will be measurably more trustworthy and operationally useful than most prior point-solutions. citeturn23view2turn23view3turn24view3turn26view1

What remains incomplete in the public literature is a fully standardized, openly released benchmark for **end-to-end CTI extraction with layout-aware ingestion, multilingual support, full STIX 2.1 validity, ATT&CK sub-technique grounding, and downstream SOC impact**. That is the clearest research gap and the strongest opportunity for your project to be evaluated highly: not only building a system, but also producing an evaluation methodology that the field itself still lacks. citeturn15view6turn24view3turn25view0turn27view1turn26view1

## Selected references

The most important standards and platform references for the build are OASIS STIX 2.1 and TAXII 2.1, MITRE ATT&CK and its STIX/TAXII data access, NIST SP 800-150 on CTI sharing, ENISA’s CTL methodology, OpenCTI, MISP, and the official OASIS Python libraries for STIX and TAXII. citeturn23view3turn18view0turn18view5turn23view2turn23view4turn19view1turn19view5turn19view3turn17view0

The most important extraction and ATT&CK/STIX papers for your bibliography are **AttacKG**, **CTI-to-MITRE**, **STIXnet**, **AnnoCTR**, **AZERG / From Text to Actionable Intelligence**, **MITREtrieval**, **Looking Beyond IoCs / LADDER**, **ThreatPilot**, **IntelEX**, **LLMCloudHunter**, **Actionable Cyber Threat Intelligence using Knowledge Graphs and Large Language Models**, **TIJERE**, and **Threat Intelligence Extraction Framework (TIEF)**. citeturn31academia11turn33view0turn15view0turn24view0turn24view3turn34search11turn37search0turn15view7turn2academia16turn27view0turn36view0turn30view0turn38view0

The most important datasets and benchmarks are **AnnoCTR**, **AZERG**, **CTI-HAL**, **WAVE-27K**, **TRAM**, **AttackSeqBench**, **ExCyTIn-Bench**, and **CTI-REALM**. citeturn24view0turn24view3turn25view0turn24view2turn18view7turn26view0turn27view1turn26view1

The repositories and tools I would actually reuse in an implementation are **TRAM** for a strong ATT&CK mapping baseline and benchmark harness, **OpenCTI** for STIX-native analyst workflows and graph-backed intelligence operations, **MISP** for sharing/export/integration, **AZERG** for STIX-task training data, **AnnoCTR** for document-level concept detection, **MITREtrieval** and **LADDER** as reusable ATT&CK mapping baselines, and the official **cti-python-stix2** and **cti-taxii-client** libraries for standards-compliant object creation and exchange. citeturn18view7turn19view1turn19view5turn24view3turn24view4turn34search0turn37search2turn19view3turn17view0

**Bottom line:** if your goal is a project that is both academically strong and likely to score highly, the best direction is a **hybrid, evidence-grounded CTI extraction platform** that ingests unstructured reports, extracts IoCs/entities/relations/events, maps them to ATT&CK with retrieval-constrained reasoning, generates **valid STIX 2.1 bundles**, supports **human analyst correction**, and exports to **OpenCTI/MISP/TAXII/SIEM**. That design is both better supported by the literature and much more defensible in evaluation than a pure LLM demo. citeturn15view0turn24view3turn31academia11turn27view0turn19view1turn19view5turn23view3