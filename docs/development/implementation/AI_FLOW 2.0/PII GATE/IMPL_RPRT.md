# PII Gate — Implementation report

- **Date:** 2026-09-30
- **Detector version:** `1.2.0` · **Policy version:** `3.0.0`
- **Status:** delivered — M4 contract (7 phases `[x]`) → M5 gate (Phases 8–15 `[x]`, 17 `[x]`, **16 deferred** to a separate ML evaluation task)
- **Scope:** `apps/ai-worker/app/pii/` (14 modules) + `app/pipeline/` + `app/config/settings.py` + `packages/storage/` + `packages/canonical/`
- **Plan docs:** [IMPL_PLAN.md](./IMPL_PLAN.md) (Revision 3 — M4 + M5, statuses in three places) · [IMPL_ARCH.md](./IMPL_ARCH.md) (design reference)
- **Verification:** ai-worker suite **809 passed** · `packages/storage` **19 passed** · `make lint` at the 4 pre-existing `packages/storage` errors · smoke check `1.2.0 3.0.0`

> **Two milestones, one report.** This file covers M4 (the contract) and M5 (the
> implementation) together, mirroring
> [`CLASSIFICATION 2.0/IMPL_RPRT.md`](../CLASSIFICATION%202.0/IMPL_RPRT.md),
> which spans its M1/M2/M3 the same way. Every M5 section is tagged so the
> boundary stays visible — `[M4: …]` marks a contract decision, `[M5 P14: …]` a
> later one. Where M5 changed what M4 specified, M4's version is stated first
> and the change is named, rather than the earlier text being silently replaced.

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
                                Сергеевича. Номер талона: 2026030710155500000001."
fbbcb675.../canonical.json → fields.note: "...для пациента Шадеркина Дениса
                                Сергеевича (М, 39 лет)..."
```

That content then persisted into `document_extractions.data`, because
`DocumentAnalysisCompleted.data` is written verbatim
(`apps/account-api/app/services/documents.py:536`). A prompt rule asking the
model not to do this is a *request*, not a control — which is exactly why
`canonical.yaml:100` failed. Hence the second guard line (`canonical_guard.py`).

**That leak is now closed.** `[M5 P14]` The sanitized model replaces `canonical`
before all three consumers, and the two leak shapes are asserted clean at all
three dump points — S3 `canonical.json`, S3 `structured.md`, and the
`DocumentAnalysisCompleted.data` payload. The assertion is **one loop over a
list of three surfaces**, not three tests
(`test_pipeline.py:846`), and that shape is the point: a per-surface test suite
passes happily when the guard is wired *after* `canonical.model_dump` and a
fourth sink is added later and never asserted. Here the sink list *is* the
assertion, so a new surface cannot be covered by accident. Two companion tests
close the gaps a single loop leaves open — one that a masked-everything guard
would fail (the clinician's name and the service date must survive), and one that
the *object in the middle* is sanitized rather than only the outputs.

**Headline design decisions:**

| Decision | Rationale |
|---|---|
| PII presence alone never blocks | A medical record is *expected* to carry patient identity; blocking on presence would halt every document the platform exists to process. Only `secret` blocks — that is a security incident, not a fact about the document's subject. |
| The gate is document-level, not per-schema | `PIIGate.inspect(document, context)`, not `AppointmentPIIGate`. One gate for every type, so a new document type is covered the day it is added. |
| Raw PII cannot cross a boundary **structurally** | `value` is `Field(exclude=True)`; summaries have no value field at all. Not a call-site discipline — a control. |
| Fingerprint is HMAC, not a hash | Low-entropy identifiers (СНИЛС, полис ОМС, дата рождения) are brute-forceable in seconds; a plain `sha256` column would be the value in disguise. |
| Traversal and judgement are separate | The canonical walk enumerates every string leaf with no key allow-list; the detector decides what is PII. An allow-list inside the walk would hide a second, undocumented judgement. |
| Stubs raise instead of returning `[]` | A stub returning `[]` is fail-open: the pipeline looks healthy and every document passes. |
| **[M5 P14]** The same values evaluate differently at a persistence boundary | A canonical payload and a source document can be headed for the same place and must not resolve to the same action — `stage` participates where `destination` alone cannot express the leak. |
| **[M5 P17]** A combination escalates the *decision*, never `actions` | `actions[category]` is the remediation channel and the sanitizer masks iff it is `REDACT`. Writing `REVIEW` into it would make the per-category table lie. |
| **[M5 P16 deferred]** No ML detector, and no stub for one | An unwired detector is untested code. The chain is the whole chain, and that is recorded rather than padded. |

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

**[M5 P14] Aggregation is per leaf; the decision is not.** The guard aggregates
each leaf's findings separately, then evaluates the policy **once** over the union
of all leaves. Per-leaf verdicts would have no defined precedence against each
other — which is also why `[M5 P17]`'s combination rule is document-scoped rather
than per-leaf, and is recorded there as a deviation from ORDER §13.1's wording.
Remediation, by contrast, *is* per leaf: a mask replaces exactly the spans its own
leaf's findings justify.

Boundary invariants (locked, test-enforced):

- **Deterministic where it can be:** the payload walk visits every string leaf in a
  fixed order, de-duplication is by fingerprint, and policy precedence is a total
  order. Detection confidence thresholds are M6's calibration.
- **No runtime coupling:** `app.pii` imports no `app.classification` and no
  `packages.canonical` type — `[M5]` the third guard was added and asserted. The
  shared types are `TYPE_CHECKING`-only.
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
├── __init__.py          # public API: 85 sorted, resolvable exports
├── models.py            # Phase 1 — 7 enums, PIIFinding, PIIFindingSummary,
│                        #   PIIScanResult, PIIAuditRecord, PIIDecisionResult
├── exceptions.py        # PIIError + 5 subclasses (PIIDecisionError = fail-closed)
├── schemas.py           # Phase 2 — PII_SCAN_RESULT_SCHEMA, PII_FINDING_SCHEMA
│                        #   (derived from the models, never hand-maintained)
├── detectors.py         # Phase 3 contract + M5 P9/P13 impl — PIIDetector
│                        #   protocol, CompositePIIDetector, StructuredFieldPIIDetector,
│                        #   PatternPIIDetector, SecretPIIDetector, build_detector_chain;
│                        #   DETECTOR_VERSION
├── aggregation.py       # Phase 3 — PIIAggregator protocol, DefaultPIIAggregator;
│                        #   dedup rule
├── masking.py           # Phase 4 — mask_pii_value, hash_pii_value (HMAC-SHA256);
│                        #   MASK_RULES, FIXED_MASKS, FINGERPRINT_PREFIX
├── redaction.py         # Phase 4 — PIIRedactor protocol, RedactorBase,
│                        #   PlaceholderRedactor, placeholder_for
├── policy.py            # Phase 5 contract + M5 P9/P17 impl — DEFAULT_POLICY,
│                        #   CATEGORY_RISK, PIIRule, PIICombinationRule, PIIPolicy,
│                        #   PIIPolicyContext, DefaultPolicyEngine; PII_POLICY_VERSION
├── gate.py              # Phase 5 — PIIGate protocol, DefaultPIIGate, DocumentPIIGateResult,
│                        #   DECISION_OUTCOMES, HALTING_DECISIONS, build_document_gate
├── canonical_guard.py   # Phase 6 + M5 P14 — walk_string_leaves,
│                        #   CanonicalPIIViolation, DefaultCanonicalPIIInspector,
│                        #   PIIRemediation, DECISION_REMEDIATION, sanitize_canonical_payload,
│                        #   build_canonical_guard
├── artifact.py          # M5 Phase 10 — build_pii_artifact, the §4.7 "pii" block
├── persistence.py       # Phase 7 — "pii" block key set, PII_ARTIFACT_FILENAME,
│                        #   PII_AUDIT_EVENTS, DECISION_AUDIT_EVENTS
└── fixtures.py          # Phase 7 — app-owned manifest loader, stdlib-only
```

`tests/unit/pii/` is now **19 files / 598 tests** (M4: 8 / 262; M5 added
`test_detectors_behaviour`, `test_aggregation_behaviour`, `test_policy_behaviour`,
`test_redaction_behaviour`, `test_canonical_guard_behaviour`, `test_artifact`,
`test_settings_boundary`, `test_manifest_verification`, `test_external_boundary`,
`test_combination_policy`, plus `tests/unit/pipeline/test_pipeline.py` for the
wiring and `tests/support/pii_imports.py` for the AST import-guard helpers. The
flat layout mirrors `app/classification/` — *not* IMPL_ARCH Phase 1's
`pii/domain/` subpackage; recorded as a deliberate deviation so M5 does not
re-litigate it.

> **Correction to the M4 report.** It cited
> `apps/ai-worker/app/pii/README.md` three times as a code-adjacent document.
> **No such file exists and none was ever committed.** The module-level prose
> lives in the modules' own docstrings, which is where the substantive
> documentation is. Recorded rather than quietly dropped, because a report that
> points at a file that is not there is worse than one that admits it.

---

## 4. Domain model (`models.py`)

- **`PIICategory`** — 23 members in 6 groups. §4.1's heading said "22 values";
  the taxonomy is **23** (recorded deviation — `medical_record_number` is its own
  category, which is why the count is one higher than the plan's prose).
- **`PIISource`** — `pattern · structured_field · ner · llm · canonical`.
  `canonical` marks a finding raised by the post-extraction guard.
  **`ner` is defined but never produced** — `[M5 P16 deferred]`, see §14.
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
real substring in-process, and the alternative makes "no raw PII" a call-site
discipline instead of a control.

> ⚠️ `model_json_schema()` on `PIIFinding` still lists `value` and
> `value_fingerprint` — `exclude` is a serialization concern, not a schema one.
> `PIIFinding` is **not** a wire contract; schemas and artifacts derive from
> `PIIFindingSummary` only. This is why §5 assertion #2 is satisfied from the
> summary type (recorded deviation).

---

## 5. Masking & fingerprinting (`masking.py`) — implemented, unchanged in M5

The only engine that shipped in M4 with no `NotImplementedError`, because both
functions are fully determined pure functions. M5 did not touch this module.

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
   same disguise. `[M5 P8]` The secret is read from `Settings.pii_fingerprint_secret`
   at chain construction, and the pipeline **refuses to start** without it.
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
3. **[M5 P17]** Compute the combination escalation (below) — a separate signal
   that joins the decision, not a replacement for the table.
4. Reduce to one decision by precedence:

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
| `internal_llm` | Base table unchanged. `[M5 P15]` The destination is now **resolved from `Settings.llm_mode`**, so switching providers is a configuration change rather than a code change. |
| `external_llm` | Escalates the **18** categories of `REDACT_ON_EXTERNAL` (identity + contact + government + medical_id) to `REDACT`. `practitioner` and `secret` excluded on purpose. |
| `persistence` | Base table — **except** under `stage=canonical`, where `[M5 P14]` the same 18 categories escalate to `REDACT` (`REDACT_ON_PERSIST`). `practitioner`, the clinical facts (`age`/`gender`/`nationality`) and `secret` deliberately do not. |
| `unknown` | Forces `REVIEW` for every category. Fails closed. |

`REDACT_ON_EXTERNAL` is 18 categories because the override needs **group**
membership, not risk level: "everything that identifies a patient" spans four
groups and three risk levels, and a rule expressed through risk would sweep in
the practitioner group at `medium`.

**The redact-unavailable escalation.** An override can demand `REDACT` while
`context.redaction_available` is `False`. The contradiction resolves by escalating
the category to `REVIEW`, **never** downgrading to `ALLOW`. A document that must be
redacted and cannot be is a document a human must see; silently allowing it would
send unredacted PII to an external provider while the artifact claimed it was
merely reviewed. `[M5 P12]` The redactor now exists and reports itself available,
so this path is reachable only by explicitly constructing the context.

**[M5 P14] Per-category remediation.** `PIIDecision` decides halt-vs-continue; it
does not decide what to mask. Masking is driven by `PIIDecisionResult.actions[category]`,
and a canonical leaf is masked iff its action is `REDACT`. Consequences that
matter: a `PERSON_NAME` redaction leaves `DOCTOR_NAME` and `ORGANIZATION_NAME`
intact, so `render_document` keeps working; and an `ALLOW`-but-recorded category
stays legible to a human reviewing the canonical. Masking on the document-level
decision instead would blank every finding in a run that happened to contain one
redaction.

**[M5 P17] Combination rules — the narrow threshold.** M4 recorded as a gap that
the table has exactly two actions, so on the default `internal_llm` destination
the engine could only return `ALLOW` or `BLOCK` and `REVIEW` was **unreachable**.
`PIIPolicy.combinations` closes that, shipping one row:

```text
PIICombinationRule(requires_groups={"government"}, min_count=2, decision=REVIEW)
```

Two distinct state identifiers in one document are a combination worth a human.
The two thresholds ORDER §13.1 offers as examples were measured against the whole
dataset and **both rejected**:

| candidate | why not |
|---|---|
| ≥2 distinct HIGH categories | СНИЛС + ОМС + № карты is **three** HIGH categories and the normal shape of a Russian record. Halts routine care. |
| identity + government ID | Fires on `IDENTIFIER_MARKER` (ФИО + СНИЛС), Phase 13's deliberate **allow** path. |
| **≥2 distinct government identifiers** | **Shipped.** Fires on the §45.19 accept case exactly; silent on all six fixtures. |

Three properties, each because a specific alternative was wrong:

- **The rule lives on `PIIPolicy`**, not in a module constant. `PII_POLICY_VERSION`
  *is* `DEFAULT_POLICY.version`, and the reason that constant exists is that a
  stored result must be re-derivable from the version it names. A threshold table
  the version cannot name makes a stored verdict irreproducible.
- **It escalates the decision and never touches `actions`** (see remediation
  above). The escalation is recorded in **`reasons`** — a `REVIEW` that does not say
  why is a halt nobody can triage. This is open decision 14 holding structurally:
  `REVIEW` adds no `REDACT`, so a review still cannot rewrite the document it asks
  about.
- **`decision` may only be `REVIEW`**, validated at construction. A rule that could
  `BLOCK` would make itself the second block source and contradict
  `_default_rules()`; `SECRET` is the only thing that blocks, because a credential
  is a vulnerability rather than a fact about the document's subject.

Three construction-time validators ship alongside: `min_count >= 2` (a threshold
below 2 is a per-category rule in disguise), a non-empty group set, and unknown
group names rejected — a misspelled group would otherwise raise a bare `KeyError`
on the first document reaching the rule, naming neither the group nor the policy
version.

**Policy completeness is enforced, not assumed.** `PIIPolicy` rejects a partial
table at construction (`PIIPolicyError`). The two plausible fallbacks for a
missing category — skip the finding, or default to `ALLOW` — both leak, so
"someone forgot a category" is a configuration error rather than a production
incident.

`DECISION_OUTCOMES` (`gate.py`) is the §0 decision table as data, keyed by
decision *values*, with a test asserting the key set equals `PIIDecision`'s — a
new decision cannot arrive without an outcome.

---

## 7. Redaction (`redaction.py`) — **[M5 P12] implemented**

`[M4]` Redaction produces a **new** artifact string and never rewrites the original.
The algorithm was fully specified while it was unreachable, because the spec is
what makes switching destinations a config change. M5 implemented it and it is
now live on the external path.

**Locked algorithm (as implemented):**

1. **Resolve every finding to a span.** Prefer `start`/`end` when both are present
   and lie within the markdown; otherwise locate `value`. A finding that resolves
   to neither **must** raise `PIIRedactionError` — never be skipped, because a
   silently skipped redaction is a leak the artifact will happily attest to.
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

**`[M5]` The offset is verified against the value, not trusted.** The gate's
findings index the *canonicalised* `raw_text`, not the markdown, so a redactor
that trusted their offsets would replace unrelated text and leave the value in
place. `test_wrong_offsets_are_never_trusted` is the assertion.

**`[M5] H-1 — a repeated value was leaking, found live and fixed as its own
commit (`bfaf89d`).** The aggregator dedups on `(category, value_fingerprint)`, so
a value appearing **twice** in one document collapses to a single finding and
therefore a single replacement. On the contour-2 path this was found while writing
Phase 15, and it was closed as a separate commit rather than filed as dormancy.
That asymmetry is the lesson: the same document's *first* occurrence was masked
and the second was not, so the artifact carried a value it had already attested to
redacting.

---

## 8. Canonical-output guard (`canonical_guard.py`)

**The only control that stops the observed leak.** A document-only gate would
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

**Cycle tracking is path-scoped.** Containers already on the current recursion
path are skipped, so a self-referential payload terminates instead of hanging the
pipeline, while a sub-object shared between two keys is still visited under both.
Both behaviours are tested.

**`CanonicalPIIViolation` obeys the Phase 1 rule structurally:** no `value` field,
`extra="forbid"`, and a test asserts the *exact* field set — so the second leak
boundary cannot acquire a raw value later. `PIISource.CANONICAL` is implied by the
type rather than stored; the guard stamps it when converting violations into
findings.

**Remediation** (three actions, named in the contract):

| Action | What it does |
|---|---|
| `warn` | Record and continue; the document persists as-is. |
| `sanitize` | Replace the offending string with its mask and continue, so the value never reaches storage. |
| `retry_then_fail` | Do not persist; re-run extraction once with a stricter instruction, fail the document if it still leaks. |

`retry_then_fail` exists because the defect is in the prompt: failing immediately
punishes the document for a problem one re-run may fix, while persisting punishes
the patient.

**`[M4 proposed → M5 P14 confirmed]` `DECISION_REMEDIATION`:**

| Decision | Remediation | Why |
|---|---|---|
| `allow` | `warn` | Reaching the remediation step at all means violations were found, so an `ALLOW` on a payload that *did* leak should leave a trace. |
| `allow_with_warning` | `sanitize` | The main path: the persistence escalation turns a name in `fields.note` into `REDACT`, the redactor resolves it, this masks and continues. |
| `review` | `retry_then_fail` | **Corrected from M4's proposal**, which said `sanitize`. Open decision 14: a document at `REVIEW` is one a human must look at, and rewriting it would mean the thing a human was asked to review is not the thing that was published. |
| `block` | `retry_then_fail` | Confirmed. |

> **The name `RETRY_THEN_FAIL` is the outcome; no retry is implemented.** There is
> no re-extraction path, and a constant reading as "extraction is re-run" is
> corrected by a test that says so at the definition.

---

## 9. Aggregation (`aggregation.py`) — **[M5 P9] implemented**

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

**`[M5]` The live chain is three detectors, in this order:**

```text
StructuredFieldPIIDetector  →  PatternPIIDetector  →  SecretPIIDetector
```

`SecretPIIDetector` is the **only** source of `BLOCK`. That is asserted rather than
assumed: `test_only_a_credential_blocks_at_every_boundary` and the pipeline's
credential test both exist because a gate whose only block source is unbuilt is a
gate that is silently open.

---

## 10. Persistence, provenance & versioning (`persistence.py`, `artifact.py`)

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
  "detector_version": "1.2.0", "policy_version": "3.0.0",
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
> `packages/canonical/canonical/metadata.py:55-74`, and M4 could not edit
> `packages/`. A Pydantic model in `app/pii` would have left two classes for one
> shape, of which the one nobody uses is the one that rots. `[M5 P10]` the shape
> now has both homes — `build_pii_artifact` in `app/pii/artifact.py` produces it,
> `PIIMeta` in `packages/canonical/canonical/metadata.py:77` validates it, and
> tests hold the two against `PII_META_REQUIRED_KEYS`.

**The artifact** is `pii_result.json`, mirroring `classification_result.json` —
the only place masked findings are persisted in full. Block and artifact are
deliberately different surfaces: one file doing two jobs would defeat the reason
the block is optional.

**[M5 P15] The second artifact, `redacted.md`, is written only when redaction
actually changed something.** Not a copy of the input with placeholders, not a
diff, not a per-finding list: the exact text that crossed the untrusted boundary,
in placeholders, at the key the rest of the pipeline will actually send. The
deciding constraint is that at the trusted destination this is *every* document
the platform processes, so writing it unconditionally would put a second copy of
every document in storage and make "did we redact?" unanswerable. A no-op
redaction writes nothing, and `redacted is markdown` is an identity check
(`pipeline.py:602`) rather than an equality scan — the redactor returns the
*same object* when it has nothing to do, so no copy is made on the hot path.

> **[M5 P10] The artifact has no provenance envelope, and that is deliberate.**
> `build_classification_artifact` wraps its verdict in a `processing` block
> (`prompt_key`, `schema_name`, `model`, …). The PII artifact does not, because the
> fields have nothing true to say: the gate runs on `marker.md` and never sees the
> LLM, so there is no prompt or model to name.

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

**Versioning — three bumps, and the rule has teeth.** `DETECTOR_VERSION` and
`PII_POLICY_VERSION` move independently. patch = docs/comments · minor = additive
(new optional field, new `PIICategory` with a matching policy row) *and
backward-compatible* · major = breaking (required field change, enum removal,
**decision-rule change**).

```text
DETECTOR_VERSION    1.0.0 ─(P9)▶ 1.1.0 ─(P14)▶ 1.2.0
PII_POLICY_VERSION  1.0.0 ─(P14)▶ 2.0.0 ─(P17)▶ 3.0.0
```

**Any change that alters a decision for any input bumps the policy version**, so a
stored `PIIScanResult` always names the policy that produced it. "Tweak a
threshold" is a major bump, not a patch — which is why M5 Phase 17 shipped
**`3.0.0`, not the `2.1.0` the roadmap had pencilled in**. A `2.1.0` would mean
"additive and backward-compatible" attached to a rule that turns `ALLOW` into
`REVIEW`, making the stored name a lie. Phase 14 is the precedent for correcting
a roadmap rather than shipping a version that misdescribes the change.

`PII_POLICY_VERSION` reads from `DEFAULT_POLICY.version` rather than repeating
the literal, because two constants that must agree will eventually disagree.

---

## 11. Fixtures (`tests/fixtures/pii/`)

Manifest v `1.0.0` declares ground truth for **6 fixtures** — `clean`, `patient`,
`appointment`, `malicious` as markdown, plus a second **canonical-payload**
dataset that lives outside the manifest on purpose.

| Fixture | Categories | Decision | `contains_secret` |
|---|---|---|---|
| `clean/generic-notice-01.md` | — | `allow` | — |
| `patient/synthetic-consultation-01.md` | 7 | `allow_with_warning` | — |
| `appointment/synthetic-registration-01.md` | 2 | `allow_with_warning` | — |
| `malicious/synthetic-injection-01.md` | `secret` + 1 | `block` | `true` |
| `canonical/appointment/…-note-01.json` | 3 | `allow_with_warning` | — |
| `canonical/laboratory/…-note-01.json` | 4 | `allow_with_warning` | — |

`[M5 P13]` The `2b8fdd0d` marker *shape* was reproduced as a synthetic fixture,
which is what gave the pipeline an allow-path document and a block-path document
to assert on. They were originally one fixture, and that fixture was a **tripwire**:
`SecretPIIDetector` did not exist, the `api_key` row was invisible to the chain,
the document was allowed through on the `СНИЛС` alone, and the day the secret
detector landed every allow-path assertion began failing. The repair was to split
the fixture — one document per verdict — not to weaken the assertions.

`[M5 P14]` The canonical dataset is deliberately **outside** the manifest: that
manifest's `expected_decision` is a document-stage property and its loader
enumerates markdown files, so canonical payloads are loaded directly by the guard
and pipeline tests rather than inventing a second manifest schema.

`[M5 P13]` The manifest is now **measured, not declared**.
`test_manifest_verification.py` runs every entry through the real chain, aggregator
and policy engine and asserts equality on categories, decision and risk — not
containment, because a subset assertion cannot fail when a detector starts
inventing categories, and an invented category is a wrong masked value in a
persisted artifact. The cost is that every recall improvement shows up as a red
test; that is the point, because the fix is then recorded in the manifest where
the diff is visible to a reviewer.

Entry shape (§4.10): `file`, `source` (`real|synthetic`), `expected_categories`,
`expected_decision`, `expected_risk_level`, optional `contains_secret`. Seven
target directories are fixed up front — `clean patient laboratory appointment
prescription mixed malicious` — so a mis-pathed file fails instead of silently
extending the dataset.

The loader is app-owned (`app/pii/fixtures.py`, stdlib-only,
`PII_FIXTURES_DIR`-overridable) and **unexported** from `app.pii.__all__`: the
dataset is a dev/eval surface, and `app.classification` keeps its loader out of
its public API too.

**No real marker was copied, and that is a security decision, not an omission.**
`.dev/flow_upload_test/` holds real patient data, and a second copy in a new
directory would manufacture exactly the leak this milestone exists to close. A
test asserts no real marker id appears among the seeded files. Note that real PII
is *already* in the repo's test data — `2b8fdd0d` is a permanent classification
fixture — so any sweep must use copies, following M2's convention.

`expected_decision` is context-dependent and §4.10's entry keys have no
`destination` field. Rather than widen the locked entry shape, the manifest
`notes` state the assumed context (the external boundary) and a test asserts the
notes still do. The production boundary is covered separately, which is also what
keeps the two contexts from being confused for one another.

---

## 12. Pipeline wiring **[M5]** — replaces M4's "Что осталось на M5"

M4 changed only `apps/ai-worker/app/pii/**`, `tests/unit/pii/**` and
`tests/fixtures/pii/**`. M5 is the first contour to leave that footprint. Every
item of M4's handoff list is now done:

| M4 handoff | Where it landed |
|---|---|
| Implement the five stubs | `detectors.py` (P9/P13), `aggregation.py` (P9), `policy.py` (P9/P17), `redaction.py` (P12), `canonical_guard.py` (P14) |
| Fingerprint secret in `Settings` | `Settings.pii_fingerprint_secret` (P8); the pipeline refuses to start without it |
| `packages/storage` touch list | `keys.py:10-18` `MARKDOWN_ARTIFACTS["pii"] = "pii_result.json"` + `__init__.py:13` `MARKDOWN_KIND_PII` (P10); P15 added `MARKDOWN_KIND_REDACTED` → `redacted.md` beside it |
| `app/pii/artifact.py` | `build_pii_artifact` + the `§4.7` block (P10) |
| `app/pipeline/pipeline.py` | gate built in `__init__`; `inspect` after classification; **artifact uploaded before publish**; guard after `build_canonical`; `pii` in frontmatter and event `data` (P11) |
| `packages/canonical` touch list | `PIIMeta` + `FrontmatterMeta.pii` + a `pii=` parameter on `build_frontmatter_meta` (P10) |
| `apps/account-api` | **nothing** — PII metadata is internal, so no API surface and no event. (Its storage-kind allow-list is already behind, a pre-existing gap to leave alone.) |
| Supply `destination` / `redaction_available` | `build_policy_context` reads them from settings; `redaction_available` is reported by the implemented redactor (P12/P15) |
| Grow the dataset, confirm `expected_*` | P13 marker-shape fixture + P14 canonical dataset + measured manifest verification |
| Confirm or replace `DECISION_REMEDIATION` | P14 confirmed with one correction (`review → retry_then_fail`) |
| Optional `PIIMeta` shape test | Shipped: the block is validated against `PII_META_*_KEYS` on the way into the frontmatter |

**Contour 1 — the source scan.** The gate is built at start-up and runs after
classification, before extraction. A halting decision uploads **nothing** and
publishes exactly one `document.processing.failed` carrying `job_type="pii_gate"`
and `error_code` `PII_REVIEW_REQUIRED` or `PII_BLOCKED`. On the allow path the
`pii_result.json` artifact is uploaded **before** the publish event that
references it — the M2 ordering invariant, asserted by comparing upload indices
in the ordered mock call list.

**Contour 2 — the canonical guard.** After `build_canonical`, the guard sanitizes
the model *before* any consumer sees it, and a halting verdict fails the document
before either dump point. The contour-1 artifact stays on disk in that case: it
is the gate's own audit record and it carries no patient text, so "no artifacts at
all" would be the wrong claim.

**Two `job_type` values, not one reused** (`pipeline.py:102`, `:105`). Sharing
one would make the two contours indistinguishable in the failure queue, and the
distinction is the useful one: `pii_gate` means the *source* document was refused
before extraction; `pii_canonical_guard` means extraction produced something that
must not be stored — an upstream prompt defect. An operator triaging the second
needs to know that without cross-referencing which stage produced the failure.

**The complete production failure surface is five `error_code`s**, all on
`document.processing.failed` and all fail-closed:

| `error_code` | `job_type` | Meaning |
|---|---|---|
| `PII_REVIEW_REQUIRED` | `pii_gate` / `pii_canonical_guard` | a document a human must look at |
| `PII_BLOCKED` | `pii_gate` / `pii_canonical_guard` | a credential; the document does not proceed |
| `PII_REDACTION_FAILED` | `pii_gate` | contour-1 redaction raised — no span resolved |
| `PII_CANONICAL_GUARD_FAILED` | `pii_canonical_guard` | the *sanitized* payload failed re-validation |
| `PII_GUARD_ERROR` | `pii_canonical_guard` | the guard could not produce a verdict at all |

The last two are the ones worth stating, because both have a wrong-looking
alternative that the code explicitly rejects. If the sanitized payload does not
satisfy the schema, the unsanitized object is **not** written to close the gap —
that fallback is the leak with extra steps. And a `PIIDecisionError` from the guard
is published as a canonical-guard failure rather than allowed to propagate, because
a raise here would be caught by the structuring handler above and reported as a
`markdown_structuring` error, losing the fact that a security control stopped the
document.

> **`processing_status = "needs_review"` does not exist and was not faked.** The
> plan writes the two halting outcomes that way (ORDER §0, IMPL_PLAN Phase 11),
> but `DocumentAnalysisCompleted.status` is `Literal["succeeded", "failed"]` and
> `DocumentProcessingFailed` has no status field to widen. A document at `REVIEW`
> therefore fails with a distinct `error_code` instead of a new event, and no new
> event was added.

---

## 13. Deviations & deliberate departures (each recorded in IMPL_PLAN.md)

| Deviation | Why it was the right call |
|---|---|
| `PIICategory` has **23** members, not 22 | §4.1's heading said "22 values" while its own list had 23; `medical_record_number` is a category, not an alias. |
| `tests/unit/pii/__init__.py` **added** | `tests/unit/classification/` already owns `test_models.py`, `test_schemas.py`, `test_fixture_manifest.py`; without a package marker pytest's prepend import mode collides ("import file mismatch"). |
| `PIIFinding.value` is `str`, **required** | Not `str | None` as in IMPL_ARCH §5, so a finding cannot exist without the text that justified it. |
| §5 assertion #2 satisfied from `PIIFindingSummary` | `model_json_schema()` on `PIIFinding` still lists the excluded fields, so deriving a wire contract from it would produce a schema that declares the field it must hide. |
| No `jsonschema` validator | The obvious way to prove payload/schema conformance would add a dependency and re-derive a shape the models already own. |
| `tests/support/pii_imports.py` is a new shared module | Not in the plan's §5 list; needed because three phases' guard tests needed the same AST helpers. |
| Import guards are tested for their own discrimination | A guard that never fires is indistinguishable from a guard that cannot fail. |
| Stubs raise rather than return `[]` | A stub returning `[]` is fail-open: the pipeline looks healthy and every document passes as clean. |
| `DECISION_OUTCOMES` is data, not prose | The §0 table is needed as a switchable mapping; prose cannot be tested for coverage of the decision enum. |
| Phase 4 mask rules for four §4.5-absent categories | `age`, `gender`, `nationality`, `doctor_license` had no rule; left open, they would have been unmasked values. |
| The Phase 6 walk is **implemented** | Traversal is fully determined; prose would only invite a slightly different M5 reimplementation. |
| `[M5 P14]` `date_of_birth.numeric` **removed** | Escalating a category made the detector's recall claim load-bearing: that rule claimed *every* bare `YYYY-MM-DD`, including `canonical.document_date`, which is a service date written into the frontmatter by `render_document`. Recall given up deliberately — a date of birth in the declined construction is no longer found — because data loss is not a cost worth paying for a service date. |
| `[M5 P14]` `DETECTOR_VERSION` at **1.2.0**, not 1.1.0's successor for NER | A rule left and a rule arrived: neither the additive minor nor the major line. What settles it is the reason the constant exists — a stored result must name a detector whose behaviour reproduces it. |
| `[M5 P15]` `review` → `RETRY_THEN_FAIL`, not M4's `sanitize` | Rewriting a document a human was asked to review means the reviewed thing is not the published thing. |
| `[M5 P17]` Policy **2.0.0 → 3.0.0**, not 2.1.0 | §4.8 defines minor as additive *and* backward-compatible; the combination rule fails the second half. |
| `[M5 P17]` Combination is **document-scoped**, not per-leaf | ORDER §13.1 says "one free-text leaf", but the locked `PolicyEngine.evaluate` signature takes one flat list and per-leaf verdicts have no defined precedence. Document scope is also the conservative direction. |
| `[M5 P17]` The rule **narrows** ORDER §13.1's examples | Both examples were measured against the dataset and either would halt routine care. The rejected rules are asserted as *not*-the-behaviour so the decision cannot be quietly undone. |
| `[M5]` `app/pii/README.md` never existed | The M4 report cited it three times. It is not in the repository and never was; the module prose lives in the docstrings. |
| `[M5 P16]` **Phase 16 (NER) deferred**, not stubbed | No ML dependency, no backend, no setting, no test change to represent it. `PIISource.NER` stays in the enum because removing it is a breaking schema change. Revisit conditions in plan §3. |

---

## 14. Known limitations

- **[M5 P16] No NER, and that is now a recorded decision rather than a gap.** The
  chain has been the whole chain since Phase 13. `PIISource.NER` is defined but
  never produced. Revisit requires a separate ML evaluation task, an environment
  that can run the model, a real PII fixture dataset, and acceptance on measured
  precision/recall. Recall alone disqualifies it: a NER claiming every name in a
  note is not better than the pattern chain, it is slower.
- **A `REVIEW` has no consumer (R9, R15).** `REVIEW` halts the document and there
  is no human UI and no audit sink. A tripping document stalls with **zero
  artifacts**, one `document.processing.failed`, and a log line — the evidence
  exists only in the logs, and the document is neither queued nor recoverable
  without a re-upload. Phase 17 made `REVIEW` reachable for the first time
  without adding a durable review state, which needs the audit sink M4 deferred.
  There is deliberately **no operator lever** for the threshold, following
  `REDACTION_AVAILABLE`'s precedent that an operator must not disable a control
  with an env var; the only softening path is a versioned, reviewable edit to the
  policy data.
- **The combination threshold is calibrated against synthetic fixtures, not real
  records.** No fixture carries *any* government identifier, so the rule is dormant
  across the whole dataset and a test asserts that. Real-world Russian records
  carrying СНИЛС **and** ОМС are the untested population, and M6 measures them.
  The narrower the rule, the smaller the availability risk; the cost is that
  "two identifiers in one document" is the only combination it will ever catch.
- **Numeric leaves are a blind spot.** The walk yields `str` leaves only, so a
  СНИЛС or phone serialized as a bare JSON number is not inspected. Deliberately
  not patched: scanning numbers means scanning every measurement value, date
  component and internal id in every lab payload.
- **`PIIAuditRecord` has no `destination`.** The block carries it; the record does
  not. A document leaked externally and the same document sent internally produce
  near-identical records apart from the event name.
- **Partial redaction is not fixable by redaction.** Two limits, both recorded
  rather than hidden: a value the detector found only *partially* (the fixture's
  address is detected as `г. Москва`, so `ул. Примерная, д. 1, кв. 2` survives), and
  — after H-1 — a repeated value is now fully redacted, but only because the fix
  was made; the aggregator still collapses duplicates to one finding, so a
  *partially* detected repeated value remains exposed.
- **No false-positive rate is measured.** M6 owns calibration. What M5 can say is
  narrow: no rule in the shipped table fires on any fixture, and each threshold's
  narrowness is asserted rather than assumed.
- **Pre-existing, not ours:** account-api's storage-kind allow-list
  (`app/services/storage.py:80-85`) omits even `classification`; `packages/observability`
  is a 0-byte stub; account-api's `request_logging.py` maskers match field names
  by substring (so `"name"` also matches `"schema_name"`) and live where ai-worker
  cannot import them.

---

## 15. Verification

| Check | Result |
|---|---|
| `uv run pytest tests/unit/pii` | **598 passed** |
| `uv run pytest tests/unit/pipeline` | **46 passed** |
| `uv run pytest` (full ai-worker) | **809 passed**, 5 warnings |
| `uv run --project packages/storage pytest packages/storage` | **19 passed** |
| `uvx ruff check app/pii tests/unit/pii app/pipeline` | clean |
| `uvx ruff format --check app/pii` | clean |
| Root `make lint` | 4 errors, all pre-existing in `packages/storage` |
| `import app.pii` with `app.pipeline` + `app.classification` + `packages.canonical` blocked | passes (subprocess guard) |
| `app/pii` exports | 85, sorted, unique, all resolvable |
| Smoke check | `1.2.0 3.0.0` |

Per-file test counts:

| File | Tests | Covers |
|---|---|---|
| `test_models.py` | 23 | enum values, model shapes, frozen, import boundaries |
| `test_schemas.py` | 13 | schema parity, no `value` at schema level |
| `test_detectors.py` | 22 | protocol, stubs raise, composite order/non-empty |
| `test_detectors_behaviour.py` | 45 | pattern/labelled/secret detection, the `2b8fdd0d` shape |
| `test_masking_redaction.py` | 38 | all 23 mask rules, HMAC |
| `test_policy_gate.py` | 72 | §4.4 table, policy completeness, decision matrix, `DECISION_OUTCOMES` |
| `test_policy_behaviour.py` | 21 | overrides, redact-unavailable, empty document |
| `test_aggregation_behaviour.py` | 16 | dedup key, empty-fingerprint bypass, survivor selection |
| `test_gate_behaviour.py` | 12 | `PIIGate.inspect` over the real chain |
| `test_canonical_guard.py` | 34 | walk, paths, cycles, `DECISION_REMEDIATION`, real leak paths |
| `test_canonical_guard_behaviour.py` | 35 | persistence escalation, per-category sanitizer, both dump points |
| `test_redaction_behaviour.py` | 40 | the redaction algorithm, offset verification, repeated values (H-1) |
| `test_persistence_contract.py` | 33 | §4.7 block, audit without values, versions, SemVer |
| `test_fixture_manifest.py` | 34 | manifest shape, disk↔manifest parity, enum validity |
| `test_manifest_verification.py` | 34 | `expected_*` measured against the real chain |
| `test_artifact.py` | 32 | `build_pii_artifact`, block shape, upload-before-publish |
| `test_settings_boundary.py` | 37 | fingerprint secret, chain construction, chain order |
| `test_external_boundary.py` | 30 | `EXTERNAL_LLM` redaction, versions |
| `test_combination_policy.py` | 27 | the threshold, both sides, precedence, validators |

Plus `tests/unit/pipeline/test_pipeline.py` (46) for the wiring, and
`packages/storage/tests/test_keys.py` for the artifact key.

The three assertions carrying the security value (plan §5):

1. `"value"` is absent from `PIIFindingSummary` / `PIIScanResult` fields and from
   `PIIFinding.model_dump()` — the exclusion is structural;
2. `PII_FINDING_SCHEMA` has no `"value"` property — schema-level proof;
3. `PIIAuditRecord` has no `"value"` / `"value_fingerprint"`, and the **exact**
   field set is asserted so a field cannot be appended later.

Plus the contour tests that are the milestone's actual acceptance criterion, in
`test_pipeline.py` — one loop over the three surfaces, plus the two companions:

| # | Test | Assertion |
|---|---|---|
| 1 | `test_canonical_guard_sanitizes_all_three_sinks` | one loop over `canonical.json` / `structured.md` / event `data`: no patient name, no ticket number, **and** `[PERSON_NAME]` present — the third clause catches a guard that dropped the note instead of masking it |
| 2 | `test_canonical_guard_keeps_the_clinician_and_the_service_date` | `document_date == "2026-03-05"` and `Петров И. С.` intact; a masked-everything guard fails here |
| 3 | `test_the_extracted_payload_the_pipeline_holds_is_the_sanitized_one` | the model handed to the frontmatter builder is the sanitized one — the *ordering* claim the output test cannot make |
| 4 | `test_canonical_guard_blocks_a_secret_reaching_any_sink` | contour-2 halt precedes every dump |
| 5 | `test_a_combination_halts_contour_2_before_any_dump` | the P17 rule halts on contour 2 as well as contour 1 |

```bash
cd apps/ai-worker
uv run pytest tests/unit/pii -v      # 598
uv run pytest                        # 809, full suite
uv run pytest tests/unit/pipeline -v # 46, wiring
uvx ruff check app/pii tests/unit/pii app/pipeline
```

Commands must run from `apps/ai-worker`; from the repo root resolution can fail
on the `torch==2.13.0` macOS wheel (pre-existing, CI runs linux).

---

## 16. Appendix — document tree

```text
PII GATE/
├── IMPL_ARCH.md          # design reference (taxonomy, principles, phases 1–10, §§1–45)
├── IMPL_PLAN.md          # M4 + M5 runbook (Revision 3; statuses in three places)
├── IMPL_RPRT.md          # this report
```

Related: `docs/development/ORGS/IMPL_ARCH.md` (organization contour),
`../CLASSIFICATION 2.0/IMPL_RPRT.md` (the sibling report this one mirrors in
structure), `../ORDER.md` (§13 the M5 leak analysis and scope rulings),
`docs/messaging/EVENTS.md` (event catalog — no new event; `data["pii"]` is a new
*key* on an existing event, flagged as R11 for M6 if the catalog formalizes
`data`).
