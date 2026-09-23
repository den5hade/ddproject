# Classification 2.0 — Implementation Plan (M1: Contract Only)

**Scope.** This plan defines **M1 – Classification 2.0 contract** only (specification, schemas, models, service interfaces, normalization/signals/scoring contracts, and versioning). No implementation of detection logic, no LLM calls, no pipeline wiring in this plan. The contour is built on existing infra only — no parallel architecture.

**Depth sources:** [IMPL_RPRT.md](./IMPL_RPRT.md) (implementation report; the superseded design spec is preserved in git history, referenced below as "design-spec §…"), [AI_FLOW 2.0/STRUCTURE.md](../STRUCTURE.md#1-ai-worker), [AI_FLOW 2.0/ORDER.md](../ORDER.md#1-classification-20), [IMPL_PLAN_SCHEMA.md](../../operational/IMPL_PLAN_SCHEMA.md). The plan keeps condensed summaries only; full design is superseded — the implementation report and code are the source of truth (original spec in git history).

**Revision 1** — initial M1-only plan (2025-09-22).

**Status legend:** `[ ]` pending · `[x]` done.

---

## 0. Overview

**Current state (as-is):** ai-worker uses keyword-based `classify_document_type(markdown, client_type)` in `apps/ai-worker/app/classification/classifier.py` returning `"laboratory"|"prescription"|"default"`. The string is passed directly to prompt dispatch (`canonical.yaml` by doc-type) and to `canonical.build_canonical` which falls back to `GenericCanonical` for `"default"`. `NormalizedDocument` does not exist. Classification 2.0-related modules are empty placeholders: `app/classification/{models,resolver,scoring,normalize}.py`, `app/classification/signals/{base,laboratory,prescription,appointment,generic}.py`, `app/canonical/registry/{definitions,registry,resolver}.py`, `app/canonical/core/__init__.py`.

**Target state (M1 contract):** Define a deterministic, rule-based classification contract inside `apps/ai-worker/app/classification/` with flat layout (aligning with STRUCTURE.md §4). The contract consists of:
- Domain models/enums: `DocumentType`, `DocumentSubtype` (laboratory/appointment/prescription/discharge/diagnosis/imaging/consultation/other), `ClassificationConfidence`, `ClassificationDecision`, `ClassificationSignal`, `ClassificationResult` (Pydantic). These are **contract types only** (no scoring logic implemented in M1).
- Schemas (JSON Schema exports) for `ClassificationResult` and signals to enforce a stable wire contract across pipeline stages.
- Service interface: `ClassificationService` protocol/class with `classify(document: NormalizedDocument, context: ProcessingContext) -> ClassificationResult` (method signatures only; bodies may be `NotImplementedError` or minimal stubs returning the type). No detector implementations, no scoring algorithm code beyond type contracts.
- Normalization contract: `NormalizedDocument` dataclass and `TextNormalizer` protocol (method signatures + field contracts). No normalization implementation in M1.
- Signals contract: `SignalDetector` base/protocol and per-type detector class stubs (`LaboratorySignalDetector`, `AppointmentSignalDetector`, `PrescriptionSignalDetector`, `GenericSignalDetector`) with explicit return types (`list[ClassificationSignal]`). No regex/weight logic.
- Scoring/decision contract: `ScoringEngine` protocol + `ClassifierVersion` constant. Weights, thresholds, margin rules are **documented as contract constants** (not computed). Decision fields (`confidence`, `confidence_level`, `decision`, `method`, `reasons`, `signals`, `classifier_version`) are defined and versioned.
- Schema resolution contract: `SchemaResolver` protocol and `SCHEMA_REGISTRY` mapping shape `(document_type, document_subtype) -> schema_key` (values documented, no runtime resolution logic required to execute beyond type hints in M1, but the mapping contract is locked).
- Versioning: `classifier_version = "2.0.0"` constant and versioning policy recorded.

**Invariants (locked):**
- Classification is **deterministic and rule-based by contract** (method = `"rule_score"` in the contract; LLM fallback remains out of scope for M1). 
- Boundary: *Classification answers “what kind of document is this?”; Extraction answers “what structured medical information is contained in this document?”* (per design-spec §1443). 
- **No import dependency** from `classification/` to `canonical/extraction` schemas (one-way dependency: pipeline/orchestration maps `document_type` → schema via `SchemaResolver`).
- Flat module layout inside `apps/ai-worker/app/classification/` (aligns with STRUCTURE.md §4). The `domain/` subpackage proposed in design-spec §33 is **not used** in this plan; this is an explicit deviation from the design spec and is recorded here (see §7).
- `NormalizedDocument` is introduced as a contract type (separate from existing canonical extraction models). Marker.md enters pipeline as text; normalization produces `NormalizedDocument` (structure: `raw_text`, `headings`, `tables`, `paragraphs`, `metadata`).
- Classification result is an explicit `ClassificationResult` object (not a bare string). Pipeline integration point is the `ClassificationService.classify` contract (wiring deferred to M2/M3).
- Versioning is mandatory: `classifier_version = "2.0.0"` constant; any future change to the contract increments version per SemVer (policy in §7).
- Classification metadata persistence shape is **locked** (§4): `{"classification": {...}}` block (no new DB table in this contour). S3 artifact `classification/result.json` path shape is locked.

---

## 1. Execution summary

| Phase | Scope | Status |
|---|---|---|
| 1 | Domain contract (enums, models, ClassificationResult, signals, decision, confidence) | [x] |
| 2 | Schemas (JSON Schema exports) for ClassificationResult/signals | [x] |
| 3 | Service interface (ClassificationService protocol + service.py contract stubs) | [x] |
| 4 | Normalization contract (NormalizedDocument + TextNormalizer protocol) | [x] |
| 5 | Signals contract (SignalDetector base + per-type detector stubs) | [x] |
| 6 | Scoring/decision + SchemaResolver contract + Versioning | [x] |

---

## 2. Completed phases

### Phase 1 — Domain contract [x] (2025-09-22)

**Status:** Complete — contract types only, no behavior changes. Files changed:
- `apps/ai-worker/app/classification/models.py` — enums (`DocumentType`, `LaboratorySubtype`, `ClassificationConfidenceLevel`, `ClassificationDecision`, `ClassificationMethod`) and Pydantic models (`ClassificationSignal`, `ClassificationResult`) with `extra="forbid"`. `ClassificationResult.method` is the string `Literal["rule_score","llm_fallback","manual"]` per the locked shape; `ClassificationMethod` enum also provided for programmatic use.
- `apps/ai-worker/app/classification/exceptions.py` — added `InvalidClassificationInputError`, `SchemaResolutionError` (empty contract subclasses).
- `apps/ai-worker/app/classification/__init__.py` — exported Phase 1 types; legacy `classify_document_type` retained.
- `apps/ai-worker/tests/unit/classification/test_models.py` — new contract tests (enum values, defaults, `extra="forbid"`, exception hierarchy). `test_classifier.py` untouched.

**Verification:** 16 tests pass (`uv run pytest tests/unit/classification`), `make lint` clean on touched paths, import smoke check passes.

**Deviation:** flat layout within `apps/ai-worker/app/classification/` chosen over the `domain/` subpackage proposed in design-spec §33, matching STRUCTURE.md §4 and existing scaffolding (identical to the deviation recorded in §7).

### Phase 2 — Schemas [x] (2025-09-22)

**Status:** Complete — `apps/ai-worker/app/classification/schemas.py` exports `CLASSIFICATION_RESULT_SCHEMA` and `CLASSIFICATION_SIGNAL_SCHEMA`, derived at import time from the Phase 1 Pydantic models via `model_json_schema()` (guarantees enum values/required fields/defaults stay in sync; no runtime generation CLI). New `tests/unit/classification/test_schemas.py` locks schema keys, `additionalProperties: false`, and enum parity with the models.

**Verification:** 20 tests pass, `make lint` clean on touched paths.

### Phase 3 — Service interface [x] (2025-09-22)

**Status:** Complete — `apps/ai-worker/app/classification/service.py` defines `ClassificationService` (Protocol) with `async def classify(self, document, context) -> ClassificationResult` using `from __future__ import annotations` + `TYPE_CHECKING` for `NormalizedDocument`/`ProcessingContext` (no circular imports; both types are forward references until Phase 4). `ClassificationServiceBase` stub raises `NotImplementedError` on instantiation. New `tests/unit/classification/test_service.py` verifies protocol-ness, base-stub behavior, and that a structurally conforming implementation is invocable through the protocol.

**Verification:** 23 tests pass, ruff clean on touched paths.

### Phase 4 — Normalization contract [x] (2025-09-22)

**Status:** Complete — `apps/ai-worker/app/classification/normalize.py` defines frozen dataclass `NormalizedDocument(raw_text, headings, tables, paragraphs, metadata)` (stdlib only) and sync `TextNormalizer` Protocol (`normalize(markdown: str) -> NormalizedDocument`); sync choice documented in module docstring per §7 default. `NormalizedDocument` added to package exports. New `tests/unit/classification/test_normalize.py` verifies field/default/frozen behavior and structural protocol conformance.

**Verification:** 28 tests pass, ruff clean on touched paths, import smoke check for `NormalizedDocument` passes.

### Phase 5 — Signals contract [x] (2025-09-22)

**Status:** Complete — `signals/base.py` defines `SignalDetector` Protocol (`detect(document) -> list[ClassificationSignal]`, string annotations for `NormalizedDocument`) alongside the existing legacy `Signal` placeholder (kept intact). Detector stubs `LaboratorySignalDetector`, `AppointmentSignalDetector`, `PrescriptionSignalDetector`, `GenericSignalDetector` conform to the protocol, raise `NotImplementedError` on `detect`, and document their intended signal categories. `signals/__init__.py` exports all four plus `Signal`/`SignalDetector`. New `tests/unit/classification/test_signals.py` verifies protocol-ness, conformance, stub behavior, return annotations, and package exports.

**Verification:** 33 tests pass, ruff clean on touched paths.

### Phase 6 — Scoring/decision + SchemaResolver contract + Versioning [x] (2025-09-22)

**Status:** Complete — `scoring.py` defines `CLASSIFIER_VERSION = "2.0.0"`, contract constants (`WEIGHT_STRONG/WEIGHT_MEDIUM/WEIGHT_WEAK/WEIGHT_CONTRADICTING`, `THRESH_HIGH_MIN`/`THRESH_MED_LOW`), the documented margin rule, and the `ScoringEngine` Protocol (all informational in M1, nothing computed). `resolver.py` defines the locked `SCHEMA_REGISTRY` mapping shape (specialized keys for laboratory/appointment/prescription; `generic.v1` for other + placeholders) and the `SchemaResolver` Protocol. `__init__.py` exports `CLASSIFIER_VERSION` alongside the Phase 1 public API. New `tests/unit/classification/test_scoring_resolver.py` locks version, weights, thresholds, registry shape, and protocol usability.

**Verification:** 41 tests pass, ruff clean on touched paths, acceptance import smoke check prints `ok`.

**M1 complete:** all six phases done. Contract-only — no detection logic, no pipeline wiring; `test_classifier.py` and the legacy `classify_document_type` path are untouched.

---

## 3. Pending phases

### Phase 1 — Domain contract [x]

**Scope.** Create contract types in flat layout: `apps/ai-worker/app/classification/models.py`, `apps/ai-worker/app/classification/exceptions.py` (if needed), and `apps/ai-worker/app/classification/__init__.py` exports. Define enums/models with full field descriptions and Literal constraints (no behavior).

**Deliverables (file-level contracts):**
- `apps/ai-worker/app/classification/models.py` (new or extended from placeholder):
  - `class DocumentType(str, Enum)`: `LABORATORY="laboratory"`, `APPOINTMENT="appointment"`, `PRESCRIPTION="prescription"`, `DISCHARGE="discharge"`, `DIAGNOSIS="diagnosis"`, `IMAGING="imaging"`, `CONSULTATION="consultation"`, `OTHER="other"`.
  - `class LaboratorySubtype(str, Enum)`: `HEMATOLOGY="hematology"`, `BIOCHEMISTRY="biochemistry"`, `URINALYSIS="urinalysis"`, `HORMONES="hormones"`, `MICROBIOLOGY="microbiology"`, `UNKNOWN="unknown"`.
  - `class ClassificationConfidenceLevel(str, Enum)`: `HIGH="high"`, `MEDIUM="medium"`, `LOW="low"`.
  - `class ClassificationDecision(str, Enum)`: `ACCEPT="accept"`, `AMBIGUOUS="ambiguous"`, `FALLBACK="fallback"`.
  - `class ClassificationMethod(str, Enum)` (or `Literal`): `"rule_score"`, `"llm_fallback"`, `"manual"`.
  - `class ClassificationSignal(BaseModel)`: `name: str`, `weight: float`, `matched: bool`, `matches: int = 0`, `score: float = 0.0` (Pydantic v2, `extra="forbid"`). Field contracts only.
  - `class ClassificationReason(str)` not required; use `list[str]` in result (human-readable). Keep machine-readable in `signals`.
  - `class ClassificationResult(BaseModel)`: `document_type: DocumentType`, `document_subtype: str | None = None`, `confidence: float` (0.0–1.0 range documented), `confidence_level: ClassificationConfidenceLevel`, `decision: ClassificationDecision`, `method: Literal["rule_score","llm_fallback","manual"] = "rule_score"`, `reasons: list[str]`, `signals: list[ClassificationSignal]`, `classifier_version: str`, `warnings: list[str] = []`. `extra="forbid"`.
- `apps/ai-worker/app/classification/exceptions.py`: define `ClassificationError(Exception)`, `InvalidClassificationInputError(ClassificationError)`, `SchemaResolutionError(ClassificationError)` (empty classes, contracts only).
- `apps/ai-worker/app/classification/__init__.py`: export key types (document the public API surface).

**Deps:** None.  
**Accept:** All enums/models exist as above, importable (`from app.classification import models`), type hints complete, Pydantic models validate with `extra="forbid"`, no runtime logic beyond field defaults. Unit import test passes conceptually.

### Phase 2 — Schemas (JSON Schema exports) [x]

**Scope.** Define stable wire contracts (JSON Schema) for `ClassificationResult` and related types without generating code at runtime in M1 (documented schema objects or `.py` constants). Store under `apps/ai-worker/app/classification/schemas.py` (flat layout per STRUCTURE.md §4; placeholder exists conceptually).

**Deliverables:**
- `apps/ai-worker/app/classification/schemas.py`:
  - `CLASSIFICATION_RESULT_SCHEMA: dict` (JSON Schema Draft 7/2020-12 or Pydantic model_json_schema()) — documents required fields: `document_type`, `document_subtype`, `confidence`, `confidence_level`, `decision`, `method`, `reasons`, `signals`, `classifier_version`, `warnings`. 
  - `CLASSIFICATION_SIGNAL_SCHEMA: dict` — for `signals[]` items.
  - Comments documenting enums values and constraints (0.0 ≤ confidence ≤ 1.0). No schema generation CLI required in M1.

**Deps:** Phase 1.  
**Accept:** Schema dicts exist, reference the same enum values as Phase 1, importable. No behavior changes.

### Phase 3 — Service interface [x]

**Scope.** Define `ClassificationService` contract only (protocol/class) in flat layout. `apps/ai-worker/app/classification/service.py` and/or `__init__.py` exports. No detector/scoring implementation.

**Deliverables:**
- `apps/ai-worker/app/classification/service.py` (create contract):
  - `class ClassificationService(Protocol)` or `ABC`:
    - `async def classify(self, document: "NormalizedDocument", context: "ProcessingContext") -> "ClassificationResult": ...` (protocol method, no body required)
  - Optional `ClassificationServiceBase` stub class raising `NotImplementedError` if instantiated (contract only). No concrete implementation.
- Type-only imports for `NormalizedDocument` (Phase 4) and `ProcessingContext` (`apps/ai-worker/app/pipeline/context.py`) via `if TYPE_CHECKING:` or string annotations (to avoid circular imports).

**Deps:** Phase 1, Phase 4 (types).  
**Accept:** Interface is importable, method signature matches spec, return type is `ClassificationResult`, no business logic. mypy-style type checks pass on annotations.

### Phase 4 — Normalization contract [x]

**Scope.** Introduce `NormalizedDocument` and normalization contract in flat layout. `apps/ai-worker/app/classification/normalize.py` (placeholder exists) defines types/protocols only; no implementation.

**Deliverables:**
- `apps/ai-worker/app/classification/normalize.py`:
  - `@dataclass(frozen=True)` `NormalizedDocument`:
    - `raw_text: str`
    - `headings: list[str]`
    - `tables: list[str]` (table rows/markdown table blocks as strings; contract only)
    - `paragraphs: list[str]`
    - `metadata: dict[str, Any] = field(default_factory=dict)`
  - `class TextNormalizer(Protocol)`:
    - `def normalize(self, markdown: str) -> NormalizedDocument: ...` (sync or async contract documented; prefer sync for pure normalization; document choice)
- `apps/ai-worker/app/classification/__init__.py` may export `NormalizedDocument`.

**Deps:** None (uses stdlib only).  
**Accept:** Types exist, importable, frozen dataclass with fields per design-spec §§15–16. No parsing logic.

### Phase 5 — Signals contract [x]

**Scope.** Define detector contracts only (no regex/weights/logic). Use flat layout per STRUCTURE.md §4 (files `signals/base.py`, `signals/laboratory.py`, `signals/appointment.py`, `signals/prescription.py`, `signals/generic.py` exist as placeholders).

**Deliverables:**
- `apps/ai-worker/app/classification/signals/base.py`:
  - `class SignalDetector(Protocol)`:
    - `def detect(self, document: "NormalizedDocument") -> list["ClassificationSignal"]: ...`
- `apps/ai-worker/app/classification/signals/laboratory.py`:
  - `class LaboratorySignalDetector(SignalDetector)` (stub class) — implements protocol signature; body empty or `raise NotImplementedError` (no implementation). Document intended signal categories in class docstring (laboratory_section, reference_range, measurement_unit, result_value, laboratory_parameter, abnormal_flag, specimen, laboratory_number, biomarker, hematology_marker) — contract only.
- `apps/ai-worker/app/classification/signals/appointment.py`:
  - `class AppointmentSignalDetector(SignalDetector)` stub; docstring lists intended categories (appointment/reception/visit, doctor/specialist/specialty, cabinet/room, appointment time, talon/ticket, запись/приём/врач/кабинет/талон).
- `apps/ai-worker/app/classification/signals/prescription.py`:
  - `class PrescriptionSignalDetector(SignalDetector)` stub; docstring lists intended categories (назначение/препарат/лекарственный, дозировка/dose/frequency/курс/принимать, формы/единицы).
- `apps/ai-worker/app/classification/signals/generic.py`:
  - `class GenericSignalDetector(SignalDetector)` stub (fallback detector contract).

**Deps:** Phase 1, Phase 4.  
**Accept:** All detector classes conform to `SignalDetector` protocol (type-checkable), importable, no detection logic implemented.

### Phase 6 — Scoring/decision + SchemaResolver contract + Versioning [x]

**Scope.** Define scoring/decision contract constants and `ScoringEngine` protocol; define schema resolution contract (`SchemaResolver` protocol + `SCHEMA_REGISTRY` mapping shape and `classifier_version`). Files: `apps/ai-worker/app/classification/scoring.py` (placeholder), `apps/ai-worker/app/classification/resolver.py` (placeholder), and `apps/ai-worker/app/classification/__init__.py`/constants.

**Deliverables:**
- `apps/ai-worker/app/classification/scoring.py`:
  - `CLASSIFIER_VERSION = "2.0.0"` (constant).
  - Contract constants documenting scoring weights (informational only, not used in M1): `WEIGHT_STRONG = 5.0`, `WEIGHT_MEDIUM = 3.0`, `WEIGHT_WEAK = 1.0`, `WEIGHT_CONTRADICTING = -4.0` (comments: “contract constants — not computed in M1”).
  - Confidence thresholds documented (comments): `THRESH_HIGH_MIN = 0.90`, `THRESH_MED_LOW = 0.70` (0.90–1.00 HIGH, 0.70–0.89 MEDIUM, < 0.70 LOW) — calibration deferred to evaluation (M3).
  - Margin rule documented (comment): ambiguous if `top_score - second_score` < margin threshold (value not enforced in M1).
  - `class ScoringEngine(Protocol)`:
    - `def score(self, signals: list["ClassificationSignal"]) -> tuple["DocumentType", float, list[str], ClassificationDecision, ClassificationConfidenceLevel]: ...` (protocol only; no implementation)
- `apps/ai-worker/app/classification/resolver.py`:
  - `SCHEMA_REGISTRY: dict[tuple[str, str | None], str]` = contract mapping (documented keys/values). Locked keys: `("laboratory","hematology") -> "laboratory.v1"`, `("laboratory", None) -> "laboratory.v1"`, `("appointment", None) -> "appointment.v1"`, `("prescription", None) -> "prescription.v1"`, `("other", None) -> "generic.v1"`, plus placeholders documented for other types (`discharge/diagnosis/imaging/consultation`) mapping to `"generic.v1"` until specialized schemas exist (contract only).
  - `class SchemaResolver(Protocol)`:
    - `def resolve(self, document_type: "DocumentType", document_subtype: str | None = None) -> str: ...`
- `apps/ai-worker/app/classification/__init__.py`: export `CLASSIFIER_VERSION`, `DocumentType`, `ClassificationResult`, `ClassificationDecision`, `ClassificationConfidenceLevel`, `NormalizedDocument` (public API surface).

**Deps:** Phase 1–5.  
**Accept:** Constants and protocols exist, mapping shape locked, version `"2.0.0"`, all importable. No runtime resolution/scoring logic.

---

## 4. Locked design reference (condensed)

**Boundary & invariants:** Classification answers “what kind?” (not extraction). Deterministic rule-based contract (method `"rule_score"`). Flat layout (no `domain/` subpackage) — this is an **explicit deviation** from the design spec §33; see §7. `NormalizedDocument` is a new contract type (separate from canonical extraction models). No classification→extraction import.

**ClassificationResult contract (locked shape):**
```text
document_type (DocumentType)
document_subtype (str|null)
confidence (float 0–1)
confidence_level (HIGH|MEDIUM|LOW)
decision (ACCEPT|AMBIGUOUS|FALLBACK)
method ("rule_score"|"llm_fallback"|"manual") default "rule_score"
reasons (list[str])
signals (list[{name,weight,matched,matches,score}])
classifier_version (str "2.0.0")
warnings (list[str])
```

**Schema resolution contract (locked):**
```text
("laboratory","hematology")→"laboratory.v1"
("laboratory",None)→"laboratory.v1"
("appointment",None)→"appointment.v1"
("prescription",None)→"prescription.v1"
("other",None)→"generic.v1"
(discharge/diagnosis/imaging/consultation,*)→"generic.v1" (documented)
```
`SchemaResolver` is protocol-only in M1.

**Persistence shape (locked for future integration):** classification metadata block
```json
{
  "classification": {
    "type": "laboratory",
    "subtype": "hematology",
    "confidence": 0.96,
    "confidence_level": "high",
    "decision": "accept",
    "method": "rule_score",
    "classifier_version": "2.0.0",
    "reasons": ["laboratory_section_detected","reference_ranges_detected"],
    "warnings": []
  }
}
```
(no new DB table). S3 artifact path shape: `classification/result.json` under the processing attempt/version path (documented; implementation deferred).

**Normalization contract (locked):** `NormalizedDocument(raw_text, headings, tables, paragraphs, metadata)` — frozen dataclass. Marker.md is input text.

---

## 5. Tests

**Approach (M1):** contract-level tests only (importability, type shapes, enum values, schema dict keys, protocol conformance on stubs). No detection logic tests. Existing `tests/unit/classification/test_classifier.py` (7 keyword tests) remain unchanged in M1 (they test current keyword classifier).

**Test commands:**
- ai-worker unit tests: `cd apps/ai-worker && uv run pytest` (current baseline). In M1 we only add contract tests (no behavior changes). Expect existing 7 tests to still pass.
- Lint (repo): `make lint` → `uvx ruff check apps packages tests` (from repo root). 
- Type-check: **none configured** in repo (no mypy/pyright). No type-check command required by repo; we rely on type hints + Pydantic validation.
- All Python tests: `make test` (optional, broader scope). 
- Focused classification contract tests (if added): `cd apps/ai-worker && uv run pytest tests/unit/classification -v`.

**M1 acceptance verification (minimum):**
- All new modules import without errors: `python -c "from app.classification import DocumentType, ClassificationResult, CLASSIFIER_VERSION, NormalizedDocument; print('ok')"` (from `apps/ai-worker`).
- Schema dicts importable and contain required keys (`document_type`, `confidence`, `decision`, `classifier_version`).
- Protocols are type-checkable (structural subtyping on stubs). No runtime side effects.

---

## 6. Implementation order

1. **Phase 1 — Domain contract** [x]  
   Implement enums/models/exceptions in flat layout. Verify imports.
2. **Phase 2 — Schemas (JSON Schema exports)** [x]  
   Add `schemas.py` with `CLASSIFICATION_RESULT_SCHEMA`, `CLASSIFICATION_SIGNAL_SCHEMA`. Verify import.
3. **Phase 3 — Service interface** [x]  
   Add `service.py` with `ClassificationService` protocol (TYPE_CHECKING for cross-imports). Verify signature.
4. **Phase 4 — Normalization contract** [x]  
   Add `normalize.py` with `NormalizedDocument` + `TextNormalizer` protocol. Verify import.
5. **Phase 5 — Signals contract** [x]  
   Add/update `signals/base.py`, `signals/laboratory.py`, `signals/appointment.py`, `signals/prescription.py`, `signals/generic.py` as stubs implementing protocol. Verify protocol conformance.
6. **Phase 6 — Scoring/decision + SchemaResolver contract + Versioning** [x]  
   Add constants/protocols in `scoring.py`, `resolver.py`; update `__init__.py` exports. Verify version `"2.0.0"`, registry shape locked.

**Each phase:** implement → update this status (all three places: heading, §1 table, §6 list) → pause for confirmation before next phase.

---

## 7. Notes & conventions

### Gotchas (verified)
- **Flat vs domain layout deviation (explicit):** STRUCTURE.md §4 shows flat `classification/{models,schemas,service,validators,exceptions}.py`; design-spec §33 proposes `classification/domain/{enums,models}.py`. We choose **flat layout** to match existing scaffolding and STRUCTURE.md. This is a `Deviation:` and will be recorded in Phase 1 Implementation Status if/when phases are marked done later. No code moves of non-existent domain code required.
- **Existing keyword classifier remains intact in M1.** Contract-only changes; no behavior change to pipeline. Existing tests (`test_classifier.py`) must continue to pass.
- `NormalizedDocument` is new (not present in codebase). Keep separate from `packages/canonical` models to avoid coupling classification to extraction schemas.
- Use string annotations + `TYPE_CHECKING` for `ProcessingContext`/`NormalizedDocument` cross-imports (avoid cycles between `classification` and `pipeline`).
- Pydantic v2: use `BaseModel` with `extra="forbid"` for `ClassificationResult` and `ClassificationSignal`.

### Open decisions (defaults chosen)
- **Normalization method signature:** `TextNormalizer.normalize(markdown: str) -> NormalizedDocument` (sync). Default chosen (normalization is pure string/structure transform). Can revisit to async if OCR/IO added later.
- **Subtype optionality:** `document_subtype: str | None = None` (per the design spec). Default `None` allowed.
- **Generic mapping:** `discharge/diagnosis/imaging/consultation` → `"generic.v1"` until specialized canonical schemas exist. Default chosen to keep pipeline stable.
- **Confidence range/documentation:** enforce 0.0–1.0 in comments only (no validator in M1). Default documented.

### Risks (mitigations in place)
- **Spec drift between STRUCTURE.md and the design spec:** Mitigated by explicit deviation note above and choosing one layout (flat). 
- **Premature implementation:** M1 is contract-only (stubs, protocols, types). No detection logic prevents behavior changes. 
- **Missing type-check in CI:** Repo has no mypy/pyright. Mitigation: rely on Pydantic validation + import tests + ruff. If type-checking becomes required later, evaluate tooling separately.

### Versioning policy (locked)
- `classifier_version = "2.0.0"` (M1 contract baseline). 
- Patch (x.y.Z): doc/comment fixes only, no semantic contract change. 
- Minor (x.Y.z): additive (new optional fields, new enum values) — backward compatible. 
- Major (X.y.z): breaking (required field changes, enum removals, decision rules change) — incompatible. Update version on any contract change.

### Conventions
- Follow repo conventions: `make lint` clean; keep changes minimal and localized to `apps/ai-worker/app/classification/` and `apps/ai-worker/app/canonical/registry/` (contracts only). No edits to pipeline/extraction in M1.
- Status mirrored in three places: §1 table, §3/§6 headings, §6 ordered list. Update all three when flipping phases.
- Deviations labeled explicitly in Implementation Status when phases complete (per schema grammar).
