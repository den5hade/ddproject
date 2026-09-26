# PII Gate — Implementation Plan (M4: Specification)

**Scope.** This plan defines **M4 – PII Gate specification** (ORDER.md **M4**): the
contract only — domain enums/models, detector/masking/redaction/policy/gate interfaces, the
post-extraction canonical-output guard, the locked persistence shape, and versioning. No
detection logic, no LLM calls, no pipeline wiring, no cross-package changes in this plan. The
contour is built on existing infra only — no parallel architecture. M5 implements; M6 evaluates.

**Depth sources:** [IMPL_ARCH.md](./IMPL_ARCH.md) (PII gate design spec, §§1–38), [ORDER.md](../ORDER.md)
(§2 PII Gate, §8 interface, §12 milestones), [STRUCTURE.md](../STRUCTURE.md) (§2 pipeline,
§5 `pii/` layering), [SUMMARY.md](../SUMMARY.md) (§11 PII gate, §12 medical identity split,
Phase 4), [Classification 2.0 CONTRACT_IMPL_PLAN.md](../CLASSIFICATION%202.0/CONTRACT_IMPL_PLAN.md)
(the M1 contract precedent this contour mirrors), [IMPL_PLAN_SCHEMA.md](../../operational/IMPL_PLAN_SCHEMA.md).
Full taxonomy/policy tables are condensed in §4; the plan holds decisions, not the design prose.

**Revision 1** — initial M4-only plan (2026-09-26). M3 (Classification 2.0 evaluation) closed
2026-09-23 at `classifier_version = "2.1.0"` (`33af39f`), so M4 is next per ORDER §12.

Status legend: `[ ]` pending · `[x]` done.

---

## 0. Overview

**Current (as-is):** PII mitigation is one prompt line.

```text
app/prompts/canonical.yaml:100
  - Never include patient identity (name, date of birth, SNILS, insurance policy number).
```

`apps/ai-worker/app/pii/` exists as five docstring-only placeholders (`__init__.py`,
`detectors.py`, `gate.py`, `models.py`, `policy.py`) plus one real symbol,
`PIIError` (`app/pii/exceptions.py:5`). Nothing in `app/pii/` is imported by the pipeline
(`app/pipeline/pipeline.py:60-77` constructs no gate), no artifact kind, no event field, no DB
column exists for PII. Consequently **the observed leak is live today** — real runs in
`.dev/flow_upload_test/`:

```text
2b8fdd0d.../marker.md  → ФИО: Шадеркин Денис Сергеевич · Полис №: 8152510822001720
                          СНИЛС: 123-067-082 21 · Дата рождения: 27.07.1984
2b8fdd0d.../canonical.json → fields.note: "...для пациента Шадеркина Дениса Сергеевича.
                                Номер талона: 2026030709303211960141."
fbbcb675.../canonical.json → fields.note: "...для пациента Шадеркина Дениса Сергеевича (М, 39 лет)..."
```

The same content persists into `document_extractions.data` because
`DocumentAnalysisCompleted.data` is dumped verbatim (`apps/account-api/app/services/documents.py:536`).
The prompt rule is a request to the model, not a control — SUMMARY.md §11 is the analysis of
exactly this failure.

**Target (M4):** two locked contracts, one for each boundary where PII can escape.

```text
marker.md
  → MarkdownNormalizer → NormalizedDocument            (already exists, reused as-is)
  → CLASSIFICATION (parallel, unchanged)               ClassificationService.classify
  → PII GATE (contract)                                PIIGate.inspect(document, context) -> PIIScanResult
       │                                                 detect → aggregate → policy → decide
       ├── ALLOW          → continue
       ├── ALLOW_WITH_WARNING → continue, record
       ├── REVIEW         → halt, needs_review (no human UI yet)
       └── BLOCK          → halt, processing failure
  → SchemaResolver → LLM extraction → build_canonical   (unchanged)
  → CANONICAL GUARD (contract)                          CanonicalPIIInspector.inspect(payload)
       └── canonical.json / structured.md / document_extractions.data   (guarded, no PII written)
  → pii_result.json → S3   ·  frontmatter `pii:`  ·  event data["pii"]
```

M4 writes **no** pipeline code. It fixes the types, the two decision boundaries, the
serialization contract, and the versions that M5 will implement and M6 will calibrate.

**Key mechanisms.** Detection and policy are separate contracts, so detectors change without
policy edits and vice versa (STRUCTURE §5, IMPL_ARCH §2/§17). Raw values exist only in-process and
are structurally incapable of leaking (they are excluded from serialization, and the
serializable summary type has no field for them). Risk and action are **policy configuration**,
not detection output (IMPL_ARCH §12), so jurisdiction and org-specific rules are data, not code.

**Invariants (locked):**

- **PII presence alone never blocks.** A medical document is *expected* to carry patient
  identity; `PII detected → reject` is explicitly rejected (ORDER §2, IMPL_ARCH §2). `BLOCK` is
  reserved for `SECRET` and fail-closed conditions; `REVIEW` for unexpected high-risk
  combinations. Normal patient identity in an internal pipeline is `ALLOW`.
- **No raw PII value crosses a boundary.** `PIIFinding.value` is `Field(exclude=True)`;
  `PIIFindingSummary` / `PIIAuditRecord` / `PIIScanResult` have no value field at all. Logs,
  audit, events, artifacts and frontmatter carry `masked_value` only (IMPL_ARCH §6, §19, §22, §26).
- **`value_fingerprint` is a salted HMAC-SHA256, never a plain hash.** Low-entropy identifiers
  (СНИЛС = 9 digits + checksum, полис ОМС = 16 digits, дата рождения) are brute-forceable in
  seconds, so a plain `sha256` is the value wearing a disguise. The secret comes from settings
  and the fingerprint is never logged.
- **The gate is a document-level capability, not a schema-level one.** `app/pii/` must not
  import `app/classification/` (mirrors Classification's no-extraction-import rule, ORDER §8)
  and must not import `packages.canonical` models. If the pipeline wants to pass document type
  into policy, it passes a plain `str`.
- **Originals are immutable.** `marker.md` and the upload are never rewritten. Redaction
  produces a *new* artifact string; replacements are applied right-to-left so earlier offsets
  stay valid (deterministic and testable).
- **The current LLM provider is trusted, explicitly and by name.**
  `ai_base_url` is `https://foundation-models.api.cloud.ru/v1` (`app/config/settings.py:27`) — an
  external vendor, but the *only* provider we have. M4 locks `PIIDestination.INTERNAL_LLM` as
  the default, so no pre-extraction redaction happens today; `REDACT` is fully specified and
  unreachable until an external/offshore provider is configured. This is a deliberate,
  recorded deferral, not an oversight (IMPL_ARCH §16).
- **Fail closed on gate failure.** If the gate itself cannot produce a decision,
  `PIIDecisionError` is raised and the pipeline must not proceed to extraction. M4 locks the
  exception; M5 wires the halt.
- **M4 touches `apps/ai-worker/app/pii/**` only.** The cross-package contract (storage kind,
  frontmatter model, event field) is *documented* in §4 and coded in M5 — same discipline as
  M1, which documented classification persistence without touching `packages/`.
- **PII Gate is one security control, not a compliance layer.** It does not make the platform
  GDPR/HIPAA/152-ФЗ compliant; that also depends on storage, access, retention, consent,
  encryption, residency, processor agreements, deletion, backups and incident response
  (IMPL_ARCH §37). Do not cite this plan as evidence of compliance.
- **Raw PII is internal-only.** The gate's output is a security artifact; it must not become
  user-facing through the normal document API (IMPL_ARCH §26).

---

## 1. Execution summary

| Phase | Scope | Status |
|---|---|---|
| 1 | Domain contract (enums, `PIIFinding`/`PIIFindingSummary`/`PIIScanResult`/audit, exceptions) | [x] |
| 2 | Schemas (JSON Schema exports for scan result + finding summary) | [x] |
| 3 | Detector contract (`PIIDetector` protocol, per-kind stubs, aggregator/dedup) | [x] |
| 4 | Masking & redaction contract (mask table, fingerprint, `PIIRedactor`) | [x] |
| 5 | Policy + gate contract (`DEFAULT_POLICY`, `PolicyEngine`, `PIIGate.inspect`) | [x] |
| 6 | Canonical-output guard contract (post-extraction leak boundary) | [x] |
| 7 | Persistence, provenance, versioning contract (+ M5 hand-off touch lists) | [x] |

M4 is complete when all seven phases are `[x]`, the full ai-worker suite is green on the
174-test baseline, and `make lint` is clean.

**M4 status: complete.** All seven phases `[x]`. `uv run pytest` → 436 passed
(174 baseline + 262 PII contract tests). `uvx ruff check app/pii tests/unit/pii
tests/support` → clean. `make lint` reports only 4 pre-existing `packages/storage`
errors, unrelated to this milestone and present before M4 began. Everything is
uncommitted, and no `packages/` or `app/pipeline/` file was modified — every
cross-package edit is still recorded in §4.9 as documented-not-made.

---

## 2. Completed phases

### Phase 1 — Domain contract [x]

**Status.** Done — the contract types exist, validate and are proven boundary-safe; see
"Phase 1 Implementation Status" below.

**Changes.** Replaced the three docstring-only placeholders with the real domain contract and
added the Phase 1 test module.

```text
apps/ai-worker/app/pii/models.py        enums + PIIFinding / PIIFindingSummary /
                                        PIIScanResult / PIIAuditRecord / PIIDecisionResult
apps/ai-worker/app/pii/exceptions.py    PIIError + 5 subclasses
apps/ai-worker/app/pii/__init__.py      public surface, 18 exports
apps/ai-worker/tests/unit/pii/          test_models.py (21 tests) + __init__.py
```

- 6 enums, declared group-by-group in the §4.1 order: `PIICategory` (23 members),
  `PIISource`, `PIIRiskLevel`, `PIIAction`, `PIIDecision`, `PIIDestination`, `PIIScanStage`.
- `PIIFinding` is `frozen=True, extra="forbid"` with `value` and `value_fingerprint` both
  `Field(exclude=True)`; `masked_value` is a plain required field.
- `PIIFindingSummary` / `PIIScanResult` / `PIIAuditRecord` have no value field **at all** — not
  excluded, absent — so the three plan §5 assertions hold on `model_fields`, not on dump
  behaviour.
- No validators anywhere, mirroring `app/classification/models.py`; `confidence` range and
  `findings_count == len(findings)` are documented, not enforced.

**Verification.** 21 tests in `tests/unit/pii/test_models.py` pass; full ai-worker suite
195 passed (was 174, +21) — no regressions. `uvx ruff check apps/ai-worker/app/pii
apps/ai-worker/tests/unit/pii` clean. `make lint` reports 4 errors, all pre-existing in
`packages/storage/` (`storage/s3.py:84` E501, `tests/test_markdown_helpers.py` I001/F401/UP012)
and left untouched per convention.

#### Phase 1 Implementation Status

- **Files created:** `apps/ai-worker/tests/unit/pii/test_models.py`,
  `apps/ai-worker/tests/unit/pii/__init__.py`.
- **Files modified:** `apps/ai-worker/app/pii/{models,exceptions,__init__}.py` (placeholders
  replaced in place; no new module names, per the "reuse the existing placeholders" convention).
- **Deviation — `PIICategory` has 23 members, not 22.** §4.1's heading said "22 values" while
  its own list contains 23 (IMPL_ARCH §3 contributes 21, plus `TICKET_NUMBER` from the real
  `2b8fdd0d` marker and `SECRET` from IMPL_ARCH §13). The §4.1 member list is normative and is
  implemented as written; the count in §4.1 has been corrected to 23. The §4.4 policy table and
  the §4.5 mask table both already cover all 23, so Phases 4 and 5 are unaffected.
- **Deviation — `tests/unit/pii/__init__.py` added**, contradicting the §7 gotcha "test subdirs
  have no `__init__.py`". Reason: `tests/unit/classification/` already owns `test_models.py`,
  `test_schemas.py` and `test_fixture_manifest.py`, and the plan's own §5 file list asks M4 for
  all three names. Without a package marker, pytest's default prepend import mode assigns
  same-named sibling files the same module name and the full suite dies with "import file
  mismatch" — observed, not theoretical. The marker is scoped to `tests/unit/pii/`, so it stays
  inside the M4 footprint; the global alternative (markers across `tests/unit/**`, or
  `importmode=importlib`) is a separate cleanup, not an M4 dependency. The §7 gotcha is annotated
  accordingly.
- **Deviation — `PIIFinding.value` is `str`, required**, not `str | None` as in IMPL_ARCH §5. A finding
  that exists without the text that justified it cannot be redacted (Phase 4) and would make
  "no raw value" a call-site discipline rather than a control. The §7 open decision on raw-value
  handling is honoured, with IMPL_ARCH's optionality tightened.
- **Empirical note — `Field(exclude=True)` does not remove the field from
  `PIIFinding.model_json_schema()`.** `exclude` is a serialization concern only, so the in-process
  type still *declares* `value`/`value_fingerprint` (and marks them required) in its generated
  schema. This is why Phase 2 must derive `PII_FINDING_SCHEMA` from `PIIFindingSummary` — the
  plan's §5 acceptance already says so; the trap is now documented in the `PIIFinding` docstring
  and pinned by `test_finding_summary_schema_is_the_wire_contract`, so nobody "helpfully"
  re-derives it from `PIIFinding` later.
- **Empirical note — `PIIFinding` is frozen but not hashable** (`metadata` is a `dict`). Pinned by
  `test_finding_is_not_hashable`; Phase 3's aggregator must dedup on the
  `(category, value_fingerprint)` tuple, not on the model.
- **Pre-existing issues left untouched per convention:** the 4 `packages/storage/` lint errors
  above, and account-api's kind allow-list gap (§7) which is M5's business, not M4's.
- **Verification recap:** `uv run pytest tests/unit/pii` → 21 passed; `uv run pytest` → 195
  passed; `uvx ruff check apps/ai-worker/app/pii apps/ai-worker/tests/unit/pii` → clean. No
  commit yet (M4 is committed as a whole or not at all — the user's call).
- **Next step:** Phase 2 (Schemas) — done, see below.

### Phase 2 — Schemas [x]

**Status.** Done — both schema constants are derived from the Phase 1 models and the "no
`value` property" proof is asserted; see "Phase 2 Implementation Status" below.

**Changes.**

```text
apps/ai-worker/app/pii/schemas.py            PII_SCAN_RESULT_SCHEMA, PII_FINDING_SCHEMA
apps/ai-worker/tests/unit/pii/test_schemas.py  13 tests
```

- `PII_SCAN_RESULT_SCHEMA = PIIScanResult.model_json_schema()`,
  `PII_FINDING_SCHEMA = PIIFindingSummary.model_json_schema()` — derived at import time, exactly
  as `app/classification/schemas.py:19-23`, so enum values and required fields cannot drift.
- Not re-exported from `app/pii/__init__.py`, mirroring `app/classification/__init__.py`, which
  also keeps schemas out of the package surface.
- No schema-generation CLI, no new dependency, nothing hand-maintained: the `description` entries
  are the Phase 1 model docstrings, so the schema carries the security rationale (why
  `PIIFinding` is not a wire type, what `categories` vs `category_counts` means) into the
  artifact rather than duplicating it.

**Verification.** 13 tests in `tests/unit/pii/test_schemas.py` pass; full ai-worker suite
208 passed (was 195, +13). `uvx ruff check apps/ai-worker/app/pii apps/ai-worker/tests/unit/pii`
clean.

#### Phase 2 Implementation Status

- **Files created:** `apps/ai-worker/app/pii/schemas.py`,
  `apps/ai-worker/tests/unit/pii/test_schemas.py`.
- **Files modified:** none (Phase 1 files untouched).
- **Deviation — the §5 assertion #2 is satisfied from `PIIFindingSummary`, not
  `PIIFinding`.** Already predicted by Phase 1; now executable. `PII_FINDING_SCHEMA` cannot
  contain a `value` property, because the type it is derived from has no such field — the
  invariant is structural rather than a filter someone could forget to apply. Pinned both ways by
  `test_finding_schema_has_no_value_property` and
  `test_schemas_never_derived_from_pii_finding` (which asserts `PIIFinding`'s schema *does*
  declare `value`, so nobody re-derives from the wrong model later and silently regresses it).
- **Strengthening — deep, recursive "no value" check.** §5 asks for "no `value` property in the
  finding schema". A `value` field could equally hide in the `PIIFindingSummary` entry nested
  under `PII_SCAN_RESULT_SCHEMA["$defs"]`, where a shallow `["properties"]` lookup would miss it.
  `test_no_value_property_anywhere_in_either_schema` walks both documents at any depth; the same
  walker is then reused on a real `model_dump(mode="json")` payload in
  `test_real_payload_conforms_to_schema`, so the end-to-end claim is "what M5 writes to
  `pii_result.json` contains no value field and no raw text", proven through the actual
  serialization path rather than through `model_fields` inspection.
- **Deviation — no `jsonschema` validator.** The obvious way to prove payload/schema conformance
  is a real validator, and `jsonschema` is *not* installed in the workspace. M4's budget says no
  new dependency (§5) and M1 set the precedent of not needing one, so conformance is asserted
  structurally: emitted keys must equal the schema's property set, required keys must be present,
  and every enum-valued payload field must be a real enum member. That covers the drift that
  actually happens (a field added, renamed or retyped in Phase 1 without re-reading the schema);
  it does not claim full JSON Schema semantics, and the module docstring does not overstate it.
  If a future phase wants machine validation of the artifact, adding `jsonschema` as a **dev**
  dependency is the right move — deliberately not done here.
- **Empirical note — schema size.** The generated documents are large (~250 lines of JSON for
  the scan result) because Pydantic embeds the Phase 1 docstrings as `description`. Verified
  harmless: nothing consumes these schemas at runtime (same as classification — grep shows only
  tests read them), and the size buys an artifact that explains itself. If a future phase feeds
  these into a real validator or an LLM tool schema, trim the docstrings then, not now.
- **Empirical note — `masked_value` survives a naive leak grep, a quoted one is clean.** The only
  key in either schema containing the substring `value` is `masked_value`, so a sloppy
  `assert "value" not in json.dumps(payload)` fails for the wrong reason. A quoted-key scan —
  `re.search(r'"value"\s*:', blob)` — returns no match, because the character before `value` in
  `"masked_value":` is `_`, not `"`. Relevant to Phase 7: the "no PII in logs/artifact" check
  (plan §5 defers it to M5) must match **quoted key names**, not substrings, or it will
  false-positive on the one field that is allowed to carry a value-derived string.
- **Verification recap:** `uv run pytest tests/unit/pii` → 34 passed (21 Phase 1 + 13 Phase 2);
  `uv run pytest` → 208 passed; `uvx ruff check apps/ai-worker/app/pii
  apps/ai-worker/tests/unit/pii` → clean. Still uncommitted.
- **Next step:** Phase 3 (Detector contract) — done, see below.

### Phase 3 — Detector contract [x]

**Status.** Done — protocol, four stubs, composite ordering, aggregator dedup rule, version
constant and the import boundary are locked and tested; see "Phase 3 Implementation Status"
below.

**Changes.**

```text
apps/ai-worker/app/pii/detectors.py            PIIDetector protocol, PIIDetectorBase,
                                               Pattern/StructuredField/Secret/Composite stubs,
                                               DETECTOR_VERSION = "1.0.0"
apps/ai-worker/app/pii/aggregation.py          PIIAggregator protocol, PIIAggregatorBase stub,
                                               the locked dedup rule
apps/ai-worker/app/pii/__init__.py             +9 exports (27 total)
apps/ai-worker/tests/support/pii_imports.py    AST import classifier for the boundary guards
apps/ai-worker/tests/unit/pii/test_detectors.py 20 tests
apps/ai-worker/tests/unit/pii/test_models.py   guards rewritten on the AST classifier (+2 tests)
```

**Verification.** 20 tests in `tests/unit/pii/test_detectors.py` pass; full ai-worker suite
230 passed (was 208, +22). `uvx ruff check apps/ai-worker/app/pii apps/ai-worker/tests/unit/pii
apps/ai-worker/tests/support` clean.

#### Phase 3 Implementation Status

- **Files created:** `apps/ai-worker/app/pii/aggregation.py`,
  `apps/ai-worker/tests/support/pii_imports.py`, `apps/ai-worker/tests/unit/pii/test_detectors.py`.
- **Files modified:** `apps/ai-worker/app/pii/detectors.py` (placeholder replaced),
  `apps/ai-worker/app/pii/__init__.py`, `apps/ai-worker/tests/unit/pii/test_models.py`.
- **Deviation — the Phase 1 import guard had to be rewritten, and it got stronger.** The Phase 1
  guard was a substring scan over source lines, which cannot tell a runtime import from a
  `if TYPE_CHECKING:` one — so the sanctioned borrow of `NormalizedDocument` (plan §3: "no
  `app.classification` import **beyond the shared `NormalizedDocument` type**, via
  `TYPE_CHECKING`") would have either failed the build or forced the borrow to be abandoned.
  Replaced with an AST classifier (`tests/support/pii_imports.py`) that buckets imports into
  runtime vs. type-only. Three guards now: no infrastructure at runtime, no classification /
  pipeline / canonical **at runtime**, and type-only borrows restricted to exactly
  `("app.classification.normalize", "NormalizedDocument")` — a set literal, so widening the
  boundary is a visible diff. `app.classification.normalize` is in the runtime-forbidden list
  too, on purpose: if the borrow ever becomes a runtime import, PII would no longer be usable
  without classification being importable, and the guard must say so.
- **Deviation — `tests/support/pii_imports.py` is a new shared module** (not in the plan's §5
  file list). The guard logic is needed by two test modules, and a boundary control that exists
  in two copies is one that can drift. `tests/support/` is already the sanctioned home for
  cross-test delegates (`tests/support/classification_fixtures.py`). Stdlib `ast` only — M4 still
  adds no dependency.
- **Deviation — the guard is tested for its own discrimination.** Every import guard is satisfied
  by *empty* result sets, which is also exactly what a broken AST walk returns. Two tests build a
  synthetic module containing a runtime classification import, an infrastructure import and two
  type-only imports, and assert the classifier puts each in the right bucket. Without this, a
  future refactor that broke the walk would turn four architectural guards into four no-ops.
- **Deviation — `PIIDetectorBase` is instantiable; the `NotImplementedError` lives in `detect`.**
  This deliberately differs from `ClassificationServiceBase`, which raises in `__init__`. M5 must
  be able to construct the whole chain — including members whose `detect` is not written yet — to
  assert every declared detector is actually wired, and to prove an unimplemented detector fails
  loudly. The same shape carries into `PIIAggregatorBase`, `RedactorBase` (Phase 4) and
  `PIIGateBase` (Phase 5) so M4 is internally consistent.
- **Deviation — stubs raise rather than return `[]`.** A stub returning `[]` is a fail-open
  default: wired but unimplemented, it reports "no PII found" and the gate `ALLOW`s. Documented
  in the module docstring precisely so a later reader does not "fix" it.
- **Behavior added — `CompositePIIDetector.__init__` rejects an empty chain** with
  `InvalidPIIInputError`. The only configuration that disables the gate while still looking
  healthy in the pipeline; it belongs in the constructor, not at scan time. Storing the chain as
  an immutable tuple makes "deterministic detector order" a property of the configuration.
- **Pulled forward — `DETECTOR_VERSION = "1.0.0"`** from Phase 7. Phase 3 writes
  `detectors.py`, `PIIFinding.detector_version` is required, and the M5 acceptance smoke check
  imports the constant; leaving it for Phase 7 would mean a detector that cannot stamp its own
  findings. `PII_POLICY_VERSION` stays in Phase 5, where `policy.py` is written.
- **Contract requirement discovered for Phase 4 — `hash_pii_value` must normalize before
  hashing.** Aggregation dedups on `(category, value_fingerprint)`, so the fingerprint must be
  computed over NFC-normalized, case-folded, whitespace-collapsed text. Otherwise `Иванов` and
  `ИВАНОВ  ` — case and spacing variants of one name, the normal case in Marker output — get
  different fingerprints and the dedup this phase specifies silently never happens. This is a
  correctness dependency between two phases, so it is now written into the Phase 4 block below
  and into `aggregation.py`.
- **Safety rule locked — an empty `value_fingerprint` bypasses dedup.** Keying on
  `(category, "")` would merge two genuinely different values (a patient's name into a passport
  finding) and delete one from the result. A duplicate finding is recoverable; a merged one is
  not. Pinned in the module docstring and asserted by a documentation test.
- **Deferred by design — no working aggregator.** `PIIAggregatorBase` raises; the dedup rule is
  prose plus a documentation test. Rationale: M4 is a contract milestone (§5 "no detection-logic
  tests"), and the rule's only inputs are the two Phase 1 fields, whose shapes are already
  locked. Implementing it now would be M5 code with no real findings to calibrate it against.
- **Deferred by design — no NER/LLM detector stubs**, per §7. This is also *why* the per-detector
  category assignment stays in docstrings: with NER/LLM deferred, `AGE`/`GENDER`/`NATIONALITY`
  and free-text `ADDRESS` have no owner among the four stubs, so a machine-checked
  "every category is claimed exactly once" mapping would fail today by construction. The
  docstrings carry the intent (and a test asserts each names real `PIICategory` members); M5 turns
  it into a `ClassVar` mapping when the taxonomy is fully assigned.
- **Verification recap:** `uv run pytest tests/unit/pii` → 56 passed (23 + 13 + 20);
  `uv run pytest` → 230 passed; `uvx ruff check apps/ai-worker/app/pii
  apps/ai-worker/tests/unit/pii apps/ai-worker/tests/support` → clean. Still uncommitted.
- **Next step:** Phase 4 (Masking & redaction) — done, see below.

---

### Phase 4 — Masking & redaction contract [x]

`app/pii/masking.py` — `mask_pii_value(category, value) -> str` (per-category table, §4) and
`hash_pii_value(value, *, secret) -> str` (salted HMAC-SHA256, secret supplied by the caller —
never a module constant and never a plain digest). `app/pii/redaction.py` — `PIIRedactor`
Protocol (`redact(markdown, findings) -> str`), `RedactorBase` stub, `PlaceholderRedactor` stub,
placeholder token = `[CATEGORY_UPPER]`, and the right-to-left offset rule.
Tests: `tests/unit/pii/test_masking_redaction.py`.
**Accept:** every `PIICategory` has a mask rule in the table; fingerprint is deterministic for
the same `(value, secret)` and differs for a different secret; redactor stub raises
`NotImplementedError`; redaction is documented non-mutating.
**Deps:** Phases 1, 3.

**Requirement carried in from Phase 3.** `hash_pii_value` must **normalize before hashing** (NFC,
case-fold, collapse whitespace). Phase 3 locked aggregation dedup on
`(category, value_fingerprint)`, so an un-normalized fingerprint makes `Иванов` and `ИВАНОВ  ` —
one name, two OCR variants — look like distinct entities and the dedup silently never fires.
Correctness of `aggregation.py` depends on this; it is a contract requirement, not a nicety.
Related: an empty fingerprint must never be produced as a "normalization" side effect, or two
distinct values collide on `(category, "")`.

**Delivered**

**Changes.**

```text
apps/ai-worker/app/pii/masking.py              MASK_RULES (all 23 categories), FIXED_MASKS,
                                               FINGERPRINT_PREFIX, mask_pii_value,
                                               hash_pii_value (HMAC-SHA256, normalizing)
apps/ai-worker/app/pii/redaction.py            PIIRedactor protocol, RedactorBase stub,
                                               PlaceholderRedactor stub, placeholder_for
apps/ai-worker/app/pii/__init__.py             +6 exports (36 total)
apps/ai-worker/tests/unit/pii/test_masking_redaction.py  37 tests
```

- `app/pii/masking.py` — `MASK_RULES` (all 23 categories), `FIXED_MASKS`, `mask_pii_value`,
  `hash_pii_value`; `app/pii/redaction.py` — `PIIRedactor`, `RedactorBase`, `PlaceholderRedactor`,
  `placeholder_for`. The six new public names are re-exported from `app/pii`.
- **Mask table closed — four categories were unspecified by §4.5.** The plan named 18 of 23;
  `AGE`/`GENDER` appeared only in §7, and `NATIONALITY`, `DOCTOR_LICENSE` and
  `MEDICAL_RECORD_NUMBER` nowhere. Since the acceptance criterion is "every category has a rule",
  each gap is resolved explicitly rather than left to a reader: `AGE`, `GENDER` and `NATIONALITY` →
  `fixed` `**` (single low-entropy token, no debugging value in a first character);
  `DOCTOR_LICENSE` → `keep2`; `MEDICAL_RECORD_NUMBER` → `keep2`. The last two are the substantive
  calls — both are opaque identifiers, so they join the `TICKET_NUMBER`/`*_ID` family, and
  deliberately do **not** follow `ORGANIZATION_ID` into `none`, because the distinction the
  medical/practitioner split draws is that an organization's registration identifies no patient
  while a license and a medical record number both belong to an identified person.
- **Phone rule fixed — the visible set is the leading `+` + country digit and the last four
  digits, derived from digit positions rather than character positions.** For `+79991234567` this
  reproduces §4.5's `+7******4567` exactly. Deriving it from digits means separator and spacing
  variants (`+7 (999) 123-45-67`) reveal the *same* digits, so one number cannot redact differently
  depending on OCR spacing; a mask derived from character offsets would shift the visible tail.
  Separators inside the tail are starred, so the output is never mistaken for a valid number.
- **Email rule corrected — only the first domain label is masked, the rest stays verbatim.**
  §4.5's own illustration `i****@d****.ru` shows the TLD intact, and the first label is where the
  identity lives (`ivanov.ru`, `ivanov` in `ivanov.mail.example.com`); everything after it is
  routing infrastructure. Masking every label would over-mask `.ru` into `.r*`, and the earlier
  "mask all labels" reading was rejected for that reason.
- **Fingerprinting normalizes, masking does not.** `_normalize_for_fingerprint` applies
  NFC + case-fold + strip + whitespace-collapse before hashing, satisfying the Phase 3
  requirement. Masking deliberately skips normalization, because a mask exists so a human can
  recognize an entity in a log line and must therefore reflect the characters the document
  actually contains. The two must not share a normalizer, and the module docstring says so
  explicitly to stop a later reader from unifying them.
- **Empty secret rejected with `InvalidPIIInputError`; `secret` is keyword-only and required.**
  HMAC with an empty key is an unkeyed digest, which is the exact disguise this function exists to
  avoid, so it fails loudly rather than producing a fingerprint that looks keyed and is not.
- **Empty/whitespace values still fingerprint** to the HMAC of the empty string. This is what
  keeps Phase 3's "an empty fingerprint bypasses dedup" rule reserved for a detector that genuinely
  failed to fingerprint, rather than being triggered as a normalization side effect.
- **No `hash_pii_value` logging or persistence**, per §7: the fingerprint is in-process only, and
  `document_id` + `category` + offset remains the sanctioned join key.
- **Redaction is specified prose, not code.** `PIIRedactor.redact`'s locked algorithm: resolve
  spans (offsets when present, otherwise locate `value` — a redactor that understood only offsets
  would fail open on exactly the findings that arrive without them), merge overlapping spans before
  replacing, replace right-to-left because each edit invalidates later offsets, mutate nothing
  (`markdown` is an immutable `str`, `findings` is the caller's list, the result is a new string),
  and raise `PIIRedactionError` rather than skip an unresolvable finding. A silently skipped
  redaction is a leak the artifact would happily attest to. Overlaps are merged rather than
  ordered, because applying overlapping spans corrupts text while skipping the second leaves part
  of it exposed. `RedactorBase.redact` raises from the method rather than `__init__`, consistent
  with `PIIDetectorBase`, so the M5 gate can build its whole chain and prove an unimplemented
  redactor fails loudly instead of quietly returning the input unredacted.
- **Placeholder built from the enum member name, not its value** (`[PERSON_NAME]`), so it stays
  stable under a value rename; exposed as `placeholder_for` so no caller hand-builds the format.
  `RedactorBase` and `PlaceholderRedactor` remain stubs per §5.
- **Test design: the leak test is a property test, and its exemptions are pinned.** A generic walk
  asserts no run of `max_reveal + 1` identifying characters survives any mask, walked per token over
  alphanumeric runs only (punctuation is format — the dots in `**.**.****` are supposed to show).
  `fixed`, `email` and `none` are exempt from the walk because a match there is coincidental format
  text (the `д.` of an address mask collides with the `Д` of `Денис`) or a deliberate reveal (the
  TLD); each exemption names the exact-output test that pins it, and a test fails if an exemption
  loses its pin, so the exemption set cannot quietly become a hole. Also asserted: masks are
  constant per value under `fixed`, secret-dependence and non-plain-digest of the fingerprint, the
  `+7 (999) 123-45-67` variant revealing the same digits as the compact form, and the new modules
  importing nothing outside `app/pii` and stdlib.
- **Verification recap:** `uv run pytest tests/unit/pii` → 93 passed (23 + 13 + 20 + 37);
  `uv run pytest` → 267 passed; `uvx ruff check app/pii tests/unit/pii tests/support` → clean.
  Root `make lint` still reports only the 4 pre-existing `packages/storage` errors. Still
  uncommitted.
- **Next step:** Phase 5 (Policy + gate contract) — done, see below.

---

### Phase 5 — Policy + gate contract [x]

`app/pii/policy.py` — `PIIPolicyContext` (destination, stage, optional `document_type: str |
None`, `organization_id`, `redaction_available`), `PIIRule`, `PIIPolicy`, `CATEGORY_RISK`,
`DEFAULT_POLICY` (the locked table, §4), `PolicyEngine` Protocol
(`evaluate(findings, context) -> PIIDecisionResult`), and `PII_POLICY_VERSION = "1.0.0"`.
`app/pii/gate.py` (placeholder exists) — `PIIGate` Protocol with the exact ORDER §8 signature
`async def inspect(document, context) -> PIIScanResult`, `PIIGateBase` stub, and the documented
decision→outcome mapping (`REVIEW` → halt + `needs_review`; `BLOCK` → halt + processing
failure). Tests: `tests/unit/pii/test_policy_gate.py`.
**Accept:** DEFAULT_POLICY table is importable and asserted value-for-value; decision
precedence `BLOCK > REVIEW > ALLOW_WITH_WARNING > ALLOW` is documented; the protocol signature
matches ORDER §8 character-for-character; a no-`app.classification`-import guard test passes.
**Deps:** Phases 1, 3, 4.

#### Phase 5 Implementation Status

**Changes.**

```text
apps/ai-worker/app/pii/policy.py              PIIRule, PIIPolicy, PIIPolicyContext,
                                               CATEGORY_RISK, PII_CATEGORY_GROUPS,
                                               REDACT_ON_EXTERNAL, DEFAULT_POLICY,
                                               PII_POLICY_VERSION, PolicyEngine,
                                               PolicyEngineBase
apps/ai-worker/app/pii/gate.py                PIIGate protocol (ORDER §8), PIIGateBase,
                                               DECISION_OUTCOMES
apps/ai-worker/app/pii/__init__.py            +13 exports (49 total)
apps/ai-worker/tests/support/pii_imports.py   allowlist += type-only ProcessingContext
apps/ai-worker/tests/unit/pii/test_policy_gate.py  71 tests
```

- **Table transcribed value-for-value and asserted against literals.** `CATEGORY_RISK` covers
  all 23 categories at 1 critical / 10 high / 6 medium / 6 low, and the test asserts each
  category's level against a literal rather than against a copy of the dict — a dict compared
  to itself would pass forever and prove nothing. `DEFAULT_POLICY` blocks only `SECRET`; all
  22 others allow, per §4.4 and IMPL_ARCH §13 (a medical record is *expected* to carry a patient's
  name, so treating that as a violation would halt every document the platform exists to
  process).
- **`PII_CATEGORY_GROUPS` added as data.** The `EXTERNAL_LLM` override needs *group*
  membership, not risk level: "everything a patient is identified by" spans four groups and
  three risk levels, so expressing the override through risk would have swept in the
  `practitioner` group at `medium`. `REDACT_ON_EXTERNAL` is the derived 18; the test asserts
  the groups partition the taxonomy (disjoint, 23 total).
- **`PIIPolicy` enforces full coverage.** A policy missing a category has no action for it, and
  both plausible fallbacks — skip the finding, default it to `ALLOW` — leak. A
  `model_validator` rejects a partial table with `PIIPolicyError` at construction, turning
  "someone forgot a category" from a production incident into a startup error.
- **`PII_POLICY_VERSION` reads from `DEFAULT_POLICY.version`** rather than repeating the
  literal, because two constants that must agree will eventually disagree.
- **`PIIRule` does not carry its category.** The category is the key in `PIIPolicy.rules`;
  repeating it inside the value would give the table two sources of truth for one fact.
- **Guard change — the type-only allowlist now permits `app.pipeline.context.ProcessingContext`.**
  ORDER §8 fixes `PIIGate.inspect(document: NormalizedDocument, context: ProcessingContext)`,
  and Phase 3's guard forbade *all* `app.pipeline` borrows, so the locked signature was
  unwritable as specified. Resolved the way `app/classification/service.py:39-40` already
  resolves the identical problem: a `TYPE_CHECKING`-only import. The runtime guard is
  unchanged and still forbids `app.pipeline` at runtime, and
  `test_pii_package_imports_with_no_pipeline_and_no_classification` proves the end state in a
  subprocess — `import app.pii` succeeds with both packages blocked at the import system, and
  neither appears in `sys.modules`. A second test pins the allowlist to exactly those two
  symbols so it cannot be widened wholesale later.
- **`get_type_hints` cannot resolve the gate's annotations, and that is the proof.** Both types
  are `TYPE_CHECKING`-only, so they are absent from the module namespace at runtime. The tests
  assert the annotations as the strings they are, and separately assert that
  `get_type_hints(PIIGate.inspect)` raises `NameError` — the same fact, read as a positive
  rather than worked around.
- **Stubs raise from the method, not `__init__`.** `PolicyEngineBase` and `PIIGateBase` mirror
  `PIIDetectorBase` (Phase 3) rather than the classification services, so M5 can construct its
  whole chain and prove each component fails loudly when called. A policy engine that silently
  returned `ALLOW` would report every document clean; a gate that returned an empty `ALLOW`
  result would be the most dangerous stub in the repository.
- **Deferred by design — no working engine**, same call as Phase 3's aggregator: M4 is a
  contract milestone (§5) and the accept criterion is that precedence is *documented*. The
  algorithm is prose in the module docstring plus documentation tests that pin each clause
  (precedence order, the `max`-risk rule, the empty-findings case, every destination, the
  pipeline order).
- **Deviation — `DECISION_OUTCOMES` is data, not prose.** The §0 decision table is a
  `dict[str, str]` keyed by `PIIDecision` *values*, so M5's pipeline can switch on it and a test
  can assert the key set equals the enum's values — adding a decision without an outcome then
  fails the suite instead of reaching production as an unhandled case. A companion test asserts
  the halting set is exactly `{review, block}`.
- **Verification recap:** `uv run pytest tests/unit/pii` → 164 passed (23 + 13 + 20 + 37 + 71);
  `uv run pytest` → 338 passed; `uvx ruff check app/pii tests/unit/pii tests/support` → clean.
  Root `make lint` still reports only the 4 pre-existing `packages/storage` errors. Still
  uncommitted.
- **Next step:** Phase 6 (Canonical-output guard contract) — done, see below.

#### Contract gaps found in Phase 5 — for an M5/M6 decision, not resolved here

These are recorded rather than fixed. Each would require inventing policy the plan locked, and
the calibration data for them does not exist until M5 produces real findings.

- **`REVIEW` is unreachable on the default destination, so IMPL_ARCH §13's "suspicious document" case
  cannot occur.** §4.4's table has exactly two actions — `block` for `SECRET`, `allow` for
  everything else — so on `INTERNAL_LLM` the engine can only ever return `ALLOW` or `BLOCK`.
  IMPL_ARCH §13's second example ("a passport plus many unexpected identifiers" → `REVIEW`) requires a
  rule the locked table has no room for: a per-category table has no notion of a *combination*
  or a *count*. `ALLOW_WITH_WARNING` is reachable (via the `EXTERNAL_LLM` override's `REDACT`),
  but `REVIEW` is not reachable at all. A threshold ("≥N distinct high-risk categories →
  `REVIEW`") is exactly the kind of number that must be calibrated against real documents, and
  guessing one in a contract milestone would bake an unvalidated security threshold into the
  type. M5/M6 must add an explicit combination rule, or accept that `REVIEW` only ever fires
  for `destination=UNKNOWN`.
- **`REDACT` with `redaction_available=false` was unspecified.** §4.4 states
  `redaction_available=false` today and makes `EXTERNAL_LLM` demand `redact`, so the
  contradictory combination is the *default* state of the world, not a corner case. Resolved in
  the contract as **escalate to `REVIEW`, never downgrade to `ALLOW`**: a document that must be
  redacted and cannot be is one a human has to look at, and downgrading would send unredacted
  PII to an external provider while the artifact claimed a mere review. `PIIPolicyContext`
  therefore defaults `redaction_available=False` — the fail-closed direction. If M5 would rather
  treat this as `BLOCK`, that is a one-line change to the documented rule.
- **`PIIGate.inspect` cannot see the inputs that select an override.** `ProcessingContext` carries
  `document_id`, `document_version_id`, `patient_id`, `client_type`, `processing_id` and
  `attributes` — but not `destination` or `redaction_available`, the two inputs that choose a
  policy override. §4.6's "the gate needs no context change in M5" holds for the *fields*, but
  something has to supply these two. M5 must pass them from gate configuration; the signature
  was left exactly as ORDER §8 fixed it rather than widened, and the alternative — smuggling
  them through `attributes` — is rejected because a policy input arriving in a free-form dict
  cannot be validated or defaulted. Noted in `gate.py`'s docstring so M5 meets it rather than
  rediscovers it.

---

### Phase 6 — Canonical-output guard contract [x]

`app/pii/canonical_guard.py` — `CanonicalPIIViolation` (field path, category, masked value,
confidence), `CanonicalPIIInspector` Protocol
(`inspect(payload: dict[str, Any]) -> list[CanonicalPIIViolation]`), the **free-form walk rule**
(`BaseCanonical.fields` is `Any`, so the guard walks every string in the serialized payload
rather than a fixed field list), and the decision mapping reusing the Phase 5 engine with
`stage=CANONICAL`, `destination=PERSISTENCE`. Remediation actions (`warn` / `sanitize` / `retry_then_fail`)
are named in the contract; implementations land in M5.
Tests: `tests/unit/pii/test_canonical_guard.py`.
**Accept:** protocol + violation shape locked; a no-`packages.canonical`-model-import guard test
passes; the contract covers the two real leaks (`fields.note` patient name + ticket number).
**Deps:** Phases 1, 4, 5.

#### Phase 6 Implementation Status

**Changes.**

```text
apps/ai-worker/app/pii/canonical_guard.py      CanonicalPIIViolation, CanonicalPIIInspector,
                                               CanonicalPIIInspectorBase, PIIRemediation,
                                               DECISION_REMEDIATION, walk_string_leaves,
                                               CANONICAL_POLICY_{STAGE,DESTINATION}
apps/ai-worker/app/pii/__init__.py             +8 exports (57 total)
apps/ai-worker/tests/unit/pii/test_canonical_guard.py  33 tests
```

- **The walk is implemented, not just specified.** Every other engine in this
  milestone is a stub, but traversal is the one part of this contract that is
  fully determined — there is nothing to calibrate — so specifying it in prose
  would only invite an M5 reimplementation that walks something slightly
  different. `walk_string_leaves(payload)` yields `(field_path, value)` for every
  string leaf, tested behaviorally.
- **Path format chosen to match the evidence: `fields.note`.** Dotted dict keys,
  `[i]` list indices, so `fields.medications[0].doctor` traces back to a line in
  the artifact. Two tests assert the real leaks (`2b8fdd0d` with the ticket
  number, `fbbcb675` with name + age) are found at exactly that path, which is
  the plan's accept criterion discharged against the actual observed documents
  rather than a synthetic payload.
- **Traversal and judgement kept apart.** The walk inspects *every* string,
  including structural ones like `"schema_name": "generic"`, and has no key
  allow-list; the detector decides what is PII. An allow-list inside the
  traversal would put a second, undocumented judgement there and would need
  re-auditing every time a schema gains a field. Structural strings simply do not
  match.
- **Cycle tracking is path-scoped.** Containers already on the current recursion
  path are skipped, so a self-referential payload terminates instead of hanging
  the pipeline, while a sub-object shared between two keys is still visited under
  both. Both behaviours are tested.
- **`CanonicalPIIViolation` obeys the Phase 1 rule structurally.** No `value`
  field, `extra="forbid"`, frozen, and a test asserts the exact field set — so
  the second leak boundary cannot acquire a raw value later. The violation is the
  thing a caller persists about a leak, and a second copy of the leak is worse
  than no record.
- **`PIISource.CANONICAL` is implied by the type, not stored.** The enum member
  exists "so a finding raised by the Phase 6 guard is attributable", and M5 stamps
  it when converting violations into `PIIFinding`s. A field on a model that can
  only ever come from this one place would be a field that can disagree with its
  own type.
- **`PIIRemediation` is declared here, not in `models.py`.** `models.py`'s enum
  set was closed in Phase 1 and is asserted by the Phase 2 schema-parity tests;
  remediation is a guard concern, not an attribute of a finding.
- **`CANONICAL_POLICY_{STAGE,DESTINATION}` are named constants** because those two
  inputs change how the *same values* evaluate: a name in a payload heading for
  PostgreSQL is a persistence question, not a source-document one, and evaluating
  it as `stage=DOCUMENT` would consult the wrong policy rows.
- **Verification recap:** `uv run pytest tests/unit/pii` → 197 passed
  (23 + 13 + 20 + 37 + 71 + 33); `uv run pytest` → 371 passed;
  `uvx ruff check app/pii tests/unit/pii tests/support` → clean. Root `make lint`
  still reports only the 4 pre-existing `packages/storage` errors. Still
  uncommitted.
- **Next step:** Phase 7 (Persistence, provenance & versioning) — done, see below.

#### Contract gaps found in Phase 6 — for an M5 decision, not resolved here

- **Numeric leaves are a known blind spot.** The walk yields `str` leaves only,
  because that is what this phase specifies and because the observed leak is
  prose. A СНИЛС or phone serialized as a bare JSON *number* is not inspected.
  Deliberately not patched here: scanning numbers means scanning every
  measurement value, date component and internal id in every laboratory payload,
  and that false-positive surface is a calibration problem for M5's detectors, not
  something to decide inside a traversal. If M5 finds numeric identifiers leaking,
  the fix is a detector concern over an extended leaf set — not a change to the
  walk's contract.
- **The decision → remediation mapping is M4's proposal, not a locked decision.**
  §6 asks for the three actions to be "named in the contract", which they are, and
  `DECISION_REMEDIATION` supplies a mapping so the vocabulary is testable and
  complete against `PIIDecision`. The choices are judgement calls and are marked
  as such in the code: `ALLOW` still maps to `WARN` (reaching remediation at all
  means violations were found, and per the Phase 5 gap an `ALLOW` on a payload
  that did leak should leave a trace); `REVIEW` sanitizes (the guard exists
  because the observed leak reached `canonical.json` — halting for human review is
  no reason to also write the patient's name to storage on the way to the queue);
  `BLOCK` is the only retry-then-fail. M5 confirms or replaces it; the docstring
  says so, and a test asserts the module still claims to be unlocked.
- **`CanonicalPIIInspector.inspect` takes only the payload, so policy inputs must be
  constructor state.** Same shape as the Phase 5 finding about `PIIGate.inspect`
  not being able to see `destination`: `PIIPolicyContext` requires an
  `organization_id` and the guard is asked for neither. M5 constructs the
  inspector with its policy and organization; the protocol signature was left as
  §6 fixed it rather than widened.

---

### Phase 7 — Persistence, provenance & versioning [x]

Locks the serialized shapes and versions, and records the M5 touch lists. Code: `app/pii/`
version constants (`DETECTOR_VERSION` in `detectors.py`, `PII_POLICY_VERSION` in `policy.py`),
the locked `"pii"` frontmatter/event block, the `pii_result.json` artifact shape, the audit
record shape, and the fixture-manifest shape for `tests/fixtures/pii/`. Cross-package edits are
**documented, not made** (M5). Tests: `tests/unit/pii/test_persistence_contract.py`,
`tests/unit/pii/test_fixture_manifest.py`.
**Accept:** the `"pii"` block keys match §4 exactly; the audit record has no value or fingerprint
field; version constants are importable; three synthetic fixtures prove the manifest shape.
**Deps:** Phases 1–6.

#### Phase 7 Implementation Status

**Changes.**

```text
apps/ai-worker/app/pii/persistence.py          PII_META_BLOCK_KEY, PII_ARTIFACT_FILENAME,
                                               PII_META_{REQUIRED,OPTIONAL}_KEYS,
                                               PII_AUDIT_EVENTS, PII_REDACTED_EVENT,
                                               DECISION_AUDIT_EVENTS
apps/ai-worker/app/pii/fixtures.py             PIIFixture, iter_pii_fixtures,
                                               FIXTURES_DIR, MANIFEST_PATH,
                                               PII_FIXTURE_DIRECTORIES
apps/ai-worker/app/pii/__init__.py             +7 exports (64 total)
apps/ai-worker/tests/fixtures/pii/manifest.json
apps/ai-worker/tests/fixtures/pii/{clean,patient,malicious}/  3 synthetic fixtures
apps/ai-worker/tests/unit/pii/test_persistence_contract.py    33 tests
apps/ai-worker/tests/unit/pii/test_fixture_manifest.py        32 tests
```

- **The block shape is data, not a model, and that is the load-bearing decision.**
  §4.7 fixes `"pii"` as a sibling of `ClassificationMeta` in
  `packages/canonical/canonical/metadata.py:55-74`, and M4 must not edit
  `packages/`. Defining a Pydantic model here would leave M5 with two classes for
  one shape, of which the one nobody uses is the one that rots. So the key set is
  `PII_META_REQUIRED_KEYS` / `PII_META_OPTIONAL_KEYS`, asserted against §4.7's own
  JSON example. A JSON Schema was rejected for the same reason plus one: every
  schema in `app/pii/schemas.py` is *derived* from a contract model precisely so
  it cannot drift (see that module's docstring), and there is no model here to
  derive from — a hand-written schema would reintroduce exactly the drift the
  Phase 2 pattern exists to prevent.
- **Nine required keys, two defaulted, asserted to be exactly eleven.** The split
  mirrors `ClassificationMeta`, where `reasons`/`warnings` default to empty lists
  and everything else is required. `category_counts` and `categories` are both
  required because `category_counts` is authoritative and `categories` is derived
  from it — a consumer forced to recompute the tally to render a list will get it
  wrong for precisely the duplicate findings aggregation exists to remove.
- **`DECISION_AUDIT_EVENTS` is keyed by decision, and `ALLOW` shares
  `pii.scan.completed` with `ALLOW_WITH_WARNING`.** They differ in the stored
  result, not in what happened operationally; a consumer asking "was this scanned?"
  should not need to know the decision vocabulary. `BLOCK` and `REVIEW` are
  distinct, and a test asserts the map's key set equals `PIIDecision`'s, so a new
  decision cannot arrive without an event.
- **`pii.redacted` is additive and is deliberately not a decision's own event.**
  A redacted-and-allowed document is both, and collapsing them would make "how
  often do we redact" unanswerable without joining against the stored result. A
  test asserts `PII_REDACTED_EVENT not in DECISION_AUDIT_EVENTS.values()`.
- **The manifest ships three fixtures, all synthetic, on purpose.** `clean` →
  `allow`/`low`, `patient` → `review`/`high` across seven categories,
  `malicious` → `block`/`critical` with `contains_secret`. M4 has no detector, so
  the `expected_*` fields are a specification M5 confirms rather than something a
  test can verify — the tests that carry weight here are structural (shape, path
  resolution, enum validity, on-disk/manifest parity). **No real marker was
  copied**, and that is a security decision, not an omission: `.dev/flow_upload_test/`
  holds real patient data, and adding a second copy to a new directory would
  manufacture exactly the leak this milestone exists to close. A test asserts the
  seeded set contains no real marker id. The sweep is M5's, where the copied
  markers live in a directory the guard already scans.
- **`expected_decision` is context-dependent, and §4.10's entry keys have no
  destination field.** Phase 5 makes a patient category `ALLOW_WITH_WARNING` at an
  internal destination and `REVIEW` at the external one, so a single expected value
  is wrong half the time. Rather than widen the locked entry shape, the manifest
  `notes` state the assumed context (the external boundary) and a test asserts the
  notes still do. `clean` and `malicious` are context-independent — no findings, and
  a secret blocks at every destination — so only the patient entry depends on it.
- **The fixture loader is app-owned and unexported, mirroring
  `app/classification/fixtures.py`.** It lives in the app so M5's detection CLI and
  the test suite read one manifest, and it is *not* in `app.pii.__all__`: the
  dataset is a dev/eval surface, and `app.classification` keeps its loader out of
  its public API too. Two loaders rather than one shared one, because the entry
  shapes genuinely differ (`expected_categories` + `expected_risk_level` +
  `contains_secret` here, `expected_type` + `expected_subtype` there) and a union
  would put three always-null fields on every PII entry.
- **On-disk/manifest parity is asserted,** copying
  `tests/unit/classification/test_fixture_manifest.py:66-72`. A fixture file
  without an entry, or an entry without a file, fails the suite.
- **§4.7's three §5 assertions are all discharged:** the block keys match §4.7 and
  none is a value, mask or fingerprint; `PIIAuditRecord`'s field set is asserted
  *exactly*, not just "no `value`", so a field cannot be appended later; both
  version constants are importable from their home modules and are stamped on both
  the block and the persisted result. The SemVer rule that matters — any change
  altering a decision bumps the policy version — lives only in prose, so a test
  asserts the `persistence` docstring still states it.
- **Verification:** `uv run pytest tests/unit/pii` → 262 passed
  (23 + 13 + 20 + 37 + 71 + 33 + 65); `uv run pytest` → 436 passed;
  `uvx ruff check app/pii tests/unit/pii tests/support` and `ruff format --check` on
  the touched files → clean. Root `make lint` unchanged (4 pre-existing
  `packages/storage` errors). Still uncommitted.
- **M4 is complete.** No further phase in this plan; the next work is M5.

#### Contract gaps found in Phase 7 — for an M5 decision, not resolved here

- **`expected_decision` in the manifest is only meaningful against a stated
  destination.** Resolved inside the manifest for M4 by documenting the assumed
  context in `notes`, but the underlying tension is real and M5 owns it: either
  the manifest entry grows a `destination` (widening the §4.10 shape this phase
  locked) or the evaluation suite is parameterised over destinations and the
  manifest becomes a per-destination matrix. Left as-is, so M5 chooses with the
  real detector in hand.
- **`PII_META_*_KEYS` is a key *set*, not a typed shape.** Nothing validates an
  actual block against it yet, because the validating model is `PIIMeta` and that
  lives in `packages/`. So M4 can prove the intended shape but not that a written
  block conforms to it. Once §4.9's first touch list is done, the natural move is a
  test that validates a sample block through the real `PIIMeta` and asserts its
  field set equals `PII_META_REQUIRED_KEYS | PII_META_OPTIONAL_KEYS` — which is
  what turns this phase's assertion from transcription into enforcement.
- **`PIIAuditRecord` has no `destination` field**, so an audit trail cannot answer
  "where was this document sent", and a leaked document at the external boundary
  and the same document sent internally produce identical records apart from the
  event name. §4.7's example block carries `destination` and the record does not.
  Not added here: the audit record is a Phase 1 model with a field set asserted in
  three phases' tests, and widening it is a schema-versioned change belonging to
  whoever writes the first real audit sink.

---


---

## 3. Pending phases

None — all seven M4 phases are implemented. Every item §4.9 lists as an M5
touch list is still unmade, by design: M4 delivers the contract and M5 delivers
the gate. The next work is not a phase of this plan but the milestone it hands
off to, starting with the implementation stubs that currently raise
(`PIIDetectorBase`, `PIIAggregatorBase`, `PolicyEngineBase`, `PIIGateBase`,
`CanonicalPIIInspectorBase`) and the cross-package edits recorded in §4.9.

## 4. Locked design reference (condensed)

### 4.1 `PIICategory` (23 values, 5 groups + secrets)

Grouped per IMPL_ARCH §3/§4. `TICKET_NUMBER` is added from real evidence
(`2b8fdd0d` marker: `Номер талона: 2026030709303211960141`); `SECRET` from IMPL_ARCH §13. Count
corrected 22 → 23 in Phase 1 (the list below always held 23 members; see the Phase 1
Implementation Status).

```text
identity      PERSON_NAME DATE_OF_BIRTH AGE GENDER NATIONALITY
contact       EMAIL PHONE ADDRESS
government    PASSPORT NATIONAL_ID INSURANCE_NUMBER SNILS INN
medical id    PATIENT_ID MEDICAL_RECORD_NUMBER LAB_ORDER_ID ENCOUNTER_ID TICKET_NUMBER
practitioner  DOCTOR_NAME DOCTOR_LICENSE ORGANIZATION_NAME ORGANIZATION_ID
secret        SECRET
```

`ORGANIZATION_*` and `DOCTOR_*` are deliberately *not* patient PII: a clinic's name is not a
patient identifier (IMPL_ARCH §3), and the future `AppointmentCanonical` needs practitioner and
organization data (ORDER §5). Splitting them here prevents a policy that redacts the issuing
clinic along with the patient.

### 4.2 Supporting enums

```text
PIISource        pattern | structured_field | ner | llm | canonical
PIIRiskLevel     low | medium | high | critical
PIIAction        allow | warn | redact | review | block
PIIDecision      allow | allow_with_warning | review | block
PIIDestination   internal_llm | external_llm | persistence | unknown
PIIScanStage     document | canonical
```

`PIIDecision` follows IMPL_ARCH §13, not the `{"status": "allowed"}` sketch in ORDER §2 — the enum
vocabulary of IMPL_ARCH wins; recorded as a deviation in §7. `PIISource.canonical` exists so a finding
raised by the Phase 6 guard is attributable to a different mechanism than a source-document scan.

### 4.3 Models

`PIIFinding` — in-process only, frozen, `extra="forbid"`:

```text
category (PIICategory)
value (str)                    ← Field(exclude=True): never serialized, never logged
masked_value (str)             ← required; built by mask_pii_value()
value_fingerprint (str)        ← required; salted HMAC via hash_pii_value(); never logged
confidence (float 0–1)         ← documented range, no validator (mirrors ClassificationResult.confidence)
source (PIISource) · detector (str) · detector_version (str)
start (int|None) · end (int|None) · metadata (dict)
```

`PIIFindingSummary` — what crosses a boundary; `extra="forbid"`:

```text
category · masked_value · confidence · source · detector · start · end
```

No `value`, no `value_fingerprint`. `PIIScanResult` — the aggregate:

```text
decision (PIIDecision) · risk_level (PIIRiskLevel) · stage (PIIScanStage)
destination (PIIDestination) · findings (list[PIIFindingSummary]) · findings_count (int)
category_counts (dict[str,int]) · reasons (list[str]) · warnings (list[str])
detector_version · policy_version · processed_at (datetime)
```

`PIIAuditRecord` — IMPL_ARCH §22; `event`, `document_id`, `stage`, `decision`, `risk_level`,
`findings_count`, `detector_version`, `policy_version`, `occurred_at`. No values, no
fingerprints, no detector internals. `PIIDecisionResult` — internal policy output
(`decision`, `risk_level`, `actions: dict[PIICategory, PIIAction]`, `reasons`, `warnings`);
distinct from `PIIScanResult`, which is the persisted, boundary-safe projection of it.

Exceptions (extending the existing `PIIError`): `InvalidPIIInputError`, `PIIDetectorError`,
`PIIPolicyError`, `PIIRedactionError`, `PIIDecisionError` (the fail-closed path).

### 4.4 Default policy (locked baseline)

Risk ladder matches IMPL_ARCH §12's example. Actions are stated for the default
`destination=INTERNAL_LLM`; `redaction_available=false` today.

```text
SECRET                                    critical  block
PASSPORT NATIONAL_ID INN SNILS INSURANCE_NUMBER
PATIENT_ID MEDICAL_RECORD_NUMBER LAB_ORDER_ID
ENCOUNTER_ID TICKET_NUMBER                 high      allow
PERSON_NAME DOCTOR_NAME DATE_OF_BIRTH
PHONE ADDRESS DOCTOR_LICENSE               medium    allow
AGE GENDER NATIONALITY EMAIL
ORGANIZATION_NAME ORGANIZATION_ID          low       allow
```

Overrides: `destination=EXTERNAL_LLM` → all identity/government/medical-id/contact categories
become `redact`; `destination=UNKNOWN` → `review` (fail closed). Precedence
`block > review > allow_with_warning > allow`; `risk_level = max(category_risk[c])` over
findings; `ALLOW_WITH_WARNING` when any `warn`/`redact` action applied and no `review`/`block`.

### 4.5 Mask table (locked, per category)

Least-significant 2–4 characters only, for human debugging; everything else `*`.

```text
SECRET              →  ****                        (never reveal, no tail)
PERSON_NAME          →  И***** И***** И*********    (IMPL_ARCH §6)
DOCTOR_NAME          →  И***** И***** И*********
PHONE                →  +7******4567               (IMPL_ARCH §6)
EMAIL                →  i****@d****.ru
DATE_OF_BIRTH        →  **.**.****
SNILS                →  ***-***-*** **
INSURANCE_NUMBER     →  ******************
PASSPORT             →  **** ******
NATIONAL_ID, INN    →  ************
ADDRESS              →  г. *******, ул. *******, д. **
TICKET_NUMBER, *_ID  →  first 2 chars + * (remainder)
ORGANIZATION_NAME/ID →  unmasked (not patient PII)
```

### 4.6 Interfaces

```python
class PIIDetector(Protocol):
    def detect(self, document: NormalizedDocument) -> list[PIIFinding]: ...

class PIIAggregator(Protocol):
    def aggregate(self, findings: list[PIIFinding]) -> list[PIIFinding]: ...

class PIIRedactor(Protocol):
    def redact(self, markdown: str, findings: list[PIIFinding]) -> str: ...

class PolicyEngine(Protocol):
    def evaluate(self, findings: list[PIIFinding], context: PIIPolicyContext) -> PIIDecisionResult: ...

class PIIGate(Protocol):
    async def inspect(self, document: NormalizedDocument, context: ProcessingContext) -> PIIScanResult: ...

class CanonicalPIIInspector(Protocol):
    def inspect(self, payload: dict[str, Any]) -> list[CanonicalPIIViolation]: ...
```

`PIIGate.inspect` is the ORDER §8 signature verbatim, so PII stays a document-level capability
and never becomes `AppointmentPIIGate` (ORDER §8). Sync vs async: detectors, aggregation,
masking, redaction and the guard are sync (pure string transforms); only `PIIGate.inspect` is
async, mirroring `ClassificationService.classify` (`app/classification/service.py:43-52`).

`NormalizedDocument` is **reused**, not rebuilt (IMPL_ARCH Phase 2): one normalizer feeds both
classification and PII. `ProcessingContext` (`app/pipeline/context.py:7-15`) already
carries `document_id`, `document_version_id`, `patient_id`, `client_type`, `processing_id`,
`attributes` — the gate needs no context change in M5. The gate result is *not* added to
`ProcessingContext` as a field: classification isn't either, and both ride in the event/metadata.

### 4.7 Persistence shape (locked for M5)

Mirrors Classification 2.0 exactly — artifact + frontmatter block + event `data` key, **no new
event, no new DB table, no new migration**:

```json
"pii": {
  "decision": "allow",
  "risk_level": "medium",
  "stage": "document",
  "destination": "internal_llm",
  "findings_count": 7,
  "category_counts": { "person_name": 1, "date_of_birth": 1, "medical_record_number": 1,
                       "doctor_name": 1, "organization_name": 1, "address": 2 },
  "categories": ["person_name", "date_of_birth", "medical_record_number"],
  "detector_version": "1.0.0",
  "policy_version": "1.0.0",
  "reasons": ["expected_medical_identity"],
  "warnings": []
}
```

The block shape matches `ClassificationMeta` (`packages/canonical/canonical/metadata.py:55-74`):
same `extra="forbid"`, `reasons`/`warnings` lists, `*_version` string — `PIIMeta` will be its
sibling in the same file, and `FrontmatterMeta.pii` its optional field (`:93` has
`classification: ClassificationMeta | None = None`). Full findings (masked) live only in
`pii_result.json`, mirroring `classification_result.json`. `categories` is a convenience list for
UI/metrics; `category_counts` is authoritative.

**Audit events** (IMPL_ARCH Phase 9, no values): `pii.scan.completed`, `pii.blocked`,
`pii.review.required`, `pii.redacted`. Audit must be written (IMPL_ARCH §22) but must never carry
PII values (IMPL_ARCH §22, §6).

### 4.8 Versioning

`DETECTOR_VERSION = "1.0.0"` (in `app/pii/detectors.py`), `PII_POLICY_VERSION = "1.0.0"` (in
`app/pii/policy.py`). SemVer policy identical to Classification's (§7 of the M1 plan): patch =
docs/comments; minor = additive (new optional fields, new `PIICategory` values) — **a new
category also requires a policy row, or it inherits no action**; major = breaking (required field
changes, enum removals, decision-rule changes). Any change that alters a decision bumps the
policy version, so a stored `PIIScanResult` can always be interpreted by the policy that produced it.

### 4.9 M5 touch lists (documented here, executed in M5)

`packages/storage`: `storage/keys.py:10-15` add `"pii": "pii_result.json"` to
`MARKDOWN_ARTIFACTS` + update the docstring at `:38-47`; `storage/__init__.py:9-12` add
`MARKDOWN_KIND_PII` and its `__all__` entry (alphabetical, after `MARKDOWN_KIND_CLASSIFICATION`);
`tests/test_keys.py` extend the known-kinds and classification-key cases.

`apps/ai-worker`: `app/artifacts/models.py:3-17` and `app/artifacts/__init__.py:3-26`
re-export the new kind; `app/pii/artifact.py` gains `build_pii_artifact(...)` mirroring
`app/classification/artifact.py:18-50`; `app/pipeline/pipeline.py` constructs `PIIGate` in
`__init__` (`:60-77`), calls `inspect` after classification (`:147`), uploads the artifact
**before** publishing (the ordering invariant from M2 Phase 4, `:190-196`), adds the guard after
`build_canonical` (`:164`), and adds `pii` to frontmatter (`:167-176`) and event `data` (`:235-241`).

`packages/canonical`: `canonical/metadata.py` gains `PIIMeta` + `FrontmatterMeta.pii`;
`canonical/__init__.py` re-exports; `apps/ai-worker/app/canonical/rendering.py:36-72` gains a
`pii=` parameter on `build_frontmatter_meta`.

`apps/account-api`: if account-api ever reads the artifact, its hard-coded kind allow-list
(`app/services/storage.py:80-85`) must gain the new kind — it currently omits even
`classification`, so this is a pre-existing gap, not a PII regression. PII metadata is internal
(IMPL_ARCH §26), so **no API surface and no event are added** in M5.

### 4.10 Fixture manifest shape (M4 seeds it, M5 fills it)

`tests/fixtures/pii/manifest.json` mirrors the classification manifest (loader shape in
`app/classification/fixtures.py:52-67`): top-level `version` + `notes` + `fixtures[]` where each
entry has `file`, `source` (`real`|`synthetic`), `expected_categories` (list),
`expected_decision`, `expected_risk_level`, and optionally `contains_secret` (bool).
Directories per IMPL_ARCH Phase 10: `clean/ patient/ laboratory/ appointment/ prescription/ mixed/
malicious/`. M4 seeds `clean/`, `patient/` and `malicious/` synthetically to prove the shape; the
real-marker sweep (copying `.dev/flow_upload_test/`) is M5.

---

## 5. Tests

**Approach (M4): contract-level only** — importability, enum values, field shapes, schema keys,
protocol conformance on stubs, policy table values, mask rules, and boundary assertions. No
detection-logic tests (nothing detects yet), mirroring M1's approach.

The three assertions that carry the security value:

```text
1. "value" not in PIIFindingSummary.model_fields / PIIScanResult.model_fields
   and "value" not in PIIFinding.model_dump()          (exclusion is structural)
2. no "value" property in PII_FINDING_SCHEMA            (schema-level proof)
3. no "value"/"value_fingerprint" in PIIAuditRecord.model_fields
```

Plus two import guards: no `s3`/`rabbit`/`storage` import in `app/pii/*` (mirrors
`test_service.py:184-195`), and no `app.classification` domain import in `app/pii/*` — the
architectural boundary from ORDER §8. A runtime "no PII in logs" test needs an implementation and
lands in M5; in M4 it is asserted structurally on the models.

**Files:** `tests/unit/pii/{test_models,test_schemas,test_detectors,test_masking_redaction,test_policy_gate,test_canonical_guard,test_persistence_contract,test_fixture_manifest}.py`.
No `__init__.py` in test dirs (matches `tests/unit/classification/`).

**Commands:**

```bash
cd apps/ai-worker && uv run pytest tests/unit/pii -v          # focused
cd apps/ai-worker && uv run pytest                            # full: 174 baseline, must stay green
uv run --project packages/storage pytest packages/storage     # only after M5 touches keys.py
make lint                                                      # uvx ruff check apps packages tests
```

**Acceptance smoke check (from `apps/ai-worker`):**

```bash
uv run python -c "from app.pii import PIICategory, PIIScanResult, PIIGate, DETECTOR_VERSION, PII_POLICY_VERSION; print('ok')"
```

M4 introduces **no** new runtime dependency (stdlib `re`/`hmac`/`hashlib` + Pydantic only) and
**no** migration.

---

## 6. Implementation order

1. **Phase 1 — Domain contract** [x] — enums, models, exceptions. Everything else depends on it.
2. **Phase 2 — Schemas** [x] — derives from Phase 1, so the "no `value` in schema" proof lands early.
3. **Phase 3 — Detector contract** [x] — protocol + stubs + aggregator; do it early so the
   `PIIFinding` construction requirements (masked/fingerprint) get exercised by real consumers.
4. **Phase 4 — Masking & redaction** [x] — needs Phase 1 fields; independent of Phase 3 logic.
5. **Phase 5 — Policy + gate** [x] — the core contract; needs detectors and masking to be
   well-shaped, so it lands after them.
6. **Phase 6 — Canonical-output guard** [x] — needs the policy engine it reuses.
7. **Phase 7 — Persistence, provenance & versioning** [x] — last: it projects the frozen shapes.

Author in parallel with phases 3–4: the `tests/fixtures/pii/` synthetic trio (do early so Phase 5
policy tests have ground truth, as M2 Phase 5's dataset preceded its verification phase).

Each phase: implement → update status in all three places (§1 table, §3 heading, §6 list) → pause
for confirmation. Deviations labeled `Deviation:` in the phase's Implementation Status block.

---

## 7. Notes & conventions

### Gotchas (verified)

- **The leak is live, not hypothetical.** Both `2b8fdd0d.../canonical.json` and
  `fbbcb675.../canonical.json` contain the patient's full name; the first also carries the ticket
  number and address. `2b8fdd0d` is already a permanent classification fixture
  (`tests/fixtures/classification/appointment/2b8fdd0d.md:16-25`), so the same real PII is already
  in the repo's test data — the PII dataset should reuse copies, not `.dev` references (M2's
  convention).
- **`BaseCanonical.fields` is `Any`** (`packages/canonical/canonical/schemas/__init__.py:67-89`),
  and `GenericCanonical` is the current default model (`:124-139`). There is no field list to
  guard — hence the free-form payload walk in Phase 6. Prompting alone cannot hold this line,
  which is precisely why `canonical.yaml:100` failed.
- **Nested PII also persists to PostgreSQL.** `DocumentAnalysisCompleted.data` is written
  verbatim into `document_extractions.data` (`apps/account-api/app/services/documents.py:536`),
  so an event-level `data["pii"]` block is how account-api learns the verdict without a new table.
- **account-api's storage allow-list is already behind** — `app/services/storage.py:80-85` omits
  `MARKDOWN_KIND_CLASSIFICATION`, so account-api cannot read the classification artifact today.
  Pre-existing gap; leave it alone unless M5 needs account-api to read the PII artifact (it
  should not — PII metadata is internal, IMPL_ARCH §26).
- **Existing masking helpers are not reusable.** `apps/account-api/app/middleware/request_logging.py:387-566`
  has header/body maskers, but they are methods on a FastAPI middleware, match field names by
  *substring* (so `"name"` also matches `"schema_name"`/`"filename"`), and live in account-api
  where ai-worker cannot import them. `packages/observability` is declared by all six apps but is a
  0-byte stub. M4 therefore defines its own small, typed masker in `app/pii/masking.py`; extracting
  the middleware helpers to a shared module is a separate cleanup, not an M4 dependency.
- **No feature flags exist** in `Settings` (only `prompts_dir`, `pdf_dpi`, `pdf_format`,
  `ai_model`). M5 needs one new setting for the fingerprint secret (§4.3); M4 does not touch
  settings. A fingerprint secret must not fall back to a hard-coded default.
- **No mypy/pyright in the repo**; type errors surface as Pydantic/import failures. This is the
  existing convention from M1, not a new gap — `ruff` + Pydantic + import smoke checks are the gate.
- **Test subdirs have no `__init__.py`** (`tests/unit/classification/`), but
  `tests/support/__init__.py` exists. `tests/unit/pii/` is the exception and **does** have one:
  `tests/unit/classification/` already owns `test_models.py`, `test_schemas.py` and
  `test_fixture_manifest.py`, and without a package marker pytest's prepend import mode makes
  same-named siblings collide ("import file mismatch") — observed during Phase 1. A
  `tests/support/pii_fixtures.py` delegate (mirroring `tests/support/classification_fixtures.py:1-21`)
  is the place to put manifest iteration once the dataset grows.
- **Fixture-manifest tests are strict.** `test_fixture_manifest.py:66-72` asserts the `.md` set on
  disk equals the manifest set, so the PII manifest must be complete in the same commit that adds
  a fixture file.
- **Ruff is repo-root only** (`pyproject.toml:29-37`, line-length 100, `select = ["E","F","I","UP","B","SIM"]`).
  `I` sorting matters: `__all__` lists and import blocks must stay alphabetical.

### Open decisions (defaults chosen)

- **Raw value handling:** in-memory-only `value` (`Field(exclude=True)`) + `masked_value` +
  salted `value_fingerprint`; serialized summary carries `masked_value` only. Chosen over
  dropping `value` entirely because redaction needs the real text in-process, and over IMPL_ARCH §5's
  literal shape because relying on call-site discipline is not a control.
- **Persistence surface:** mirror Classification 2.0 (artifact + frontmatter block + event `data`
  key; no new event, no new table, no migration). Chosen for contract consistency and zero churn
  in `packages/contracts` + `account-api`. A dedicated `document.pii-checked` event is the natural
  later step *if* PII ever needs to be consumed independently of analysis (e.g. bulk upload
  screening before extraction); it is explicitly out of M4.
- **Current provider is trusted:** `destination` defaults to `INTERNAL_LLM`, so no pre-extraction
  redaction today; `REDACT` is fully specified but unreachable. Reversible by a one-line default
  change once an external provider is added, which is the point of making it data.
- **M4 includes the canonical-output guard.** It is the only contract that stops the leak that was
  actually observed; a document-only gate would have left `fields.note` unguarded.
- **NER/LLM detectors are deferred** (IMPL_ARCH §10/§11): contract stubs only for pattern,
  structured-field, secret and composite. Rationale: deterministic detectors are testable and
  reviewable; NER/LLM detectors get added in M5+ behind the same protocol, and the LLM detector
  is explicitly never the sole control.
- **`value_fingerprint` is not logged and not persisted** in the frontmatter/event block. If
  cross-scan correlation is later needed, the `document_id` + `category` + offset triple is the
  sanctioned join key.
- **`age`/`gender` as PII categories:** kept (IMPL_ARCH §3 identity group) at LOW risk, masked to `**`.
  They appear in the real lab note (`"(М, 39 лет)"`), so ignoring them would leave a real channel open.
- **`document_type` in policy context** is a plain `str | None`, deliberately not `DocumentType`,
  to keep `app/pii/` free of any `app.classification` import.
- **Risk/action in policy, not detection.** `PIIDetector.detect()` never returns risk or action;
  only the engine assigns them. This is what makes org-specific policy data rather than code (IMPL_ARCH §17, §25).

### Risks (mitigations in place)

- **Contract over-specification.** 22 categories and 7 enums in a contract-only milestone could
  turn into an unmaintainable surface. Mitigated by: all values are used by at least one real
  fixture or by IMPL_ARCH, the policy table is data, and additions are minor-version events.
- **False positives degrading extraction** (IMPL_ARCH §34): e.g. `Москва` as address vs clinic address.
  Mitigated by `ALLOW` being the default for identity/contact, by `masked_value` + offsets +
  `detector` in every finding (so M6 can triage), and by `REVIEW` never auto-redacting.
- **Fingerprint treated as a safe hash.** A plain digest here would be a re-identification channel
  for low-entropy IDs. Mitigated by locking HMAC+salt, keeping fingerprints out of logs and the
  persisted block, and asserting both in Phase 4/7 tests.
- **Gate wired in the wrong place** — after extraction, where it cannot help. Mitigated by
  ORDER §23/§24 (parallel with classification) plus the lock that the guard *also* exists post-
  extraction; the pipeline diagram in §0 shows both, and M5 acceptance requires the guard.
- **Compliance misreading.** Someone cites this gate as HIPAA/152-ФЗ/GDPR proof. Mitigated by the
  explicit invariant in §0 and IMPL_ARCH §37.
- **No type-check in CI.** Same as every prior contour; mitigated by Pydantic + import smoke
  checks + ruff, per existing convention.
- **`docs/messaging/EVENTS.md` staleness.** Not touched in M4 (no new event); if the surface ever
  changes, the catalog at `EVENTS.md:8-18` must be updated in the same commit.

### Versioning policy (locked)

`DETECTOR_VERSION = "1.0.0"`, `PII_POLICY_VERSION = "1.0.0"` at M4. Patch = docs/comments only.
Minor = additive (new optional field, new `PIICategory` with a matching policy row) and
backward-compatible. Major = breaking (required field change, enum removal, decision-rule
change) — any change that alters a decision for any input bumps the policy version, so a stored
`PIIScanResult` always names the policy that produced it. Detector and policy versions move
independently, mirroring `classifier_version` (currently `2.1.0`).

### Conventions

- Follow `docs/development/operational/CONTRIBUTING.md`. M4 changes are localized to
  `apps/ai-worker/app/pii/**` and `apps/ai-worker/tests/unit/pii/**` plus
  `apps/ai-worker/tests/fixtures/pii/**`; no pipeline, package or migration edits.
- Reuse the existing placeholder files rather than renaming: `detectors.py`, `gate.py`,
  `models.py`, `policy.py`, `exceptions.py` already exist. New files: `schemas.py`,
  `aggregation.py`, `masking.py`, `redaction.py`, `canonical_guard.py` (+ `artifact.py` in M5).
- Flat layout, mirroring `app/classification/` and STRUCTURE §5 — not IMPL_ARCH Phase 1's
  `pii/domain/` subpackage. Same deviation as the Classification M1 plan; recorded here so M5
  doesn't re-litigate it.
- Pydantic v2, `extra="forbid"` on every boundary model, `model_json_schema()` for schemas,
  `str, Enum` for enums, `Protocol` for interfaces, string annotations + `TYPE_CHECKING` for
  cross-package types.
- Status mirrored in three places: §1 table, §3 heading, §6 list.
