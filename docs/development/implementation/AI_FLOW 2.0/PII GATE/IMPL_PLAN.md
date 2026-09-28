# PII Gate — Implementation Plan (M4: Specification · M5: Gate)

**Scope.** Two milestones in one plan file. **M4 – PII Gate specification** (ORDER.md **M4**): the
contract only — domain enums/models, detector/masking/redaction/policy/gate interfaces, the
post-extraction canonical-output guard, the locked persistence shape, and versioning. **Done.**
**M5 – PII Gate**: the implementations those contracts specify, both contours wired into the
pipeline, and the cross-package persistence surface M4 deliberately did not touch. M5 closes the
live leak through `fields.note`. Built on existing infra only — no parallel architecture. M6
evaluates and calibrates the false-positive rate.

**Depth sources:** [IMPL_ARCH.md](./IMPL_ARCH.md) (PII gate design spec, §§1–45),
[IMPL_RPRT.md](./IMPL_RPRT.md) (M4 implementation report and hand-off), [ORDER.md](../ORDER.md)
(§2 PII Gate, §8 interface, §12 milestones, **§13 the M5 leak analysis and scope rulings**),
[STRUCTURE.md](../STRUCTURE.md) (§2 pipeline, §5 `pii/` layering), [SUMMARY.md](../SUMMARY.md)
(§11 PII gate, §12 medical identity split, Phase 4),
[Classification 2.0 CONTRACT_IMPL_PLAN.md](../CLASSIFICATION%202.0/CONTRACT_IMPL_PLAN.md)
(the M1 contract precedent this contour mirrors), [IMPL_PLAN_SCHEMA.md](../../operational/IMPL_PLAN_SCHEMA.md).
Full taxonomy/policy tables are condensed in §4; the plan holds decisions, not the design prose.

**Revision 1** — initial M4-only plan (2026-09-26). M3 (Classification 2.0 evaluation) closed
2026-09-23 at `classifier_version = "2.1.0"` (`33af39f`), so M4 is next per ORDER §12.

**Revision 2** — (2026-09-28) **M5 phases added.** M4 closed as `ef412d2`: 436 tests green (174
baseline + 262 PII contract tests), `make lint` clean apart from 4 pre-existing `packages/storage`
errors. What changed: (a) M4's seven phases moved **verbatim** into §2 — history is not rewritten;
(b) ten M5 phases added as §3, sequenced per IMPL_ARCH §45's 19-step order; (c) §4 gains §4.11
(persistence escalation policy) and §4.12 (per-category remediation), and §4.8 gains the M5 version
roadmap; (d) §5, §6, §7 extended for M5. **Scope ruling:** IMPL_ARCH §45's full order is
authoritative over ORDER §13.8's contour-2-only limit — the user chose full order, so M5 builds both
contours. See §7 open decision 1. **Revision 2 corrected four M4 statements in §4** that M4 recorded
as future work and that are now settled: §4.7's version example, §4.9's title and its missing
pipeline-ordering note, and §4.10's instruction to *copy* `.dev/flow_upload_test/` markers into the
dataset — the last of these is a correction, not an addition, since ORDER §13.3 forbids committing
real patient data and M4's wording said the opposite. **M4's phase blocks in §2 were left byte-identical**,
including a formatting drift from Revision 1: Phases 4–7 omit the `**Status.**` and
`**Verification.**` labels, and Phase 4 has no `#### Phase 4 Implementation Status` heading, so all
four carry their verification as a `**Verification recap:**` bullet instead. Recorded rather than
reformatted, per schema rule 4; M5 phases use the §4 grammar consistently.

Status legend: `[ ]` pending · `[x]` done.

---

## 0. Overview

**Current (as-is, after M4):** the contract is complete, the behaviour is not. The five base
classes still raise, so **the observed leak is live**.

```text
upload (PDF)
  → OCR (external LLM, pipeline.py:92)          ← UNGATED, pre-marker, see §7 risk R1
  → marker.md
  → MarkdownNormalizer → NormalizedDocument
  → CLASSIFICATION
  → PII GATE  ── PIIGateBase.inspect() → NotImplementedError      ← contract only
  → LLM extraction → build_canonical
  → CANONICAL GUARD ── CanonicalPIIInspectorBase.inspect() → raises ← contract only
  → canonical.json  (S3)          :199  ┐
      structured.md   (S3)         :203  ├─ fields.note carries the patient's name
      event data["canonical"]      :236  ┘  → account-api:536 → document_extractions.data
```

The leak, verbatim from `.dev/flow_upload_test/`:

```text
2b8fdd0d.../marker.md      → ФИО: Шадеркин Денис Сергеевич · Полис №: 8152510822001720
                              СНИЛС: 123-067-082 21 · Дата рождения: 27.07.1984
2b8fdd0d.../canonical.json → fields.note: "...для пациента Шадеркина Дениса Сергеевича.
                                  Номер талона: 2026030709303211960141."
fbbcb675.../canonical.json → fields.note: "...для пациента Шадеркина Дениса Сергеевича (М, 39 лет)..."
```

The prompt rule at `app/prompts/canonical.yaml:100` is a *request* to the model, not a control —
SUMMARY.md §11 is the analysis of exactly that failure.

**Target (M5):** both contours executable, the canonical object sanitized before every dump point.

```text
  → OCR (external LLM)   DOCUMENTED TRUSTED BOUNDARY — cannot be gated, produces marker.md
  → marker.md → NormalizedDocument
  → CLASSIFICATION
  → PII GATE (contour 1)   PIIGate.inspect(document, ctx) -> PIIScanResult
       detect → aggregate → policy → decide
       ├── ALLOW / ALLOW_WITH_WARNING → continue
       ├── REVIEW  → halt, processing_status = needs_review
       └── BLOCK   → halt, processing failure (SECRET only)
  → PIIRedactor.redact → redacted text, only when destination = EXTERNAL_LLM
  → LLM extraction → build_canonical
  → CANONICAL GUARD (contour 2)  CanonicalPIIInspector.inspect(payload)
       escalation: identity/contact/government/medical_id @ persistence → REDACT
       sanitize_canonical_payload(...)  ← per-category, REDACT actions only
  → sanitized canonical ──┬─ canonical.json  (S3)  :199
                          ├─ structured.md   (S3)  :203
                          └─ event data      :236
  → pii_result.json (S3, uploaded BEFORE publish) · frontmatter `pii:` · event data["pii"]
```

**Key mechanisms.** Detection and policy are separate contracts, so detectors change without policy
edits and vice versa (STRUCTURE §5, IMPL_ARCH §2/§17). Raw values exist only in-process and are
structurally incapable of leaking. Risk and action are **policy configuration**, not detection
output (IMPL_ARCH §12), so escalation for the persistence destination is a data change, not a code
change — which is exactly why Phase 14 costs a version bump and not a refactor.

**Invariants (locked — all M4 invariants still bind, plus the M5 additions):**

- **PII presence alone never blocks.** A medical document is *expected* to carry patient identity;
  `PII detected → reject` is explicitly rejected (ORDER §2, IMPL_ARCH §2). `BLOCK` is reserved for
  `SECRET` and fail-closed conditions; `REVIEW` for unexpected high-risk combinations.
- **No raw PII value crosses a boundary.** `PIIFinding.value` is `Field(exclude=True)`;
  `PIIFindingSummary` / `PIIAuditRecord` / `PIIScanResult` have no value field at all. Logs, audit,
  events, artifacts and frontmatter carry `masked_value` only (IMPL_ARCH §6, §19, §22, §26).
- **`value_fingerprint` is a salted HMAC-SHA256, never a plain hash.** Low-entropy identifiers
  (СНИЛС = 9 digits + checksum, полис ОМС = 16 digits, дата рождения) are brute-forceable in
  seconds. The secret comes from settings, is never hard-coded, never defaults, and the fingerprint
  is never logged. **Supplied as of M5 Phase 8** (`settings.pii_fingerprint_secret` /
  `PII_FINGERPRINT_SECRET`, empty by default and rejected by every consumer), and still unused in
  production because nothing detects until Phase 9.
- **The gate is a document-level capability, not a schema-level one.** `app/pii/` must not import
  `app/classification/` and must not import `packages.canonical` models. Document type crosses into
  policy as a plain `str`.
- **Originals are immutable.** `marker.md` and the upload are never rewritten. Redaction produces a
  *new* artifact string; replacements are applied right-to-left so earlier offsets stay valid.
- **The current LLM provider is trusted, explicitly and by name.** `ai_base_url` is
  `https://foundation-models.api.cloud.ru/v1` (`app/config/settings.py:27`) — an external vendor,
  but the only provider available. `PIIDestination.INTERNAL_LLM` is the default, so
  pre-extraction redaction is dormant until an external/offshore provider is configured. Phase 15
  makes that a setting rather than a constant.
- **Fail closed on gate failure.** If the gate cannot produce a decision, `PIIDecisionError` is
  raised and the pipeline must not proceed to extraction **or to persistence**. M4 locked the
  exception; M5 wires the halt.
- **Remediation is per-category, not per-decision.** The document-level `PIIDecision` decides
  halt-vs-continue only. What gets masked is decided by `PIIDecisionResult.actions[category]` — see
  §4.12. Getting this wrong destroys `doctor_name` / `organization_name`, which `render_document`
  needs and IMPL_ARCH §3.1 explicitly excludes from patient PII.
- **Aggregation is per-leaf, never across leaves.** Two paths holding the same value are two
  separate findings. Merging them would let a remediation fix one path while the second keeps
  leaking — the exact failure mode ORDER §13.6 calls out.
- **M5 touches the pipeline and `packages/`.** M4 touched `app/pii/**` only; every cross-package
  edit M4 documented in §4.9 is executed in M5 (Phases 10, 11, 14).
- **PII Gate is one security control, not a compliance layer.** It does not make the platform
  GDPR/HIPAA/152-ФЗ compliant (IMPL_ARCH §37). Do not cite this plan as evidence of compliance.
- **Raw PII is internal-only.** The gate's output is a security artifact; it must not become
  user-facing through the normal document API (IMPL_ARCH §26).

---

## 1. Execution summary

| Phase | Milestone | Scope | Status |
|---|---|---|---|
| 1 | M4 | Domain contract (enums, `PIIFinding`/`PIIFindingSummary`/`PIIScanResult`/audit, exceptions) | [x] |
| 2 | M4 | Schemas (JSON Schema exports for scan result + finding summary) | [x] |
| 3 | M4 | Detector contract (`PIIDetector` protocol, per-kind stubs, aggregator/dedup) | [x] |
| 4 | M4 | Masking & redaction contract (mask table, fingerprint, `PIIRedactor`) | [x] |
| 5 | M4 | Policy + gate contract (`DEFAULT_POLICY`, `PolicyEngine`, `PIIGate.inspect`) | [x] |
| 6 | M4 | Canonical-output guard contract (post-extraction leak boundary) | [x] |
| 7 | M4 | Persistence, provenance, versioning contract (+ M5 hand-off touch lists) | [x] |
| 8 | M5 | HMAC secret in settings + `PIIPolicyContext` boundary validation | [x] |
| 9 | M5 | Pattern detector → aggregator → policy engine → `PIIGate.inspect` | [ ] |
| 10 | M5 | Persistence surface (`pii_result.json`, `MARKDOWN_KIND_PII`, `PIIMeta`, frontmatter) | [ ] |
| 11 | M5 | Contour 1 wiring — `inspect` after classification, artifact before publish | [ ] |
| 12 | M5 | Markdown redaction (`PIIRedactor.redact`) | [ ] |
| 13 | M5 | Marker-shape fixture + structured-field and secret detectors | [ ] |
| 14 | M5 | Canonical guard — escalation policy, per-category sanitizer, both dump points | [ ] |
| 15 | M5 | `EXTERNAL_LLM` destination + redaction on the extraction path | [ ] |
| 16 | M5 | NER detector (P1) | [ ] |
| 17 | M5 | `REVIEW` combination threshold (P1) | [ ] |

**M4 status: complete.** All seven phases `[x]`, committed as `ef412d2`. `uv run pytest` → 436
passed (174 baseline + 262 PII contract tests). `make lint` reports only 4 pre-existing
`packages/storage` errors, unrelated to this milestone and present before M4 began.

**M5 status: in progress — Phases 8–9 done, 10–17 pending.** `uv run pytest` → 546 passed
(436 baseline + 110 new). The gate now *works* in memory: `await gate.inspect(document, context)`
detects, deduplicates, evaluates policy and returns a verdict — the first vertical slice. It is
still not **in production**: nothing in `app/pipeline` calls it yet (Phase 11), nothing is
persisted (Phase 10), and the two detector stubs in the chain still raise.

**M5 is complete when** Phases 8–17 are `[x]`, the full ai-worker suite is green on the 436-test
baseline, `packages/storage` is green, and — the criterion that actually distinguishes M5 from M4 —
**the two real leaks from `.dev/flow_upload_test/` produce a clean `canonical.json`, a clean
`structured.md`, and a clean event `data`**, asserted in three separate tests, one per dump point.
A green suite that does not include that assertion does not count as M5 done.

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

## 3. Phases 8–17

Ten phases, sequenced per IMPL_ARCH §45's 19-step order. The three **vertical slices** are marked
**VS#1/#2/#3**; they are the phases that turn a contract into a working control, and each is a
plausible stopping point if the milestone needs to ship partially. Phases 8 and 9 are `[x]` and
their status is recorded in place below, M4-style; the remaining eight are `[ ]`.

### Phase 8 — HMAC secret + policy context boundary [x]

`Settings.pii_fingerprint_secret` (env `PII_FINGERPRINT_SECRET`) with **no usable default**;
`app/pii/detectors.py` gains a settings-driven factory that raises `InvalidPIIInputError` on an
empty secret rather than degrading to a plain hash. Add `PIIPolicyContext` boundary validation —
`organization_id` non-empty, `destination` resolved from settings — plus the `organization_id`
source (ORDER §13.6: `settings.s3_tenant_id`, because neither `ProcessingContext` nor any event
contract carries a tenant, and cross-package event changes are out of M5). Tests: secret
required, empty secret fails closed, fingerprint differs under two secrets, context validation.
Deps: none — first because nothing can compute a fingerprint without it (§45.01–02).
**Accept:** `hash_pii_value` is unreachable with a missing or empty secret, proven by a test that
constructs the detector chain with no setting and expects the raise.

#### Phase 8 Implementation Status

**Changes.**

```text
apps/ai-worker/app/config/settings.py     pii_fingerprint_secret (env PII_FINGERPRINT_SECRET)
apps/ai-worker/app/pii/detectors.py       PII_FINGERPRINT_SECRET_ENV,
                                          PIIDetectorBase.__init__(fingerprint_secret=),
                                          PIIDetectorBase.fingerprint, build_detector_chain
apps/ai-worker/app/pii/policy.py          PIIPolicyContext._require_organization,
                                          DEFAULT_DESTINATION, build_policy_context
apps/ai-worker/app/pii/masking.py         hash_pii_value now rejects a whitespace-only secret
apps/ai-worker/app/pii/__init__.py        +4 exports (68 total)
.env.example                              documents PII_FINGERPRINT_SECRET for operators
apps/ai-worker/tests/support/pii_imports.py   allowlist += type-only Settings
apps/ai-worker/tests/unit/pii/test_detectors.py      allowlist test generalized (1 test)
apps/ai-worker/tests/unit/pii/test_policy_gate.py    allowlist test renamed + widened (1 test)
apps/ai-worker/tests/unit/pii/test_settings_boundary.py  30 tests
```

- **Two choke points, not one.** `build_detector_chain(settings)` validates at **construction**,
  so a misconfigured worker fails at start-up rather than emitting unkeyed fingerprints at 3am;
  `PIIDetectorBase.fingerprint()` validates again **per call**, so a detector built directly (a
  test, a future tool, an ad-hoc script) still cannot produce a finding. The plan asked for the
  first; the second is what makes "no key, no finding" a property of the type rather than of the
  pipeline's wiring.
- **Deviation — the factory takes `Settings`, not a bare secret string**, which required widening
  the type-only import allowlist to three symbols. Taken because the accept criterion is phrased
  as "constructs the detector chain **with no setting**", because `organization_id`'s source
  (`settings.s3_tenant_id`, ORDER §13.6) is only pinned if something inside `app/pii` names it,
  and because a bare `str` parameter would have pushed both wirings into the pipeline. The
  import is **type-only**: a runtime `app.config` import would make the security control
  unimportable without an environment and would pull `messaging.topology` in transitively
  (`settings.py:5`). Proven in a subprocess with `app.config` and `messaging` blocked, mirroring
  the M4 pipeline guard.
- **Deviation — `pii_fingerprint_secret` defaults to `""`, not to a required field.** A required
  field would fail `settings = Settings()` at import time (`settings.py:88`) and take the whole
  worker — and all 465 tests — down with it. "No usable default" is therefore delivered as *an
  empty default that is loudly unusable*: the field holds no secret, and every consumer rejects
  it. The alternative (a required field plus a separate dev/test settings object) trades a real
  fail-closed property for a boot-order one.
- **Deviation — the secret is instance state on the base class, with an empty default.** Required
  by the wording but wrong for `CompositePIIDetector`, which contributes no category and
  fingerprints nothing; requiring a key there would assert a guarantee the container cannot keep.
  So the base takes `fingerprint_secret=""` (no key, and `fingerprint()` fails closed), the
  factory passes the real one to each member, and the composite accepts and ignores it. The
  secret is private, absent from `repr`, and there is a test that no public attribute exposes it.
- **Chain order is `StructuredField` → `Pattern` → `Secret`,** not declaration order. Aggregation
  breaks a confidence tie in favour of the first detector in the chain, so the *stronger* signal
  (a value behind a known label, per its own M4 docstring) must come first or a tie resolves to
  the weaker form. `Secret` last for visibility, not for effect: order cannot soften a `BLOCK`.
  Pinned by a test, because Phase 9's confidence constants are what make this moot and Phase 16
  will append to this tuple.
- **Deviation — `hash_pii_value` (an M4 module, 37 tests) now rejects whitespace-only secrets**,
  not just empty ones. A three-candidate key is an unkeyed digest wearing a smaller disguise, and
  the check belongs at the one function that computes the digest. No M4 assertion changed: the
  existing test covers `""`, and the secrets used elsewhere in that module are real strings.
- **Deviation — `organization_id` is validated on the model, not in the factory**, so a directly
  constructed context cannot bypass it. The value is stripped and blank is rejected with
  `PIIPolicyError` — a domain error a caller can catch, rather than a `min_length` constraint
  that would surface as a `ValidationError` about a field the caller never named. Pydantic
  propagates the non-`ValueError` out of the validator unwrapped, matching the existing
  `PIIPolicy._require_full_coverage`.
- **`DEFAULT_DESTINATION = PIIDestination.INTERNAL_LLM` added as a named constant.** Phase 8 must
  not add the LLM-destination setting — §4.9 assigns that to Phase 15 — but the value still needs
  one home, so Phase 15's change is a single line plus a settings read rather than a hunt through
  call sites. The docstring names the phase that replaces it, and a test asserts it still does.
- **Deviation — `.env.example` gained the variable.** Not in §4.9's touch list, but a setting no
  operator can discover is a setting that stays unset, and "unset" now means the worker refuses to
  start its PII gate. The comment carries the `secrets.token_urlsafe(32)` recipe and the "treat it
  as config, not ephemeral env" note from §7 R5.
- **Neither version constant moved.** `DETECTOR_VERSION` stays `1.0.0` and `PII_POLICY_VERSION`
  stays `1.0.0`: the roadmap in §7 reserves `1.1.0` for Phase 9's additive `detect_text` and
  `2.0.0` for Phase 14's decision change, and Phase 8 changes no decision and produces no finding.
  The argument for leaving the detector version alone: it stamps *findings*, and there are none.
  Bumping here would have pushed the locked roadmap's NER step to `1.3.0`.
- **Verification recap:** `uv run pytest tests/unit/pii` → 292 passed (262 M4 + 30 Phase 8);
  `uv run pytest` → 466 passed; `uvx ruff check app/pii app/config tests/unit/pii tests/support`
  and `ruff format --check` on the touched files → clean. Root `make lint` still reports only the
  4 pre-existing `packages/storage` errors; `packages/storage` suite 15 passed. Still uncommitted.
- **Next step:** Phase 9 (Pattern detector → aggregator → policy → gate) — the first vertical
  slice, and the first phase where the gate returns a verdict instead of raising.

### Phase 9 — Pattern detector → aggregator → policy → gate [x] · **VS#1**

`detect_text(text) -> list[PIIFinding]` added to the `PIIDetector` protocol; `detect(NormalizedDocument)`
demoted to a wrapper that calls it on `document.raw_text` and aggregates once
(`DETECTOR_VERSION` 1.0.0→**1.1.0**, additive). `PatternPIIDetector` implemented — Cyrillic ФИО
(including declined forms, §7 gotcha G1), СНИЛС, полис ОМС, phone, email, дата рождения, талон.
`PIIAggregator.aggregate` dedups on `(category, value_fingerprint)` and is **only ever called on
one leaf's findings**. `PolicyEngine.evaluate` implements §4.4. `PIIGate.inspect` composes
detect → aggregate → policy → project into `PIIScanResult`. `CompositePIIDetector` fans out.
Tests: per-category patterns, declined-name regression, dedup-within-a-leaf, policy table row per
category, decision precedence, boundary-safety of the projected result.
Deps: Phase 8. (§45.03–06)
**Accept:** `await gate.inspect(document, context)` returns a `PIIScanResult` for the
`synthetic-consultation-01` fixture with the manifest's `expected_decision`/`expected_risk_level`,
and the result dumps with no `value` key at any depth.

#### Phase 9 Implementation Status

**Changes.**

```text
apps/ai-worker/app/pii/detectors.py  PIIDetector.detect_text in the protocol, _Pattern.group,
                                      PatternPIIDetector (11 rules), _MD_DECOR, case-folded
                                      contour's after-label name rule, CompositePIIDetector
                                      fan-out + empty-chain guard, DETECTOR_VERSION 1.1.0
apps/ai-worker/app/pii/aggregation.py  DefaultPIIAggregator
apps/ai-worker/app/pii/policy.py        RISK_ORDER + DefaultPolicyEngine
apps/ai-worker/app/pii/gate.py          PolicyContextBuilder + DefaultPIIGate
apps/ai-worker/app/pii/__init__.py      +5 exports (73 total)
apps/ai-worker/tests/unit/pii/test_detectors_behaviour.py        31 tests
apps/ai-worker/tests/unit/pii/test_aggregation_behaviour.py     16 tests
apps/ai-worker/tests/unit/pii/test_policy_behaviour.py          21 tests
apps/ai-worker/tests/unit/pii/test_gate_behaviour.py            11 tests
apps/ai-worker/tests/unit/pii/test_detectors.py                 M4 contract guards updated
apps/ai-worker/tests/unit/pii/test_policy_gate.py               M4 contract guards updated
apps/ai-worker/tests/unit/pii/test_persistence_contract.py      detector version 1.1.0
```

- **`detect_text` is the real API and `detect` is a wrapper.** The plan's wording demotes
  `detect(NormalizedDocument)` to "call it on `document.raw_text`", and that is what it does —
  but the gate passes the text through anyway rather than taking the document, because the gate
  aggregates **per leaf** and Phase 10 needs a gate that can scan one string at a time. The
  document-shaped method stays because M4's contract named it and the interface guard tests it.
- **Deviation — four bare-digit rules were deleted, and the accept criterion is why one came back.**
  The fixture's own `Номер карты: 0000001234` was being claimed simultaneously as a `national_id`,
  a `ticket_number` and (separately) a `medical_record_number` — three guesses, one of them right.
  A pattern cannot distinguish a passport, an INN, a card and a ticket by length. Surviving:
  СНИЛС (11 digits **plus** a check-digit algorithm, which is why its confidence is 0.9 and not
  0.7), полис ОМС (16 digits, and the 12-digit overlap with a passport is a *disjoint* pair of
  boundaries so the first rule wins), passport (**with** separators — a form, not a length), and
  `medical_record_number.labelled_card`, which requires the label. The last one is an explicit
  deviation from the plan's seven-rule list: the manifest's `expected_risk_level` of `high` for
  this fixture is only reproducible if a `HIGH` category is found, and the labelled card is the
  one high-risk value the document actually contains. A label is the only evidence that turns a
  length into an identity; Phase 13's structured detector supersedes this rule with more of the
  same evidence. Left as a known false positive: the `malicious/synthetic-injection-01`
  fixture's 28-digit API key, which this layer claims as a `ticket_number` and Phase 13's secret
  detector will claim as a credential — the one case where a later detector should *outrank* an
  earlier one on the same span, which the chain order and the tie-break do not yet express.
- **Deviation — the case-folded contour got its own name rule, and it is the phase's real content.**
  §7's gotcha G1 anticipated a *declined* form («к Шадеркину Д.С.»); the actual failure was upstream
  of declension. `NormalizedDocument.raw_text` is `str.casefold()`ed, so «Смирнова Ольга Ивановна»
  reaches the detector as «смирнова ольга ивановна» and a title-case rule cannot fire — on the
  fixture in the repository, and on every real document. Two rules now exist:
  `person_name.three_token` (title-case, for unfolded input) and `person_name.after_label`, which
  anchors on a name-introducing word and captures the three tokens **after** it, so the label never
  lands in the masked value. The folded rule is a recall-over-precision trade and it is documented
  as one: «сдан анализ крови» matches. That false positive is a `MEDIUM` reviewable risk and M6's
  calibration problem; the alternative is a name detector that never fires in production.
- **`_MD_DECOR` exists because emphasis markers are not cosmetic.** `raw_text` keeps markdown, so
  the fixture's real text is `**пациент:** смирнова ольга ивановна`. A rule allowing only a colon
  and a space after the label matched the file on disk and found **nothing** in the document the
  pipeline actually hands the gate — the same blind spot as case-folding, one layer down, and found
  only because the acceptance test runs the real normalizer over the real fixture. Without it the
  phase would have shipped "green" against a rule that never fires.
- **`_LONG_DIGIT_RUN` is 12 digits, matching the real marker** (22) with room below it, not 9. At
  9 the rule claimed the fixture's 10-digit card as a `ticket_number`; at 12 the 10-digit run
  claims nothing and the 16-digit policy number still claims both itself and the overlapping
  ticket-shaped span, with the specific rule winning.
- **`RISK_ORDER` is exported, because `max()` on a `str` enum is wrong.** `PIIRiskLevel` is a
  `str` enum, so `max(findings, key=lambda f: f.risk_level)` orders `"low" > "high"` and returns
  the *lowest* risk in the document. The engine takes the maximum by explicit rank instead, and
  `RISK_ORDER` is public so a caller aggregating its own results cannot reintroduce the bug.
- **`PolicyContextBuilder` is a parameter of `DefaultPIIGate`, not a lookup inside it.** The gate
  needs `organization_id` (from settings), `destination` (Phase 15) and `redaction_available` (the
  pipeline, which owns the redactor) — three sources, two of them outside `app/pii`. A builder
  passed in at construction is the only way to keep the gate a pure function of its inputs; the
  alternative (policy inputs in `ProcessingContext.attributes`, or `document.metadata`) would make
  the verdict depend on ambient state that no type describes, and `metadata` is exactly where a raw
  value could reappear. The builder is required, not defaulted: `None` raises.
- **Redaction-unavailable escalation is what the acceptance test actually exercises.** Phase 9 has
  no redactor, so at `EXTERNAL_LLM` the fixture's `REVIEW` is the *escalation* path, not a plain
  verdict. The same document at `INTERNAL_LLM` returns `ALLOW` with **identical findings** — a test
  asserts the destination changes the verdict and not the evidence, because a gate that dropped
  evidence at the permissive destination would be a gate with a memory problem.
- **Boundary safety is asserted by walking the serialized JSON**, not by reading attributes: a
  recursive `_walk_keys` over `result.model_dump_json()` fails on any `value` or `value_fingerprint`
  key at any depth. Reading attributes would not catch a value nested inside a future container.
- **No pipeline wiring, and none is claimed.** `app/pipeline` still does not call the gate
  (Phase 11), nothing is persisted (Phase 10), and `build_detector_chain` still returns the
  `StructuredField`/`Secret` stubs, which raise — so a chain-built gate raises on the first
  document. The acceptance test therefore composes `PatternPIIDetector` directly, which is the
  honest reading of a phase that says "pattern detector → …".
- **Verification recap:** `uv run pytest tests/unit/pii` → 372 passed (292 + 80); `uv run pytest` →
  546 passed; `uvx ruff check`/`format --check` on `app/pii` and `tests/unit/pii` → clean. Root
  `make lint` still reports only the 4 pre-existing `packages/storage` errors; `packages/storage`
  15 passed. Still uncommitted.
- **Next step:** Phase 10 (persistence surface) — `PIIMeta`, `build_pii_artifact`, the storage
  keys — which turns this in-memory verdict into something an operator can read after the fact.

### Phase 10 — Persistence surface [ ]

`packages/storage`: `"pii": "pii_result.json"` in `MARKDOWN_ARTIFACTS` + `MARKDOWN_KIND_PII` in
`storage/__init__.py` (`__all__`, alphabetical) + `tests/test_keys.py`. `apps/ai-worker`:
`app/artifacts/{models,__init__}.py` re-export, `app/pii/artifact.py` gains `build_pii_artifact(...)`
mirroring `app/classification/artifact.py:18-50`. `packages/canonical`: `PIIMeta` +
`FrontmatterMeta.pii` in `canonical/metadata.py`, re-exported from `canonical/__init__.py`;
`app/canonical/rendering.py:36-72` gains `pii=` on `build_frontmatter_meta`. No new event, no DB
table, no migration, **no account-api change** (PII metadata is internal, IMPL_ARCH §26).
Tests: `test_keys.py` known-kinds; `PIIMeta` rejects unknown keys; `to_dict()` emits the §4.7
block; `build_pii_artifact` writes `PII_SCAN_RESULT_SCHEMA`-conformant JSON.
Deps: Phase 9. (§45.07–09)
**Accept:** `build_pii_artifact` output validates against `PII_SCAN_RESULT_SCHEMA` structurally and
contains no raw value; `build_frontmatter_meta(pii=...)` round-trips through `render_frontmatter`.

### Phase 11 — Contour 1 wiring [ ]

`PIIGate` constructed in `DocumentPipeline.__init__` (`:60-77`); `inspect` called after
classification and **before** extraction (`:147`). `ALLOW`/`ALLOW_WITH_WARNING` continue;
`REVIEW` → halt with `processing_status='needs_review'`; `BLOCK` → processing failure. The
`pii_result.json` artifact is uploaded **before** the event is published — the M2 Phase 4 ordering
invariant, and the reason account-api can never see an event whose artifact is missing. Frontmatter
`pii:` block and `event data["pii"]` populated. Tests: `test_pipeline.py` covers each decision's
outcome, the artifact-before-publish ordering, and that `BLOCK` never reaches extraction.
Deps: Phases 9, 10. (§45.10–11)
**Accept:** with a `SECRET` fixture, `handle_structuring` raises the failure path and **zero**
artifacts for the analysis stage are published; with a clean fixture the pipeline is byte-identical
to the pre-M5 output apart from the new `pii` keys.

### Phase 12 — Markdown redaction [ ]

`PIIRedactor.redact(markdown, findings)` implemented over `(start, end)` spans, applied
**right-to-left** so earlier offsets stay valid, replacing each with `placeholder_for(category)`.
`redaction_available` is set `True` in the constructed context. The redacted markdown is a
**new** artifact string; `marker.md` and the upload are never rewritten. Tests: span replacement
correctness, right-to-left offset stability, non-overlapping and adjacent spans, no-op on empty
findings, `SECRET` placeholder reveals nothing, idempotence.
Deps: Phase 9. (§45.12)
**Accept:** redacting the `synthetic-consultation-01` fixture removes every
`expected_categories` value from the output while leaving all other characters byte-identical.

### Phase 13 — Marker-shape fixture + structured & secret detectors [ ]

`StructuredFieldPIIDetector` (labelled fields: `ФИО:`, `СНИЛС:`, `Полис №:`, `Дата рождения:`,
`Номер талона:`) and `SecretPIIDetector` (credentials only — the sole source of `BLOCK`). One
dataset entry reproducing the **shape** of the real `2b8fdd0d` marker, synthetically instantiated
(ORDER §13.3 forbids committing real patient data — see §7 decision 9), with `expected_*` now
**confirmed against a real detector** rather than declared, which is the whole point of the entry.
Tests: the manifest's `expected_*` are asserted against actual `PIIGate` output, so a detector
regression fails the manifest test.
Deps: Phase 9. (§45.13–14)
**Accept:** every `expected_*` in `manifest.json` is machine-verified; the declined-name marker
shape yields `person_name` + `ticket_number` and nothing else.

### Phase 14 — Canonical guard [ ] · **VS#2**

`CanonicalPIIInspector.inspect` implemented: `walk_string_leaves(payload)` → `detect_text` per leaf
→ `aggregate` **per leaf** → violations carrying `field_path`. **Escalation policy** (§4.11):
identity / contact / government / medical_id at `stage=canonical, destination=persistence` →
`REDACT`, bumping `PII_POLICY_VERSION` 1.0.0→**2.0.0**. **Per-category sanitizer** (§4.12):
`sanitize_canonical_payload(payload, violations, actions)` masks only violations whose
`actions[category] == REDACT`. Guard runs after `build_canonical` (`:164`); the **sanitized object
replaces `canonical` before all three consumers** — S3 `canonical.json` (`:199`), `render_document`
(`:203`), event `data` (`:236`). Sanitization is a rebuild, not an in-place mutation: dump →
sanitize by path → `type(canonical).model_validate(...)`; a re-validation failure **fails closed**
rather than persisting the unsanitized object. `BLOCK`/`REVIEW` halts before any persistence.
Tests: both real leaks as fixtures, asserted clean at **all three** dump points separately; the
clinical facts in the note (`М, 39 лет`) survive; the same value at two paths is masked at both;
`doctor_name` survives a `person_name` redaction; policy version is 2.0.0; fail-closed on
re-validation failure.
Deps: Phases 9, 10, 11. (§45.15–16)
**Accept:** `2b8fdd0d` and `fbbcb675` payloads produce a `canonical.json` and `structured.md` with
no patient name, and an event `data` with no patient name — three tests, not one.

### Phase 15 — `EXTERNAL_LLM` destination + redaction on the extraction path [ ] · **VS#3**

`destination` for the extraction step resolved from settings (trusted vs external) instead of
hard-coded `INTERNAL_LLM` (§7 decision 12). When `EXTERNAL_LLM` **and** `redaction_available`, the
extraction call receives redacted text; the canonical guard still sees the original so nothing is
lost from the internal record. The OCR call at `pipeline.py:92` is recorded as a **documented
trusted boundary** — the gate consumes `marker.md`, which OCR *produces*, so this design cannot gate
it (§7 risk R1). Tests: trusted provider → original text reaches the extraction prompt; external
provider → redacted text reaches it and the verdict is `ALLOW_WITH_WARNING`; redaction unavailable
+ external → escalation to `REVIEW` per §4.11.
Deps: Phases 11, 12, 14. (§45.17)
**Accept:** flipping the provider setting changes the text the extraction call sees, and the test
asserts the redacted text contains no `expected_categories` value.

### Phase 16 — NER detector [ ] · P1

`PIISource.NER` populated by a detector behind the existing protocol, added **after** the
deterministic detectors so it can only widen coverage, never override a `BLOCK`. A graceful no-op
when no model is configured — M6 may decide to leave it off entirely. Tests: protocol conformance,
it composes through `CompositePIIDetector`, absence of a model changes nothing.
Deps: Phase 9. (§45.18)
**Accept:** the NER detector is never the sole control — a `SECRET` detected only by NER still
yields `BLOCK`, and a document NER finds nothing in still passes.

### Phase 17 — `REVIEW` combination threshold [ ] · P1

The §13.1 "unknown limitation" closed: unexpected high-risk **combinations** (e.g. ≥2 distinct HIGH
categories, or identity + government ID in one free-text leaf) escalate to `REVIEW` instead of
`ALLOW`. Policy data, not code (IMPL_ARCH §17). `PII_POLICY_VERSION` 2.0.0→**2.1.0**. `REVIEW`
still never auto-redacts (§7 open decision, M4). Tests: the combination table, both sides of every
threshold, and that a single HIGH category alone stays `ALLOW`.
Deps: Phase 14. (§45.19)
**Accept:** a leaf with `SNILS` + `INSURANCE_NUMBER` + `PERSON_NAME` is `REVIEW`; the same leaf with
only `PERSON_NAME` is `ALLOW`.

---

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

### 4.7 Persistence shape (locked — implemented in M5 Phase 10)

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
  "detector_version": "1.1.0",
  "policy_version": "2.0.0",
  "reasons": ["expected_medical_identity"],
  "warnings": []
}
```

The block shape matches `ClassificationMeta` (`packages/canonical/canonical/metadata.py:55-74`):
same `extra="forbid"`, `reasons`/`warnings` lists, `*_version` string — `PIIMeta` will be its
sibling in the same file, and `FrontmatterMeta.pii` its optional field (`:93` has
`classification: ClassificationMeta | None = None`). Full findings (masked) live only in
`pii_result.json`, mirroring `classification_result.json`. `categories` is a convenience list for
UI/metrics; `category_counts` is authoritative. The versions above are the end-of-M5 values from
the §7 roadmap; Phase 10 emits whatever is current at the time, and a test asserts the block
carries the live constants rather than a copy.

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
The M5 roadmap that moves both constants — `1.0.0 → 1.1.0 → 1.2.0` and `1.0.0 → 2.0.0 → 2.1.0` —
is in §7 (Versioning policy).

### 4.9 M5 touch lists (documented in M4, executed in M5 — Phases 10, 11, 14)

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

**Phase 14 additionally, in `apps/ai-worker/app/pipeline/pipeline.py`:** the guard call sits
immediately after `build_canonical` (`:164`), and its output **replaces** the `canonical`
binding so all three consumers — `canonical.json` (`:199`), `render_document` (`:203`) and event
`data` (`:236`) — read the sanitized object. Sanitizing a local copy, or moving the guard after
the dump, leaves at least one surface leaking; this is the single most important ordering
constraint in M5.

**Phase 8 additionally, in `apps/ai-worker/app/config/settings.py`:** `pii_fingerprint_secret`
(Phase 8) and the LLM destination (Phase 15). No other settings change.

`apps/account-api`: if account-api ever reads the artifact, its hard-coded kind allow-list
(`app/services/storage.py:80-85`) must gain the new kind — it currently omits even
`classification`, so this is a pre-existing gap, not a PII regression. PII metadata is internal
(IMPL_ARCH §26), so **no API surface and no event are added** in M5.

### 4.10 Fixture manifest shape (M4 seeded it, M5 Phase 13 confirms it)

`tests/fixtures/pii/manifest.json` mirrors the classification manifest (loader shape in
`app/classification/fixtures.py:52-67`): top-level `version` + `notes` + `fixtures[]` where each
entry has `file`, `source` (`real`|`synthetic`), `expected_categories` (list),
`expected_decision`, `expected_risk_level`, and optionally `contains_secret` (bool).
Directories per IMPL_ARCH Phase 10: `clean/ patient/ laboratory/ appointment/ prescription/ mixed/
malicious/`. M4 seeds `clean/`, `patient/` and `malicious/` synthetically to prove the shape.

**Correction to the M4 text here:** this section originally said the M5 sweep would consist of
*copies of `.dev/flow_upload_test/`*. It does not, and must not — ORDER §13.3 forbids committing
real patient data, because duplicating the leak into the repo creates the second copy this
milestone exists to prevent. M5 Phase 13 adds a **synthetic** file reproducing the real marker's
label/value shape, and its `expected_*` are confirmed against a real detector for the first
time. See §7 decision 9.


### 4.11 Persistence escalation policy (new in M5, Phase 14)

ORDER §13.4's finding: the §4.4 default table makes identity / contact / government / medical_id
`ALLOW` at every destination, so a canonical document persists a patient's name — which is exactly
the observed leak. The M4 table is correct for the *source* contour (IMPL_ARCH §2: PII presence
never blocks) and wrong for *persistence*, where the question is not "is this document sensitive"
but "does this artifact need to carry the identifier".

```text
override: stage=canonical AND destination=persistence
  identity     PERSON_NAME DATE_OF_BIRTH
  contact      EMAIL PHONE ADDRESS
  government   PASSPORT NATIONAL_ID INSURANCE_NUMBER SNILS INN
  medical id   PATIENT_ID MEDICAL_RECORD_NUMBER LAB_ORDER_ID ENCOUNTER_ID TICKET_NUMBER
    -> action REDACT (was ALLOW)

unchanged at persistence:
  SECRET                    -> BLOCK   (unchanged, and the only BLOCK source)
  AGE GENDER NATIONALITY    -> ALLOW   (clinical facts, ORDER §13.7 - masking them destroys the note)
  DOCTOR_* ORGANIZATION_*   -> ALLOW   (not patient PII, IMPL_ARCH §3.1)
```

`REDACT` with a working sanitizer resolves to `ALLOW_WITH_WARNING` + `PIIRemediation.SANITIZE`; the
document is saved with a mask and the run continues. `REDACT` with `redaction_available=False`
escalates to `REVIEW` (§4.4) — which is why Phase 8 must fail closed on a missing secret rather than
silently producing unmaskable findings. Precedence stays `block > review > allow_with_warning >
allow`, so a single `SECRET` still fails the document even when everything else is redacted.

This is **policy data, not code** (IMPL_ARCH §17): it is a row set in `DEFAULT_POLICY`, versioned
by `PII_POLICY_VERSION` 1.0.0 -> 2.0.0 (§7), and reversible without touching the guard.

### 4.12 Per-category remediation (new in M5, Phase 14)

`PIIDecision` decides **halt vs continue** for the document. It does not decide what to mask.
Masking is driven by `PIIDecisionResult.actions[category]`, which exists for exactly this purpose
and is dropped from the persisted `PIIScanResult`.

```text
decision (document level)  --> halt | continue        <- PIIGate, DECISION_REMEDIATION
actions[category]          --> which leaves to mask   <- sanitize_canonical_payload
```

Mask a canonical leaf iff `actions[violation.category] == PIIAction.REDACT`. Consequences that
matter: a `PERSON_NAME` redaction leaves `DOCTOR_NAME` and `ORGANIZATION_NAME` intact, so
`render_document` and the future `AppointmentCanonical` keep working; and an `ALLOW`-but-recorded
category stays legible to a human reviewing the canonical. Masking on the document-level decision
instead would blank every finding in a run that happened to contain one redaction.

`PIIDecisionResult` is in-process only and carries no values, so passing `actions` to the sanitizer
does not widen the boundary — the sanitizer needs the *category*, and already holds the value it is
replacing, in the same process, on the same string.

---

## 5. Tests

**Approach, in two layers.** M4 asserted **contracts** — importability, enum values, field shapes,
schema keys, protocol conformance on stubs, policy table values, mask rules, boundary assertions.
M5 asserts **behaviour and outcomes** — that a pattern fires, that a name is masked in the right
path, that a document with a secret halts, and that the three persistence surfaces are clean. The M4
contract tests are kept, not replaced: they are what makes the refactor safe.

The three assertions that carry the security value (M4, still enforced):

```text
1. "value" not in PIIFindingSummary.model_fields / PIIScanResult.model_fields
   and "value" not in PIIFinding.model_dump()          (exclusion is structural)
2. no "value" property in PII_FINDING_SCHEMA            (schema-level proof)
3. no "value"/"value_fingerprint" in PIIAuditRecord.model_fields
```

Plus two import guards: no `s3`/`rabbit`/`storage` import in `app/pii/*`, and no
`app.classification` domain import in `app/pii/*` — the architectural boundary from ORDER §8. M5
adds the third guard this milestone makes possible: **no `packages.canonical` import in
`app/pii/*`**, asserted so the guard keeps operating on plain dicts and stays reusable.

**The M5 acceptance test (the one that matters).** For each of the two real leak payloads, three
separate assertions, one per dump point:

| # | Surface | Assertion |
|---|---|---|
| 1 | S3 `canonical.json` body | no patient name, no ticket number |
| 2 | S3 `structured.md` body | no patient name, no ticket number |
| 3 | `DocumentAnalysisCompleted.data["canonical"]` | no patient name, no ticket number |

A single test that greps one serialized blob would pass while the other two surfaces still leak,
which is precisely how the current bug survived: the leak is in `fields.note`, and `fields.note`
reaches three consumers from one object. Three tests, or the milestone is not done.

Supporting M5 tests: per-leaf aggregation (same value, two paths, both masked), per-category
remediation (`doctor_name` survives a `person_name` redaction), clinical-fact preservation
(`М, 39 лет` survives), declined-Cyrillic-name regression, fail-closed on an empty HMAC secret,
fail-closed on re-validation failure, artifact-uploaded-before-publish ordering, every decision's
pipeline outcome, `EXTERNAL_LLM` redaction, and manifest `expected_*` verified against real
detector output.

**Files (new in M5).** `tests/unit/pii/{test_detectors_behaviour,test_aggregation_behaviour,test_policy_behaviour,test_redactor_behaviour,test_guard_behaviour,test_artifact,test_settings_boundary}.py`;
`tests/unit/pipeline/test_pipeline_pii.py`; extended `tests/fixtures/pii/manifest.json` + the
`laboratory/`, `appointment/`, `prescription/`, `mixed/` directories (declared in
`PII_FIXTURE_DIRECTORIES` but not yet created); `tests/support/pii_fixtures.py` delegate once the
dataset grows past the trio. `packages/storage/tests/test_keys.py` extended in Phase 10.

**Commands:**

```bash
cd apps/ai-worker && uv run pytest tests/unit/pii -v          # focused
cd apps/ai-worker && uv run pytest                            # full: 436 baseline, must stay green
cd apps/ai-worker && uv run pytest tests/unit/pipeline -v      # contour wiring, Phases 11/14/15
uvx ruff check apps/ai-worker/app/pii apps/ai-worker/tests/unit/pii apps/ai-worker/app/pipeline
uvx ruff format --check apps/ai-worker/app/pii
uv run --project packages/storage pytest packages/storage     # required from Phase 10 on
make lint                                                      # uvx ruff check apps packages tests
```

**Acceptance smoke check (from `apps/ai-worker`):**

```bash
uv run python -c "from app.pii import PIICategory, PIIScanResult, PIIGate, DETECTOR_VERSION, PII_POLICY_VERSION; print(DETECTOR_VERSION, PII_POLICY_VERSION)"
```

Expected after Phase 14: `1.1.0 2.0.0`. M5 introduces **no** new runtime dependency (stdlib
`re`/`hmac`/`hashlib` + Pydantic only) and **no** migration.

---

## 6. Implementation order

M4 (all done, retained for history — see §2 for the per-phase record):

1. **Phase 1 — Domain contract** [x] — enums, models, exceptions. Everything else depends on it.
2. **Phase 2 — Schemas** [x] — derives from Phase 1, so the "no `value` in schema" proof lands early.
3. **Phase 3 — Detector contract** [x] — protocol + stubs + aggregator; do it early so the
   `PIIFinding` construction requirements (masked/fingerprint) get exercised by real consumers.
4. **Phase 4 — Masking & redaction** [x] — needs Phase 1 fields; independent of Phase 3 logic.
5. **Phase 5 — Policy + gate** [x] — the core contract; needs detectors and masking to be
   well-shaped, so it lands after them.
6. **Phase 6 — Canonical-output guard** [x] — needs the policy engine it reuses.
7. **Phase 7 — Persistence, provenance & versioning** [x] — last: it projects the frozen shapes.

M5 (pending — the numbering is IMPL_ARCH §45's 19-step sequence folded into phases):

8. **Phase 8 — HMAC secret + policy context boundary** [x] — first, because nothing can fingerprint
   without it and dedup depends on fingerprints (§45.01–02).
9. **Phase 9 — Pattern detector → aggregator → policy → gate** [x] — VS#1: the smallest end-to-end
   gate. Stopping point if the milestone ships partially (§45.03–06).
10. **Phase 10 — Persistence surface** [ ] — the artifact must exist before the pipeline can
    upload it (§45.07–09).
11. **Phase 11 — Contour 1 wiring** [ ] — turns VS#1 into a real control. Contour 1 works here
    (§45.10–11).
12. **Phase 12 — Markdown redaction** [ ] — needs the gate's findings; independent of the guard
    (§45.12).
13. **Phase 13 — Marker-shape fixture + structured & secret detectors** [ ] — `SECRET` detection is
    the only `BLOCK` source, so it must exist before the guard is trusted (§45.13–14).
14. **Phase 14 — Canonical guard** [ ] · VS#2 — the phase that closes the observed leak. After
    this, the milestone's purpose is met even if 15–17 slip (§45.15–16).
15. **Phase 15 — `EXTERNAL_LLM` destination + redaction** [ ] · VS#3 — dormant until a second
    provider exists; safe to defer without regressing anything (§45.17).
16. **Phase 16 — NER detector** [ ] · P1 — widens coverage, never overrides (§45.18).
17. **Phase 17 — `REVIEW` combination threshold** [ ] · P1 — policy data on top of Phase 14 (§45.19).

Phases 12 and 13 are independent of each other and can run in either order. Phase 16 is
independent of everything after 9. Each phase: implement → update status in all three places
(§1 table, §3 heading, §6 list) → pause for confirmation. Deviations labeled `Deviation:` in the
phase's Implementation Status block.

---

## 7. Notes & conventions

### Gotchas (verified)

- **G1 — the live leak is a *declined* Cyrillic name, and a naive pattern misses it.** The canonical
  text is `"...для пациента Шадеркина Дениса Сергеевича"` — genitive, mid-sentence, lowercase-initial
  words. A `Фамилия Имя Отчество` nominative pattern does not match it, and neither does a
  "capitalised word at start of string" heuristic. `PatternPIIDetector` must match capitalised
  three-word runs anywhere in the string, and Phase 9/13 carry a regression test on the exact string.
  This is the single most likely way a green Phase 9 still leaves the leak open.
- **The leak is live, not hypothetical.** Both `2b8fdd0d.../canonical.json` and
  `fbbcb675.../canonical.json` contain the patient's full name; the first also carries the ticket
  number. `2b8fdd0d` is already a permanent classification fixture
  (`tests/fixtures/classification/appointment/2b8fdd0d.md:16-25`), so the same real PII is already
  in the repo's test data — the PII dataset reuses **shapes**, and the name is instantiated
  synthetically (see decision 9).
- **`BaseCanonical.fields` is `Any`** (`packages/canonical/canonical/schemas/__init__.py:67-89`),
  and `GenericCanonical` is the current default model. There is no field list to guard — hence the
  free-form payload walk. Prompting alone cannot hold this line, which is precisely why
  `canonical.yaml:100` failed.
- **One canonical object feeds three consumers.** `canonical.json` (S3 `:199`), `structured.md`
  (`:203`) and event `data` (`:236`) are all derived from the same `canonical`. Sanitizing a
  *copy* sanitizes whichever copy that call site held; the fix has to replace the object, which is
  why Phase 14 rebuilds rather than mutates.
- **Nested PII also persists to PostgreSQL.** `DocumentAnalysisCompleted.data` is written verbatim
  into `document_extractions.data` (`apps/account-api/app/services/documents.py:536`), so an
  event-level `data["pii"]` block is how account-api learns the verdict without a new table — and
  why the event is a third leak surface the guard must reach.
- **`PIIFinding` is frozen but not hashable** (`metadata` is a `dict`, observed in M4 Phase 1). The
  aggregator dedups on the `(category, value_fingerprint)` tuple, not on the model.
- **`Field(exclude=True)` does not remove a field from `model_json_schema()`.** `exclude` is a
  serialization concern only. M4 derives `PII_FINDING_SCHEMA` from `PIIFindingSummary` and pins it
  with `test_schemas_never_derived_from_pii_finding`, so nobody re-derives it from the wrong model.
- **`GenericCanonical` is the default model and `BaseCanonical` is `extra="forbid"`, not frozen.**
  The Phase 14 round-trip (`model_dump(by_alias=True)` → sanitize → `model_validate`) depends on
  both: `extra="forbid"` means an unrecognized key after sanitization is a hard failure rather than
  a silent pass, and mutability is irrelevant because the plan rebuilds rather than mutates.
- **account-api's storage allow-list is already behind** — `app/services/storage.py:80-85` omits
  `MARKDOWN_KIND_CLASSIFICATION`, so account-api cannot read the classification artifact today.
  Pre-existing gap; M5 does **not** fix it, because PII metadata is internal (IMPL_ARCH §26).
- **Existing masking helpers are not reusable.** `apps/account-api/app/middleware/request_logging.py:387-566`
  has header/body maskers, but they are methods on a FastAPI middleware, match field names by
  *substring* (so `"name"` also matches `"schema_name"`/`"filename"`), and live in account-api
  where ai-worker cannot import them. `packages/observability` is declared by all six apps but is a
  0-byte stub. M4 therefore defined its own small, typed masker in `app/pii/masking.py`; extracting
  the middleware helpers to a shared module is a separate cleanup.
- **No feature flags exist** in `Settings` (only `prompts_dir`, `pdf_dpi`, `pdf_format`,
  `ai_model`). M5 adds two (§4.8): the fingerprint secret and the LLM destination. Neither may
  hard-code a default secret.
- **No mypy/pyright in the repo**; type errors surface as Pydantic/import failures. Existing
  convention from M1, not a new gap — `ruff` + Pydantic + import smoke checks are the gate.
- **Test subdirs have no `__init__.py`** (`tests/unit/classification/`), but `tests/support/__init__.py`
  exists. `tests/unit/pii/` is the exception and **does** have one: without a package marker
  pytest's prepend import mode makes same-named siblings collide ("import file mismatch") — observed
  during M4 Phase 1.
- **Fixture-manifest tests are strict.** `test_fixture_manifest.py:66-72` asserts the `.md` set on
  disk equals the manifest set, so the PII manifest must be complete in the same commit that adds
  a fixture file.
- **Ruff is repo-root only** (`pyproject.toml:29-37`, line-length 100, `select = ["E","F","I","UP","B","SIM"]`).
  `I` sorting matters: `__all__` lists and import blocks must stay alphabetical — and Phase 10 adds
  two `__all__` entries that must be placed correctly.

### Open decisions (defaults chosen)

- **1. Scope: IMPL_ARCH §45 full order, not ORDER §13.8's contour-2-only limit.** The two documents
  disagree. Chosen: full order — both contours, `PIIRedactor`, `EXTERNAL_LLM` redaction, and the
  `REVIEW` threshold. Rationale: §45 is the design spec's own conclusion and the only ordering whose
  dependencies are argued; §13.8 is a scoping note written while the leak was still open, and it
  predates the recognition that the canonical guard is *strictly harder* than the source contour
  (free-form `fields`, no schema, declined-name calibration). Consequence: M5 is ten phases, not
  six, and the source contour lands before the guard — so a partial shipment still leaves contour 1
  protecting the pipeline. **Reversible:** Phases 15–17 can be deferred without regressing anything.
- **2. Remediation is per-category (`actions[category] == REDACT`), not per-decision.** A
  document-level `ALLOW_WITH_WARNING` → "sanitize everything" rule would also mask `DOCTOR_NAME` and
  `ORGANIZATION_NAME`, which IMPL_ARCH §3.1 excludes from patient PII and which
  `render_document` / the future `AppointmentCanonical` need. `PIIDecisionResult.actions` exists
  precisely so M5 can act on a `REDACT` without re-deriving it from the decision. See §4.12.
- **3. Escalate to `REDACT` at `canonical`+`persistence`, not `BLOCK`.** ORDER §13.4 offered
  `REDACT`+sanitizer (A, chosen) or `BLOCK`+retry (B, rejected): under B, every legitimate note
  naming a patient would fail permanently. A note naming a patient is not an attack; it is the
  normal shape of free-form clinical text, and the clinical facts are explicitly not PII
  (ORDER §13.7). `BLOCK` stays reserved for `SECRET` and fail-closed conditions.
- **4. `organization_id` ← `settings.s3_tenant_id`.** `PIIPolicyContext.organization_id` is required,
  but neither `ProcessingContext` nor any event contract carries a tenant (ORDER §13.6).
  `s3_tenant_id` is a placeholder that is always populated, so the field is real and auditable
  today; threading a real tenant through `packages/contracts` is a separate change with a schema
  version bump, explicitly out of M5. Flagged in the artifact as the tenant identity, not
  documented as authoritative.
- **5. `detect_text()` on the protocol, `detect()` as a wrapper.** The guard walks string leaves, so
  a protocol whose only entry point takes a `NormalizedDocument` is unusable by contour 2. Additive
  → `DETECTOR_VERSION` 1.1.0. The guard passes a leaf, not a document; it cannot pass a
  `NormalizedDocument` because it runs on a canonical payload, not the source.
- **6. Aggregation is per-leaf, never across leaves.** Two paths holding the same value must stay
  two findings (ORDER §13.6): merging them lets a remediation fix one path while the second keeps
  leaking. Cost: a name in a header and a name in `fields.note` are reported twice. Accepted —
  `category_counts` makes the duplication visible, and under-counting a leak is not an acceptable
  trade.
- **7. Sanitize by rebuild, not in-place mutation.** `canonical = type(canonical).model_validate(
  sanitize(canonical.model_dump(mode="json", by_alias=True)))`. In-place attribute walking would
  need a per-schema path setter and would couple the guard to every `fields` model. A re-validation
  failure is a **fail-closed** error, never a fall back to the unsanitized object.
- **8. OCR at `pipeline.py:92` is a documented trusted boundary, not a gap to close in M5.** The
  gate consumes `marker.md`, which OCR *produces*; gating it would require a pre-OCR gate over the
  image, which is a different control with a different threat model. The call is therefore recorded
  as trusted in the pipeline docstring and in §7 risk R1. This is the honest resolution: the gate
  does not cover it, and the plan says so rather than implying full coverage.
- **9. "Real marker" means the real marker's *shape*, instantiated synthetically.** ORDER §13.3 and
  the manifest's own notes forbid committing real patient data: a second copy of the leak would be
  created by the fix for the leak. The dataset gets a synthetic file reproducing `2b8fdd0d`'s
  label/value structure (ФИО / Полис / СНИЛС / Дата рождения / Номер талона) and the *declined*
  name form from gotcha G1. `source` stays `"synthetic"`; the manifest `notes` record which real
  document the shape came from, without its contents.
- **10. Raw value handling** (carried from M4): in-memory-only `value` + `masked_value` + salted
  `value_fingerprint`; the serialized summary carries `masked_value` only.
- **11. `value_fingerprint` is not logged and not persisted** in the frontmatter/event block. If
  cross-scan correlation is later needed, `document_id` + `category` + offset is the sanctioned
  join key.
- **12. `PIIDestination` for the extraction step becomes a setting** in Phase 15, defaulting to
  `INTERNAL_LLM` (the current provider, §0 invariant). Same reasoning as M4: making the destination
  data is the point, so switching providers is a config change and not a code change.
- **13. `age`/`gender` as PII categories** (carried from M4): kept at LOW risk, masked to `**`. They
  appear in the real note (`"(М, 39 лет)"`), so ignoring them would leave a channel open — but per
  ORDER §13.7 the age itself is a clinical fact and must survive sanitization. Masking the
  `GENDER`/`AGE` *tokens* while preserving the clinical sentence is the intended behaviour, and
  Phase 14's tests assert it.
- **14. `REVIEW` never auto-redacts.** A threshold that both flags and rewrites would make a
  calibration guess destructive. `REVIEW` halts for a human.
- **15. NER is P1 and may stay off.** It is the least deterministic detector and the most expensive;
  M6 may decide the pattern + structured coverage is sufficient. Nothing else in M5 depends on it.

### Risks (mitigations in place)

- **R1 — OCR sends the document to an external LLM before any gate runs.** `pipeline.py:92` is
  upstream of both contours; §7 decision 8 documents it as trusted, and §0's diagram marks it
  `UNGATED`. Not a defect of M5 — a property of the ordering — but the single largest remaining
  exposure, and it must be stated in every report of this milestone's coverage. Mitigation when it
  is addressed properly: a pre-OCR control over the image, or a trusted OCR deployment.
- **R2 — the guard is only as good as the pattern set on free-form text.** `fields.note` is `Any`;
  there is no schema to lean on. Mitigated by: the declined-name regression (G1), the per-leaf walk
  that inspects *every* string leaf rather than a fixed field list, and M6's calibration pass over
  `.dev/flow_upload_test/`. A guard that finds nothing on the real payloads is a failed milestone
  even with a green suite — hence the three-surface acceptance test.
- **R3 — sanitizing a category the render depends on.** Masking `DOCTOR_NAME` would degrade every
  prescription. Mitigated by per-category remediation (decision 2) and by a test that asserts
  `doctor_name` survives a `person_name` redaction.
- **R4 — sanitization breaks schema validation.** Masking a typed field (e.g. a `ResultItem.value`
  that is `str | float`) can produce a value the model rejects. Mitigated by fail-closed rebuild
  (decision 7) — a loud failure in Phase 14's tests, not a silent leak in production.
- **R5 — fingerprint secret rotation invalidates stored fingerprints.** A rotated secret changes
  every fingerprint, so pre-rotation `value_fingerprint` values no longer match. Contained: nothing
  reads or persists fingerprints (decision 11), and dedup is within a single scan, so there is no
  cross-scan comparison to break. Mitigated by keeping them out of the artifact — the decision that
  makes rotation a non-event. The secret must still be stable, because changing it changes
  `PIIScanResult` output; treat it as config, not ephemeral env.
- **R6 — `policy_version` in already-stored data goes stale.** Phase 14 writes `2.0.0`; the seeded
  `document_extractions` rows from the dev runs carry no `pii` block at all, and pre-M5 artifacts
  carry `1.0.0`. Nothing reads either yet, so **no migration is written and none is needed** — but
  any future consumer must treat a missing or older `policy_version` as "not evaluated under current
  policy" rather than "allowed". Recorded here so the assumption is explicit rather than
  discovered.
- **R7 — false positives degrading extraction** (IMPL_ARCH §34): e.g. `Москва` as address vs clinic
  address; a three-word capitalised run as a ФИО. Mitigated by `ALLOW` being the default for
  identity/contact, by `masked_value` + offsets + `detector` in every finding (so M6 can triage),
  and by `REVIEW` never auto-redacting.
- **R8 — fingerprint treated as a safe hash.** Mitigated by locking HMAC+salt, keeping fingerprints
  out of logs and the persisted block, and asserting both.
- **R9 — a `REVIEW` decision with no consumer.** `REVIEW` sets `processing_status='needs_review'`
  and there is no human UI yet (IMPL_ARCH §2.1, ORDER §2). A document in `needs_review` stalls
  silently. Mitigated by writing the `pii.review.required` audit event, which is the only signal
  available; the UI is out of M5 and flagged rather than hidden.
- **R10 — compliance misreading.** Someone cites this gate as HIPAA/152-ФЗ/GDPR proof. Mitigated by
  the explicit invariant in §0 and IMPL_ARCH §37.
- **R11 — `EVENTS.md` staleness.** No new event in M5, so the catalog at `EVENTS.md:8-18` does not
  change. But `data["pii"]` and `data["classification"]` are new keys on an existing event; if
  M6 formalizes the `data` shape, the catalog must be updated in the same commit.
- **R12 — no type-check in CI.** Same as every prior contour; mitigated by Pydantic + import smoke
  checks + ruff, per existing convention.

### Versioning policy (locked)

`DETECTOR_VERSION = "1.0.0"`, `PII_POLICY_VERSION = "1.0.0"` at M4. Patch = docs/comments only.
Minor = additive (new optional field, new `PIICategory` with a matching policy row) and
backward-compatible. Major = breaking (required field change, enum removal, **decision-rule
change**) — any change that alters a decision for any input bumps the policy version, so a stored
`PIIScanResult` always names the policy that produced it. Detector and policy versions move
independently, mirroring `classifier_version` (currently `2.1.0`).

M5 version roadmap:

```text
DETECTOR_VERSION    1.0.0 ──(Ph 9, additive detect_text)──▶ 1.1.0 ──(Ph 16, NER)──▶ 1.2.0
PII_POLICY_VERSION  1.0.0 ──(Ph 14, persistence escalation)▶ 2.0.0 ──(Ph 17, thresholds)▶ 2.1.0
```

`1.0.0 → 2.0.0` is **major** because it changes a decision: at `stage=canonical,
destination=persistence`, identity/contact/government/medical_id move from `allow` to `redact`
(§4.11). A document that would previously have been persisted with a name in it is now masked. That
is the milestone's entire point, and it is exactly the change a stored `policy_version` exists to
make interpretable.

### Conventions

- Follow `docs/development/operational/CONTRIBUTING.md`. M4 changes were localized to
  `apps/ai-worker/app/pii/**` and `tests/unit/pii/**` plus `tests/fixtures/pii/**`. **M5 is the
  first contour to leave that footprint**: `app/pipeline/pipeline.py`, `app/config/settings.py`,
  `app/artifacts/`, `app/canonical/rendering.py`, `packages/storage/storage/keys.py` and
  `packages/canonical/canonical/metadata.py` are all in scope, exactly as §4.9 recorded.
- Reuse the existing files rather than renaming: `detectors.py`, `gate.py`, `models.py`,
  `policy.py`, `exceptions.py`, `aggregation.py`, `masking.py`, `redaction.py`,
  `canonical_guard.py` all exist. New in M5: `artifact.py` only.
- Flat layout, mirroring `app/classification/` and STRUCTURE §5 — not IMPL_ARCH Phase 1's
  `pii/domain/` subpackage. Same deviation as the Classification M1 plan; recorded so M5 doesn't
  re-litigate it.
- Pydantic v2, `extra="forbid"` on every boundary model, `model_json_schema()` for schemas,
  `str, Enum` for enums, `Protocol` for interfaces, string annotations + `TYPE_CHECKING` for
  cross-package types.
- Status mirrored in three places: §1 table, §3 heading, §6 list.
