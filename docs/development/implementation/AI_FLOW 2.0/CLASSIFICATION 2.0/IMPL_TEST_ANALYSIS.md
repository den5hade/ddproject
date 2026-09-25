# Classification 2.1.0 — Flow Test Analysis & Fix Plan

- **Date:** 2026-09-25
- **Test source:** `.dev/flow_upload_test/250926.txt`
- **Classifier version:** `2.1.0`
- **Status:** analysis complete; remediation plan proposed
- **Scope:** six documents listed in the test source; no unlisted documents from `.dev/flow_upload_test/`
- **Implementation status:** no application changes made by this analysis

Related documents:

- [IMPL_RPRT.md](./IMPL_RPRT.md) — Classification 2.0 implementation report
- [IMPL_PLAN.md](./IMPL_PLAN.md) — implementation plan
- [EVAL_IMPL_PLAN.md](./EVAL_IMPL_PLAN.md) — evaluation and calibration plan
- [EVAL_FLOW.md](../../../../apps/ai-worker/app/classification/EVAL_FLOW.md) — classification evaluation runbook

---

## 1. Executive summary

The current implementation is technically reliable for the laboratory and appointment cases represented in the existing regression dataset, but it is not yet a safe general document router.

The six-document test produced two materially incorrect classifications:

- A functional cardiac diagnostic report was classified as `laboratory`.
- An abdominal ultrasound report was classified as `laboratory`.

Both were accepted with high confidence (`0.9454545454545454` and `0.9`). The underlying cause is not corrupt input or an infrastructure failure: diagnostic reports contain numeric measurements, and the laboratory detector currently treats three or more decimal-looking table cells as a strong `laboratory.result_value` signal without requiring laboratory context.

The supported laboratory and appointment cases remain correct. However, the appointment case exposes a separate extraction and privacy gap: it is classified correctly but routed to the generic prompt, and the resulting canonical note contains direct patient identifiers. Diagnostic reports are similarly routed to the laboratory extraction schema, so their findings are presented as laboratory results.

**Verdict:** retain `2.1.0` for the currently covered laboratory/appointment scope, but do not treat the classifier as complete for diagnostic or imaging documents. Implement the P0/P1 items in this document before expanding the supported document-type contract.

### Headline metrics

| metric | result |
|---|---:|
| Documents tested | 6 |
| Correct semantic document type | 4/6 (66.7%) |
| Correct among currently supported laboratory/appointment cases | 4/4 (100%) |
| False laboratory classifications | 2/6 (33.3%) |
| Laboratory precision | 3/5 (60%) |
| Laboratory recall | 3/3 (100%) |
| Classifications accepted with high confidence | 6/6 |
| Technical integrity checks | passed |
| Deterministic read-only rerun | passed |

The small sample must not be interpreted as a stable production accuracy estimate. It is a targeted acceptance test that exposes two high-impact failure modes.

---

## 2. Scope, ground truth, and method

### 2.1 Input selection

The analyzed source file is `.dev/flow_upload_test/250926.txt`. The six IDs below are the complete test scope. Other directories present under `.dev/flow_upload_test/` were not included because they are not listed in the source file.

| short ID | full document ID | source document | ground-truth type | proposed subtype |
|---|---|---|---|---|
| `311a0a42` | `311a0a42-d19c-461d-b2b0-b788d89b075e` | laboratory report, one ESR result | `laboratory` | `hematology` |
| `e9420e81` | `e9420e81-6d47-490b-b68c-544811869238` | complete blood count | `laboratory` | `hematology` |
| `f1130ec3` | `f1130ec3-9ffd-4be9-a9ba-dfc5b76a10c4` | electronic appointment confirmation | `appointment` | `null` |
| `3bee892c` | `3bee892c-16a3-4632-8e23-c5bd3e771524` | functional cardiac diagnostic report | `diagnostic` | `functional_diagnostics` |
| `c4e01278` | `c4e01278-b6a1-4831-aef3-aece8d7ef323` | abdominal ultrasound report | `imaging` | `ultrasound` |
| `b29e3f45` | `b29e3f45-b172-4486-bc71-6029e29b1cb9` | biochemical laboratory report | `laboratory` | `biochemistry` |

Ground truth is derived from the document headings, modality, table structure, and conclusion in each `marker.md`, not from the classifier output.

### 2.2 Artifacts reviewed

For each document, the review compared:

- `marker.md` — source normalized markdown;
- `classification_result.json` — classifier verdict and signal trace;
- `canonical.json` — extraction output;
- `structured.md` — rendered structured output;
- frontmatter and processing metadata;
- the original document and hash metadata where present.

The classifier was rerun read-only against the current source code. The saved verdicts and reasons reproduced exactly, so the observed failures are deterministic behavior of the current implementation rather than a transient LLM result.

### 2.3 Classification and extraction are separate concerns

The current architecture correctly keeps classification and extraction separate:

```text
marker.md
  → MarkdownNormalizer
  → RuleBasedClassificationService
  → RegistrySchemaResolver
  → canonical extraction prompt
  → Pydantic canonical validation
  → artifacts and events
```

Classification answers “what kind of document is this?” Extraction answers “what structured information is present?” The two boundaries must remain explicit, but the resolver must not route a semantically incorrect classification to a valid-looking but inappropriate schema.

---

## 3. Results

### 3.1 Per-document classification

| document | expected | observed | confidence | decision | outcome |
|---|---|---|---:|---|---|
| `311a0a42` | `laboratory/hematology` | `laboratory/hematology` | 1.0 | `accept` | correct |
| `e9420e81` | `laboratory/hematology` | `laboratory/hematology` | 1.0 | `accept` | correct; 22 extracted results |
| `f1130ec3` | `appointment` | `appointment` | 1.0 | `accept` | type correct; generic extraction and privacy issue |
| `3bee892c` | `diagnostic/functional_diagnostics` | `laboratory/null` | 0.9454545454545454 | `accept` | **false laboratory**; diagnostic findings stored as lab results |
| `c4e01278` | `imaging/ultrasound` | `laboratory/null` | 0.9 | `accept` | **false laboratory**; ultrasound findings stored as lab results |
| `b29e3f45` | `laboratory/biochemistry` | `laboratory/biochemistry` | 1.0 | `accept` | correct; 7 extracted results |

The false-laboratory cases are more serious than an ordinary low-confidence error. They have high confidence, no warnings, and a schema that makes the result appear authoritative to downstream consumers.

### 3.2 Extraction and schema routing

| document | observed schema | extraction summary | semantic quality |
|---|---|---|---|
| `311a0a42` | `laboratory` | 1 result, material and staff captured | acceptable for the narrow laboratory schema |
| `e9420e81` | `laboratory` | 22 results, 3 flags | acceptable; large result table is preserved |
| `f1130ec3` | `generic` | one free-form note | insufficiently structured; note contains direct patient identifiers |
| `3bee892c` | `laboratory` | 4 findings represented as laboratory results | semantically wrong; cardiac observations are not laboratory analytes |
| `c4e01278` | `laboratory` | 28 findings represented as laboratory results | semantically wrong; imaging observations are not laboratory analytes |
| `b29e3f45` | `laboratory` | 7 results, equipment and staff captured | acceptable for the narrow laboratory schema |

The generic appointment output also records `document_date: 2026-03-07` while the appointment date in the source is `19 марта` without a year. The year is therefore inferred rather than present in the appointment line. The generic prompt does not define how to preserve ambiguous source dates safely.

### 3.3 Artifact integrity and reproducibility

| check | result | interpretation |
|---|---|---|
| Required artifact presence | pass | all six directories contain the expected source and output artifacts |
| JSON parsing and required fields | pass | all saved artifacts parse and contain the expected fields |
| Document IDs and document-version IDs | pass | classification, canonical, and frontmatter identifiers agree |
| SHA-256 metadata | pass | no artifact-integrity mismatch found |
| Page count/frontmatter consistency | pass | page metadata is coherent with the source artifacts |
| Pydantic/canonical schema gate | pass | all stored canonical payloads are structurally valid |
| Classification/canonical metadata consistency | pass mechanically | both artifacts agree on the observed type; this does not prove semantic correctness |
| Read-only classifier rerun | pass | all six verdicts and reasons reproduce |

The validation result is therefore structurally green but semantically incomplete. `build_validation_meta()` defaults to `status: valid` and `schema_valid: true`; it does not evaluate whether the document type matches the content, whether the extraction preserves the important fields, or whether PII is present.

### 3.4 Operational metadata

- The six documents contain 12 source pages in total.
- The artifacts record 20,085 extraction tokens in total; this is an operational observation, not a performance benchmark.
- `cost_usd` is currently reported as `0.0` by a hard-coded/default value and must not be treated as measured cost.
- `processing_id` is `null` in the reviewed artifacts, which weakens end-to-end correlation.
- Stage latency is not recorded in the artifacts, so classification and extraction latency cannot be compared from this test alone.

---

## 4. Findings and root causes

### F-01 — Numeric diagnostic measurements are treated as laboratory results

**Evidence.** `laboratory.result_value` fires when a table contains at least three decimal-looking cells. The cardiac document produces 13 matches and a score of 65; the ultrasound document produces 7 matches and a score of 35. Neither document contains laboratory markers, reference ranges, a tested specimen, or a laboratory report heading.

**Impact.** A valid-looking canonical laboratory payload is generated with a `laboratory` type, which downstream structured output and UI interpret as laboratory measurements. Confidence is high because the wrong signal is strong, not because the semantic decision is verified.

**Code references.**

- `apps/ai-worker/app/classification/signals/laboratory.py:69-70` — numeric-cell pattern;
- `apps/ai-worker/app/classification/signals/laboratory.py:241-249` — unconditional `result_value` emission;
- `apps/ai-worker/app/classification/signals/laboratory.py:327-345` — microbiology signal, which does not apply to these reports;
- `apps/ai-worker/app/classification/service.py:74-79` — only laboratory, appointment, prescription, and generic detectors are active.

**Required fix.** Laboratory numeric evidence must be contextual. A numeric table alone must not be sufficient to accept `laboratory`. Add diagnostic/imaging detectors and a laboratory gate that requires at least one laboratory-specific signal such as a laboratory section, reference range, specimen, or laboratory analyte/header.

### F-02 — Instrumental diagnostics and imaging have no active classifier route

`DocumentType` already contains `IMAGING`, but the service does not instantiate an imaging detector. There is no `DIAGNOSTIC` value for non-image instrumental reports, and the resolver maps both `diagnosis` and `imaging` to the generic schema.

**Code references.**

- `apps/ai-worker/app/classification/models.py:15-25` — current `DocumentType` enum;
- `apps/ai-worker/app/classification/resolver.py:20-32` — imaging/diagnosis fall back to `generic.v1`;
- `apps/ai-worker/app/classification/resolver.py:35-40` — generic prompt mapping.

**Impact.** Even if an image keyword is recognized, there is no supported canonical schema for a diagnostic study or ultrasound report. The current output loses modality-specific meaning and exposes it through the wrong result-card model.

**Required fix.** Add an explicit taxonomy and extraction route:

- `diagnostic/functional_diagnostics` for the functional cardiac report;
- `imaging/ultrasound` for the abdominal ultrasound report;
- a diagnostic/imaging canonical schema that preserves study name, protocol, findings, measurements, conclusion, equipment, recommendations, and staff.

### F-03 — Appointment classification is correct, but extraction and privacy controls are incomplete

The appointment is correctly identified with strong structural evidence, but `appointment.v1` is deliberately routed to the default generic prompt. The generic prompt has no explicit prohibition against patient identity data. The resulting note contains the patient’s full name and residential address.

**Code references.**

- `apps/ai-worker/app/classification/resolver.py:9-13,23-24,35-40` — appointment schema exists but resolves to `default`;
- `apps/ai-worker/app/prompts/canonical.yaml:5-26` — generic prompt and envelope;
- `apps/ai-worker/app/prompts/canonical.yaml:96-101` — laboratory prompt contains the PII rule that generic extraction lacks;
- `.dev/flow_upload_test/f1130ec3-9ffd-4be9-a9ba-dfc5b76a10c4/canonical.json:10` — direct identifiers in the generated note (values intentionally not repeated here).

**Impact.** Appointment data is not structured into appointment-specific fields, and the canonical artifact can expose direct patient identifiers. This is a data-minimization issue as well as a product-quality issue.

**Required fix.** Implement `AppointmentCanonical`, route appointment classifications to it, apply a common PII policy to every prompt, and add a deterministic post-extraction redaction/check step. The appointment schema should retain appointment date/time, doctor, specialty, organization, department, location, and a non-patient reference identifier only when policy permits it.

### F-04 — Appointment time matching is not context-bound

The cardiac and ultrasound reports contain times in their examination metadata, so the appointment detector emits `appointment.appointment_time` even though the documents are not appointments. This signal contributes to the wrong classification rather than suppressing it.

**Code references.**

- `apps/ai-worker/app/classification/signals/appointment.py:55-57` — time phrases/regex;
- `apps/ai-worker/app/classification/signals/appointment.py:123-134` — time signal is emitted from raw text;
- `.dev/flow_upload_test/3bee892c-16a3-4632-8e23-c5bd3e771524/classification_result.json:26-32` — time evidence in a diagnostic report;
- `.dev/flow_upload_test/c4e01278-b6a1-4831-aef3-aece8d7ef323/classification_result.json:26-32` — time evidence in an ultrasound report.

**Required fix.** Require appointment context for time evidence: an appointment heading, electronic-registration phrase, ticket/doctor/cabinet fields, or a structurally recognized appointment table. A bare `HH:MM` value must be weak or neutral evidence.

### F-05 — “Номер карты” is incorrectly treated as a laboratory number

Both instrumental reports contain a patient card number, and the laboratory detector includes `номер карты` in its weak laboratory-number vocabulary. This is patient metadata, not evidence that the document is a laboratory report.

**Code reference.** `apps/ai-worker/app/classification/signals/laboratory.py:94-102`.

**Required fix.** Remove generic `номер карты` from laboratory evidence. Keep only explicit laboratory identifiers such as `лаб. номер`, `номер заказа`, `номер пробы`, or `номер анализа` when they occur in laboratory context.

### F-06 — Confidence measures score dominance, not semantic correctness

The confidence formula is:

```text
dominance = margin / max(top, 1.0)
strength  = min(1.0, top / STRENGTH_REF)
confidence = 0.6 * dominance + 0.4 * strength
```

This measures how strongly one rule bucket wins over another. It does not measure whether the winning type is semantically appropriate. A false laboratory result can therefore be `high` confidence.

**Code reference.** `apps/ai-worker/app/classification/scoring.py:137-150`.

The pipeline also copies `classification.confidence` into the `DocumentAnalysisCompleted.confidence` field at `apps/ai-worker/app/pipeline/pipeline.py:223-235`. Consumers can therefore mistake classification confidence for extraction confidence.

**Required fix.** Keep classification confidence and extraction quality as separate concepts. Add explicit extraction quality/confidence metadata, semantic validation warnings, and a versioned event contract decision. Do not silently change the meaning of an existing event field.

### F-07 — Validation is structural and defaults to green

`build_validation_meta()` returns `valid`, `schema_valid: true`, and an empty warning list by default. The artifact is accepted because it matches a Pydantic shape, not because the selected schema is appropriate for the document.

**Code reference.** `apps/ai-worker/app/canonical/validation.py:7-20`.

**Required fix.** Add semantic checks for:

- type/schema agreement;
- required document-specific sections;
- suspicious type/schema combinations such as diagnostic content in a laboratory payload;
- PII in canonical and structured outputs;
- date ambiguity and source/date disagreement;
- extraction completeness and OCR-quality indicators;
- source marker versus canonical type mismatch.

### F-08 — Operational provenance is incomplete

The reviewed artifacts show `processing_id: null`, a hard-coded `cost_usd: 0.0`, and no stage-level latency. This prevents reliable production diagnosis of model latency, token cost, and processing correlation.

**Required fix.** Populate processing correlation IDs, calculate or explicitly mark cost as unavailable, and record separate classifier, extraction, validation, and upload timings.

---

## 5. Proposed fix plan

Status legend: `[ ]` not started · `[x]` complete.

### Phase 0 — Lock the evidence and contain false laboratory results [ ]

**Goal:** prevent known diagnostic/imaging reports from being accepted as laboratory documents while the full taxonomy is implemented.

1. Add the six source markers to a versioned regression fixture set. Copy them into `apps/ai-worker/tests/fixtures/classification/`; tests must not depend on `.dev`.
2. Add ground-truth expectations for:
   - `laboratory/hematology`;
   - `laboratory/biochemistry`;
   - `appointment`;
   - `diagnostic/functional_diagnostics`;
   - `imaging/ultrasound`.
3. Add negative assertions for `false_laboratory == 0` and diagnostic/imaging content not routed to `laboratory.v1`.
4. Make `laboratory.result_value` conditional on laboratory context. At minimum, require a laboratory section, reference range, specimen, laboratory table headers, or a laboratory analyte marker.
5. Remove `номер карты` from `_LAB_NUMBER_PHRASES`.
6. Make time-only evidence neutral unless appointment context is present.

**Exit criteria.** The two known instrumental reports cannot be accepted as `laboratory`; all three laboratory reports and the appointment remain correct. The regression suite must fail if either false-laboratory case returns.

**Likely files.**

- `apps/ai-worker/app/classification/signals/laboratory.py`
- `apps/ai-worker/app/classification/signals/appointment.py`
- `apps/ai-worker/app/classification/service.py`
- `apps/ai-worker/tests/fixtures/classification/manifest.json`
- `apps/ai-worker/tests/fixtures/classification/**`
- `apps/ai-worker/tests/unit/classification/**`

### Phase 1 — Add diagnostic and imaging taxonomy/detectors [ ]

**Goal:** classify the documents by the actual domain rather than by the presence of numbers.

1. Extend `DocumentType` with `diagnostic` or agree on an equivalent contract-level representation for non-image instrumental studies.
2. Add and register `DiagnosticSignalDetector` and `ImagingSignalDetector`.
3. Add high-precision signals for:
   - `протокол инструментального исследования`;
   - `функциональная диагностика`, ECG/HRV and other modality terms;
   - `ультразвуковое исследование`, `УЗ-аппарат`, probe/frequency terms;
   - diagnostic/imaging protocol and conclusion sections.
4. Add negative or contradictory laboratory evidence when a document has a diagnostic/imaging protocol and lacks laboratory-specific markers.
5. Add subtype rules for the observed modalities without hard-coding document IDs.
6. Update the contract, scoring, metadata, event, and frontend type consumers together.

**Exit criteria.** `3bee892c...` resolves to `diagnostic/functional_diagnostics`; `c4e01278...` resolves to `imaging/ultrasound`; neither receives a laboratory subtype or laboratory prompt.

**Contract impact.** Adding a new `DocumentType` value is a wire-contract change. The classifier version should be bumped from `2.1.0` to `2.2.0` when the new routing is enabled.

### Phase 2 — Add dedicated extraction schemas [ ]

**Goal:** preserve clinically meaningful structure instead of coercing all measurements into laboratory results.

1. Add `DiagnosticCanonical` and `ImagingCanonical`, or a shared diagnostic schema with explicit modality-specific fields and a type discriminator. The preferred design is a shared diagnostic model plus a distinct `type` value so consumers can distinguish `diagnostic` and `imaging` without duplicating field definitions.
2. Add an `AppointmentCanonical` schema with explicit appointment fields.
3. Register all three schemas in `SCHEMA_REGISTRY` and `SCHEMA_PROMPT_KEY`.
4. Add prompts with strict field allowlists and null/uncertain handling.
5. Keep institution, study, equipment, conclusion, recommendations, and performing staff where present.
6. Render the new schemas in `structured.md` and update the web extraction viewer so the model is not restricted to observation cards.

**Exit criteria.**

- cardiac findings remain diagnostic observations, not laboratory analytes;
- ultrasound measurements remain imaging findings with modality and conclusion;
- appointment date/time and provider fields are structured;
- no generic free-form note is used for a supported appointment or diagnostic document.

**Likely files.**

- `apps/ai-worker/app/classification/resolver.py`
- `apps/ai-worker/app/canonical/` schema and rendering modules
- `apps/ai-worker/app/prompts/canonical.yaml`
- `apps/web/` extraction viewer and API type files
- `apps/ai-worker/tests/unit/pipeline/test_pipeline.py`
- `apps/ai-worker/tests/unit/classification/test_scoring_resolver.py`

### Phase 3 — Enforce PII minimization and source fidelity [ ]

**Goal:** ensure canonical and downstream artifacts contain only data allowed by the medical-data policy.

1. Add the same identity exclusion rules to every prompt, not only the laboratory prompt.
2. Add a post-extraction validation/redaction layer for canonical and structured output. At minimum, detect patient name, date of birth, OMS policy number, SNILS, phone, home address, identity-document data, and patient card number.
3. Preserve source text only in the immutable source artifact, not in the canonical note.
4. Preserve ambiguous dates verbatim and set parsed date fields to `null` when the year is not supported by the source.
5. Add tests for both prompt output and the deterministic post-processing layer.

**Exit criteria.** The appointment canonical output contains no direct patient identifiers; the appointment year is not silently invented; all existing laboratory outputs continue to pass schema and PII tests.

### Phase 4 — Separate confidence, validation, and provenance [ ]

**Goal:** make operational metadata explainable and semantically safe.

1. Preserve the existing `classification.confidence` meaning as classifier score confidence.
2. Add a separate extraction quality/confidence field and document its calculation.
3. Decide whether `DocumentAnalysisCompleted.confidence` represents extraction confidence or classification confidence; make the decision explicit in the event contract and version it if necessary.
4. Populate `processing_id` consistently.
5. Record stage timings: normalization/classification, LLM extraction, validation, upload, and total.
6. Replace hard-coded zero cost with a measured value or an explicit unavailable/null state.

**Exit criteria.** A consumer can distinguish “classifier is confident” from “the extracted content is complete and trustworthy,” and every failed or degraded extraction has an actionable warning.

### Phase 5 — Expand regression and release gates [ ]

**Goal:** prevent recurrence and make the next classifier version measurable.

1. Add the six fixtures to the manifest with source, expected type, subtype, decision, schema, and relevant extraction assertions.
2. Add a diagnostic/imaging detector test for each modality.
3. Add resolver tests for every new type/subtype.
4. Add a canonical fixture test for appointment, diagnostic, and imaging required fields.
5. Add PII, date-ambiguity, and wrong-schema tests.
6. Add metrics for:
   - type accuracy;
   - false laboratory count;
   - wrong-schema count;
   - PII leakage;
   - extraction field completeness;
   - confidence correctness by band;
   - deterministic reruns.
7. Run the existing 11-fixture dataset and the new six-document set together.

**Acceptance criteria.**

- 6/6 new documents have the expected semantic type.
- 0 false-laboratory classifications.
- 0 wrong-schema outputs on the new diagnostic, imaging, and appointment cases.
- 100% of supported appointment/diagnostic/imaging cases use their dedicated schema.
- 0 direct patient identifiers in canonical, structured, or event data.
- Existing regression fixtures remain green.
- Repeated classification runs remain byte-identical.
- The classifier version and all dependent contract tests are updated together.

---

## 6. Recommended release order

1. **Immediate containment:** Phase 0 only. This should prevent the known false-laboratory failure without changing the public taxonomy.
2. **Shadow evaluation:** run Phases 1–3 behind a feature flag or in a non-production evaluation mode; compare against the six-document ground truth and the existing 11-fixture dataset.
3. **Contract migration:** update all classification, canonical, storage, event, API, and frontend consumers before enabling new types.
4. **Classifier version:** bump to `2.2.0` when diagnostic/imaging routing changes output semantics.
5. **UI enablement:** deploy the new extraction renderers only after the dedicated schemas are available.
6. **Calibration:** expand the real-document dataset beyond this six-document set before tuning thresholds globally; the current sample is too small for broad percentage-based calibration.

---

## 7. Risks and decisions

| risk/decision | recommendation |
|---|---|
| New `diagnostic` type is a public contract change | Version the event/storage contract and migrate consumers together |
| Diagnostic and imaging can share extraction fields | Share a model if useful, but retain distinct `type` values for routing and UI |
| Adding stronger numeric rules may reduce laboratory recall | Add real laboratory negatives and positives before changing weights; measure false-laboratory separately |
| Generic prompt is used by several types | Apply a shared safety policy and post-extraction check rather than relying on one prompt |
| Confidence is already consumed downstream | Do not silently repurpose the existing event field; add an explicit extraction-quality field |
| Small sample encourages overfitting | Treat the six documents as a regression gate, not a calibration dataset; add more real markers before broad tuning |
| `номер карты` is ambiguous across document types | Treat it as neutral patient metadata unless paired with explicit laboratory context |

---

## 8. Verification commands

Run from the repository root unless noted:

```text
make lint
make eval-classification
uv run --project apps/ai-worker pytest apps/ai-worker/tests/unit/classification -v
```

Run the pipeline tests from `apps/ai-worker` so the prompt paths resolve:

```text
uv run pytest tests/unit/pipeline -v
```

A broad suite can be run with:

```text
make test
```

There is no separate `typecheck`/mypy/pyright target defined in the repository Makefile. Python type safety is currently covered by Pydantic validation, import smoke tests, and the pytest suites. If a type checker is added later, it should be included in the release gate for all new canonical models and event contracts.

---

## 9. Definition of done

The fix is complete when:

- the two instrumental reports are no longer classified as laboratory;
- diagnostic and imaging reports have explicit types, subtypes, schemas, and renderers;
- appointment reports have a dedicated privacy-safe canonical schema;
- numeric table evidence cannot independently force a laboratory classification;
- patient identifiers are removed from canonical, structured, and event data;
- classification confidence, extraction quality, validation warnings, cost, latency, and processing correlation are distinct and observable;
- the six-document regression and the existing 11-fixture regression are both green;
- repeated runs are deterministic;
- the classifier version, contract tests, API types, and documentation are updated consistently.

**Recommended next action:** implement Phase 0 as an isolated bug-fix change, then use its regression results to size the taxonomy/schema migration in Phases 1–3.
