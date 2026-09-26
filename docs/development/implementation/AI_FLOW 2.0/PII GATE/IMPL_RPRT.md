# PII Gate — Implementation report

- **Date:** 2026-09-26
- **Detector version:** `1.0.0` · **Policy version:** `1.0.0`
- **Status:** contract complete (M4, all 7 phases `[x]`) — **not wired**; no detector, policy engine, redactor, gate or canonical guard implementation ships in M4, and `app/pipeline` does not import `app.pii`
- **Scope:** `apps/ai-worker/app/pii/` (13 modules) + `tests/unit/pii/` + `tests/fixtures/pii/`
- **Plan docs:** [IMPL_PLAN.md](./IMPL_PLAN.md) (M4, all `[x]`) · [IMPL_ARCH.md](./IMPL_ARCH.md) (design reference)
- **Code-adjacent doc:** [README.md](../../../../../apps/ai-worker/app/pii/README.md) — модуль-по-модулю, на русском
- **Verification:** ai-worker suite **436 passed** (174 baseline + **262** PII contract tests), `ruff` clean on the PII paths

> **Read this first if you are the M5 implementer.** M4 delivers a *contract*,
> not a feature. Five base classes raise `NotImplementedError` by design. Nothing
> in this milestone scans, decides, redacts, writes or blocks anything. The
> handoff list is [§12](#12-что-осталось-на-m5).

---

## 1. Executive summary

The PII gate answers **“does this document contain sensitive data, and may it
proceed?”** — a capability orthogonal to Classification 2.0, which answers *what
kind of document is this*. The two never import each other at runtime.

**It exists because of an observed leak, not a hypothetical one.** In
`.dev/flow_upload_test/`, two real documents carry the patient's full name inside
`canonical.json` — not in `marker.md`, but copied by the extraction model into
the free prose of a doctor's note:

```
2b8fdd0d.../canonical.json → fields.note: "...для пациента Шадеркина Дениса
                                Сергеевича. Номер талона: 2026030709303211960141."
fbbcb675.../canonical.json → fields.note: "...для пациента Шадеркина Дениса
                                Сергеевича (М, 39 лет)..."
```

That content then persisted into `document_extractions.data`, because
`DocumentAnalysisCompleted.data` is written verbatim
(`apps/account-api/app/services/documents.py:536`). A prompt rule asking the
model not to do this is a *request*, not a control — which is exactly why
`canonical.yaml:100` failed. Hence the second guard line (`canonical_guard.py`),
the only contract in M4 that stops this specific leak.

**Headline design decisions:**

| Decision | Rationale |
|---|---|
| PII presence alone never blocks | A medical record is *expected* to carry patient identity; blocking on presence would halt every document the platform exists to process. Only `secret` blocks — that is a security incident, not a fact about the document's subject. |
| The gate is document-level, not per-schema | `PIIGate.inspect(document, context)`, not `AppointmentPIIGate`. One gate for every type, so a new document type is covered the day it is added. |
| Raw PII cannot cross a boundary **structurally** | `value` is `Field(exclude=True)`; summaries have no value field at all. Not a call-site discipline — a control. |
| Fingerprint is HMAC, not a hash | Low-entropy identifiers (СНИЛС, полис ОМС, дата рождения) are brute-forceable in seconds; a plain `sha256` column would be the value in disguise. |
| Traversal and judgement are separate | The canonical walk enumerates every string leaf with no key allow-list; the detector decides what is PII. An allow-list inside the walk would hide a second, undocumented judgement. |
| Stubs raise instead of returning `[]` | A stub returning `[]` is fail-open: the pipeline looks healthy and every document passes. |

---

## 2. Architecture & flow

```text
NormalizedDocument ──► detect ──► aggregate ──► policy ──► decide ──► PIIScanResult
   (общий тип)        детекторы   дедупликация   правила   вердикт     (безопасный)
                                        │
                                        └── dedup key: (category, value_fingerprint)

BaseCanonical.model_dump() ──► walk_string_leaves ──► detect ──► CanonicalPIIViolation
  (второй контур)                  (все строковые листья)              (только маски)
```

**Two independent contours,** kept separable in the persisted result via
`PIISource.CANONICAL`: `stage=DOCUMENT` (source scan) and `stage=CANONICAL`
(post-extraction guard). The guard's findings are evaluated with
`CANONICAL_POLICY_STAGE`/`CANONICAL_POLICY_DESTINATION` because the *same values*
evaluate differently at a persistence boundary than at a source boundary.

**Order is locked: detect → aggregate → policy → decide.** Detectors first
because policy has nothing to reason about without findings; aggregation *before*
policy because the dedup key is `(category, value_fingerprint)` and a policy
counting pre-dedup findings would inflate its own risk assessment with one value
seen twice.

Boundary invariants (locked, test-enforced):

- **Deterministic where it can be:** the payload walk visits every string leaf in a
  fixed order, de-duplication is by fingerprint, and policy precedence is a total
  order. Detection confidence thresholds are M5's calibration, not M4's.
- **No runtime coupling:** `app.pii` imports no `app.classification` and no
  `packages.canonical` type. The two shared types are `TYPE_CHECKING`-only.
- **Document-level capability:** one gate, all document types.
- **Fail closed:** an undecidable gate raises `PIIDecisionError`; the pipeline
  must not proceed to extraction. An exception, not a default — the tempting
  default is `ALLOW`, and a gate that says "clean" whenever confused is worse
  than no gate.
- **No new event, no new table, no migration:** the verdict rides the existing
  frontmatter/event block, mirroring Classification 2.0.

---

## 3. Code layout

```text
apps/ai-worker/app/pii/
├── __init__.py          # public API: 64 sorted, resolvable exports
├── models.py            # Phase 1 — 7 enums, PIIFinding, PIIFindingSummary,
│                        #   PIIScanResult, PIIAuditRecord, PIIDecisionResult
├── exceptions.py        # PIIError + 5 subclasses (PIIDecisionError = fail-closed)
├── schemas.py           # Phase 2 — PII_SCAN_RESULT_SCHEMA, PII_FINDING_SCHEMA
│                        #   (derived from the models, never hand-maintained)
├── detectors.py         # Phase 3 — PIIDetector protocol, 4 stubs, Composite;
│                        #   DETECTOR_VERSION
├── aggregation.py       # Phase 3 — PIIAggregator protocol + stub; dedup rule
├── masking.py           # Phase 4 — mask_pii_value, hash_pii_value (HMAC-SHA256);
│                        #   MASK_RULES, FIXED_MASKS, FINGERPRINT_PREFIX
├── redaction.py         # Phase 4 — PIIRedactor protocol, RedactorBase,
│                        #   PlaceholderRedactor, placeholder_for
├── policy.py            # Phase 5 — DEFAULT_POLICY, CATEGORY_RISK, PIIRule,
│                        #   PIIPolicy, PIIPolicyContext, PolicyEngine;
│                        #   PII_POLICY_VERSION
├── gate.py              # Phase 5 — PIIGate protocol + stub, DECISION_OUTCOMES
├── canonical_guard.py   # Phase 6 — walk_string_leaves, CanonicalPIIViolation,
│                        #   CanonicalPIIInspector(+Base), PIIRemediation,
│                        #   DECISION_REMEDIATION
├── persistence.py       # Phase 7 — "pii" block key set, PII_ARTIFACT_FILENAME,
│                        #   PII_AUDIT_EVENTS, DECISION_AUDIT_EVENTS
├── fixtures.py          # Phase 7 — app-owned manifest loader, stdlib-only
└── README.md            # comprehensive module documentation (rus.)
```

Plus `tests/unit/pii/` (8 files, 262 tests), `tests/fixtures/pii/` (manifest +
3 synthetic fixtures) and `tests/support/pii_imports.py` (AST import-guard
helpers). Flat layout mirrors `app/classification/` — *not* IMPL_ARCH Phase 1's
`pii/domain/` subpackage; recorded as a deliberate deviation so M5 does not
re-litigate it.

---

## 4. Domain model (`models.py`)

- **`PIICategory`** — 23 members in 6 groups. §4.1's heading said "22 values";
  the taxonomy is **23** (recorded deviation — `medical_record_number` is its own
  category, which is why the count is one higher than the plan's prose).
- **`PIISource`** — `pattern · structured_field · ner · llm · canonical`.
  `canonical` marks a finding raised by the post-extraction guard.
- **`PIIRiskLevel`** — `low · medium · high · critical`. Assigned by *policy*,
  never by detection.
- **`PIIAction`** — `allow · warn · redact · review · block` (per-category).
- **`PIIDecision`** — `allow · allow_with_warning · review · block` (document
  level). Follows IMPL_ARCH's enum, not the `{"status": "allowed"}` sketch in ORDER §2;
  the IMPL_ARCH enum wins and the deviation is recorded in the plan.
- **`PIIDestination`** — `internal_llm · external_llm · persistence · unknown`.
- **`PIIScanStage`** — `document · canonical`.

**The three types that cross no boundary wrong:**

| Type | Carries | Explicitly cannot carry |
|---|---|---|
| `PIIFinding` | raw `value`, `masked_value`, `value_fingerprint`, offsets | — (in-process only; `value`/`value_fingerprint` are `Field(exclude=True)`) |
| `PIIFindingSummary` | `masked_value`, category, confidence, source, detector, offsets | no `value`, no `value_fingerprint` |
| `PIIScanResult` | decision, risk, stage, destination, findings[], counts, versions | no value, no fingerprint, no action map |
| `PIIAuditRecord` | event, document id, stage, decision, risk, count, versions | no value, no fingerprint, no detector internals |

`PIIFinding.value` is `str` and **required** (not `str | None` as in IMPL_ARCH §5) so a
finding cannot exist without the text that justified it — redaction needs the
real substring in-process, and the alternative makes "no raw value" a call-site
discipline instead of a control.

> ⚠️ `model_json_schema()` on `PIIFinding` still lists `value` and
> `value_fingerprint` — `exclude` is a serialization concern, not a schema one.
> `PIIFinding` is **not** a wire contract; schemas and artifacts derive from
> `PIIFindingSummary` only. This is why §5 assertion #2 is satisfied from the
> summary type (recorded deviation).

---

## 5. Masking & fingerprinting (`masking.py`) — fully implemented

The only engine in M4 with no `NotImplementedError`, because both functions are
fully determined pure functions.

**`mask_pii_value(category, value)`** — the one and only place a mask is built,
so the leak surface is a single function.

| Rule | Behaviour | Categories |
|---|---|---|
| `none` | value unchanged | `organization_name`, `organization_id` |
| `fixed` | constant, value-independent | `date_of_birth`, `snils`, `passport`, `inn`, `national_id`, `insurance_number`, `address`, `age`, `gender`, `nationality`, `secret` |
| `token` | per whitespace token: first char kept, rest starred | `person_name`, `doctor_name` |
| `keep2` | first two chars kept, rest starred | `patient_id`, `medical_record_number`, `lab_order_id`, `encounter_id`, `ticket_number`, `doctor_license` |
| `email` | `ivanov@example.com` → `i*****@e******.com` | `email` |
| `phone` | leading `+` + country digit + last four digits | `phone` |

Worked examples (verified against the code):

```text
Шадеркин Денис Сергеевич        → Ш******* Д**** С********
ivanov@example.com              → i*****@e******.com
+79991234567                    → +7******4567
1974-03-12                      → **.**.****
г. Москва, ул. Тверская, д. 5   → г. *******, ул. *******, д. **
123-456-789 00                  → ***-***-*** **
0000001234                      → 00********
ООО Клиника                     → ООО Клиника
```

`MASK_RULES` covers all 23 categories, and that is a test: a new category without a
rule is a failing test, not an unmasked value in production. An unimplemented
rule *name* raises `PIIPolicyError` — returning the raw value there would be the
worst bug the module could have.

Four categories are absent from §4.5's table and were closed here rather than left
to a future reader. Two of the gaps were substantive: `doctor_license` → `keep2`
(an opaque identifier held by a named individual, so it joins the `*_ID` family
rather than being unmasked like `organization_id`) and `medical_record_number` →
`keep2` (it does not match §4.5's `*_ID` glob, but it is the identifier that
actually leaked, and it must not be the one high-risk identifier with no mask).

**`hash_pii_value(value, *, secret)`** — salted HMAC-SHA256, returned as
`hmac-sha256:<64 hex>`. Three enforced rules:

1. `secret` is a **required keyword argument**; no module constant, no default (a
   default is a hard-coded secret, which is no secret). An empty secret raises
   `InvalidPIIInputError` — HMAC with an empty key is an unkeyed digest in the
   same disguise.
2. The fingerprint is **never logged and never persisted**. It rides
   `PIIFinding.value_fingerprint` in-process only. If cross-scan correlation is
   ever needed, the sanctioned join key is `document_id` + `category` + offset.
3. **Fingerprinting normalizes; masking does not.** `hash_pii_value` applies NFC +
   casefold + whitespace collapse, because aggregation dedup is keyed on the
   fingerprint and `Иванов` / `ИВАНОВ␣␣` — one name, two OCR variants, normal for
   Marker — would otherwise never dedup. `mask_pii_value` deliberately does *not*
   normalize: a mask exists so a human recognizes an entity in a log line, so it
   must reflect the characters actually present in the document.

An empty or whitespace-only value still yields a well-formed fingerprint (HMAC of
the empty string), so the "empty fingerprint bypasses dedup" rule in
`aggregation.py` stays reserved for a detector that genuinely failed to
fingerprint, and is never triggered as a normalization side effect.

---

## 6. Policy (`policy.py`)

**Locked decision algorithm:**

1. Resolve an action per category from `PIIRule`, then apply the destination
   override.
2. `risk_level` = **maximum** category risk across findings
   (`low < medium < high < critical`). No findings → `LOW`: an empty scan is not a
   risky scan, and defaulting upward would make every empty document suspicious.
3. Reduce actions to one decision by precedence:

```text
BLOCK > REVIEW > ALLOW_WITH_WARNING > ALLOW
```

The highest-precedence action wins, so one secret in a thousand findings blocks
the document. `ALLOW_WITH_WARNING` is not an action but a **residue**: produced
when at least one `WARN`/`REDACT` applied and nothing stronger did. Otherwise a
redacted document would be reported as a plain `ALLOW` and the record of what was
removed would be lost — the one thing the artifact exists to preserve.

**Risk table §4.4 (23 rows, asserted value-by-value against the plan, not against
a copy of itself):**

| Risk | Count | Categories | Action |
|---|---|---|---|
| `critical` | 1 | `secret` | `BLOCK` |
| `high` | 10 | `passport`, `national_id`, `inn`, `snils`, `insurance_number`, `patient_id`, `medical_record_number`, `lab_order_id`, `encounter_id`, `ticket_number` | `ALLOW` → `REDACT` on external |
| `medium` | 6 | `person_name`, `doctor_name`, `date_of_birth`, `phone`, `address`, `doctor_license` | `ALLOW` → `REDACT` on external |
| `low` | 6 | `age`, `gender`, `nationality`, `email`, `organization_name`, `organization_id` | `ALLOW` → `REDACT` on external |

**Destination overrides:**

| Destination | Behaviour |
|---|---|
| `internal_llm` | Base table unchanged. **The default** — the current provider is external but trusted by name (`ai_base_url = https://foundation-models.api.cloud.ru/v1`), so no pre-extraction redaction runs today. |
| `external_llm` | Escalates the **18** categories of `REDACT_ON_EXTERNAL` (identity + contact + government + medical_id) to `REDACT`. `practitioner` and `secret` excluded on purpose. |
| `persistence` | Base table; the Phase 6 guard evaluates under this destination. |
| `unknown` | Forces `REVIEW` for every category. Fails closed. |

`REDACT_ON_EXTERNAL` is 18 categories because the override needs **group**
membership, not risk level: "everything that identifies a patient" spans four
groups and three risk levels, and a rule expressed through risk would sweep in
the practitioner group at `medium`.

**The redact-unavailable escalation.** An override can demand `REDACT` while
`context.redaction_available` is `False` — which is today's state, since no
redactor exists. The contradiction resolves by escalating the category to
`REVIEW`, **never** downgrading to `ALLOW`. A document that must be redacted and
cannot be is a document a human must see; silently allowing it would send
unredacted PII to an external provider while the artifact claimed it was merely
reviewed.

**Policy completeness is enforced, not assumed.** `PIIPolicy` rejects a partial
table at construction (`PIIPolicyError`). The two plausible fallbacks for a
missing category — skip the finding, or default to `ALLOW` — both leak, so
"someone forgot a category" is a configuration error rather than a production
incident.

`DECISION_OUTCOMES` (`gate.py`) is the §0 decision table as data, keyed by
decision *values*, with a test asserting the key set equals `PIIDecision`'s — a
new decision cannot arrive without an outcome.

---

## 7. Redaction (`redaction.py`) — contract only

Redaction produces a **new** artifact string and never rewrites the original.
`REDACT` is fully specified even though it is unreachable while the only provider
is trusted by name — the spec is what makes switching destinations a config
change.

**Locked algorithm:**

1. **Resolve every finding to a span.** Prefer `start`/`end` when both are present
   and lie within the markdown; otherwise locate `value`. A finding that resolves
   to neither **must** raise `PIIRedactionError` — never be skipped, because a
   silently skipped redaction is a leak the artifact will happily attest to. The
   fallback is mandatory: structured-field and canonical-guard findings
   legitimately arrive without offsets.
2. **Merge overlapping spans** before replacing. Two overlapping spans applied
   right-to-left corrupt the text; skipping the second leaves part unredacted —
   a partial leak. Merging makes both impossible. The placeholder comes from the
   highest-confidence finding in the group; ties resolve leftmost.
3. **Replace right-to-left.** Each replacement differs in length from the text it
   replaces, so offsets computed before the first edit are invalid afterwards.
4. **Mutate nothing.** `markdown` is an immutable `str`; `findings` is the
   caller's list.

Placeholder tokens are `[CATEGORY_UPPER]`, built from the enum **member name**
(so the token survives a value rename). The token is a marker for a reviewer, not
a reversible encoding — nothing maps `[PERSON_NAME]` back to a value.

---

## 8. Canonical-output guard (`canonical_guard.py`)

**The only contract that stops the observed leak.** A document-only gate would
not have caught it: the PII was not in a field the gate declined to read, it was
copied by the model into free prose.

**The walk is free-form, and that is forced by the type.** `BaseCanonical.fields`
is `Any` (`packages/canonical/canonical/schemas/__init__.py:67-89`) and
`GenericCanonical` accepts `dict[str, Any]`. There is no field list to guard, and a
guard written against one would be a guard that misses the next schema. So
`walk_string_leaves` enumerates **every string leaf** and yields
`(field_path, value)`:

```text
fields.note                       ← the observed leak, exactly
fields.medications[0].doctor      ← dotted keys, [i] list indices
```

Traversal and judgement are deliberately separate. The module decides *where to
look* — completely, deterministically, **with no key allow-list**; the detector
decides *what counts as PII*. A structural string like `"appointment"` is
inspected like any other and simply will not match. Skipping known-structural keys
inside the walk would put a second, undocumented judgement there, needing
re-audit every time a schema gains a field.

**The walk is implemented, not just specified** — the one engine in M4 that is.
Traversal is fully determined, so specifying it in prose would only invite an M5
reimplementation that walks something slightly different. It is tested
behaviorally against the *actual* leak: the real `2b8fdd0d` (name + ticket
number) and `fbbcb675` (name + age) payloads are asserted to be found at exactly
`fields.note`, which discharges the plan's accept criterion against observed
documents rather than a synthetic payload.

**Cycle tracking is path-scoped.** Containers already on the current recursion
path are skipped, so a self-referential payload terminates instead of hanging the
pipeline, while a sub-object shared between two keys is still visited under both.
Both behaviours are tested.

**`CanonicalPIIViolation` obeys the Phase 1 rule structurally:** no `value` field,
`extra="forbid"`, and a test asserts the *exact* field set — so the second leak
boundary cannot acquire a raw value later. `PIISource.CANONICAL` is implied by the
type rather than stored; M5 stamps it when converting violations into findings.

**Remediation** (three actions, named in the contract):

| Action | What it does |
|---|---|
| `warn` | Record and continue; the document persists as-is. |
| `sanitize` | Replace the offending string with its mask and continue, so the value never reaches storage. |
| `retry_then_fail` | Do not persist; re-run extraction once with a stricter instruction, fail the document if it still leaks. |

`retry_then_fail` exists because the defect is in the prompt: failing immediately
punishes the document for a problem one re-run may fix, while persisting punishes
the patient.

> ⚠️ **`DECISION_REMEDIATION` is M4's proposal, not a locked decision.** The
> actions are named because the plan requires it; which action belongs to which
> decision is an M5 call, recorded as such in the code and asserted still-unlocked
> by a test. Current proposal: `allow → warn`, `allow_with_warning → sanitize`,
> `review → sanitize`, `block → retry_then_fail`.

---

## 9. Aggregation (`aggregation.py`) — contract only

**Dedup key: `(category, value_fingerprint)`.** Both halves are load-bearing.
`category` because the same text can be two different things (`39` as an age is
not a PII collision; a name as `person_name` vs `doctor_name` is a genuine
misclassification that must not be silently collapsed). `value_fingerprint`
because aggregation therefore never holds, compares or orders raw PII.

**A finding with an empty fingerprint bypasses dedup entirely.** This is the one
rule that is a safety property rather than a nicety: if two different values both
hash to `""`, keying on `(category, "")` would merge a patient's name into a
passport finding and delete one of them. Reporting a duplicate is recoverable; a
merged finding is not.

**Survivor selection:** highest `confidence`; ties broken by earliest position in
the input list. Because `CompositePIIDetector` preserves configured order, "first
configured detector wins" is a stable, explainable rule that never depends on set
or dict iteration order — so a pattern-form and a labelled-form match of the same
name resolve identically on every run.

**Output order: first appearance**, deliberately not sorted — the persisted
`findings[]` should read in scan order so a reviewer can follow the document, and
`category_counts` is the authoritative per-category tally regardless. A future
requirement to sort must arrive as an explicit contract change.

**Why detector order is load-bearing:** it decides which of two equally-confident
findings survives, so reordering a chain is a policy-visible change, not a
refactor. An empty chain is rejected in `CompositePIIDetector.__init__` — a
composite with no detectors reports "no PII found", the one configuration that
disables the gate while still looking healthy.

---

## 10. Persistence, provenance & versioning (`persistence.py`)

**The `"pii"` block** — one key for frontmatter and event `data`, `extra="forbid"`
like `ClassificationMeta`. No new event, no new table, no migration: the verdict
rides metadata that is already written, which is how account-api learns it for
free.

```json
"pii": {
  "decision": "allow", "risk_level": "medium", "stage": "document",
  "destination": "internal_llm", "findings_count": 7,
  "category_counts": { "person_name": 1, "date_of_birth": 1, "medical_record_number": 1,
                       "doctor_name": 1, "organization_name": 1, "address": 2 },
  "categories": ["person_name", "date_of_birth", "medical_record_number"],
  "detector_version": "1.0.0", "policy_version": "1.0.0",
  "reasons": ["expected_medical_identity"], "warnings": []
}
```

9 required keys + 2 defaulted (`reasons`, `warnings`), mirroring
`ClassificationMeta`. `category_counts` is authoritative; `categories` is derived
from it for UI and metrics. **Both** are required — a consumer forced to
recompute the tally would get it wrong for exactly the duplicates aggregation
exists to remove.

> **The block shape is data, not a model, and that is load-bearing.** §4.7 fixes
> `PIIMeta` as a sibling of `ClassificationMeta` in
> `packages/canonical/canonical/metadata.py:55-74`, and M4 may not edit
> `packages/`. A Pydantic model here would leave M5 with two classes for one
> shape, of which the one nobody uses is the one that rots. A JSON Schema was
> rejected for the same reason plus one: every schema in `schemas.py` is *derived*
> from a model precisely so it cannot drift, and a hand-written one would
> reintroduce exactly that drift.

**The artifact** is `pii_result.json`, mirroring `classification_result.json` —
the only place masked findings are persisted in full. Block and artifact are
deliberately different surfaces: one file doing two jobs would defeat the reason
the block is optional.

**Audit events — the complete vocabulary is four:**

| Event | When |
|---|---|
| `pii.scan.completed` | `allow` and `allow_with_warning` |
| `pii.review.required` | `review` |
| `pii.blocked` | `block` |
| `pii.redacted` | **in addition to** the decision's event, when redaction applied |

`allow` and `allow_with_warning` share `pii.scan.completed` deliberately: they
differ in the stored result, not in the operational event, and a consumer asking
"was this scanned?" should not need the decision vocabulary. `pii.redacted` is
additive, never a decision's own event — collapsing the two would make "how often
do we redact" unanswerable without a join against the stored result. The map's
key set is asserted equal to `PIIDecision`'s, so a new decision cannot arrive
without an event.

**Versioning.** `DETECTOR_VERSION = "1.0.0"`, `PII_POLICY_VERSION = "1.0.0"`
(read from `DEFAULT_POLICY.version`, so two constants that must agree cannot
drift). patch = docs/comments · minor = additive (new optional field, new
`PIICategory` with a matching policy row) · major = breaking (required field
change, enum removal, **decision-rule change**).

The rule with teeth: **any change that alters a decision for any input bumps the
policy version**, so a stored `PIIScanResult` always names the policy that
produced it. "Tweak a threshold" is a major bump, not a patch. Detector and policy
versions move independently, mirroring `classifier_version`.

---

## 11. Fixtures (`tests/fixtures/pii/`)

Manifest v `1.0.0` declares ground truth for **3 fixtures, all synthetic** —
`clean`, `patient`, `malicious` — the widest decision spread obtainable without a
real marker, seeded to prove the manifest shape (§4.10).

| Fixture | Categories | Decision | Risk | `contains_secret` |
|---|---|---|---|---|
| `clean/generic-notice-01.md` | — | `allow` | `low` | — |
| `patient/synthetic-consultation-01.md` | 7 | `review` | `high` | — |
| `malicious/synthetic-injection-01.md` | `secret` | `block` | `critical` | `true` |

Entry shape (§4.10): `file`, `source` (`real|synthetic`), `expected_categories`,
`expected_decision`, `expected_risk_level`, optional `contains_secret`. Seven
target directories are fixed up front — `clean patient laboratory appointment
prescription mixed malicious` — so M5's real-marker sweep has a vocabulary and a
mis-pathed file fails instead of silently extending the dataset.

The loader is app-owned (`app/pii/fixtures.py`, stdlib-only,
`PII_FIXTURES_DIR`-overridable) and **unexported** from `app.pii.__all__`: the
dataset is a dev/eval surface, and `app.classification` keeps its loader out of
its public API too. Two loaders rather than one shared one, because the entry
shapes genuinely differ and a union would put three always-null fields on every
PII entry.

**No real marker was copied, and that is a security decision, not an omission.**
`.dev/flow_upload_test/` holds real patient data, and a second copy in a new
directory would manufacture exactly the leak this milestone exists to close. A
test asserts no real marker id appears among the seeded files. Note that real PII
is *already* in the repo's test data — `2b8fdd0d` is a permanent classification
fixture — so the M5 sweep must use copies, following M2's convention.

`expected_decision` is context-dependent (Phase 5 makes a patient category
`ALLOW_WITH_WARNING` internally and `REVIEW` externally) and §4.10's entry keys
have no `destination` field. Rather than widen the locked entry shape, the
manifest `notes` state the assumed context (the external boundary) and a test
asserts the notes still do.

---

## 12. Что осталось на M5

M4 changed **only** `apps/ai-worker/app/pii/**`, `tests/unit/pii/**` and
`tests/fixtures/pii/**`. No `packages/`, no `app/pipeline/`, no migration was
touched — every cross-package edit is recorded in plan §4.9 as
documented-not-made. The M5 list:

1. **Implement the five stubs:** `PIIDetector.detect`, `PIIAggregator.aggregate`,
   `PolicyEngine.evaluate`, `PIIRedactor.redact`,
   `CanonicalPIIInspector.inspect`. Each is specified in prose in its module's
   docstring — M4 locked the algorithm, not just the signature.
2. **Add the fingerprint secret to `Settings`.** `app/config/settings.py` has
   **no** PII setting today (M4 did not touch settings, and there was nothing to
   configure while nothing executes). The secret must be high-entropy, stable
   across deploys — rotating it makes all accumulated fingerprints mutually
   incomparable — never hard-coded, never defaulted.
3. **Execute the §4.9 touch lists:**
   - `packages/storage`: add `"pii": "pii_result.json"` to `MARKDOWN_ARTIFACTS`
     and `MARKDOWN_KIND_PII`.
   - `apps/ai-worker`: `app/pii/artifact.py` gains `build_pii_artifact(...)`;
     `app/pipeline/pipeline.py` constructs the gate in `__init__`, calls `inspect`
     after classification (`:147`), **uploads the artifact before publishing**
     (the M2 ordering invariant, `:190-196`), adds the guard after
     `build_canonical` (`:164`), and adds `pii` to frontmatter and event `data`
     (`:235-241`).
   - `packages/canonical`: `PIIMeta` + `FrontmatterMeta.pii`, and a `pii=`
     parameter on `build_frontmatter_meta`.
   - `apps/account-api`: **nothing** — PII metadata is internal (IMPL_ARCH §26), so no
     API surface and no event are added. (Its storage kind allow-list is already
     behind — it omits even `classification` — a pre-existing gap to leave alone.)
4. **Supply `destination` and `redaction_available`** to the gate from
   configuration. `ProcessingContext` carries neither, and they must not be
   smuggled through `attributes`: a policy input arriving in a free-form dict
   cannot be validated or defaulted. Likewise `CanonicalPIIInspector.inspect`
   takes only the payload, so the policy context must be constructor state.
5. **Grow the dataset** with copied real markers and confirm the `expected_*`
   fields against real detectors.
6. **Confirm or replace `DECISION_REMEDIATION`** — currently M4's proposal.
7. **Optional hardening:** a test that validates a sample `"pii"` block through
   the real `PIIMeta` and asserts its field set equals
   `PII_META_REQUIRED_KEYS | PII_META_OPTIONAL_KEYS` — this turns Phase 7's
   assertion from transcription into enforcement, and only becomes possible once
   `PIIMeta` exists.

---

## 13. Deviations & deliberate departures (each recorded in IMPL_PLAN.md)

| Deviation | Why it was the right call |
|---|---|
| `PIICategory` has **23** members, not 22 | §4.1's heading said "22 values" while its own list had 23; `medical_record_number` is a category, not an alias. |
| `tests/unit/pii/__init__.py` **added** | `tests/unit/classification/` already owns `test_models.py`, `test_schemas.py`, `test_fixture_manifest.py`; without a package marker pytest's prepend import mode collides ("import file mismatch"), observed during Phase 1. |
| `PIIFinding.value` is `str`, **required** | Not `str | None` as in IMPL_ARCH §5, so a finding cannot exist without the text that justified it. |
| §5 assertion #2 satisfied from `PIIFindingSummary` | `model_json_schema()` on `PIIFinding` still lists the excluded fields, so deriving a wire contract from it would produce a schema that declares the field it must hide. |
| No `jsonschema` validator | The obvious way to prove payload/schema conformance would add a dependency and re-derive a shape the models already own; the value-key assertions carry the security weight instead. |
| `tests/support/pii_imports.py` is a new shared module | Not in the plan's §5 list; needed because three phases' guard tests needed the same AST helpers. |
| Import guards are tested for their own discrimination | A guard that never fires is indistinguishable from a guard that cannot fail; positive/negative cases are asserted. |
| `PIIDetectorBase` is instantiable; the raise lives in `detect` | M5 must be able to construct the whole chain — including not-yet-implemented members — and prove each link fails loudly where the work is. |
| Stubs raise rather than return `[]` | A stub returning `[]` is fail-open: the pipeline looks healthy and every document passes as clean. |
| `DECISION_OUTCOMES` is data, not prose | The §0 table is needed as a switchable mapping; prose cannot be tested for coverage of the decision enum. |
| Phase 4 mask rules for four §4.5-absent categories | `age`, `gender`, `nationality`, `doctor_license` had no rule; left open, they would have been unmasked values. |
| The Phase 6 walk is **implemented** | Traversal is fully determined; prose would only invite a slightly different M5 reimplementation. |
| `DETECTOR_VERSION` pulled forward from Phase 7 | Phase 3 writes the constant; leaving it for Phase 7 would mean a detector that cannot stamp its own findings. |

---

## 14. Known limitations

- **Nothing is wired.** No detector finds anything; the policy engine does not
  evaluate; the gate does not run. This is the defining limitation of M4, not a
  defect.
- **Numeric leaves are a blind spot.** The walk yields `str` leaves only, so a
  СНИЛС or phone serialized as a bare JSON number is not inspected. Deliberately
  not patched: scanning numbers means scanning every measurement value, date
  component and internal id in every lab payload — a calibration problem for M5's
  detectors, not a traversal decision.
- **`PIIAuditRecord` has no `destination`.** The block carries it; the record does
  not. So a document leaked externally and the same document sent internally
  produce near-identical records apart from the event name. Not added here: the
  field set is asserted in three phases' tests, and widening it is a
  schema-versioned change belonging to whoever writes the first real audit sink.
- **`PII_META_*_KEYS` is a key *set*, not a validated shape.** M4 can prove the
  intended block but not that a written block conforms to it — the validating
  model is `PIIMeta`, which lives in `packages/`. See §12 item 7.
- **No threshold is calibrated, and it shows in the decision matrix.** The one
  rule with no locked number — *how many identifiers make a document suspicious*
  — cannot be written without real findings, and M6 owns it. Consequence, recorded
  as a Phase 5 gap: **§4.4's table has exactly two actions** (`block` for `secret`,
  `allow` for everything else), so on the default `internal_llm` destination the
  engine can only ever return `ALLOW` or `BLOCK`. `REVIEW` is unreachable there
  entirely, so IMPL_ARCH §13's "a passport plus many unexpected identifiers" case
  cannot occur; a per-category table has no notion of a *combination* or a
  *count*. `ALLOW_WITH_WARNING` is reachable, but only via the `external_llm`
  override's `REDACT`. M5/M6 must add an explicit combination rule, or accept that
  `REVIEW` fires only for `destination=unknown` or `redact_unavailable`.
- **Fixture expectations are unverified.** With no detectors, `expected_*` are a
  specification for M5, not a checked result. The load-bearing tests here are
  structural.
- **`destination` defaults to `internal_llm`,** so the whole `REDACT` path is
  specified but unreachable today. That is the intended state while the only
  provider is trusted by name.
- **Pre-existing, not ours:** account-api's storage-kind allow-list
  (`app/services/storage.py:80-85`) omits even `classification`; `packages/observability`
  is a 0-byte stub; account-api's `request_logging.py` maskers match field names
  by substring (so `"name"` also matches `"schema_name"`) and live where ai-worker
  cannot import them, which is why M4 defined its own typed masker.

---

## 15. Verification

| Check | Result |
|---|---|
| `uv run pytest tests/unit/pii` | **262 passed** (23 + 13 + 20 + 37 + 71 + 33 + 33 + 32) |
| `uv run pytest` (full ai-worker) | **436 passed**, 5 warnings (174 baseline + 262) |
| `uvx ruff check app/pii tests/unit/pii tests/support` | clean |
| `uvx ruff format --check` on touched files | clean |
| `import app.pii` with `app.pipeline` + `app.classification` blocked | passes (subprocess guard) |
| `app/pii` exports | 64, sorted, unique, all resolvable |
| Root `make lint` | 4 errors, all pre-existing in `packages/storage` |

Per-file test counts:

| File | Tests | Covers |
|---|---|---|
| `test_models.py` | 23 | enum values, model shapes, frozen, import boundaries |
| `test_schemas.py` | 13 | schema parity, no `value` at schema level |
| `test_detectors.py` | 20 | protocol, stubs raise, composite order/non-empty |
| `test_masking_redaction.py` | 37 | all 23 mask rules, HMAC, redaction algorithm |
| `test_policy_gate.py` | 71 | §4.4 table, policy completeness, decision matrix, `DECISION_OUTCOMES`, subprocess import guard |
| `test_canonical_guard.py` | 33 | walk, paths, cycles, `DECISION_REMEDIATION`, real leak paths |
| `test_persistence_contract.py` | 33 | §4.7 block, audit without values, versions, SemVer |
| `test_fixture_manifest.py` | 32 | manifest shape, disk↔manifest parity, enum validity |

The three assertions carrying the security value (plan §5):

1. `"value"` is absent from `PIIFindingSummary` / `PIIScanResult` fields and from
   `PIIFinding.model_dump()` — the exclusion is structural;
2. `PII_FINDING_SCHEMA` has no `"value"` property — schema-level proof;
3. `PIIAuditRecord` has no `"value"` / `"value_fingerprint"`, and the **exact**
   field set is asserted so a field cannot be appended later.

```bash
cd apps/ai-worker
uv run pytest tests/unit/pii -v      # 262 contract tests
uv run pytest                        # 436, full suite
uvx ruff check app/pii tests/unit/pii tests/support
```

Commands must run from `apps/ai-worker`; from the repo root resolution can fail
on the `torch==2.13.0` macOS wheel (pre-existing, CI runs linux).

---

## 16. Appendix — document tree

```text
PII GATE/
├── IMPL_ARCH.md              # design reference (taxonomy, principles, phases 1–10)
├── IMPL_PLAN.md        # M4 runbook: 7 phases, all [x], statuses in 3 places
├── IMPL_RPRT.md        # this report
└── ../../../../../apps/ai-worker/app/pii/README.md   # module docs (rus.)
```

Related: `docs/development/ORGS/IMPL_ARCH.md` (organization contour),
`../CLASSIFICATION 2.0/IMPL_RPRT.md` (the classification report this one mirrors
in structure), `docs/messaging/EVENTS.md` (event catalog — untouched, since M4
adds no event).
