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

**Revision 3** — (2026-09-30) **Phase 16 DEFERRED, Phase 17 scoped and shipped.** What changed:
(a) **Phase 16 (NER) is DEFERRED** — a separate ML evaluation task, not a partial implementation. No
ML/torch/transformers/spaCy dependency, no NER backend, no change to the detector chain;
`PIISource.NER` and `DETECTOR_VERSION = 1.2.0` both stay exactly as they are. Revisit conditions in
§3 Phase 16 and §7 open decision 15. (b) **Phase 17 expanded** from a three-line stub into a full
implementation plan, and shipped — §4.13 (combination rules) added, R15 added, `PII_POLICY_VERSION`
2.0.0→**3.0.0**. (c) **The roadmap number `2.1.0` for Phase 17 is corrected to `3.0.0`**: §4.8 makes
major = "any change that alters a decision for any input", and the combination rule turns `ALLOW` into
`REVIEW` for inputs that return `ALLOW` today. Preserving `2.1.0` would have shipped a version
violating the SemVer rule two sections above it. Precedent: Phase 14 already corrected the detector
roadmap the same way. (d) §4.7's example block corrected — it read `detector_version "1.3.0"`, written
when Phase 16 was expected to land, and `policy_version "2.0.0"`. (e) **Corrected a pre-existing
drift**: the §1 table carried Phases 9, 11, 12 and 14 as `[ ]` while their §3 headings and status
blocks read `[x]` — the revisions that closed them updated the heading and prose but not the table,
so the schema's "update status in all three places" rule had been broken since Phase 14. Repaired
here rather than left as a second inconsistency in the same file as a deferral record. Phase 17's own
status update was applied to all three places correctly.

Status legend: `[ ]` pending · `[x]` done · `[~]` deferred (out of the current milestone).

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
| 9 | M5 | Pattern detector → aggregator → policy engine → `PIIGate.inspect` | [x] |
| 10 | M5 | Persistence surface (`pii_result.json`, `MARKDOWN_KIND_PII`, `PIIMeta`, frontmatter) | [x] |
| 11 | M5 | Contour 1 wiring — `inspect` after classification, artifact before publish | [x] |
| 12 | M5 | Markdown redaction (`PIIRedactor.redact`) | [x] |
| 13 | M5 | Marker-shape fixture + structured-field and secret detectors | [x] |
| 14 | M5 | Canonical guard — escalation policy, per-category sanitizer, both dump points | [x] |
| 15 | M5 | `EXTERNAL_LLM` destination + redaction on the extraction path | [x] |
| 16 | M5 | NER detector (P1) — **DEFERRED** to a separate ML evaluation task | [~] |
| 17 | M5 | `REVIEW` combination threshold (P1) — narrow government-identifier rule | [x] |

**M4 status: complete.** All seven phases `[x]`, committed as `ef412d2`. `uv run pytest` → 436
passed (174 baseline + 262 PII contract tests). `make lint` reports only 4 pre-existing
`packages/storage` errors, unrelated to this milestone and present before M4 began.

**M5 status: complete — Phases 8–15 and 17 done, 16 deferred.** `uv run pytest` → 809 passed.
The gate now *works* in memory — `await gate.inspect(document, context)` detects, deduplicates,
evaluates policy and returns a verdict — and it is now **in production**: `DocumentPipeline` builds it
at start-up, inspects every document after classification and before extraction, halts on
`REVIEW`/`BLOCK` before a single byte is written, and on the allow path uploads `pii_result.json` and
carries the §4.7 block in both the frontmatter and the event payload. Redaction is implemented, tested
against the real fixture, and reported to the policy as available — and stays mostly dormant, because
at the trusted internal destination the policy issues no `REDACT` action.

Since Phase 13 the detector chain is the whole chain, so the risk R13 is **closed**: a document
carrying a credential reaches `BLOCK`, and `doctor_name` is detected by the labelled detector rather
than left to a two-token ФИО rule that would also match `Уважаемые жильцы`. **Since Phase 14** the
canonical-guard contour is wired and the observed `canonical.json` leak is **closed**: the sanitized
model replaces `canonical` before all three consumers, and the two leak shapes are asserted clean at
all three dump points. **Since Phase 17** `REVIEW` is reachable at the production boundary for the
first time: the narrow government-identifier rule (§4.13) escalates a document carrying two distinct
state identifiers, and the pipeline halt path executes end to end in production for the first time
since it was written. The remaining limits are recorded rather than hidden — the manifest's
`expected_decision` is measured at one named boundary rather than all three, because §4.10's entry
keys have no `destination` field (Deviation 1, Phase 13 status), and a `REVIEW` halt still has no human
consumer (R9, R15).

**M5 is complete when** Phases 8–15 and 17 are `[x]` **and Phase 16 is deferred with its revisit
conditions recorded** — a deferral is an outcome, not an omission, and M5 does not reopen to add a
model — the full ai-worker suite is green on the 436-test baseline, `packages/storage` is green, and —
the criterion that actually distinguishes M5 from M4 — **the two real leaks from
`.dev/flow_upload_test/` produce a clean `canonical.json`, a clean `structured.md`, and a clean event
`data`**, asserted in three separate tests, one per dump point. A green suite that does not include
that assertion does not count as M5 done.

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
plausible stopping point if the milestone needs to ship partially. Phases 8, 9 and 10 are `[x]` and
their status is recorded in place below, M4-style; the remaining seven are `[ ]`.

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

### Phase 10 — Persistence surface [x]

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

#### Phase 10 Implementation Status

**Changes.**

```text
packages/storage/storage/keys.py            "pii": "pii_result.json" in MARKDOWN_ARTIFACTS,
                                           docstring :40-44
packages/storage/storage/__init__.py        MARKDOWN_KIND_PII + __all__ (alphabetical)
packages/storage/tests/test_keys.py         +3 tests, MARKDOWN_ARTIFACTS imported
packages/canonical/canonical/metadata.py    PIIMeta (after ClassificationMeta), FrontmatterMeta.pii
packages/canonical/canonical/__init__.py    PIIMeta re-export (import block + __all__)
packages/canonical/tests/test_canonical.py  +8 tests
apps/ai-worker/app/pii/artifact.py          build_pii_artifact, build_pii_meta_block  (NEW)
apps/ai-worker/app/pii/__init__.py          +2 exports (75 total)
apps/ai-worker/app/artifacts/models.py      MARKDOWN_KIND_PII re-export (+ __all__)
apps/ai-worker/app/artifacts/__init__.py    MARKDOWN_KIND_PII re-export (+ __all__)
apps/ai-worker/app/canonical/rendering.py   build_frontmatter_meta(pii=…)
apps/ai-worker/tests/unit/pii/test_artifact.py  32 tests
```

- **M4 Phase 7's recorded gap is discharged.** `PII_META_REQUIRED_KEYS` /
  `PII_META_OPTIONAL_KEYS` were a key *set* with nothing validating a written block against them —
  the plan's own words. They now have three enforcement points: `build_pii_meta_block` is asserted
  to emit exactly their union, `PIIMeta` is asserted to have exactly that field set, and a real
  block round-trips through `PIIMeta` (`extra="forbid"`) into `FrontmatterMeta.to_dict()` and back
  out of `render_frontmatter`. The two homes of the shape — data in `app/pii`, model in
  `packages/canonical` — are pinned against each other rather than against a literal, which is the
  only way a transcription stays honest.
- **Deviation — the artifact has no provenance envelope, unlike the classification one.** The plan
  said "mirroring `app/classification/artifact.py:18-50`", and `build_classification_artifact` does
  wrap its verdict in `processing` + `generated_at`. This one does not, because those fields have
  nothing true to say: the classification verdict is produced *before* extraction, so the prompt and
  model are the only record of the run it belongs to. **The PII gate runs on `marker.md` and never
  sees the LLM** — stamping `pii_result.json` with the extraction's `model` / `prompt_key` /
  `schema_name` would record provenance for a call the gate did not make. And an envelope is the one
  thing that would stop the artifact being `PII_SCAN_RESULT_SCHEMA`-conformant, which is the phase's
  stated accept criterion. `PIIScanResult` already carries `detector_version`, `policy_version` and
  `processed_at`, and the S3 key already encodes tenant/patient/document/version. The absence is
  asserted (`test_artifact_carries_no_envelope_the_schema_does_not_declare`), because a future
  contributor mirroring the classification habit would otherwise break the plan's validation claim
  while every other test stayed green.
- **Deviation — `build_pii_meta_block` was added, and it is the phase's most load-bearing new
  function.** The plan named only `build_pii_artifact`. The block needs a producer, and there are
  exactly two options: the pipeline hand-builds it at two call sites (frontmatter and event `data`),
  or one function builds it once. The second was chosen because **the block is consumed twice and
  must not be able to disagree with itself** — the M5 milestone's own history is two surfaces
  carrying one leak. It is also what makes the M4 gap dischargeable at all: a hand-built literal in
  the pipeline is not testable here.
- **Deviation — the block is a plain `dict`, not a `PIIMeta`.** `app/pii` may not import
  `packages.canonical` (ORDER §8, and M5's third import guard, which `pii_imports.py` already
  forbade from Phase 3). So `PIIMeta` is the block's *reader*, not its producer, and
  `FrontmatterMeta` does the validating — which turns block drift into a `ValidationError` the
  pipeline already handles, instead of a rendered verdict carrying a field no consumer reads. The
  cost is a second home for the shape; `test_artifact_module_imports_no_canonical_model` asserts the
  module imports nothing but `json`, `typing` and `app.pii.models`, so the convenience cannot be
  taken silently.
- **Deviation — versions are copied off the result, not read from the constants.** §4.7 says "a test
  asserts the block carries the live constants rather than a copy". Read literally that would have
  `build_pii_meta_block` read `DETECTOR_VERSION` / `PII_POLICY_VERSION` directly, which would
  mislabel any re-serialized older result — the opposite of what `policy_version` exists for
  (plan §4.8, risks R5/R6). The end-to-end claim is asserted instead on a **freshly gated** result,
  which is the real wiring: the gate stamps the result from the constants, so block == constants
  today, and `test_block_versions_come_from_the_result_not_from_the_constants` pins the *source* by
  checking a deliberately-stale result keeps its stale version.
- **Two new tests beyond the plan's list, both cheap and both about a class of bug the repo has
  already hit.** `test_every_markdown_artifact_filename_is_unique` — two kinds mapping to one
  filename means the second upload silently overwrites the first. `test_the_two_all_lists_stay_alphabetical`
  — Phase 10 adds an entry to two `__all__` lists and the plan's §7 records that ruff's `I` rule
  makes ordering a real convention.
- **The storage filename constant is pinned by duplication, deliberately.**
  `app/pii/persistence.PII_ARTIFACT_FILENAME` cannot be imported from `packages/storage` (it depends
  on the worker app), so `test_pii_kind_resolves_to_the_declared_filename` compares the table's value
  to a plain literal in the test. That is the only place the two can be checked against each other,
  and a literal beats asserting the package's own dict against itself.
- **`categories` is derived from `category_counts` and sorted.** §4.7 makes the counts authoritative
  and the list a convenience; deriving it means no consumer can recompute the tally wrongly, and
  sorting means two scans of the same document render byte-identical blocks. The block deep-copies
  `category_counts` / `reasons` / `warnings`, so a caller mutating what it was handed cannot reach
  back into the result (`test_block_does_not_alias_the_result`).
- **Tests run the real gate, not a hand-built result.** 32 tests, every shape assertion driven from
  `gate.inspect` over the `synthetic-consultation-01` fixture at `INTERNAL_LLM` — the destination the
  worker actually runs with, chosen deliberately: the manifest's `expected_decision` is
  destination-dependent (M4 Phase 7 gap 1), and Phase 10 persists the *production* verdict. The
  no-leak claim is asserted two ways — no `value` key at any depth, *and* none of the fixture's own
  tokens (`Смирнова`, `1974-03-12`, …) anywhere in the artifact — because the first is true by
  construction and would survive a detector that wrote a patient's name into `masked_value`.
  Quoted-key matching throughout, per Phase 2's recorded `masked_value` trap.
- **No pipeline change, and none is claimed.** `pipeline.py` does not import `build_pii_artifact` or
  `MARKDOWN_KIND_PII`; Phase 11 wires both. Nothing is uploaded, no event carries `data["pii"]`, and
  the `structured.md` a real run produces still has no `pii:` block. The phase's accept criterion is
  about the *shapes*, and the shapes are what was built.
- **No new version bump.** `DETECTOR_VERSION` stays `1.1.0` and `PII_POLICY_VERSION` stays `1.0.0`:
  Phase 10 changes no decision and produces no finding. `1.0.0 → 2.0.0` remains reserved for Phase
  14's persistence escalation, which is the first phase that alters a verdict.
- **Verification recap:** `uv run pytest tests/unit/pii` → 404 passed (372 + 32); `uv run pytest` → 578
  passed (436 baseline + 142 M5); `uv run --project packages/storage pytest packages/storage` → 18
  passed (15 + 3); `uv run --project packages/canonical pytest packages/canonical` → 18 passed
  (10 + 8). `uvx ruff check apps packages tests` reports only the 4 pre-existing `packages/storage`
  errors (`s3.py:84` E501, `test_markdown_helpers.py` I001/F401/UP012), untouched per convention, and
  `uvx ruff format --check` diffs to **byte-identical output before and after this phase** on every
  path it already flagged. Smoke check prints `1.1.0 1.0.0`. Still uncommitted.
- **Next step:** Phase 11 (contour 1 wiring) — the first phase that puts the gate into a production
  path, and the one that answers the open question recorded below.

#### Open question carried into Phase 11 — one artifact or two?

The pipeline will produce **two** `PIIScanResult`s per document: a `stage=document` verdict before
extraction (Phase 11) and a `stage=canonical` verdict after `build_canonical` (Phase 14). §4.7 fixes
one `pii_result.json`, one frontmatter block (which has a single `stage` field) and one
`data["pii"]` key, so the two verdicts have to be composed somewhere, and the plan does not say how.

Phase 10 deliberately did **not** decide it: `build_pii_artifact` takes one result, so it cannot
silently produce a shape no schema covers. The candidates are (a) upload the document-stage result
in Phase 11 and let Phase 14 add a second artifact or overwrite it, (b) a `{"scans": [...]}` envelope
holding both, which breaks structural conformance with `PII_SCAN_RESULT_SCHEMA`, or (c) one file
holding the document result with the canonical result nested under it. **(a) is the one that
silently loses a verdict** and is the only one to rule out. This is Phase 14's decision to make with
both results in hand, and the constraint on it is that no already-stored `pii_result.json` may become
unreadable when the answer changes.

**What Phase 11 did, and did not, decide.** It picked option (a) for its own contour — upload the
document-stage result, and let Phase 14 decide what happens to the second one — because that is the
only option that keeps `build_pii_artifact`'s signature and the §4.7 shape intact, and because the
M2 ordering invariant wants the contour-1 verdict on disk *before* the LLM call. This is a
compatibility mechanism, not an answer to the question.

**The constraint on Phase 14, confirmed and binding.** Phase 14 **must not overwrite
`pii_result.json`.** A second stage-specific PII artifact is required — a new `MARKDOWN_ARTIFACTS`
entry, e.g. `"pii_canonical": "pii_canonical_result.json"` — or an equivalent immutable
representation that holds both scans without either being replaced. Overwriting is the "silently
loses a verdict" failure the options list calls out, and it is now out of bounds rather than merely
discouraged. The §4.7 frontmatter block carries a single `stage` and must therefore remain the
**document-stage** block, so that already-rendered `structured.md` stays readable; the canonical-stage
verdict belongs in the second artifact and, if the frontmatter is to surface it, in an additional
key that older renders simply do not have. No already-stored `pii_result.json` may become unreadable
when the answer changes — that remains the acceptance constraint on Phase 14's choice.

### Phase 11 — Contour 1 wiring [x]

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

#### Phase 11 Implementation Status

**Changes.**

```text
app/pii/detectors.py       _require_fingerprint_secret(settings) extracted; build_detector_chain
                           and the new build_available_detector_chain both call it
app/pii/gate.py            HALTING_DECISIONS: frozenset[PIIDecision]; build_document_gate(settings)
                           → DefaultPIIGate, with the PolicyContextBuilder closure
app/pii/__init__.py        3 re-exports (__all__ alphabetical)
app/pipeline/pipeline.py   PII_GATE_JOB_TYPE, PII_DECISION_ERROR_CODES; self._pii_gate =
                           build_document_gate(settings) in __init__; the gate call, the halt
                           branch, the pii_result upload, pii= on _build_frontmatter, "pii" +
                           "pii_key" in event data, error_code on _fail
tests/unit/pipeline/       9 new tests, real gate over real Russian text
tests/unit/pii/            4 tripwire tests (subset, no stub, shared choke point, gate built
                           from the available chain) + 1 HALTING_DECISIONS derivation test
```

**Decisions taken here, and why.**

1. **The gate is built by `build_document_gate(settings)`, not in the pipeline body.** The pipeline's
   `__init__` is one line with no `app.pii` vocabulary in it, so the security-relevant choices
   (which detectors run, which stage, which destination) are auditable in one function. Fail-closed
   properties are inherited, not re-decided: the secret is validated by the chain constructor, and
   `redaction_available` stays `False` so a `REDACT` with nothing to redact with still escalates.
2. **The pipeline uses `build_available_detector_chain`, not `build_detector_chain`.** The full
   chain's `StructuredFieldPIIDetector` and `SecretPIIDetector` raise `NotImplementedError` in
   `detect_text` until Phase 13, so wiring it today would not degrade to a weaker control — it would
   fail *every* document, which in practice gets "fixed" by commenting the call out. The interim
   constructor returns the implemented subset in the same relative order, and
   `test_settings_boundary.py::test_available_chain_is_a_strict_subset_of_the_full_chain` fails once
   the two are equal, which is the signal to delete it. `build_detector_chain` itself is untouched.
3. **The real gap this leaves is stated, not hidden:** `SecretPIIDetector` is the only `BLOCK`
   source, so **no document can reach `BLOCK` until Phase 13** — a document carrying a credential
   gets `ALLOW`. The gate is *narrower*, not laxer, and that is the gap Phase 13 exists to close.
   **This is a temporary compatibility mechanism, not a design.** It expires at Phase 13, which
   replaces it with `build_detector_chain` and deletes `build_available_detector_chain`; the
   subset-tripwire test is what enforces the expiry rather than a note in a changelog.
4. **`REVIEW` and `BLOCK` halt before the first upload.** The accept criterion says zero artifacts
   for a halting document, and `REVIEW` is silence in the plan, so both take the same shape: no
   artifact, no `document.analysis.completed`, no extraction, one
   `document.processing.failed`. The decision is logged with its counts and reasons.
5. **`pii_result.json` is uploaded immediately after the gate, not with the other artifacts at the
   end.** The gate has already run, so its verdict is the audit record of it; if the LLM call then
   fails, that verdict is still on disk instead of being lost with the failed request. The M2
   ordering invariant holds either way, and the test asserts the PII upload precedes `canonical.json`.
6. **One `build_pii_meta_block` call feeds the frontmatter *and* the event payload**, so the two
   surfaces cannot disagree about what the gate decided.
7. **`document_type` is read from the normalized document's metadata and is `None` in practice** —
   the pipeline normalizes with `{"client_type": ...}`. Honest, because the baseline policy ignores
   it. A type-specific policy would need the classification verdict plumbed through
   `PolicyContextBuilder`, whose signature is locked; that is a later change to the builder's
   inputs, not something to smuggle through `attributes`.

**Deviation from this phase's own text — `processing_status='needs_review'` has no field to live
in.** The plan writes the two halting outcomes as `processing_status = needs_review` and `processing
failure`. There is no such field: `DocumentAnalysisCompleted.status` is
`Literal["succeeded", "failed"]`, `DocumentProcessingFailed` has no `data`, and `processing_status`
appears nowhere in the contracts or the SQL migrations. M5 is explicitly forbidden from changing a
cross-package event contract (ORDER §13.6), and R11 records that no new event is added, so inventing
the field here would be a schema-versioned change wearing a phase's clothes.

The distinction is therefore made in `error_code`, which the contract already has and which exists
precisely to say *why* a job failed: `PII_REVIEW_REQUIRED` and `PII_BLOCKED`, with
`job_type="pii_gate"`. They are different events for whoever clears the queue — one document waiting
for a person, one document that must not be written down at all — and sharing one code would erase
exactly the distinction the plan asks for.

**This is a temporary compatibility mechanism, not a design.** It exists because a durable
`needs_review` state needs something M5 may not add: a `PIIAuditRecord` writer (the sink M4
deferred) or a schema-versioned bump of `DocumentProcessingFailed`. Until one of those exists,
`error_code` is the only field on the contract that can say *why* a document stopped, and both
halting decisions are reported through it rather than being collapsed into one. It expires when
that sink or that bump lands — not before. The invariant a later phase must preserve: `REVIEW` and
`BLOCK` must never share an `error_code`, because the whole point is that they are different events
for whoever clears the queue. `test_pipeline.py::test_every_halting_decision_has_an_error_code`
pins the key set against `HALTING_DECISIONS` so a third halting decision cannot arrive without one.

**Accept — verified.** With a clean fixture, `structured.md` diffed against the pre-Phase-11
pipeline is identical except the two per-run nondeterministic values (`doc_id`, `validated_at`) and
the 13 added `pii:` lines. With PII present, the gate reports `allow` + 1 `snils` finding, and
neither the raw value nor any fingerprint appears in `structured.md` or `pii_result.json`. A halting
verdict uploads zero artifacts and never calls the LLM.
Tests: `uv run pytest` → **593 passed**; `make lint` → the same 4 pre-existing storage failures.

### Phase 12 — Markdown redaction [x]

`PIIRedactor.redact(markdown, findings)` implemented over `(start, end)` spans, applied
**right-to-left** so earlier offsets stay valid, replacing each with `placeholder_for(category)`.
`redaction_available` is set `True` in the constructed context. The redacted markdown is a
**new** artifact string; `marker.md` and the upload are never rewritten. Tests: span replacement
correctness, right-to-left offset stability, non-overlapping and adjacent spans, no-op on empty
findings, `SECRET` placeholder reveals nothing, idempotence.
Deps: Phase 9. (§45.12)
**Accept:** redacting the `synthetic-consultation-01` fixture removes every
`expected_categories` value from the output while leaving all other characters byte-identical.

#### Phase 12 Implementation Status

**Changes.**

```text
app/pii/redaction.py      PlaceholderRedactor.redact implemented (steps 1-4); private
                          _Span, _merge_overlapping, _locate, _same_text; `re` +
                          `dataclasses` + `from __future__ import annotations`
app/pii/gate.py           REDACTION_AVAILABLE = True, passed to build_policy_context
tests/unit/pii/           new test_redaction_behaviour.py (31 tests);
                          test_masking_redaction.py: the interim stub is gone, the base
                          marker is not; stdlib allowlist gains re + dataclasses
```

**The one place this phase deviates from the locked algorithm, and why.** The module docstring
says to prefer `start`/`end` "when both are present and lie within the markdown". That test is
insufficient, and on the real caller it is *actively wrong*: findings index `document.raw_text`,
which is canonicalised (case-folded, punctuation-mapped, whitespace-collapsed), while the text being
redacted is the markdown. Measured on `synthetic-consultation-01`, **all six** findings return
offsets that are comfortably in range and point at unrelated text:

```text
person_name  (117, 140) -> "* Смирнова Ольга Иванов"   (value: "смирнова ольга ивановна")
date_of_birth (142, 152) -> ", 1974-03-"               (value: "1974-03-12")
phone         (166, 184) -> "* +7 (495) 000-11-"      (value: "+7 (495) 000-11-22")
```

Honouring those offsets would replace the wrong characters *and* leave the real value in the
document — corruption and leak in one step, with an artifact attesting to a removal that never
happened. So the offset is treated as a **hint** and accepted only when the text it selects actually
matches the finding's value; otherwise the value is located. Both halves of the deviation only change
behaviour for offsets that were *wrong*: for well-formed findings — the canonical-guard contour,
where the caller walks the exact string it scanned — the hint still wins and the fast path is kept.
The docstring's own intent ("never skip a finding, because a silently skipped redaction is a leak")
is served better by this than by the literal reading, which leaks while appearing to succeed.
M4's own `gate.py` docstring asked for exactly this ("Phase 12 must re-locate a value in the source
text rather than trust an offset across that boundary"), so this follows the plan rather than
rewriting it.

Case-insensitive location is **required**, not a convenience: the canonicaliser case-folds, so
`смирнова ольга ивановна` appears in the markdown as `Смирнова Ольга Ивановна`, and two of the six
values match nothing else. Matching runs as a case-insensitive regex over the *original* string
rather than `str.casefold()` on both sides, because `casefold` is not length-preserving
(`"ß" → "ss"`) and searching a transformed copy returns offsets into the wrong string.

**A second bug the tests caught, in the merge step.** The docstring promised "ties resolve to the
leftmost, so the output is deterministic", but two findings can share a confidence *and* a span, and
then "first one seen" put the caller's ordering into the artifact — the same document redacted twice
could produce two different files. The sort key is now `(start, end, -confidence, placeholder)`:
position dominates (so a tie is still the leftmost span) and the placeholder is the final
tiebreaker, which is intrinsic to the finding rather than to when it arrived.

**Decisions taken here.**

1. **The pipeline is unchanged, deliberately.** `marker.md`, the upload and the LLM call all stay as
   they are, because at `destination=INTERNAL_LLM` the policy issues `ALLOW` for every category but
   `SECRET` and the `REDACT` override fires only for `EXTERNAL_LLM` — so no `REDACT` action is ever
   issued and the redactor is dormant. Verified: the clean-fixture `structured.md` is still
   byte-identical to the pre-Phase-11 output apart from `doc_id`, `validated_at` and the `pii:` block,
   and the decision is still `allow`. The redacted string is a **new** artifact, produced on demand
   when something asks for it; nothing rewrites what was uploaded.
2. **`redaction_available` is a module constant, not a settings read.** It is a fact about *this
   codebase* (`redact` exists and is tested), not an operational choice — a deployment cannot
   acquire a redactor by setting an environment variable, and exposing one as config would let an
   operator declare "redaction is available" while nothing implements it. That is the exact fail-open
   the flag's `False` default was chosen to prevent. Phase 15 changes `destination`; the flag is
   already telling the truth by then.
3. **An unresolvable finding fails the whole call.** Partial redaction is not a lesser outcome, it is
   the same leak, so `PIIRedactionError` is raised rather than skipping the finding and producing a
   document that looks redacted and is not.

**Accept — met for six of seven categories, and that is a partial pass.** Redacting
`synthetic-consultation-01` through the real gate removes every value it finds and leaves every
other character byte-identical (asserted against an independent splice, not by round-tripping the
redactor against itself). The manifest declares seven `expected_categories` and the chain finds six.
The missing one is **`doctor_name`**: `Петров И. С.` is a surname plus two initials, and
`PatternPIIDetector` deliberately has no two-token ФИО rule because it would also match
`Уважаемые жильцы`-style prose and organisation names. Finding it is
`StructuredFieldPIIDetector`'s job — the fixture writes `**Врач:** Петров И. С.`, a labelled form —
and that detector is Phase 13. This is a **detection** gap, not a redaction gap.
`test_one_manifest_category_is_still_undetected_and_that_is_a_phase_13_gap` pins the uncovered set to
exactly `{"doctor_name"}`, so the gap cannot quietly widen: when Phase 13 lands the test fails and
the fix is to fold `expected_categories` into the full assertion.

**Two coverage limits worth recording, both detection-side and neither introduced here.**

- The `address` finding covers `г. Москва` only, so redaction leaves `ул. Примерная, д. 1, кв. 2`
  behind. That is how much the detector found, not a redaction failure — the redactor removes the
  spans it was given and the module docstring already says so. Labelled-address coverage is
  `StructuredFieldPIIDetector`'s.
- The aggregator dedupes on `(category, value_fingerprint)`, so a value appearing **twice** in one
  document yields one finding and therefore one replacement — the second occurrence survives. The
  locked algorithm is one span per finding, so this is not a Phase 12 defect, but it becomes a real
  leak the moment redaction goes live. It belongs with Phase 15, which is when
  `destination=EXTERNAL_LLM` first makes redaction reachable.

Tests: `uv run pytest` → **625 passed**; `make lint` → the same 4 pre-existing storage failures.

### Phase 13 — Marker-shape fixture + structured & secret detectors [x]

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

#### Phase 13 Implementation Status

**Changes.**

```text
app/pii/detectors.py       StructuredFieldPIIDetector (19 rows / 17 categories) and
                          SecretPIIDetector (10 rules) implemented; _CYR_WORD, _NAME_VALUE,
                          _standalone_digits, _LONG_DIGIT_RUN, _CELL_END, _NAME_LABELS,
                          _NAME_BOUND_WORDS and the placeholder guard are new or revised
app/pii/gate.py           build_document_gate wires all three detectors; the interim
                          constructor is deleted
app/pii/__init__.py       exports the two new detectors; build_available_detector_chain
                          is no longer exported
app/pii/fixtures.py       loader docstring no longer describes expected_* as unverifiable
tests/fixtures/pii/       appointment/synthetic-registration-01.md (the 2b8fdd0d shape,
                          invented values); manifest.json rewritten with measured expectations
tests/unit/pii/           new test_manifest_verification.py (25 tests);
                          test_fixture_manifest.py, test_detectors.py,
                          test_detectors_behaviour.py, test_redaction_behaviour.py and
                          test_settings_boundary.py: the Phase 9–12 tripwires that asserted the
                          *un*implemented state are replaced by live assertions
tests/unit/pipeline/      test_pipeline.py: SECRET_MARKER split into IDENTIFIER_MARKER and
                          CREDENTIAL_MARKER, with a real BLOCK path and an identifier-allow path
```

**The three changes of substance, in the order the plan forced them.**

1. *The chain is whole, so the interim constructor is gone.* `build_available_detector_chain`
   existed to return the implemented subset while the two live detectors raised
   `NotImplementedError`; with both scanning, the subset is the full set and the constructor is a
   second thing that can disagree with `build_detector_chain`. The pipeline now wires
   `build_document_gate(settings)` directly, and `test_settings_boundary.py` asserts the chain
   inventory instead of a subset tripwire. `DETECTOR_VERSION` stays `1.1.0`: §4.8 makes a minor bump
   an *additive* change, and this phase adds no `PIICategory` and no field to `PIIFinding` — it
   fills in the categories the locked table already declared.
2. *The fixture is the real marker reproduced, and the manifest is now an observation.* The entry
   is `appointment/synthetic-registration-01.md`: the `2b8fdd0d` **shape** with every value
   invented, per §7 decision 9 and ORDER §13.3. It yields exactly `person_name` +
   `ticket_number`, which is the accept criterion, and the test that asserts it is called out by
   name so a reader does not have to infer it from a category set.
3. *The declined genitive name is the reason the phase has a hard part.* The registration marker's
   "Электронная запись на прием для пациента Кузнецова Александра Петровича" is mid-sentence, has
   no colon and arrives already case-folded, so a nominative `ФИО:` rule cannot match it. Widening
   the label rule to catch it produced `Пациент отказался от приёма` as a `person_name`; the fix is
   a construction-aware label rule — a colon/dash separator, the declined binder
   `для|у|от пациента…`, or a bold `**Пациент**` label — plus `_NAME_BOUND_WORDS` rejecting a leading
   preposition or particle. Both halves are pinned by name in
   `test_manifest_verification.py::test_prose_after_a_patient_label_is_not_a_person_name`.

**Deviation 1 — the manifest's `expected_decision` is measured at one boundary, and the manifest
says which.** §4.10's entry keys have no `destination` field, but the same findings decide
`ALLOW` internally, `ALLOW_WITH_WARNING` where a redactor exists, and `REVIEW` where redaction is
required and unavailable. Rather than add a field to a locked shape, the manifest's `notes` name
`EXTERNAL_LLM` + `redaction_available=False` (the fail-closed direction, which is the one that
distinguishes three decisions from one) and
`test_manifest_verification.py::test_every_fixture_is_also_allow_at_the_production_boundary` covers
the other end. The cost: a manifest edited for a different boundary fails loudly rather than
quietly, which is the intended direction for that failure.

**Deviation 2 — a false positive is recorded in the manifest rather than suppressed.** The 28-digit
API key in the malicious fixture is one unbroken digit run, and
`pattern.ticket_number.long_digits` claims any run of twelve or more, so it is reported as
`ticket_number` as well as `secret`. Narrowing the rule to "not exactly 28" would fit this one
fixture and generalize to nothing. The manifest declares
`expected_categories: ["secret", "ticket_number"]`, the note explains it, and
`test_manifest_names_the_known_ticket_false_positive` keeps the explanation attached to the
behaviour. A documented false positive on a credential is a cost worth paying; an undocumented one
is a bug report filed against a detector that is behaving as designed.

**Equality, not containment, in the manifest test.** The verification module asserts
`found == set(expected_categories)`, not `expected <= found`. A subset assertion cannot fail when a
detector starts inventing categories, and an invented category is a wrong masked value in a
persisted artifact. The cost is that every recall improvement shows up as a red test; the fix is to
record the newly-observed behaviour in the manifest, where the diff is visible to a reviewer.

**Tests.** `cd apps/ai-worker && uv run pytest` → **663 passed**, 5 warnings. `ruff check` in
`apps/ai-worker` → 13 `UP042`, all in `app/classification/models.py`,
`app/pii/canonical_guard.py` and `app/pii/models.py`, i.e. on lines this phase does not touch. From
the repo root, `make lint` → 4 errors, all in `packages/storage/` and equally untouched. Recorded
rather than fixed, per §5.

**Deviation 3 — the monorepo-wide suite is not runnable on this platform, and the number above is
not a monorepo number.** `make test` (`pytest apps tests packages/messaging/tests`) fails during
*resolution*, before any test runs: `torch==2.13.0` publishes no wheel for `macosx_14_0_x86_64`.
Nothing here can change that without editing another package's dependencies, which is out of scope
and would be a bigger decision than this phase. So the 663 above is the ai-worker suite, which is
where every Phase 13 change lives; the packages this phase does not touch (storage, messaging,
account-api) are outside the measured set and are reported as such rather than counted.

### Phase 14 — Canonical guard [x] · **VS#2**

**Status: implemented.** `apps/ai-worker/app/pii/canonical_guard.py`,
`app/pii/policy.py`, `app/pii/detectors.py`, `app/pipeline/pipeline.py`; tests in
`tests/unit/pii/test_canonical_guard_behaviour.py` (new, 31) and `tests/unit/pipeline/test_pipeline.py`
(+8). Suite: 714 passed. `DETECTOR_VERSION` **1.2.0**, `PII_POLICY_VERSION` **2.0.0**. Two fixtures
under `tests/fixtures/pii/canonical/` reproduce the two observed payload *shapes* with invented
values (§7 decision 9); nothing was committed from `.dev/flow_upload_test/`.

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

**Deviations from the plan as written**, all decided during implementation:

1. **§4.11's category set is 15, not 18.** The plan's prose said "the same 18 categories as
   `REDACT_ON_EXTERNAL`", which is inconsistent with its own accept criterion and with ORDER §13.7:
   `AGE`/`GENDER`/`NATIONALITY` are in the external set, and masking them destroys the note. The
   implementable reading — `REDACT_ON_EXTERNAL - CLINICAL_FACTS` — is what shipped, because the
   accept criterion (`(М, 39 лет)` survives) is testable and the 18 is not. The subtraction is
   derived in code rather than restated, so there is no fourth literal to forget a category in.
2. **`review` halts rather than sanitizes** (decision 16). M4's `DECISION_REMEDIATION` mapped
   `review → SANITIZE`; both halting decisions now map to `RETRY_THEN_FAIL`, and **no retry is
   implemented** in this phase.
3. **`CanonicalPIIViolation` has no value-less `inspect` projection problem** — the plan's signature
   `sanitize_canonical_payload(payload, violations, actions, redactor)` would not work: the redactor
   needs the raw *span*, which a value-less violation does not carry. `inspect` keeps the locked
   projection; `evaluate_payload` returns the richer result whose `findings_by_path` feeds
   `sanitize`, and `Field(exclude=True)` keeps those values out of every dump.
4. **The verdict is not written to a second artifact** (§4.7 offered both readings). The contour-2
   verdict is recorded through the structured log and the failure event only — no
   `pii_canonical.json`, no new storage kind, no migration.
5. **`pattern.date_of_birth.numeric` was removed and `DETECTOR_VERSION` moved to 1.2.0** — the
   unplanned change described in decision 17 and R7. Not in the plan: implementing §4.11 made the
   escalation real, and a rule claiming every bare ISO date then destroyed `document_date`. The
   §7 roadmap's `1.2.0 (Phase 16)` becomes `1.3.0`.
6. **`document_date` is asserted to survive** in both the guard and pipeline suites. It is a service
   date by construction of `BaseCanonical` and `render_document` writes it into the frontmatter, so
   it is the field a `DATE_OF_BIRTH` false positive destroys first.

### Phase 15 — `EXTERNAL_LLM` destination + redaction on the extraction path [x] · **VS#3**

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

#### Phase 15 Implementation Status

**Status: implemented**, with one hotfix in front of it. `apps/ai-worker/app/config/settings.py`,
`app/pii/policy.py`, `app/pii/gate.py`, `app/pii/__init__.py`, `app/pipeline/pipeline.py`,
`app/artifacts/`, `packages/storage/storage/`, `.env.example`; tests in
`tests/unit/pii/test_external_boundary.py` (new, 30), `tests/unit/pipeline/test_pipeline.py` (+14),
`packages/storage/tests/test_keys.py` (+1). Suite: **770 passed** (was 726, +44 — 30 new, 14 in
`test_pipeline.py`). `test_settings_boundary.py` stays at 33: its tripwire is *replaced* by live
assertions rather than added to. Storage: 19 passed (+1). `DETECTOR_VERSION` **1.2.0** and `PII_POLICY_VERSION`
**2.0.0** — both unmoved, for the reason in deviation 3.

**Files.** `app/config/settings.py` (`llm_mode`), `app/pii/policy.py` (`TRUSTED_INTERNAL_URLS`,
`resolve_destination`, `DEFAULT_DESTINATION` docstring), `app/pii/gate.py`
(`DocumentPIIGateResult`, `evaluate_document`, `redact`, redactor injection, destination wiring),
`app/pii/__init__.py`, `app/pipeline/pipeline.py` (`_redact`, the `redacted.md` upload, the
`PIIRedactionError` branch, the OCR boundary section and the start-up warning),
`app/artifacts/{models,__init__}.py`, `packages/storage/storage/{keys,__init__}.py`,
`packages/storage/tests/test_keys.py`, `.env.example`, `tests/unit/pii/test_external_boundary.py`
(new), `tests/unit/pipeline/test_pipeline.py`, `tests/unit/pii/test_settings_boundary.py`,
`tests/unit/pii/test_manifest_verification.py`, `tests/unit/pii/test_{artifact,gate_behaviour}.py`
(constructor call sites).

**The gate could not redact, and that is the phase's real finding.** `PIIScanResult.findings` are
`PIIFindingSummary`, which has no `value` field at all (Phase 1 structural rule), so the pipeline
held nothing a redactor could consume. `DocumentPIIGateResult` now returns the projection *and* the
raw findings beside it, in the same shape `CanonicalPIIGuardResult` established for contour 2:
`scan_result` plus `findings` and `actions`, both `Field(exclude=True)`. `inspect()` is now the
projection of `evaluate_document()` — ORDER §8's signature and its `None`-context
`PIIDecisionError` are unchanged, so the locked contract did not move, only what is available
beside it. `DefaultPIIGate.redact` masks iff `actions[category] is REDACT` and returns `markdown`
**by identity** when nothing is, which is how the pipeline decides whether an artifact is
warranted without re-deriving the policy condition in a second place.

**Hotfix H-1, committed first (`bfaf89d`).** While writing this phase, §7 R14 was found to be
wrong about its own severity: the repeated-value leak it filed as "becomes a real leak the moment
Phase 15 makes `EXTERNAL_LLM` reachable" is **already live** in the shipped contour 2. The
aggregator dedups on `(category, value_fingerprint)` and the M4 redaction algorithm resolved a
finding to *a* span, so N occurrences of one value produced N−1 leaks — reproduced against the
shipped guard and closed in a separate commit, per the standalone-hotfix decision. Its own
deviation (a finding resolves to *every* span it occupies) is recorded in `redaction.py`.

**Deviations from the plan as written**, all decided during implementation:

1. **The guard formulation is corrected; the fidelity cost is accepted.** The plan's Phase 15 text
   says "the canonical guard still sees the original so nothing is lost from the internal record".
   That cannot be true: the canonical is built from the *redacted* LLM output, so the LLM never
   sees the original. The guard is **not** disabled — it still runs at
   `stage=canonical, destination=persistence` — but on this path it inspects a canonical built from
   placeholders, and `[PERSON_NAME]` inside `canonical.json` is correct behaviour, not a defect.
   `build_canonical_guard` was given no `llm_mode` awareness at all, and a test says so.
2. **`redacted.md` is a new storage kind**, not a log line and not a new event. The record of what
   crossed the boundary is mandatory evidence, a log line is rotated and holds no text, and
   Phase 14's "no new storage kind" precedent does not apply — Phase 14 sanitized an existing
   object, this creates a new entity. Written **only** when `redact` returned a different object
   (identity, not a re-derived policy condition), placeholders only, uploaded before the model
   call so a provider failure leaves both the verdict and the text on disk. `data["redacted_key"]`
   is **optional** rather than a permanent nullable key: at the trusted destination — the default,
   and essentially every run — there is nothing to point at, and a null key on 99% of documents
   would be a cross-package contract change (R11) for a non-event.
3. **Neither version moves.** `DETECTOR_VERSION` stays 1.2.0 and `PII_POLICY_VERSION` stays 2.0.0:
   the `EXTERNAL_LLM` override already existed in the table, and this phase changes which
   destination is *supplied*, not any decision rule, so §4.8's "any change that alters a decision"
   does not fire. A stored `pii_result.json` records `destination: external_llm`, which is what
   makes such a verdict interpretable without a bump. **Recorded gap:** the redaction mechanism has
   no version constant, so a stored artifact cannot be re-derived to prove *what* was removed —
   filed for M6, as is the missing `REDACTOR_VERSION`.
4. **The refusal raises `InvalidPIIInputError`, not a new `ConfigurationError`**, and is resolved
   from `build_document_gate`, so the worker has one start-up failure mode rather than two. A single
   trailing `/` is ignored on both sides: without it a correct configuration fails for a cosmetic
   reason, and the comparison is otherwise exact, so a slash still cannot launder an untrusted host
   (tested against `169.254.169.254`, `localhost`, and a suffix-confusion host).
5. **`pii.redacted` is a log line, not an event.** The policy already appends one warning per
   `REDACT` action, and those reach `pii_result.json` and the §4.7 block in both the frontmatter
   and the event `data`. One structured `pii_redacted` line joins them. The audit *sink* stays
   deferred to M6, as it has since M4.
6. **OCR is documented, not gated.** A "Boundaries this pipeline does not gate" section in
   `app/pipeline/pipeline.py` names `handle_converting`'s `self._ocr.to_markdown(...)`, states that
   the same `ai_*` settings drive it so `llm_mode` moves the extraction call and leaves the image
   exposure untouched, and records the pre-OCR control as out of scope. `__init__` warns at
   start-up when `external_llm` is selected, and a test asserts the docstring still names the call
   so a refactor cannot quietly delete the claim.

**Unplanned change, and the one worth reading.** Two of the tests the plan asked for could not be
written as specified. `AGE`/`GENDER`/`NATIONALITY` **are** in `REDACT_ON_EXTERNAL` — they are
demographics and demographics identify — so an external provider sees `(Ж, [AGE])` where the
persistence contour deliberately preserves `(М, 39 лет)`. The plan's "the note stays legible"
carve-out belongs to the guard, and the text sent across a boundary is not a note anyone reads.
`test_the_external_boundary_masks_the_age_and_the_persistence_one_does_not` pins the shipped
behaviour, because the alternative is a reader assuming a survival guarantee that does not hold
here. Whether masking an age is the right trade on an external boundary is M6 calibration with real
findings, and that test is where the argument starts.

### Phase 16 — NER detector [~] · P1 · **DEFERRED**

**Status.** Deferred, not partially implemented and not stubbed. This is a scope decision, not a
schedule slip: the deterministic chain is the whole chain as of Phase 13, and shipping an ML
detector would have meant adding a runtime dependency and an uncalibrated detector to a gate whose
entire value proposition is that its verdict is reproducible from a version string.

**What is deliberately left in place, unchanged:**

- `PIISource.NER` stays in `app/pii/models.py` — the enum member is part of the Phase 1 schema and
  `test_schemas.py` pins it. Removing it would be an enum removal, which §4.8 makes **breaking**.
  Keeping it costs nothing and keeps a later NER from being a breaking change to the artifact schema.
- `DETECTOR_VERSION` stays `1.2.0`. It is not bumped for a detector that does not exist.
- **No ML dependency**: no `torch`, `transformers`, `spacy`, `onnxruntime`, no model weights, no
  network model loading in `apps/ai-worker`. The `torch`/`transformers` entries in `uv.lock` arrive
  through `marker_pdf`/`marker-worker` and are OCR infrastructure, not NER.
- **No NER backend** and no model-configuration setting.
- **No change to the detector chain.** `build_detector_chain` keeps its three members in the same
  order. No NER detector is appended "disabled" — an unwired detector is untested code, and
  `test_chain_wires_every_declared_detector_in_a_fixed_order` is what records the absence.
- **No test changes to represent the deferral.** The existing chain test asserting three members *is*
  the record. Adding an assertion that NER is absent would be a tripwire that fires when Phase 16
  eventually lands, encoding a deferral as if it were a constraint.

Original scope, preserved for the record: `PIISource.NER` populated by a detector behind the existing
protocol, added **after** the deterministic detectors so it can only widen coverage, never override a
`BLOCK`; graceful no-op when no model is configured. (§45.18)

**Revisit conditions — all four must hold before any NER work is accepted:**

1. It is scoped as a **separate ML evaluation task**, not a M5 phase. M5 does not reopen.
2. An **environment capable of running the selected model** — the current dev/CI environment is not
   one, and pretending otherwise is how a phase "ships" untested.
3. **Evaluation on a real PII fixture dataset** — real documents with real PII, not synthetic
   positives, because a synthetic set cannot produce a false-positive rate and the false-positive
   rate is the only number that decides whether this detector is affordable.
4. **Acceptance on measured precision and recall** against that dataset, with the numbers in the
   phase status. Recall alone disqualifies it: a NER that claims every name in a note is not better
   than the pattern chain, it is slower.

**NER may remain disabled until those conditions are satisfied.** Nothing in the gate is blocked on
it: §7 open decision 15 already recorded that NER is P1, may stay off, and that nothing else in M5
depends on it. The coverage it would add — free-prose names the pattern chain misses — is a
detection-recall question, and detection recall is M6's subject, not M5's.

#### Phase 16 Deferral Status

`PIISource.NER` present and schema-pinned, `DETECTOR_VERSION` at `1.2.0`, chain at three members
(`StructuredFieldPIIDetector → PatternPIIDetector → SecretPIIDetector`), no ML dependency in
`apps/ai-worker/pyproject.toml`, no NER detector class in `app/pii/detectors.py`. No code change was
made to defer this phase, which is the point: a deferral that needed a commit would have been a
change. Status synchronized across all three places (§1 table `[~]`, this heading, §6 item 16).

### Phase 17 — `REVIEW` combination threshold [x] · P1

The §13.1 "unknown limitation" closed: unexpected high-risk **combinations** escalate to `REVIEW`
instead of `ALLOW`. Policy data, not code (IMPL_ARCH §17) — a new `PIICombinationRule` table owned by
`PIIPolicy` (§4.13). `PII_POLICY_VERSION` 2.0.0→**3.0.0**, **not** the `2.1.0` this block originally
stated: §4.8 makes major = "any change that alters a decision for any input", and the rule turns
`ALLOW` into `REVIEW` for inputs that return `ALLOW` today (Revision 3 (c)). `REVIEW` still never
auto-redacts (§7 open decision 14). Deps: Phase 14. (§45.19)

**The shipped rule, and why it is the narrow one.** ORDER §13.1 offers two example thresholds — "≥2
distinct HIGH categories" and "identity + government ID in one free-text leaf". Both were measured
against the whole existing dataset and **both were rejected**, which is the substance of this phase:

| candidate rule | why not |
|---|---|
| ≥2 distinct HIGH categories | СНИЛС + ОМС + № карты is **three** HIGH categories and the normal shape of a Russian medical record. This halts routine care — the exact failure §0's "presence never blocks" invariant exists to prevent. |
| identity + government ID | Fires on `IDENTIFIER_MARKER` (`PERSON_NAME` + `SNILS`), which is Phase 13's **deliberate allow path**. ФИО + СНИЛС is the single most normal pair in the domain. |
| **≥2 distinct government identifiers** → `REVIEW` | **Shipped.** Two state identifiers in one document is a combination worth a human, fires on the §45.19 accept case exactly, and is silent on all six existing fixtures. |

Measured evidence for the "no existing fixture changes" claim, from the real chain, real aggregator
and real `walk_string_leaves` over all six fixtures (`CATEGORY_RISK`, `PII_CATEGORY_GROUPS['government']`):

| fixture | categories | HIGH | government |
|---|---|---|---|
| `clean/generic-notice-01.md` | — | 0 | 0 |
| `patient/synthetic-consultation-01.md` | 7 | 1 | 0 |
| `appointment/synthetic-registration-01.md` | 2 | 1 | 0 |
| `malicious/synthetic-injection-01.md` | 2 | 1 | 0 |
| `canonical/appointment/…-note-01.json` | 3 | 1 | 0 |
| `canonical/laboratory/…-note-01.json` | 4 | 1 | 0 |

No fixture has a single government identifier, so the shipped rule is dormant on the entire dataset
and no expected decision moved. That is a test, not a comment.

**`REVIEW` reaches production for the first time in this phase.** M4 Phase 5 recorded it as gap 1: at
`INTERNAL_LLM` the engine could only return `ALLOW`/`ALLOW_WITH_WARNING`/`BLOCK`, so Phase 11's
`PII_REVIEW_REQUIRED` halt path had never executed. It does now, and it is asserted end to end.

**Accept:** `SNILS` + `INSURANCE_NUMBER` + `PERSON_NAME` is `REVIEW`; the same leaf with only
`PERSON_NAME` is `ALLOW`. Tightened at implementation: `PERSON_NAME` + `SNILS` is also asserted
`ALLOW` (the narrowness assertion, and the `IDENTIFIER_MARKER` regression), `REVIEW` never writes a
`REDACT` into `actions`, the pipeline halts before the LLM is called with zero artifacts, all six
fixtures keep their decisions, and `PII_POLICY_VERSION == "3.0.0"`.

#### Phase 17 Implementation Status

Implemented and shipped. Policy data only — no detector, aggregator, guard or pipeline logic changed.
`PII_POLICY_VERSION` **3.0.0** (was 2.0.0), `DETECTOR_VERSION` **1.2.0** (unmoved). Suite: **809
passed** (770 before the phase, +39). `make lint` reports the same 4 pre-existing `packages/storage`
errors and nothing else; `uvx ruff format --check apps/ai-worker/app/pii` clean; `packages/storage` 19
passed. Smoke check: `1.2.0 3.0.0`. Status synchronized across all three places (§1 table `[x]`, this
heading, §6 item 17).

**Files changed**

| file | change |
|---|---|
| `app/pii/policy.py` | `PIICombinationRule` (3 validators + `matches` + `reason`); `PIIPolicy.combinations` + `_require_known_groups`; `_default_combinations()`; `DEFAULT_POLICY.combinations`; `DefaultPolicyEngine._combination()`; `_decide(actions, escalation)`; `DEFAULT_POLICY_VERSION` 2.0.0→3.0.0; `__all__` |
| `app/pii/__init__.py` | `PIICombinationRule` exported (import + `__all__`) |
| `app/pii/detectors.py` | docstring only — the `1.2.0 2.0.0` smoke-check claim is now `1.2.0 3.0.0` |
| `tests/unit/pii/test_combination_policy.py` | **new**, 27 tests |
| `tests/unit/pipeline/test_pipeline.py` | `COMBINATION_MARKER` fixture + 3 tests (contour 1 review, allow/review separation, contour 2 halt) |
| `tests/unit/pii/test_manifest_verification.py` | +2 tests: the combination never fires on a fixture (×2 boundaries), and the dataset carries no government identifier |
| `tests/unit/pii/{test_external_boundary,test_persistence_contract,test_policy_gate}.py` | the three `2.0.0` pins → `3.0.0`, with the reasoning rewritten (one test renamed: "did not move" was no longer true) |
| `IMPL_PLAN.md` | Revision 3, §1, §3, §4.7, §4.8, §4.13, §5, §6, §7 |

**Acceptance criteria, all ten verified**

| # | criterion | verified by |
|---|---|---|
| 1 | `PERSON_NAME + SNILS` does not trigger `REVIEW` | `test_person_name_and_snils_stay_allow`; `test_identifiers_alone_do_not_block_even_with_a_real_gate` (pre-existing) |
| 2 | `PERSON_NAME + SNILS + INSURANCE_NUMBER` triggers `REVIEW` | `test_person_name_and_snils_and_insurance_number_is_review`; `test_two_government_identifiers_review_through_the_real_gate` |
| 3 | `REVIEW` never introduces `REDACT` actions | `test_review_never_adds_a_redact_action` (compares the `actions` map against a combination-free policy) |
| 4 | `REVIEW` halts before LLM execution | `test_two_government_identifiers_review_through_the_real_gate` — `extract_canonical.called is False` |
| 5 | no downstream artifacts for a `REVIEW` halt | same test, `upload_bytes.call_args_list == []`; contour 2 in `test_a_combination_halts_contour_2_before_any_dump` |
| 6 | all existing fixtures keep their decisions | `test_no_fixture_trips_the_combination_threshold` (4 fixtures × 2 boundaries) + the pre-existing per-fixture equality assertions; `test_no_fixture_carries_a_government_identifier_at_all` |
| 7 | `PII_POLICY_VERSION == "3.0.0"` | `test_the_rule_is_reachable_through_the_stamped_policy_version` + the three rewritten pins |
| 8 | version reflected consistently in metadata/tests/docs | 3 test pins, `detectors.py` docstring, §4.7 example, §4.8, §7 roadmap — all corrected; artifact/frontmatter carry the live constant (pre-existing test) |
| 9 | the rule is reproducible from the persisted version | `test_the_rule_is_reachable_through_the_stamped_policy_version` — the table lives on `PIIPolicy`, and `PII_POLICY_VERSION` *is* `DEFAULT_POLICY.version` |
| 10 | Phase 16 absent from the runtime chain | pre-existing `test_chain_wires_every_declared_detector_in_a_fixed_order` pins exactly three detectors, and was **not modified**; no NER class, no ML dependency, no setting |

**Decision matrix, measured** (real engine, a `combinations=()` policy for "before"):

| input | before 2.0.0 | after 3.0.0 |
|---|---|---|
| no findings | `allow` | `allow` |
| one government id (`SNILS`) | `allow` | `allow` |
| `PERSON_NAME` alone | `allow` | `allow` |
| `PERSON_NAME + SNILS` | `allow` | `allow` |
| `SNILS + INSURANCE_NUMBER` | `allow` | **`review`** |
| `SNILS + INSURANCE_NUMBER + PERSON_NAME` | `allow` | **`review`** |
| `SNILS + PASSPORT + INN` | `allow` | **`review`** |
| `MRN + TICKET_NUMBER` (2 HIGH, not government) | `allow` | `allow` |
| `SNILS + SECRET` | `block` | `block` |
| `SNILS + INSURANCE_NUMBER + SECRET` | `block` | `block` |
| `SNILS` (external_llm) | `allow_with_warning` | `allow_with_warning` |
| `SNILS + INSURANCE_NUMBER` (external_llm) | `allow_with_warning` | **`review`** |
| `SNILS` (unknown destination) | `review` | `review` |
| `SNILS + INSURANCE_NUMBER` (unknown destination) | `review` | `review` |
| `SNILS` (canonical+persistence) | `allow_with_warning` | `allow_with_warning` |
| `SNILS + INSURANCE_NUMBER` (canonical+persistence) | `allow_with_warning` | **`review`** |
| `SNILS + INSURANCE_NUMBER` (internal, no redactor) | `allow` | **`review`** |

Read the last four rows together, because they are the two design decisions rather than consequences.
At `canonical`+`persistence` the `REVIEW` arrives **with** the `REDACT` actions intact — the escalation
outranks the save, so the document halts before either dump point instead of being written masked. At
`external_llm` the same split appears in the other direction: a `REVIEW` that would otherwise be
`allow_with_warning`, with the redaction still in `actions`. `BLOCK` is unmoved in every row, which is
what keeps `SECRET` the only block source.

**The tests were mutation-tested, because a narrowness rule is only as real as the assertions holding
it in place.** Two mutations were applied to the shipped table and the suite re-run:

| mutation | result |
|---|---|
| `combinations=()` — the rule removed | **10 failures** across `test_combination_policy.py` and `test_pipeline.py`, including both pipeline tests and every `actions`-preservation assertion |
| `requires_groups={"government", "identity"}` — the **rejected** "identity + government" rule from ORDER §13.1 | **21 failures**: the 4 narrowness tests, the canonical-guard contour, and the entire Phase 15 external-redaction path |

The second row is the concrete answer to "why not the wider rule": it does not merely trip the new
tests, it takes down the canonical guard and every redaction test Phase 15 shipped, because ФИО +
one identifier is the shape of essentially every patient document in the dataset. Both mutations were
reverted and the suite re-verified at 809.

**Deviations**

1. **`2.1.0` → `3.0.0`**, approved and argued in §4.13 and §7. The roadmap number was wrong under
   §4.8's own definition, and Phase 14 is the precedent for correcting a roadmap rather than shipping a
   version that misdescribes the change.
2. **Document-scoped, not leaf-scoped.** ORDER §13.1 says "in one free-text leaf"; §4.13 records why
   the locked `PolicyEngine.evaluate` signature cannot express it, and that document scope is the
   conservative direction. `test_a_combination_applies_at_every_destination` makes the deviation visible.
3. **The rule narrows ORDER §13.1's examples rather than implementing one of them.** Recorded with the
   measurement in the Phase 17 block; the rejected rules are asserted as *not*-the-behaviour in
   `test_two_high_categories_that_are_not_government_still_allow` and
   `test_identity_plus_a_government_identifier_still_allows`, so the decision cannot be quietly undone.

**Residual risk:** R15, unchanged by this phase and now sharper — `REVIEW` is production-reachable, so
a tripping document halts with zero artifacts, one `document.processing.failed`, and no human consumer.
The mitigating evidence is `test_no_fixture_carries_a_government_identifier_at_all`: the rule is dormant
across the whole dataset, and the day that stops being true the alarm fires before production does.
Real-world Russian records with СНИЛС *and* ОМС are the untested population; M6 measures them.



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
  "detector_version": "1.2.0",
  "policy_version": "3.0.0",
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
the §7 roadmap — corrected in Revision 3 (d): the block originally read `detector_version "1.3.0"`,
which was written when Phase 16's NER was expected to land and which that phase's deferral made wrong.
Phase 10 emits whatever is current at the time, and a test asserts the block carries the live
constants rather than a copy.

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
The M5 roadmap that moves both constants — `1.0.0 → 1.1.0 → 1.2.0` and `1.0.0 → 2.0.0 → 3.0.0` —
is in §7 (Versioning policy). The second chain's last step was originally written as `2.1.0` and is
corrected in Revision 3 (c); §7 records why, and Phase 16's deferral means the detector chain ends M5
at `1.2.0`.

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

### 4.13 Combination rules (new in M5, Phase 17)

ORDER §13.1's "unknown limitation": every rule so far is **per category**, so the base table has no
way to say that one finding is fine and two together are not. The two natural candidate thresholds
were both measured and rejected (Phase 17 block: ≥2 HIGH halts routine medical records; identity +
government ID fires on `IDENTIFIER_MARKER`, Phase 13's deliberate allow path). What ships is one row:

```text
PIICombinationRule(requires_groups={"government"}, min_count=2, decision=REVIEW)
  fires when >= 2 DISTINCT categories from the "government" group appear in one document
  -> document decision escalates to REVIEW
```

`PII_CATEGORY_GROUPS["government"]` = `PASSPORT NATIONAL_ID INSURANCE_NUMBER SNILS INN` — the five
categories the §4.11 persistence escalation already treats as a set, so the rule references the group
by name and cannot drift from it.

**Three properties this design holds, each because of a specific alternative that was wrong:**

1. **The rule lives in `PIIPolicy`, not in a module constant.** `PII_POLICY_VERSION` is
   `DEFAULT_POLICY.version`, and the entire reason the constant exists is that a stored
   `PIIScanResult` must be re-derivable from the version it names (Phase 14's §7 argument). A
   threshold table that the version does not name is a table a stored verdict cannot be reproduced
   from — which is acceptance criterion 9. `PIIPolicy.combinations` defaults to `()`, which keeps every
   existing hand-built policy in the tests valid.
2. **The combination escalates the *decision* and never touches `actions`.** §4.12 makes
   `actions[category]` the remediation channel, and the canonical sanitizer masks a leaf iff that
   action is `REDACT`. Writing `REVIEW` into the participating categories would stop the sanitizer
   masking those leaves in any future where `REVIEW` does not halt, and would make the per-category
   table lie about what it decided. So `evaluate` derives the escalation separately, `_decide` applies
   it, and the escalation is recorded in **`reasons`** — the field §4.12's triage story already names
   as "the only account of a review a human will ever see". A `REVIEW` that does not say *why* is a
   review nobody can triage. This is decision 14 (§7) holding structurally: `REVIEW` adds no `REDACT`,
   so a review still cannot rewrite the document it is asking about.
3. **`decision` on a combination rule may only be `REVIEW`.** Validated at construction. A rule that
   could emit `BLOCK` would make itself the second `BLOCK` source and contradict the invariant
   stated in `_default_rules()` — `SECRET` is the only thing that blocks, because a credential is a
   vulnerability rather than a fact about the document's subject. Constructing a `BLOCK` rule is a
   `PIIPolicyError` at import time, not a latent policy change.

**Document-scoped, not leaf-scoped — a recorded deviation.** ORDER §13.1's examples say "in one
free-text leaf". That is not expressible under the locked `PolicyEngine.evaluate(findings, context)`
signature: it receives one flat list, `PIIFinding` carries no path, and `canonical_guard.py`'s
docstring states the rationale for evaluating once over the union of all leaves — per-leaf verdicts
would have no defined precedence against each other. Document scope is therefore used, and **this is
recorded as a deviation from §13.1's wording rather than silently narrowed**. It is also strictly the
more conservative of the two: document scope catches a superset of the leaf-scoped cases, and with the
narrow threshold above, the wider scope costs nothing on the dataset (no fixture carries two
government identifiers at all).

**Version.** `PII_POLICY_VERSION` 2.0.0 → **3.0.0**. §4.8: minor = additive *and backward-compatible*;
major = "any change that alters a decision for any input". This rule returns `REVIEW` where the same
input returns `ALLOW` today, which is a decision change by the plan's own words, so minor is wrong and
the `2.1.0` this section's predecessor stated was inconsistent with the SemVer rule two sections above
it. Keeping `2.1.0` to preserve a roadmap number would have shipped a version that misdescribes the
change. Policy data, reversible without touching detection (IMPL_ARCH §17).

**No operator lever, deliberately.** There is no setting for this threshold, matching
`REDACTION_AVAILABLE`'s precedent that an operator must not be able to disable a security control
with an environment variable. The only way to soften the rule is a versioned edit to the policy data,
which is a reviewable commit rather than a config push. R15 records what that costs.

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

**Phase 17's tests — the combination table and the narrowness assertion.** The threshold is the one
rule whose failure mode is *over-firing*, so the tests that carry the security value here are the
negative ones, and the phase adds a new file rather than growing an existing one:

| test | asserts |
|---|---|
| `test_person_name_and_snils_stay_allow` | `PERSON_NAME` + `SNILS` → `ALLOW` (the `IDENTIFIER_MARKER` regression) |
| `test_three_categories_escalate_to_review` | `SNILS` + `INSURANCE_NUMBER` + `PERSON_NAME` → `REVIEW` (§45.19) |
| `test_single_government_identifier_does_not_escalate` | one government ID alone → `ALLOW` (the "both sides of the threshold") |
| `test_review_never_adds_a_redact_action` | the escalation reaches the decision and `reasons`, and `actions` is byte-identical to the pre-combination map |
| `test_combination_loses_to_block` | `SECRET` + two government IDs → `BLOCK`, not `REVIEW` (precedence) |
| `test_combination_is_recorded_in_reasons` | the reason string names the groups and the count |
| `test_combination_does_not_weaken_the_persistence_escalation` | at `stage=canonical, destination=persistence` a combination keeps the `REDACT` in `actions` |
| `test_no_fixture_changes_decision` | all six fixtures keep their measured decision at both boundaries — the availability guard, a test not a comment |
| `test_a_combination_rule_may_not_block` | a `BLOCK` combination is a `PIIPolicyError` at construction |
| `test_policy_with_no_combinations_is_unaffected` | `combinations=()` is the rollback switch and changes nothing |
| `test_pipeline_halts_on_review_before_the_llm_runs` | first production-reachable `REVIEW`: `error_code=PII_REVIEW_REQUIRED`, zero artifacts, LLM never called |
| `test_a_combination_halts_before_any_dump` | contour 2: the halt precedes both dump points (decision 16) |

**Files (new in M5).** `tests/unit/pii/{test_detectors_behaviour,test_aggregation_behaviour,test_policy_behaviour,test_redactor_behaviour,test_guard_behaviour,test_artifact,test_settings_boundary,test_combination_policy}.py`;
`tests/unit/pipeline/test_pipeline_pii.py`; extended `tests/fixtures/pii/manifest.json` + the
`laboratory/`, `appointment/`, `prescription/`, `mixed/` directories (declared in
`PII_FIXTURE_DIRECTORIES` but not yet created); `tests/support/pii_fixtures.py` delegate once the
dataset grows past the trio — and past it again: Phase 13 adds `appointment/`, the `2b8fdd0d` shape,
so the set is now clean/patient/appointment/malicious. **Phase 14 adds a second dataset**,
`tests/fixtures/pii/canonical/{appointment,laboratory}/` — canonical *payloads* rather than markdown,
because the leak did not happen in `marker.md`. It is deliberately outside the manifest: that
manifest's `expected_decision` is a document-stage property and its loader enumerates markdown
files, so canonical payloads are loaded directly by the guard and pipeline tests rather than
inventing a second manifest schema. `packages/storage/tests/test_keys.py` extended
in Phase 10.

**Commands:**

```bash
cd apps/ai-worker && uv run pytest tests/unit/pii -v          # focused (598 after Phase 17)
cd apps/ai-worker && uv run pytest                            # full: 436 baseline, must stay green
                                                           #   (809 after Phase 17)
cd apps/ai-worker && uv run pytest tests/unit/pipeline -v      # contour wiring, Phases 11/14/15/17
uvx ruff check apps/ai-worker/app/pii apps/ai-worker/tests/unit/pii apps/ai-worker/app/pipeline
uvx ruff format --check apps/ai-worker/app/pii
uv run --project packages/storage pytest packages/storage     # required from Phase 10 on
make lint                                                      # uvx ruff check apps packages tests
```

**Acceptance smoke check (from `apps/ai-worker`):**

```bash
uv run python -c "from app.pii import PIICategory, PIIScanResult, PIIGate, DETECTOR_VERSION, PII_POLICY_VERSION; print(DETECTOR_VERSION, PII_POLICY_VERSION)"
```

Expected after Phase 17: `1.2.0 3.0.0`. M5 introduces **no** new runtime dependency (stdlib
`re`/`hmac`/`hashlib` + Pydantic only) and **no** migration — and Phase 16's deferral keeps that true
for the whole milestone, since the deferred phase was the only one that would have added one.

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
10. **Phase 10 — Persistence surface** [x] — the artifact must exist before the pipeline can
    upload it (§45.07–09).
11. **Phase 11 — Contour 1 wiring** [x] — turns VS#1 into a real control. Contour 1 works here
    (§45.10–11).
12. **Phase 12 — Markdown redaction** [x] — needs the gate's findings; independent of the guard
    (§45.12).
13. **Phase 13 — Marker-shape fixture + structured & secret detectors** [x] — `SECRET` detection is
    the only `BLOCK` source, so it must exist before the guard is trusted (§45.13–14).
14. **Phase 14 — Canonical guard** [x] · VS#2 — the phase that closes the observed leak. After
    this, the milestone's purpose is met even if 15–17 slip (§45.15–16). Shipped with six recorded
    deviations, one of them unplanned: `date_of_birth.numeric` removed and `DETECTOR_VERSION` at
    **1.2.0** because §4.11's escalation made its recall claim load-bearing (R7, decision 17).
15. **Phase 15 — `EXTERNAL_LLM` destination + redaction** [x] · VS#3 — shipped behind an
    operator switch, with a hotfix in front of it: a repeated-value leak in contour 2 was found
    **live** while writing the phase and closed as a separate commit (H-1, `bfaf89d`) rather than
    left as the dormancy the plan had filed it as (§45.17).
16. **Phase 16 — NER detector** [~] · P1 · **DEFERRED** — out of M5. All four revisit conditions in the
    Phase 16 block must hold first, and the phase is a separate ML evaluation task, not a M5
    reopening (§45.18).
17. **Phase 17 — `REVIEW` combination threshold** [x] · P1 — policy data on top of Phase 14 (§45.19).
    Shipped as one narrow government-identifier rule (§4.13), `PII_POLICY_VERSION` → 3.0.0. Made
    `REVIEW` reachable at the production boundary for the first time.

Phases 12 and 13 are independent of each other and can run in either order. Each phase: implement →
update status in all three places (§1 table, §3 heading, §6 list) → pause for confirmation.
Deviations labeled `Deviation:` in the phase's Implementation Status block. Revision 3 found the
three-places rule broken for Phases 9, 11, 12 and 14 — the table lagged the headings — and repaired
it, which is the reason that rule is restated here rather than assumed.

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
  **Taken in Revision 3: Phase 16 is deferred outright** (see the Phase 16 block for the four revisit
  conditions). Nothing in the gate is blocked on it — the chain has been the whole chain since Phase
  13, and the coverage NER would add is a detection-recall question that belongs to M6's calibration,
  not to a gate whose contract is that a verdict is reproducible from a version string.
- **16. Contour 2 halts on `REVIEW` as well as `BLOCK`.** M4's `DECISION_REMEDIATION` table mapped
  `review → SANITIZE`, and Phase 14 changed that to `RETRY_THEN_FAIL` for both. The reason is
  decision 14: a document at `REVIEW` is one a human must look at, and rewriting it instead would
  mean the thing a human was asked to review is not the thing that was published. The name
  `RETRY_THEN_FAIL` is the *outcome*; **no retry is implemented** — there is no re-extraction path
  in this phase, and a constant that reads as "extraction is re-run" is corrected by a test that
  says so at the definition.
- **17. A date is not a `DATE_OF_BIRTH` unless something says whose it is.** Phase 14's escalation
  turned `pattern.date_of_birth.numeric` — which claimed *every* bare `YYYY-MM-DD` — into data
  loss, because `canonical.document_date` is a service date (IMPL_ARCH §34) that
  `render_document` writes into the frontmatter. The rule is removed and the claim moves to three
  anchored `_FIELDS` rows: a label, the `д.р.` abbreviation, and a patient's ФИO immediately in
  front of the date. Recall given up, deliberately: a date of birth in the *declined* construction
  (`для пациента Смирнова Ольга Ивановна, 1974-03-12`) is no longer found, because there is no
  field label to anchor to. See R7.

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
  and by `REVIEW` never auto-redacting. **Phase 14 turned this from a fidelity risk into a data-loss
  risk** and it is the phase's one unplanned change: once `DATE_OF_BIRTH` became `REDACT` at
  `canonical`+`persistence`, a detector rule that claims every bare ISO date stopped costing a
  masked line and started destroying `document_date` — a typed envelope field the frontmatter
  renders verbatim. The rule is removed and the category is claimed only by anchored rules
  (decision 17), with `test_a_service_date_is_never_a_date_of_birth` and
  `test_canonical_guard_keeps_the_clinician_and_the_service_date` as the tripwires. The general
  lesson, recorded because it generalises: **escalating a category makes its detector's recall
  claims load-bearing in a way they were not before**, and any rule claiming a whole document's
  dates is a rule about service dates too.
- **R8 — fingerprint treated as a safe hash.** Mitigated by locking HMAC+salt, keeping fingerprints
  out of logs and the persisted block, and asserting both.
- **R9 — a `REVIEW` decision with no consumer.** `REVIEW` halts the document and there is no human
  UI yet (IMPL_ARCH §2.1, ORDER §2). A document awaiting review stalls silently. Phase 11
  implements what exists: `document.processing.failed` with `job_type="pii_gate"` and
  `error_code="PII_REVIEW_REQUIRED"`, a structured log line carrying the decision, risk level and
  category counts, and no artifacts — so the verdict is visible to a human reading the queue or the
  logs even though no UI consumes it. The plan's `processing_status='needs_review'` has no field to
  live in (see Phase 11's deviation note); a durable `needs_review` state needs the audit sink M4
  deferred, and the UI is out of M5 and flagged rather than hidden.
- **R10 — compliance misreading.** Someone cites this gate as HIPAA/152-ФЗ/GDPR proof. Mitigated by
  the explicit invariant in §0 and IMPL_ARCH §37.
- **R11 — `EVENTS.md` staleness.** No new event in M5, so the catalog at `EVENTS.md:8-18` does not
  change. But `data["pii"]` and `data["classification"]` are new keys on an existing event; if
  M6 formalizes the `data` shape, the catalog must be updated in the same commit.
- **R12 — no type-check in CI.** Same as every prior contour; mitigated by Pydantic + import smoke
  checks + ruff, per existing convention.
- **R13 — contour 1 is narrower than the architecture describes until Phase 13.** Phase 11 wires the
  gate with the *implemented* detector subset, because `StructuredFieldPIIDetector` and
  `SecretPIIDetector` still raise. The gap is specific and named: `SecretPIIDetector` is the only
  `BLOCK` source, so a document carrying a credential is currently **allowed** through extraction.
  It is a narrower gate, not a laxer one, and it is visible in three places rather than assumed
  away: `build_available_detector_chain`'s docstring, the Phase 11 status block, and
  `test_available_chain_is_a_strict_subset_of_the_full_chain`, which fails the moment the two chains
  are   equal. Phase 13 is the only thing that closes it, and the roadmap already orders Phase 13
  before the Phase 14 guard is trusted.
  **Closed in Phase 13.** Both detectors scan, so `build_available_detector_chain` is deleted rather
  than left to rot, the pipeline wires `build_document_gate` directly, and a credential-bearing
  document halts: `test_pipeline.py` asserts `BLOCK` end to end, and
  `test_manifest_verification.py::test_only_a_credential_blocks_at_every_boundary` asserts it at both
  boundaries with the same patient fixture allowed alongside. A risk register that never closes is how
  a register stops being read, so this entry is marked rather than left standing as if it applied.
- **R14 — a redacted document that still carries the value.** The gate's findings index the
  *canonicalised* `raw_text`, not the markdown, so a redactor that trusted their offsets would
  replace unrelated text and leave the value in place. Mitigated in Phase 12 by verifying the offset
  against the finding's value before trusting it and locating the value otherwise, with
  `test_wrong_offsets_are_never_trusted` and the fixture round-trip as the assertions. Residual and
  **not** fixed by redaction: a value the detector found only *partially* (the fixture's address is
  detected as `г. Москва`, so `ул. Примерная, д. 1, кв. 2` survives) and a value appearing **twice**
  in one document, which the aggregator's dedup collapses to one finding and therefore one
  replacement. Both are detection-side limits;   the second becomes a live leak when Phase 15 makes
  `destination=EXTERNAL_LLM` reachable, and is filed there.
- **R15 — `REVIEW` becomes production-reachable, and still has no consumer.** Phase 17 makes the first
  real `REVIEW` fire in production, which is the point, and it inherits R9 wholesale: no human UI, no
  audit sink, no durable `needs_review` state. A tripping document halts with **zero artifacts** and
  a single `document.processing.failed` carrying `error_code="PII_REVIEW_REQUIRED"` — so the evidence
  a reviewer needs exists only in the logs, and the document is neither queued anywhere nor recoverable
  without a re-upload. Phase 17 deliberately does **not** add a durable review state (that needs the
  audit sink M4 deferred); it makes the gap visible instead of leaving `REVIEW` unreachable, which
  would have been the worse outcome. Two further costs, both accepted rather than hidden:
  - **No operator lever.** Following `REDACTION_AVAILABLE`'s precedent, there is no setting to soften
    the threshold — an operator must not be able to disable a control with an environment variable.
    The only path is a versioned edit to `PIIPolicy.combinations`, which is a reviewable commit rather
    than a config push. If a tripping volume proves unacceptable, that is a policy change with a
    version bump, deliberately.
  - **Availability depends on the rule staying narrow.** Mitigated by measurement rather than by
    assertion: no fixture in the dataset carries *any* government identifier, so the rule is dormant
    across all six and `test_no_fixture_changes_decision` fails the day one starts tripping. The
    residual risk is real-world data this repo does not have, and it is M6's to measure.
  Residual and **not** fixed in Phase 17: everything above. Filed against R9 rather than duplicated.

### Versioning policy (locked)

`DETECTOR_VERSION = "1.0.0"`, `PII_POLICY_VERSION = "1.0.0"` at M4. Patch = docs/comments only.
Minor = additive (new optional field, new `PIICategory` with a matching policy row) and
backward-compatible. Major = breaking (required field change, enum removal, **decision-rule
change**) — any change that alters a decision for any input bumps the policy version, so a stored
`PIIScanResult` always names the policy that produced it. Detector and policy versions move
independently, mirroring `classifier_version` (currently `2.1.0`).

M5 version roadmap:

```text
DETECTOR_VERSION    1.0.0 ──(Ph 9, additive detect_text)──▶ 1.1.0 ──(Ph 14)──▶ 1.2.0 ──(Ph 16, NER)──▶ 1.3.0  [DEFERRED]
PII_POLICY_VERSION  1.0.0 ──(Ph 14, persistence escalation)▶ 2.0.0 ──(Ph 17, combinations)▶ 3.0.0
```

`1.0.0 → 2.0.0` is **major** because it changes a decision: at `stage=canonical,
destination=persistence`, identity/contact/government/medical_id move from `allow` to `redact`
(§4.11). A document that would previously have been persisted with a name in it is now masked. That
is the milestone's entire point, and it is exactly the change a stored `policy_version` exists to
make interpretable.

`2.0.0 → 3.0.0` is **major for the same reason**, and Revision 3 corrects this roadmap's own
`2.1.0` (c). §4.8 defines minor as additive *and backward-compatible* and major as "any change that
alters a decision for any input". Phase 17's rule returns `REVIEW` for a document that returns `ALLOW`
today, so it fails the backward-compatible half of minor by the plan's own definition. The reason to
care about the distinction, rather than treating it as bookkeeping: the number's whole job is to let a
stored `PIIScanResult` name the policy that produced it, and a `2.1.0` that means "additive and
backward-compatible" attached to a rule that changed a decision makes that name a lie — the same
argument that settled `1.1.0 → 1.2.0` below. Preserving the roadmap number would have been cheaper
than being right.

The detector chain ends M5 at `1.2.0` because Phase 16 is deferred. The `1.3.0` step above stays on
the roadmap: a NER detector, if the revisit conditions are ever met, is additive to a chain that
already detects `PIISource`, so minor remains the right magnitude then.

`1.1.0 → 1.2.0` is a **deviation from the roadmap this section originally stated**, where Phase 16's
NER was the step that earned `1.2.0`. Phase 14 removed `date_of_birth.numeric` and added
`date_of_birth.after_patient_name` (§14.4, "a date that is only a date"), which is a rule leaving
and a rule arriving: not the additive minor §4.8 describes, and not major either, since no required
field changed and no enum member was removed. What settles it is the reason the constant exists at
all — a stored `PIIScanResult` must name a detector whose behaviour reproduces it, and a `1.1.0`
result carrying a date of birth nobody can re-derive is a historical verdict that has become a lie.

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
