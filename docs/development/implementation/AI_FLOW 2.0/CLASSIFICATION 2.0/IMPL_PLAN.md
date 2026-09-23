# Classification 2.0 — Implementation Plan (M2: Implementation)

**Scope.** Implements Classification 2.0 (ORDER.md **M2**): a deterministic, rule-based classifier replaces the legacy keyword classifier as the pipeline's document-type router. Built on the M1 contract ([CONTRACT_IMPL_PLAN.md](./CONTRACT_IMPL_PLAN.md), done `c3a3763`) and existing infra only — no parallel architecture. Delivers normalization, signal detectors (laboratory/appointment/prescription), rule scoring + `ClassificationService`, a concrete `SchemaResolver`, pipeline wiring with classification persistence (event metadata + versioned S3 `classification_result.json` artifact), and the regression dataset. Evaluation/calibration (accuracy, schema-validity, latency, token usage, reproducibility — ORDER **M3**) is out of scope; M3 consumes this implementation as-is.

**Depth sources:** [SUM.md](./SUM.md), [CONTRACT_IMPL_PLAN.md](./CONTRACT_IMPL_PLAN.md), [ORDER.md](../ORDER.md), [SUMMARY.md](../SUMMARY.md), [STRUCTURE.md](../STRUCTURE.md), [IMPL_PLAN_SCHEMA.md](../../operational/IMPL_PLAN_SCHEMA.md). Full signal regexes/weights stay in SUM.md §§8–13; this plan is the runbook.

**Revision 1** — initial M2 plan (2026-09-23).

Status legend: `[ ]` pending · `[x]` done.

---

## 0. Overview

**Current (as-is):** `pipeline.handle_structuring` calls legacy `classify_document_type(markdown, client_type)` → `"laboratory"|"prescription"|"default"` → `canonical.yaml` dispatch + `build_canonical`. Over-specific keywords sent the real hematology PDF (`lab_3`/`lab_4`) to `generic` (17 measurements collapsed into one `note`) and the appointment JPEG to `generic`.

**Target (M2):**
```text
marker.md
  → MarkdownNormalizer → NormalizedDocument
  → signal detectors (laboratory / appointment / prescription / generic)
  → RuleScoringEngine → ClassificationResult
  → RegistrySchemaResolver → prompt_key (appointment → "default" until AppointmentCanonical)
  → LLM extraction (canonical.yaml) → build_canonical   (Pydantic = schema-validation gate)
  → classification_result.json → S3         (artifact-first)
  → DocumentAnalysisCompleted (+ classification block) → RabbitMQ
```
Frontmatter carries the same `classification` block.

**Key mechanisms:** rule scoring with explainable signals (machine-readable `signals[]` + human-readable `reasons[]`); client-declared type is a **boost**, not an override; `ClassificationService` stays S3/RabbitMQ-agnostic; orchestration persists the artifact before publishing the event.

**Invariants (locked):**
- Classification is deterministic + reproducible: same `marker.md` + same `classifier_version` → same `ClassificationResult`. Method `"rule_score"`.
- Boundary: Classification answers *what kind*; extraction answers *what medical info*. No `classification/`→extraction-schema import — orchestration resolves via `SchemaResolver`.
- `ClassificationService` imports no S3/RabbitMQ; persistence/event concerns live in `pipeline/`.
- **Artifact-first ordering:** `classification_result.json` is uploaded before `analysis-completed` is published; a failed artifact upload = processing failure (no event). Artifact is immutable per `document_version_id`.
- Persistence shape (M1-locked §4): `classification{type,subtype,confidence,confidence_level,decision,method,classifier_version,reasons,warnings}`; artifact JSON carries `format` version.
- Client-declared `document_type` (`lab_result`/`prescription`) adds a strong hint signal; it cannot force a type the content rejects.
- `classifier_version = "2.0.0"` holds through M2 (implementation of the locked contract; no semantic change). Algorithm/threshold calibration in M3 bumps to `2.1.0`.

## 1. Execution summary

| Phase | Scope | Status |
|---|---|---|
| 1 | Normalization implementation (`MarkdownNormalizer`) | [x] |
| 2 | Signal detectors implementation (lab/appointment/prescription/generic) | [x] |
| 3 | Scoring engine + `ClassificationService` + laboratory subtype | [x] |
| 4 | SchemaResolver + pipeline wiring + persistence (storage kind, artifact, event, frontmatter) | [x] |
| 5 | Regression dataset & fixtures | [x] |
| 6 | Regression + integration tests & verification | [x] |

## 2. Completed phases

### Phase 1 — Normalization implementation [x]

**Status.** Done — `MarkdownNormalizer` implemented; see "Phase 1 Implementation Status" below.

**Changes.** `apps/ai-worker/app/classification/normalize.py` gained `MarkdownNormalizer`, the concrete `TextNormalizer`: NFC unicode normalization; OCR punctuation variants (dashes, curly quotes, nbsp) mapped to canonical forms; whitespace collapse; case folding. Markdown structure is parsed into `headings` (stripped `#…` text), `tables` (contiguous `|…|` blocks as whole multi-line strings), and `paragraphs` (consecutive text lines). All views are canonicalized (case-folded) for deterministic matching. `metadata` gains `table_count`/`heading_count`/`paragraph_count` plus caller-supplied keys. `MarkdownNormalizer` exported from `app.classification.normalize` `__all__` and `app/classification/__init__.py`. `tests/unit/classification/test_normalize.py` extended with 9 implementation tests (headings/tables/paragraphs extraction, whitespace/case/unicode canonicalization, OCR punctuation, empty/None input, caller metadata, separate table blocks, protocol usability).

**Verification.** All 14 `test_normalize.py` tests pass; classification suite 50 passed (+9, was 41); full ai-worker suite 83 passed (+9, was 74); `uvx ruff check apps/ai-worker` clean. Real markers from `.dev/flow_upload_test/` normalize correctly: `fbbcb675` → 3 tables incl. `| параметр | результат | ед. изм. | референсные значения |`, `b8f07559` → 6 tables, `2b8fdd0d` → 1 table; all three yield headings/paragraphs (acceptance met).

#### Phase 1 Implementation Status

- Files created / modified: `apps/ai-worker/app/classification/normalize.py`, `apps/ai-worker/app/classification/__init__.py`, `apps/ai-worker/tests/unit/classification/test_normalize.py`.
- Deviation: none.
- Behavioral notes: all structural views (`headings`/`tables`/`paragraphs`) are **canonicalized** (case-folded + whitespace-flattened), not just `raw_text` — chosen so detectors match one canonical form everywhere. `Monospace` loss of original case in views is intentional; extraction still consumes the raw marker separately.
- Verification recap: 83 passed (was 74), ruff clean. Commit deferred until phase confirmed.
- Next step: pending — await user confirmation to start Phase 2 (signal detectors).

### Phase 2 — Signal detectors implementation [x]

**Status.** Done — detectors implemented; see "Phase 2 Implementation Status" below.

**Changes.** `signals/base.py` gained shared helpers (literal/regex occurrence counting, markdown-table cell/header extraction). All four detectors implement `detect(document) -> list[ClassificationSignal]`, emitting only matched signals with `name` (`<document_type>.<signal>`), `weight`, `matched`, `matches`:
- Laboratory: `laboratory_section` (+5), `reference_range` (+5), `measurement_unit` (+3, table-cell unit tokens), `result_value` (+5, ≥3 decimal cells), `laboratory_parameter` (+3, structural headers), `abnormal_flag` (+1), `specimen` (+3), `laboratory_number` (+1), `biomarker` (+3), `hematology_marker` (+5); contradictory `appointment_evidence` (−4).
- Appointment: `appointment_section` (+5), `doctor_specialty` (+3), `cabinet` (+3), `appointment_time` (+3), `key_value_patterns` (+5, structural key:value table rows); contradictory `laboratory_evidence` (−4).
- Prescription: `drug_terms` (+5), `dosage_frequency` (+3), `struct_medication_headers` (+3, structural).
- Generic: no-op → `[]` (scoring fallback, not a detector).
`test_signals.py` rewritten: stub-raises test replaced with list-return contract + 12 behavior tests (marker firing, matches counts, contradictory signals, cross-marker suppression, prescription structural).

**Verification.** Classification suite 62 passed (+12, was 50); full ai-worker suite 95 passed (+12, was 83); `uvx ruff check apps/ai-worker` clean. Acceptance met on real markers: `fbbcb675`/`b8f07559` → multiple positive lab signals (result_value, measurement_unit, reference_range, parameter headers, biomarkers); `2b8fdd0d` → appointment loud (appointment_section +7, key_value_patterns +9, doctor_specialty, time, cabinet) while lab detector emits only the −4 contradicting signal; `matches` correct for repeated units (e.g. `fbbcb675` measurement_unit=13, appointment reference_range deduped to header count).

#### Phase 2 Implementation Status

- Files created / modified: `apps/ai-worker/app/classification/signals/base.py`, `signals/{laboratory,appointment,prescription,generic}.py`, `tests/unit/classification/test_signals.py`.
- Deviation: `signals/base.py` gains private helpers (`count_literal`, `count_regex`, `_table_rows`, `_table_headers`, `_clean_cell`) that are implementation detail, not part of the M1 contract surface (`__all__` unchanged).
- Behavioral notes: keyword lists are M2 baselines informed by the real markers — tuning is deliberately deferred to M3 evaluation (do-not-over-fit). Contradicting signals carry `weight=−4` and only emit when their phrases are present. Detector volume on the biochemistry marker is inflated by assay-description phrases ("сыворотке или плазме крови") — accepted for M2, flagged for M3 calibration. Detectors set `score=0`; the scoring engine computes `weight×matches` in Phase 3.
- Verification recap: 95 passed (was 83), ruff clean. Commit deferred until phase confirmed.
- Next step: pending — await user confirmation to start Phase 3 (scoring engine + `RuleBasedClassificationService`).

### Phase 3 — Scoring engine + ClassificationService [x]

**Status.** Done — engine + service implemented; see "Phase 3 Implementation Status" below.

**Changes.** `scoring.py` gained `RuleScoringEngine(ScoringEngine)` and `signal_score()` plus locked constants `STRENGTH_REF=20.0`, `SCORE_FLOOR=5.0`, `AMBIGUITY_MARGIN_RATIO=0.25`. Engine implements §4: per-type totals from `<document_type>.` prefix; top/second/margin (second=0 solo); `confidence = clamp01(0.6*dominance + 0.4*strength)`; level bands; FALLBACK (<5.0 → `other`)/AMBIGUOUS (`margin < 0.25*top`, decision preserved)/ACCEPT with reasons. `service.py` gained `RuleBasedClassificationService(ClassificationServiceBase)`: runs the four detectors, injects the **client hint** boost (+5 strong signal `<type>.client_hint` for recognized `client_type` `lab_result`→laboratory / `prescription`→prescription), scores, computes the **laboratory subtype** rule (hematology ≥ biomarker and > 0 → hematology, biomarker wins → biochemistry, else None), sets `method="rule_score"`, `classifier_version="2.0.0"` and warnings ("low confidence" / "ambiguous classification"). No S3/RabbitMQ/storage imports (guarded by test). `test_scoring.py` (new, 12 tests, incl. 34v4→HIGH / 12v10→LOW-AMBIGUOUS / solo 5→MEDIUM references) + `test_service.py` extended (real-marker classification, ambiguous synthetic doc, client hint recovery, subtype, no-infra-import guard).

**Verification.** Classification suite 83 passed (+21, was 62); full ai-worker suite 116 passed (+21, was 95); ruff clean. Acceptance met on real markers: `fbbcb675`→laboratory/hematology, `b8f07559`→laboratory/biochemistry, `2b8fdd0d`→appointment, synthetic ambiguous → `ambiguous`, `classifier_version="2.0.0"`, `method="rule_score"`.

#### Phase 3 Implementation Status

- Files created / modified: `apps/ai-worker/app/classification/scoring.py`, `service.py`, `__init__.py`, `tests/unit/classification/test_scoring.py`, `tests/unit/classification/test_service.py`.
- Deviation: none. Interpretation notes — (a) the M1 `ClassificationService.classify(document: NormalizedDocument, context)` contract is kept verbatim: the normalizer is *not* invoked inside the service (documents arrive pre-normalized from the Phase 4 pipeline); the plan's "normalizer → detectors → scoring" chain is implemented as pipeline-normalization → service(detectors → scoring). (b) Client-hint signals use the locked `<document_type>.` name convention (`laboratory.client_hint`), so the boost flows into the correct type column without a `client_hint` special-case in the engine.
- Behavioral notes: per-signal `score = weight × matches` (with the `matches>0` guard) is filled into `ClassificationSignal.score` by `RuleScoringEngine.scored_signals`; detectors still emit `score=0`. Confidence on the real markers saturates at 1.00 because contradicting signals drive the runner-up total to 0 (dominance = 1.0); expected for unambiguous docs, revisit only if M3 needs better gradation. Ambiguous decision keeps the top type (decision preserved), extraction routes to generic in Phase 4.
- Verification recap: 116 passed (was 95), ruff clean. Commit deferred until phase confirmed.
- Next step: pending — await user confirmation to start Phase 4 (SchemaResolver + pipeline wiring + persistence).

### Phase 4 — SchemaResolver + pipeline wiring + persistence [x]

**Status.** Done — resolver + pipeline wiring + persistence implemented; see "Phase 4 Implementation Status" below.

**Changes.** `resolver.py` gained `RegistrySchemaResolver(SchemaResolver)` + locked `SCHEMA_PROMPT_KEY` mapping schema keys → canonical prompt keys (`laboratory.v1`→`laboratory`, `prescription.v1`→`prescription`, `generic.v1`→`default`, `appointment.v1`→`default` fallback until `AppointmentCanonical` exists — classification metadata still records `appointment`). `packages/storage` adds `MARKDOWN_KIND_CLASSIFICATION="classification"` and `"classification": "classification_result.json"` in `MARKDOWN_ARTIFACTS` (+ exports, `test_keys.py`). `packages/canonical/metadata.py` gained `ClassificationMeta` + optional `FrontmatterMeta.classification` block; `app/canonical/rendering.py build_frontmatter_meta(..., classification=None)` emits it into YAML frontmatter. `pipeline/context.py` `ProcessingContext` gains optional `processing_id`. `pipeline/pipeline.py handle_structuring` rewired: `MarkdownNormalizer → RuleBasedClassificationService → RegistrySchemaResolver` (AMBIGUOUS forces generic via `default`) → `canonical.yaml` prompt → `build_canonical` (Pydantic = validation gate) → `classification_result.json` artifact uploaded **first** → canonical/structured uploads → `analysis-completed` published only after artifact upload, carrying `data["classification"]` + `classification_key` (no event-contract change). New `app/classification/artifact.py: build_classification_artifact(...)` serializes the verdict + provenance (prompt_key, schema_name, model, prompt_version, schema_version, context ids, timestamps).

**Verification.** ai-worker suite 122 passed (+6, was 116); storage package 15 passed; canonical package 10 passed; ruff clean on `apps/ai-worker`. Acceptance met: event published only after `/classification_result.json` uploaded; appointment marker → generic extraction (`schema_name="generic"`) with `document_type="appointment"` in classification metadata (event `data` + frontmatter `classification:` block); synthetic ambiguous doc → generic extraction with `decision="ambiguous"`; legacy `classify_document_type` untouched.

#### Phase 4 Implementation Status

- Files created / modified: `apps/ai-worker/app/classification/{resolver,artifact,__init__}.py`, `apps/ai-worker/app/pipeline/{pipeline,context}.py`, `apps/ai-worker/app/canonical/rendering.py`, `apps/ai-worker/app/artifacts/{models,__init__}.py`, `packages/storage/storage/{keys,__init__}.py`, `packages/storage/tests/test_keys.py`, `packages/canonical/canonical/{metadata,__init__}.py`, `apps/ai-worker/tests/unit/pipeline/test_pipeline.py`, `apps/ai-worker/tests/unit/classification/test_scoring_resolver.py`.
- Deviation: none. Interpretation notes — (a) `build_canonical(prompt_key, raw)` uses the *prompt key* resolved by `RegistrySchemaResolver` (for appointment this deliberately differs from the classification type); prompt keys and canonical schema names coincide (`laboratory`/`prescription`/`default`) because the resolver is the single prompt→schema promotion point; (b) the artifact embeds `prompt_key`/`schema_name` so provenance is inspectable without dereferencing frontmatter; (c) event `confidence` now carries `classification.confidence` (was hardcoded 1.0).
- Behavioral notes: classification block + artifact give M3 full triage input (decision, confidence, reasons, warnings, signals, prompt_key). Appointment accession: extraction uses the `default` template while classification metadata keeps `document_type="appointment"` — document-type and extraction-fields stay decoupled. AMBIGUOUS forces `default` regardless of the resolved schema.
- Verification recap: 122 passed (was 116) + storage 15 + canonical 10; ruff clean on ai-worker (pre-existing `packages/storage/storage/s3.py:84` E501 left untouched, not in diff).
- Next step: pending — await user confirmation to start Phase 5 (regression dataset & fixtures).

### Phase 5 — Regression dataset & fixtures [x]

**Status.** Done — dataset + fixtures created; see "Phase 5 Implementation Status" below.

**Changes.** `apps/ai-worker/tests/fixtures/classification/{laboratory,appointment,prescription,other}/` created with **copies** (never references) of the three real markers from `.dev/flow_upload_test/` (`fbbcb675`→hematology, `b8f07559`→biochemistry, `2b8fdd0d`→appointment confirmation) plus synthetic `prescription_001`, `appointment_002`, `lab_without_keywords_001` (false-generic edge), `generic_001`. `manifest.json` (`version`, `notes`, `fixtures[]` of `{file, source, expected_type, expected_subtype, expected_decision}`) declares expectations verified against the M2 classifier itself before writing the manifest; new `tests/support/classification_fixtures.py: iter_classification_fixtures()` loader resolves entries to paths (also consumed by Phase 6); `tests/__init__.py` + `tests/support/__init__.py` make it importable.

**Verification.** Phase 5 tests `tests/unit/classification/test_fixture_manifest.py` (7 tests): manifest parses (`version=1.0.0`, 7 fixtures), entries carry required keys, `expected_type`/`expected_decision` are contract enum values, every fixture loads non-empty, per-type directory coverage complete, on-disk `.md` set exactly equals manifest set. ai-worker suite 129 passed (+7, was 122); ruff clean.

#### Phase 5 Implementation Status

- Files created: `apps/ai-worker/tests/fixtures/classification/**` (7 `.md`), `manifest.json`, `tests/support/classification_fixtures.py`, `tests/__init__.py`, `tests/support/__init__.py`, `tests/unit/classification/test_fixture_manifest.py`.
- Deviation: none. Interpretation notes — (a) `lab_without_keywords_001` documents the known false-generic risk: a laboratory-flavoured sheet with no discoverable keyword structure classifies `other`/fallback — precisely what M3 calibration targets; (b) manifest expectations were generated by running the actual M2 classifier over every fixture, so Phase 6 compares against current (true) behaviour rather than aspiration.
- Verification recap: 129 passed (was 122), ruff clean. Commit deferred until phase confirmed.
- Next step: pending — await user confirmation to start Phase 6 (regression + integration verification).

### Phase 6 — Regression + integration verification [x]

**Status.** Done — regression + integration verified; see "Phase 6 Implementation Status" below.

**Changes.** Per-fixture regression `tests/unit/classification/test_regression_dataset.py` over the manifest: parametrized classification of every fixture asserting declared `expected_type`/`expected_subtype`/`expected_decision`; real-lab-marker guard (every real `laboratory/**` marker must classify `laboratory`/`accept`); recall gate ≥95% type-match across the dataset. The dataset grew to 11 fixtures with 4 **real datalab-produced markers** (added by user, all `laboratory`): `datalab-output-27022026.pdf.md` (PDF-text), `datalab-output-gemotest_1_photo.jpg.md` (paper-result photo), `datalab-output-helix_3_photo.jpeg.md` (paper-result photo), `datalab-output-invitro_3_prscreen.jpg.md` (mobile print screen). **Deviation:** `laboratory.py` gained a fifth strong signal `laboratory.microbiology_marker` (+5, locked weight class) — the Helix antibiotic-sensitivity report misclassified as `prescription` because `prescription.drug_terms` matched "назначение…/…препаратам"; vocabulary is generic microbiology terms (посев/флора/микробиологическ/микроорганизм/антибиотик/бактериофаг/биоматериал…), added per Phase 6 acceptance "no lab→wrong-schema on real markers"; recalibration stays M3. The end-to-end pipeline path (`marker.md → classification → resolver → LLM (mocked) → canonical → artifact → event`) is already covered by the Phase 4 pipeline tests.

**Verification.** Classification suite 107 passed; full ai-worker suite 142 passed (+13, was 129); ruff clean on `apps/ai-worker`. Dataset recall 11/11 type-matches (1.0 ≥ 0.95). After the fix: `helix_3` → `laboratory`/accept (conf 0.92), `27022026`/`gemotest`/`invitro` → `laboratory`/`hematology`/accept, no regressions on the original markers (`2b8fdd0d` appointment, `fbbcb675` hematology, `b8f07559` biochemistry, `prescription_001`).

#### Phase 6 Implementation Status

- Files created / modified: `tests/unit/classification/test_regression_dataset.py` (new), `tests/fixtures/classification/` (+4 real datalab markers, `manifest.json` 7→11), `tests/unit/classification/test_fixture_manifest.py` (count/set → 11), `apps/ai-worker/app/classification/signals/laboratory.py` (`microbiology_marker`).
- Deviation: `laboratory.microbiology_marker` is the only detector signal added outside its Phase 2 baseline (rationale above); all four added new signals use locked weight classes only.
- Behavioral notes: `helix` marker carries no hematology/biochemistry subtype → `subtype=None` stored as-is; M3 may add a `microbiology` subtype. `make lint` still reports only pre-existing `packages/storage` errors (`s3.py:84` E501, `test_markdown_helpers.py` I001/F401/UP012) — none in the M2 diff.
- Verification recap: 142 passed (was 129), classification suite 107, ruff clean on ai-worker.
- Next step: none — M2 implementation complete. Await user confirmation of Phase 6 before considering the M2 scope closed.

## 4. Locked design reference (condensed)

**Signal weight classes (M1 constants):** strong ±5 · medium ±3 · weak ±1 · contradicting −4. Per-signal `score = weight × matches` (if `matches > 0`) else `weight` when `matched`.

**Scoring (initial, calibrated in M3 — do not over-fit):**
```text
score_type = Σ scores of signals with prefix "<document_type>."
top = max score; second = 2nd; margin = top − second (second=0 if solo)
dominance = margin / max(top, 1.0)
strength  = min(1.0, top / STRENGTH_REF)          # STRENGTH_REF = 20.0
confidence = clamp01(0.6*dominance + 0.4*strength)
level = HIGH if ≥0.90 else MEDIUM if ≥0.70 else LOW
decision: FALLBACK if top < SCORE_FLOOR(5.0)            → document_type=other
          AMBIGUOUS if margin < 0.25*top                 → extraction via generic, decision preserved
          else ACCEPT
warnings: "low confidence" / "ambiguous classification"
```
Reference points: top 34 vs 4 → ≈0.93 HIGH; 12 vs 10 → ≈0.34 LOW; solo 5 → ≈0.70 MEDIUM.

**Laboratory subtype (rule-based, minimal):** hematology if hematology_marker score ≥ biomarker score and >0; biochemistry if biomarker wins; else `None`.

**Client hint:** recognized `client_type` adds one strong signal `client_hint.laboratory|prescription` (+5).

**Pipeline ordering + artifact JSON (locked):**
```json
{
  "format": "classification/v1",
  "classifier_version": "2.0.0",
  "document_id": "", "document_version_id": "", "patient_id": "", "processing_id": "",
  "classification": { "document_type": "", "document_subtype": null,
    "confidence": 0.0, "confidence_level": "", "decision": "",
    "method": "rule_score", "reasons": [], "signals": [], "warnings": [] },
  "context": { "client_type": "", "schema_name": "", "schema_version": "1.0.0",
    "model": "", "prompt_version": "" },
  "timestamps": { "classified_at": "", "persisted_at": "" }
}
```
`classification` block in event `data` + frontmatter = M1-locked metadata dict. Storage kind `classification` → `classification_result.json`.

**Schema fallback:** `appointment.v1` (and discharge/diagnosis/imaging/consultation) resolve to `generic` extraction until their canonical schemas exist; classification type/subtype remain authoritative in metadata.

## 5. Tests

- Focused: `cd apps/ai-worker && uv run pytest tests/unit/classification -v`
- Full ai-worker: `cd apps/ai-worker && uv run pytest` (baseline 74; ~+20 after M2)
- Pipeline integration: `cd apps/ai-worker && uv run pytest tests/unit/pipeline`
- Storage package (Phase 4 kind change): `cd packages/storage && uv run pytest`
- Lint: `make lint` (repo root)
- Broad: `make test` (optional)

Each phase runs its suites + lint before the status is flipped.

## 6. Implementation order

1. **Phase 1 — Normalization implementation** [x] (foundation for detectors) — DONE
2. **Phase 2 — Signal detectors** [x] (consume `NormalizedDocument`) — DONE
3. **Phase 3 — Scoring + service** [x] (consume signals; pause — this is the classifier core) — DONE
4. **Phase 4 — Resolver + pipeline wiring + persistence** [x] (needs service + storage kind) — DONE
5. **Phase 5 — Regression dataset** [x] (needs nothing; authored in parallel) — parenthetical: do early so Phase 6 tests drive Phases 2–3 behavior — DONE
6. **Phase 6 — Regression + integration verification** [x] — DONE

Each phase: implement → update status in all three places (§1 table, §3 heading, §6 list) → pause for confirmation.

## 7. Notes & conventions

### Gotchas (verified)
- Real regression markers live at `.dev/flow_upload_test/{fbbcb675,b8f07559,2b8fdd0d}/marker.md` — copy, don't reference `.dev` from tests.
- Legacy `classify_document_type` has no pipeline callers since Phase 4 (the pipeline wires `MarkdownNormalizer → RuleBasedClassificationService → RegistrySchemaResolver`); `tests/unit/classification/test_classifier.py` still covers the legacy path. Legacy function + tests **stay intact** in M2 (zero-risk removal later in M3).
- `FrontmatterMeta` uses `extra="allow"`; still add an explicit optional `classification` field so the block serializes reliably.
- `DocumentAnalysisCompleted.data` is a free dict — the `classification` block needs no event-contract change.
- `make lint` runs `uvx ruff check apps packages tests` — Phase 4 touches `packages/storage` and `packages/canonical`, so lint covers those in the same run.
- Baseline: 74 ai-worker tests (41 classification), ruff clean.

### Open decisions (defaults chosen)
- **Confidence formula/constants** (`STRENGTH_REF=20`, 0.6/0.4 blend, `SCORE_FLOOR=5`, margin `0.25×top`): initial deterministic heuristics; calibrated on the regression dataset in M3. Default chosen.
- **Client hint strength:** +5 (strong). Could be lowered after calibration. Default: strong.
- **Laboratory subtype:** minimal hematology/biochemistry/None only; other lab subtypes (`urinalysis`/`hormones`/… in the enum) unclassified in M2. Default: minimal.
- **Appointment→generic extraction in M2:** deliberate, documented fallback until `AppointmentCanonical` (later phase). Not an M2 defect.
- **Legacy `classify_document_type`:** retained (exported, tested) in M2; pipeline stops calling it. Default: retain.
- **Processing `processing_id`:** added as optional `ProcessingContext` field (default None), populated by the pipeline.

### Risks (mitigations in place)
- **Wrong-schema / false-generic regressions** are the top risk (SUMMARY.md §29). Mitigated by locking the real markers as permanent regression fixtures in Phase 5 and keeping `decision`/`confidence` visible in metadata for M3 triage.
- **Appointment classified but extracted as generic** could look like a regression. Mitigated by asserting on `document_type` (not `schema_name`) for appointment fixtures and documenting the fallback in §4.
- **Threshold over-tuning in implementation phase.** Mitigated by explicitly deferring all calibration to M3 and fixing the formula as "initial".
- **No mypy/pyright in CI.** Mitigation: Pydantic validation + import smoke tests + ruff (unchanged convention from M1).

### Versioning policy (locked, from M1 §7)
`classifier_version` stays `"2.0.0"` in M2 (contract semantics unchanged). Any change to decision rules/thresholds/weights that alters outputs → bump minor (`2.1.0`) at the M3 calibration point. Patch = docs/comments.

### Conventions
- Follow `docs/development/CONTRIBUTING.md`; keep changes localized to `apps/ai-worker/app/classification/`, `apps/ai-worker/app/pipeline/`, `apps/ai-worker/app/canonical/rendering.py`, `packages/storage`, `packages/canonical/metadata.py`, plus tests/fixtures.
- Deviations from this plan, if any, are labeled `Deviation:` in a phase's Implementation Status paragraph when signed off.