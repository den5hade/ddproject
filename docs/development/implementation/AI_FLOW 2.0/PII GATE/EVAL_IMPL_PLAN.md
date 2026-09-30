# PII Gate — Evaluation & Calibration (M6)

**Scope.** Implements ORDER.md **M6** — PII Gate evaluation: deterministic, offline evaluation tooling for the gate built in M4/M5 ([IMPL_PLAN.md](./IMPL_PLAN.md), Revision 3, Phases 8–15 + 17 done, 16 deferred; [IMPL_RPRT.md](./IMPL_RPRT.md)), a two-source dataset model (committed synthetic regression corpus + local-only real corpus), ground-truth audit of the fixture manifest, a real-corpus calibration pass over the detector layer, count-based regression gates, and a human-readable evaluation report. Built on the existing implementation and infra only — no parallel architecture; the evaluation is a dev-only CLI consumed by the gate's own suite, not a pipeline stage. Mirrors [Classification 2.0 EVAL_IMPL_PLAN.md](../CLASSIFICATION%202.0/EVAL_IMPL_PLAN.md) (M3) in structure, because M3 is the sibling evaluation milestone and its harness is the template.

**Decisions locked at kickoff (user-confirmed 2026-09-30):**
- **Dataset — hybrid, two clearly separated corpora.** *Committed synthetic* (`tests/fixtures/pii/`): reproducible, runs in CI, deterministic regression gates, minimum security-control coverage. Derived from real documents' **structure** (table/label layout, OCR artefacts, field ordering, realistic PII placement, multiple categories, realistic combinations) with **every identity value invented** — not a mechanical string substitution, which could accidentally preserve real PII. *Local real corpus* (`$PII_FIXTURES_DIR`, gitignored): the authoritative source for precision/recall and detector-failure discovery, never committed, never required by CI.
- **Security invariant — ORDER §13.3 stands, unweakened.** No real patient data may be committed to `tests/fixtures/pii/`. The existing `tests/fixtures/classification/` dataset **does** commit 7 real markers containing real ФИО/СНИЛС/ОМС/address; that is **existing technical debt, not precedent**, and M6 must not reinterpret §13.3 to accommodate it. Enforced by `test_no_real_pii_in_fixtures.py`, not by prose.
- **No false precision.** The report distinguishes `synthetic_regression_metrics` from `real_corpus_evaluation_metrics`. If the local corpus is absent, the CLI reports that real-corpus evaluation **was not performed** — it never falls back to synthetic and never prints synthetic numbers under a real-corpus heading. CI acceptance and local calibration acceptance are two distinct levels; CI must not depend on the real corpus.
- **Manifests may be separate, schema and semantics identical.** The local manifest carries a fixture id, expected categories, expected detector source, expected decision, and provenance metadata — and **no raw PII values**.
- **Scope: measure + calibrate detectors and policy.** Out of scope: the `PIIAuditRecord` sink (M4-deferred), `REDACTOR_VERSION` (M5-filed, but not in the chosen scope), the durable `needs_review` state (that is the R9/R15 fix, not an eval task), `PIIAuditRecord.destination`, and the numeric-leaf walk (Phase 6 gap — report as a finding; changing the walk is a detector-surface change with its own calibration).
- **The Phase 17 combination rule is frozen at `PII_POLICY_VERSION = 3.0.0`** and its result is reported, not fixed. The real-corpus halt rate is a product/security policy decision, not an evaluation decision (§0, Finding C). Marked `PENDING_PRODUCT_DECISION`.

**Depth sources:** [IMPL_ARCH.md](./IMPL_ARCH.md) (PII gate design spec, §§1–45), [IMPL_PLAN.md](./IMPL_PLAN.md) (M4+M5 runbook — §4.4 policy table, §4.10 manifest shape, §4.11 persistence escalation, §4.12 per-category remediation, §4.13 combination rules, §4.8 versioning, §7 risks R1–R15 and open decisions), [IMPL_RPRT.md](./IMPL_RPRT.md) (§14 known limitations — "No false-positive rate is measured. M6 owns calibration."), [ORDER.md](../ORDER.md) (§2 PII Gate, §12 milestones, §13 the M5 leak analysis and scope rulings, §13.3 the data ruling this plan must not weaken), [STRUCTURE.md](../STRUCTURE.md) (§5 `pii/` layering), [Classification 2.0 EVAL_IMPL_PLAN.md](../CLASSIFICATION%202.0/EVAL_IMPL_PLAN.md) (the M3 harness this mirrors), [IMPL_PLAN_SCHEMA.md](../../operational/IMPL_PLAN_SCHEMA.md). The detector regexes and the taxonomy hold in `app/pii/`; this plan is the runbook.

**Revision 1** — initial M6 evaluation + calibration plan (2026-09-30). Supersedes nothing; the first M6 document. M5 closed as Phases 8–15 + 17 `[x]`, 16 `[~]` deferred, with `uv run pytest` → 809 passed and `DETECTOR_VERSION` `1.2.0` / `PII_POLICY_VERSION` `3.0.0`.

Status legend: `[ ]` pending · `[x]` done · `[~]` deferred (out of the current milestone).

---

## 0. Overview

**Current (as-is):** the gate is implemented, wired into both contours and asserted against 6 synthetic fixtures. It is **not calibrated**. `IMPL_RPRT.md` §14 states it plainly: *"No false-positive rate is measured. M6 owns calibration. What M5 can say is narrow: no rule in the shipped table fires on any fixture, and each threshold's narrowness is asserted rather than assumed."* The dataset and the guard's exposure:

```text
tests/fixtures/pii/                       .dev/flow_upload_test/  (gitignored)
  manifest.json v1.0.0 — 4 entries          9 dirs = 6 unique documents
  source: "synthetic"  ×4                    (3 md5-identical pairs)
  marker.md      4, all synthetic            9 × marker.md
  canonical/     2, fields.note ONLY         9 × canonical.json, 18 leaf paths
```

Both are inverted against what the milestone needs. The committed corpus cannot produce a false-positive rate (Phase 16's own revisit condition #3 already says so: *"a synthetic set cannot produce a false-positive rate and the false-positive rate is the only number that decides whether this detector is affordable"*). The real corpus is invisible to every test, gate and report.

**The guard has been run against one leaf path.** The 2 committed canonical fixtures are *exactly* the two leak shapes in ORDER §13.1 — `fields.note` and nothing else. Of the 18 string leaf paths present in the 9 real payloads, 17 have never been through `walk_string_leaves`:

```text
covered by a committed fixture:  fields.note
never seen by the guard:         conclusion · equipment · material · language
                                 document_date · type · subtype
                                 institution.{name,address,ogrn}
                                 performed_by[]
                                 fields.results[].{name,value,unit,interpretation,
                                                  reference_min,reference_max}
```

`institution.ogrn` is a 13-digit value on 4 of 9 real payloads and `performed_by[]` is an uppercase ФИО + role string on 6 of 9 — both exactly what a free-form-walk guard is most likely to mis-claim, and neither has ever been asserted.

**Target (M6):**

```text
EvaluationDataset (Protocol)
   ├── SyntheticFixtureDataset   tests/fixtures/pii/        committed · CI
   └── LocalRealCorpusDataset    $PII_FIXTURES_DIR          local-only · calibration
            └── both → list[FixtureEvaluation]  (one normalized record shape)
                  → compute_metrics()   multi-label, ONE implementation, no branch
                  → summarize() / render_text() / render_markdown() / _to_json()
        → evidence → detector-layer calibration (DETECTOR_VERSION bump)
        → dataset-source-aware regression gates (synthetic in CI, real locally)
        → eval report artifact + IMPL_PLAN M6 addendum
```

**Key mechanisms:** one deterministic evaluation path (`MarkdownNormalizer → CompositePIIDetector → DefaultPIIAggregator → DefaultPolicyEngine → PIIScanResult`), run at both boundaries; a fixture loader owned by the **app** (tests delegate to it) so `evaluate.py` is not a test-side script; the dataset boundary is a **Protocol with two implementations at the top of the report**, never a branch inside the metrics; every calibration change cites a numbered finding; gates below `0.1` thresholds are expressed as counts.

### Pre-calibration probe — measured, not hypothesised

A read-only pass over the local corpus on 2026-09-30 established the following before any harness existed. These are the questions M6 exists to answer, and four of them are already partially answered.

**Corpus shape.** 9 directories, **6 unique documents** (3 pairs are byte-identical uploads: `2b8fdd0d`=`f1130ec3`, `b29e3f45`=`b8f07559`, `e9420e81`=`fbbcb675`). 3 of the 6 unique documents (`2b8fdd0d`, `b29e3f45`, `e9420e81`) are already committed in the classification dataset; **3 are not** (`311a0a42`, `3bee892c`, `c4e01278`).

> **Correction to an earlier figure.** A preliminary note accompanying this plan's kickoff reported "10 directories = 7 unique documents" and a "4 of 7 = 57%" halt rate. Both were wrong — the corpus is 9 directories / 6 unique documents, and the halt rate is **4 of 6 = 67%**. The corrected figure is what §0 Finding C and Phase 3 use. The 67% figure is the one the product decision rests on.

**Finding A — the structured detector cannot read the two dominant real layouts.** `_FIELD_GAP = r"[\s:*_~>|#\-–—]*[:：][\s|*]*"` (`app/pii/detectors.py:735`) makes the colon **mandatory**, and 3 of the 6 unique real documents have no colon after the label:

```text
layout A — 3bee892c (ECG), c4e01278 (ultrasound)
    | **Дата рождения (возраст)** | **СНИЛС** |
    | 27.07.1984 (41 год) | 12306708221 |          label in a header cell,
      ... | **Адрес постоянной регистрации** |        value two rows below

layout B — b29e3f45 / b8f07559 (biochemistry)
    **СНИЛС**
    12306708221                                          label and value on
                                                         separate lines
```

So `snils.labelled`, `insurance_number.labelled`, `person_name.labelled` and `date_of_birth.demographic_shape` — the 0.95-confidence `StructuredFieldPIIDetector`, 19 rows — cannot fire on half the real corpus. Detection degrades to `PatternPIIDetector`, whose recall claims were calibrated on `2b8fdd0d`: an **appointment** form, in a corpus where 4 of 6 unique documents are lab/ECG/ultrasound. The real documents also carry `Паспорт гражданина Российской Федерации 6704 370297` (`3bee892c`) — a `PASSPORT` in the `government` group — and a second address cell, neither of which any committed fixture exercises.

**Finding B — `ОГРН` is a systematic false positive.** `ОГРН: 1028600607441` is 13 digits, and `_LONG_DIGIT_RUN` claims any run of ≥12 (`detectors.py:270`). It is present on 3 of 6 unique real documents (4 of 9 dirs), lands as `ticket_number`, and §4.11 escalates `TICKET_NUMBER` to `REDACT` at `stage=canonical, destination=persistence` — so the clinic's own registration number would be masked in every stored canonical. This is **R7 recurring on a different field**: R7 already fired once, when Phase 14's unplanned `date_of_birth.numeric` rule destroyed `document_date` and had to be removed mid-milestone. §4.11's own note is the lesson: *escalating a category makes its detector's recall claims load-bearing in a way they were not before.*

**Finding C — the Phase 17 combination rule halts 4 of 6 real documents (67%).**

| unique document | dirs | `government` categories | decision at `3.0.0` |
|---|---|---|---|
| `2b8fdd0d` appointment | `2b8fdd0d`, `f1130ec3` | SNILS + INSURANCE_NUMBER | **`review`** |
| `3bee892c` ECG | `3bee892c` | SNILS + INSURANCE_NUMBER + PASSPORT | **`review`** |
| `c4e01278` ultrasound | `c4e01278` | SNILS + INSURANCE_NUMBER + PASSPORT | **`review`** |
| `b29e3f45` biochemistry | `b29e3f45`, `b8f07559` | SNILS + INSURANCE_NUMBER | **`review`** |
| `e9420e81` hematology | `e9420e81`, `fbbcb675` | — | `allow` |
| `311a0a42` lab | `311a0a42` | — | `allow` |

Each halt is **zero artifacts**, one `document.processing.failed` with `error_code="PII_REVIEW_REQUIRED"`, and no consumer (R9/R15). This is the number R15 recorded as *"M6's to measure"* and the availability risk Phase 17 accepted in exchange for a narrow rule. **Per the kickoff ruling the rule is not changed.** What M6 produces is the measurement plus both halves of the consequence:

- **security effect** — the rule does catch what it was written to catch, on real documents, which is evidence the rule is *technically* doing its job;
- **availability / processing impact** — 67% of the current real corpus is halted, with no queue, no review UI, and no recovery path short of a re-upload.

The report must state both and decide neither.

**Finding D — the committed corpus has no realistic negative.** `clean/generic-notice-01.md` is a one-line synthetic notice. `311a0a42` is a genuine real laboratory marker with **zero** PII tokens (`снилс`/`полис`/`дата рождения`/`фио`/`талона`/`телефон` all absent) — a real clean document, and the only one in the corpus. Without it, precision cannot be measured on realistic prose, because the committed corpus contains no document in which a false positive could plausibly occur.

**Invariants (locked):**
- Evaluation is deterministic + offline: `python -m app.pii.evaluate` on a fixed corpus must be reproducible run-to-run; no LLM, no network, no storage writes.
- Format-dataset boundary: the evaluate CLI is a dev tool. It must **not** write to S3/RabbitMQ or mutate pipeline state; the report is local output (stdout / `--json` / `--report`).
- `expected_*` in either manifest is **ground truth**, not a projection of detector output. Any manifest change must be a label correction, not "make the test pass".
- **No real patient data in `tests/fixtures/pii/`.** ORDER §13.3 is not weakened, reinterpreted, or extended to accommodate the classification dataset. Enforced by a test (§5).
- **The real corpus is never loaded by default** and CI never depends on it. With `PII_FIXTURES_DIR` unset, no path under `.dev/` is reachable from the loader, and the real-corpus block in `--json` is **absent, not zero**.
- **One evaluator, two sources.** The dataset boundary is `EvaluationDataset`; both implementations produce the same `FixtureEvaluation` record. Evaluation logic is not duplicated per corpus.
- Every calibration change that alters **detection** → `DETECTOR_VERSION` bump per §4.8. Every change that alters a **decision for any input** → `PII_POLICY_VERSION` **major** bump, and a product ruling first. A detection change is in scope; a decision change is not.
- No calibration change without a numbered finding in the Phase 3 report (anti over-fitting guard).
- The Phase 17 combination rule, the `AGE`-on-`EXTERNAL_LLM` masking trade, `REDACTION_AVAILABLE`, the audit sink, the durable review state and the numeric-leaf walk are all **out of scope** — each named in §1's out-of-scope block rather than left for a reader to find.

---

## 1. Execution summary

| Phase | Scope | Status |
|---|---|---|
| 1 | Evaluation core — `evaluate.py` CLI + `EvaluationDataset` abstraction + app-owned loaders | [x] |
| 2 | Multi-label metrics + ground-truth audit of the manifest | [x] |
| 3 | Real-corpus calibration pass — measure, report, calibrate the **detector** layer | [ ] |
| 4 | Dataset-source-aware regression gates + derived fixtures + `make eval-pii` | [ ] |
| 5 | Close-out — DoD, eval report artifact, docs addendum, decision hand-off | [ ] |

**Out of scope, by ruling:**

```text
Phase 17 combination rule           PENDING_PRODUCT_DECISION · 3.0.0 frozen · not measured-and-fixed
  no removing INSURANCE_NUMBER · no 2→3 · no REVIEW→ALLOW · no Russian-record exemption
PIIAuditRecord sink                 M4-deferred; not in the chosen M6 scope
REDACTOR_VERSION                    M5-filed for M6; not in the chosen M6 scope
needs_review durable state          the R9/R15 fix, not an evaluation task
PIIAuditRecord.destination          M4 Phase 7 gap; belongs to the first real audit sink
numeric-leaf walk (Phase 6 gap)     report as a finding; the walk's contract is not M6's to change
AGE masking on EXTERNAL_LLM         reported as a second decision candidate, not resolved
F1 ticket_number label            PENDING_GROUND_TRUTH_RULING · manifest ground truth
                                   is not an evaluation decision · Phase 5 hand-off
```

---

## 3. Pending phases

### Phase 1 — Evaluation core (CLI + dataset abstraction) [x]

`app/pii/evaluate.py` — `python -m app.pii.evaluate`, mirroring `app/classification/evaluate.py`'s 18-name surface (`run_evaluation`, `evaluate_fixture`, `compute_metrics`, `compute_domain_rates`, `compute_confidence_stats`, `summarize`, `render_text`, `render_markdown`, `main`, …) so the two harnesses are learnable as one.

**The new axis — dataset source.** `app/pii/fixtures.py` grows from one manifest to two, behind a Protocol:

```text
EvaluationDataset (Protocol)
    name: str · available: bool · unavailable_reason: str | None
    iter() -> list[FixtureEvaluation]

SyntheticFixtureDataset    tests/fixtures/pii/            committed · CI
LocalRealCorpusDataset     $PII_FIXTURES_DIR (fallback
                           .dev/pii-fixtures/)           local-only · calibration
```

Both produce the **same** `FixtureEvaluation` record — the only field that differs is `dataset`. The metrics functions take `list[FixtureEvaluation]` and contain **no dataset branch**; a test asserts the evaluator never inspects `dataset` outside the renderers.

Per-fixture record: expected vs predicted categories, per-detector attribution (`{detector_name: [categories]}`), decision, risk level, stage + destination at which it was evaluated, `over_redacted` set, confidence band, and `findings_count`.

**Both boundaries.** Evaluation runs the gate twice per fixture — `stage=document, destination=INTERNAL_LLM` (contour 1, the production default) and `stage=document, destination=EXTERNAL_LLM` with `redaction_available=False` (the context the manifest's `expected_decision` has always assumed, per Phase 13's `MANIFEST_CONTEXT`). A separate contour-2 pass evaluates canonical payloads at `stage=canonical, destination=persistence`. Three rows in the report, because M4's gap 1 (Phase 7) is still true: `expected_decision` is destination-dependent and a single expected value is wrong half the time.

**Report shape — the load-bearing part.** The dataset boundary is **at the top of the report, not inside the metrics**:

```json
{
  "detector_version": "1.2.0", "policy_version": "3.0.0", "evaluation_version": "1.0.0",
  "datasets": {
    "synthetic_regression": { "available": true, "source": "committed",
                              "manifest_version": "2.0.0", "metrics": { } },
    "real_corpus":         { "available": false, "source": "local-only",
                              "reason": "PII_FIXTURES_DIR unset and no default corpus found" }
  }
}
```

`available: false` carries **no `metrics` key at all**. A synthesised empty block reads as a measurement of zero rather than an absent measurement, which is the false precision the kickoff ruling rules out. `render_markdown` states corpus availability in its header line, and `MANIFEST_AUDIT.md` records which corpus produced the shipped numbers.

CLI: stdout summary, per-fixture detail, `--json`, `--report <path>`. `main()` always returns `0` — thresholds live in pytest, as in M3. Deps: M5 as-is.
**Accept:** CLI runs on the committed corpus; output matches hand-audited expectations for 3 known fixtures (`patient/synthetic-consultation-01.md` → 7 categories / `review` at external; `appointment/synthetic-registration-01.md` → `person_name` + `ticket_number` only; `malicious/synthetic-injection-01.md` → `secret` + `ticket_number` / `block`); `--json` emits both dataset blocks with `real_corpus.available == false` and **no** `metrics` key; no test-side import from `app` (M3's subprocess guard, reused); the loader reaches nothing under `.dev/` when `PII_FIXTURES_DIR` is unset.

### Phase 2 — Metrics & ground-truth audit [x]

Metrics in `evaluate.py` (pure functions, Pydantic-typed results). **Multi-label, not single-label** — M3's `compute_metrics` is single-label by construction and `expected_categories` is a set of up to 7:

```text
per category c:  tp = c ∈ expected ∩ predicted
                 fp = c ∈ predicted \ expected
                 fn = c ∈ expected \ predicted
                 precision / recall / F1 ; support = tp + fn
                 macro (unweighted over present categories) + micro (Σ)

document level:  exact_set_match     every category matches, nothing extra
                 subset_recall       expected ⊆ predicted      ← the number that matters
                 over_fire_count     |predicted \ expected| per document

domain rates (M3's four adapted, counts alongside):
  false_positive_document   predicted ⊄ expected, ≥1 spurious category
  missed_category_document  expected ⊄ predicted
  combination_trip          decision escalated by a PIICombinationRule
  over_redacted             a category masked that no detector claimed
  false_positive_detector   per-detector FP count, so Finding A/B become numbers

detector attribution:  per-detector tp/fp/fn
confidence reliability:  same 3-band table as M3, keyed on PIIFinding.confidence
```

`over_redacted` is the metric M3 has no analogue for and the one that catches the R7 class of bug: a rule that destroys data it was never asked to touch. It is computed **per category, not per document**, because `document_date` being masked is invisible at document granularity — that is exactly how it shipped undetected in Phase 14.

Audit both manifests entry by entry. Committed: confirm each `expected_categories` is human-verifiable from the derived text alone, and each `expected_detector_source` is justified. Local: build it, but **no raw PII values** in it. Deps: Phase 1.
**Accept:** metrics unit-tested against hand-built mini sets with exact fractions (M3 Phase 2 pattern); the audit produces a numbered findings list; **no label flipped without a recorded rationale**; `MANIFEST_AUDIT.md` exists and every entry cites its provenance without reproducing a patient's data.

**Delivered.** `EVALUATION_VERSION` `1.0.0` → `1.1.0` (additive metric layers; the detector and policy versions are untouched). The four reductions are `compute_category_metrics`, `compute_domain_rates`, `compute_detector_attribution` and `compute_confidence_stats`, exported and reachable as `DatasetEvaluation` properties, with the AST corpus-blindness guard parametrized over all five reductions plus `summarize` and a completeness check so a sixth cannot be added unguarded. Exact-fraction tests live in `tests/unit/pii/test_evaluate_metrics.py` (45), the audit's own obligations in `tests/unit/pii/test_manifest_audit.py` (12). Committed corpus: 6 fixtures / 10 boundary rows / 20 findings / 11 observed categories, every category at F1 1.0, 0 false-positive claims, 0 declared-layer mismatches.

**Three unit decisions and one divergence are recorded in `MANIFEST_AUDIT.md` § Measurement decisions (D1–D4)**, because a unit is the part of a rate that is invisible in its output until it is wrong:

| decision | subject | note |
|---|---|---|
| **D1** | claims and declared-source mismatches counted per fixture, not per boundary row | counting per row reported the corpus's 20 claims as 33; the committed corpus hid it because every claim in it is currently correct and `2 × 0 = 0` |
| **D2** | `over_redacted` per category over `category_observations` (`Σ \|expected_categories\|` = 18 here) | the plan's "per category, not per document", with the row variant rejected: it reads a boundary difference as a fidelity defect. Structurally 0 today, which is the point |
| **D3** | `source_expectation_mismatches` denominated by the 5 fixtures that declare a source | a corpus that declares nothing is not "mismatched 0 times"; 0/0 would print as 0.0% |
| **D4** | per-detector attribution has **no `fn`** — diverges from this phase's `per-detector tp/fp/fn` | **ruled in Phase 2 review: accepted as delivered.** A miss has no claimant, and it is already published twice — `CategoryMetrics.fn` (the count, per category) and `DomainRates.missed_category_document` (the rate, per document) — so a per-rule copy would be a third statement of a fact with no new information. The attributable layer property is D3's `source_expectation_mismatches` |

Two defects were found and fixed while verifying the phase, both recorded as findings rather than quietly patched: the per-boundary mark conflated "the category set agreed" with "the decision agreed" and printed `MISMATCH` on rows whose categories matched exactly (**F10**), and the same D1 accounting error (**D1**). **F1** — the committed corpus's labels were measured from the detector, so it has no false positive by construction — is **ruled in Phase 2 review: not applied**, filed as `PENDING_GROUND_TRUTH_RULING` and handed off as a product decision in **Phase 5**. It is deliberately *not* a third `PENDING_PRODUCT_DECISION`: the two existing items are policy questions, and this one changes what the corpus *is*, which no phase of M6 may decide. `ticket_number` stays in `expected_categories` for the whole milestone, and with it the standing constraint that **no committed-corpus figure may be quoted as a precision measurement**. Phase 3 cites F4 and F6 for its detector changes.

### Phase 3 — Real-corpus calibration pass [ ]

Local-only. Assemble `.dev/pii-fixtures/` (symlinks or a copy step from `.dev/flow_upload_test/`, so the local manifest is stable and the corpus is gitignored), write its manifest per the no-raw-values rule, run the evaluator, and record the report.

**Then calibrate the detector layer only.** Each change cites a numbered finding, exactly as M3 Phase 3:

- **Finding A** — teach `StructuredFieldPIIDetector` the two colonless layouts (header-cell value two rows below; bold label on its own line). The label is already the mechanism; what is missing is the gap. Note the tension: widening the gap is a recall change that also widens the false-positive surface, which is why it needs the measurement, not an argument.
- **Finding B** — stop `ticket_number.long_digits` claiming an `ОГРН`. A bare digit run cannot distinguish a ticket from a company registration number; the label is the only evidence, and `ОГРН` is a label. Whatever the fix, it must be pinned by a test that asserts a 13-digit `ОГРН` under its own label is not `ticket_number`.

Bump `DETECTOR_VERSION` per §4.8 (a rule leaving and a rule arriving is neither purely additive nor breaking — the `1.1.0 → 1.2.0` precedent in §4.8's roadmap is the precedent, and the reason it moved is the reason this one will).

**Then report, and stop.** Finding C and the `AGE`/`EXTERNAL_LLM` trade are written up with the measurement and **not changed**: `PII_POLICY_VERSION` stays `3.0.0`; no `INSURANCE_NUMBER` removal, no 2→3, no `REVIEW`→`ALLOW`, no Russian-medical-record exemption. Each is filed in `MANIFEST_AUDIT.md` as `PENDING_PRODUCT_DECISION` with the numbers, the per-document evidence, and the framing the ruling requires — *not* evidence that the rule is technically incorrect, but evidence of a large operational impact on the current corpus. Deps: Phase 2.
**Accept:** the report contains the Finding C table verbatim — total documents evaluated, count carrying `SNILS` + `INSURANCE_NUMBER`, count halted, percentage, per-document evidence, resulting decision, and for each whether it would otherwise have been `allow` / `allow_with_warning`, plus the zero-artifact / no-consumer consequence — and states that **4 of 6 (67%)** of the current real corpus halts; the rule is at `3.0.0` with a test asserting it; `MANIFEST_AUDIT.md` marks it `PENDING_PRODUCT_DECISION`; every detector change has a cited finding; `MANIFEST_AUDIT.md` records whether the real corpus was available for the run.

### Phase 4 — Regression gates, derived fixtures, `make eval-pii` [ ]

Rework the gates to be **dataset-source aware**: CI gates assert **only** on `synthetic_regression`; the real-corpus assertions run locally and never in CI. Real-corpus test modules `skip` with an explicit reason when the corpus is absent — never a silent pass.

Add the **derived committed fixtures** — the structurally faithful, value-invented corpus:

```text
tests/fixtures/pii/manifest.json  1.0.0 → 2.0.0   (PIIFixture gains id + expected_detector_source)
  laboratory/   2 derived — layout A (header-cell) and layout B (bold label, own line)
  mixed/        2 derived — multi-page with a passport cell, and an ОГРН under its label
  clean/        1 derived — real-shaped lab marker with no PII (Finding D's committed twin)
  canonical/    4 derived payloads — laboratory-table, performed_by[], institution.*, results[]
```

Each derived fixture records `derived_from: "<short id> (layout only)"` and an `expected_detector_source` map. The `expected_detector_source` key is the machine-checkable form of Finding A: the committed fixtures pin **which layer** must fire, so "the structured detector went silent on a real layout" fails a test instead of degrading quietly. `PII_FIXTURE_DIRECTORIES` already reserves `laboratory/` and `mixed/` and they are currently empty — the derived fixtures land there, so no new directory is declared.

Manifest `version` goes to `2.0.0` because `PIIFixture` gains fields. `test_no_real_pii_in_fixtures.py` lands with this phase, since it is what makes the corpus safe to commit at all.

Makefile target `make eval-pii`. **The M3 gotcha applies**: the target must `cd apps/ai-worker && uv run python -m app.pii.evaluate`; `uv run --project apps/ai-worker python -m …` from the repo root fails with `no module named 'app'`. Deps: Phase 3.
**Accept:** `make eval-pii` runs; CI green with the local corpus **absent**; the real-corpus test module skips with a stated reason; every committed fixture's `expected_detector_source` is asserted; `test_no_real_pii_in_fixtures.py` passes.

### Phase 5 — Close-out (DoD) [ ]

Verify ORDER.md §DoD against the PII Gate items and write the decision hand-offs. The report artifact states which corpus produced each metric and whether the real corpus was available for the run. Add an M6 addendum to `IMPL_PLAN.md` (Revision 4) and a §17 to `IMPL_RPRT.md`. Record the dataset-scaling caveat: the real corpus is 6 unique documents, so every rate M6 publishes is report-grade, not a gate — the same N-is-small caveat M3 recorded, and the same reason gates stay in counts. Deps: Phase 4.
**Accept:** deliverable files listed in §"Deliverables"; this plan's three-status mirrors (§1 table, §3 headings, §6 list) all `[x]`; the two `PENDING_PRODUCT_DECISION` items are recorded as findings with numbers, not resolved; and the `PENDING_GROUND_TRUTH_RULING` item (audit **F1**, the `ticket_number` label on `malicious-synthetic-injection-01.md`) is handed off as a **third, separate** decision — a manifest ground-truth change rather than a policy one, with the numbers, the four M5 assertions the flip breaks, and the projection of the corrected metrics.

---

## 4. Locked design reference (condensed)

**Locked invariants, for the record** (IMPL_PLAN §0, restated because M6 must not weaken them): PII presence alone never blocks; no raw PII value crosses a boundary; `value_fingerprint` is a salted HMAC, never a plain hash; the gate is a document-level capability, not schema-level; originals are immutable; remediation is per-category, not per-decision; aggregation is per-leaf, never across leaves; fail closed on gate failure. M6 is an **offline observer** of all nine and changes none of them.

**Policy table (M5 baseline, read-only for M6 except by ruling):** `SECRET` → `critical`/`block`; 10 categories `high`; 6 `medium`; 6 `low`. `DEFAULT_POLICY` blocks only `SECRET`. `destination=EXTERNAL_LLM` → `REDACT_ON_EXTERNAL` (18, derived from `PII_CATEGORY_GROUPS` minus nothing at that boundary); `destination=UNKNOWN` → `review`. Precedence `block > review > allow_with_warning > allow`. §4.11 adds the persistence escalation (15 categories → `REDACT` at `stage=canonical, destination=persistence`); §4.13 adds `PIICombinationRule(requires_groups={"government"}, min_count=2, decision=REVIEW)`.

**Versioning policy (§4.8, locked):** `DETECTOR_VERSION` `1.2.0`, `PII_POLICY_VERSION` `3.0.0` at M6 start. Patch = docs/comments. Minor = additive and backward-compatible. Major = breaking, **and any change that alters a decision for any input**. Detector and policy versions move independently. M6 adds a third constant, `EVALUATION_VERSION`, stamped into the report — for the harness, so a stale report is identifiable, following the same argument that made `policy_version` worth having.

**Dataset (current, ground truth to audit in Phase 2):** `tests/fixtures/pii/manifest.json` `version 1.0.0`, 4 entries `{file, source, expected_categories, expected_decision, expected_risk_level}` + optional `contains_secret` — `clean/generic-notice-01.md` (`[]`/`allow`/`low`), `patient/synthetic-consultation-01.md` (7 categories/`review`/`high`), `appointment/synthetic-registration-01.md` (`person_name`+`ticket_number`/`review`/`high`), `malicious/synthetic-injection-01.md` (`secret`+`ticket_number`/`block`/`critical`/`contains_secret`). Plus `canonical/{appointment,laboratory}/…note-01.json`, deliberately outside the manifest. M6 → `2.0.0`, adding `id`, `expected_detector_source` and `derived_from`.

**Local corpus (new in M6, never committed):** `.dev/pii-fixtures/` with its own manifest. The ground truth is **which category is present**, not what it is: `{id, file, provenance, expected_categories, expected_detector_source, expected_decision}`. `provenance` records the shape's origin without reproducing the patient's data. `expected_decision` here is **documented, not asserted at CI** — it is the *output* Phase 3 measures, so asserting it in a gate would make the gate agree with itself.

**Fixture loader:** stays free of the pipeline; `app/pii/fixtures.py` remains stdlib-only and cwd-independent; `PII_FIXTURES_DIR` becomes the documented seam between the two corpora (it already exists and is already env-overridable — M4 built it in for exactly this and nothing has used it since).

---

## 5. Tests

**New:**

| File | Covers |
|---|---|
| `test_evaluate.py` | metrics against hand-built mini sets with exact fractions; CLI `--json`/`--report`/stdout; determinism (two runs byte-identical); no-`tests`-import subprocess guard |
| `test_dataset_isolation.py` | the two acceptance levels: synthetic gates run in CI, real-corpus module skips with a reason, `--json` has no `real_corpus.metrics` key when absent, no path under `.dev/` reachable by default |
| `test_no_real_pii_in_fixtures.py` | no `.dev/flow_upload_test` UUID or short id in any committed PII fixture or manifest; every committed СНИЛС/ОМС/ФИО/паспорт/phone/address value is invented, asserted value-for-value; a documentation test recording that the classification dataset is existing technical debt and **not** precedent, citing ORDER §13.3 |

**Modified:**

| File | Change |
|---|---|
| `test_manifest_verification.py` | + `expected_detector_source` assertions per derived fixture; real-corpus manifest parity |
| `test_canonical_guard_behaviour.py` | the 17 unguarded leaf paths — `institution.ogrn` not claimed as `ticket_number`, `performed_by[]` doctor name preserved, `document_date` preserved, `conclusion` walked |
| `test_regression_dataset.py` (new; PII has no equivalent today) | count-based gates on `synthetic_regression` only |
| `test_fixture_manifest.py` | manifest `2.0.0`; new keys; derived-fixture provenance required |
| `test_pipeline.py` | `DETECTOR_VERSION` pin after Phase 3 |

**Commands** (all from `apps/ai-worker`; from the repo root, resolution can fail on the pre-existing `torch==2.13.0` macOS wheel — CI is linux):

```text
uv run pytest tests/unit/pii -v          # 598 today, grows with M6
uv run pytest                            # 809 today (M5 close)
uv run pytest tests/unit/pipeline -v     # 46 today; the version pin lives here
uvx ruff check app/pii tests/unit/pii app/pipeline
uvx ruff format --check app/pii
uv run --project packages/storage pytest packages/storage
make lint                               # 4 pre-existing packages/storage errors, untouched
uv run python -m app.pii.evaluate        # real-corpus block absent without the corpus
make eval-pii                           # Phase 4
```

Each phase runs its suites + lint before the status is flipped.

---

## 6. Implementation order

1. **Phase 1 — Evaluation core** [x] (tooling foundation; needs nothing but the M5 implementation) — do first; every later phase reads its output
2. **Phase 2 — Metrics & ground-truth audit** [x] (consumes Phase 1 CLI; produces the evidence list)
3. **Phase 3 — Real-corpus calibration pass** [ ] (consumes Phase 2 findings; the only phase that touches `detectors.py`)
4. **Phase 4 — Regression gates & derived fixtures** [ ] (locks Phase 3 behaviour into the suite; makes the corpus committable)
5. **Phase 5 — Close-out** [ ] (DoD report + docs addendum + decision hand-off)

Each phase: implement → update status in all three places (§1 table, §3 heading, §6 list) → pause for confirmation. Baseline: ai-worker 809 + storage 19 (M5 close), ruff clean on `apps/ai-worker/app/pii`, 4 pre-existing `packages/storage` lint errors.

---

## 7. Notes & conventions

### Gotchas (verified 2026-09-30)

- **`_FIELD_GAP` mandates a colon** (`detectors.py:735`) — this is Finding A, and it is the single most consequential thing about the real corpus. Do not "fix" it in Phase 1; Phase 1 measures it, Phase 3 changes it.
- **The real lab documents use two *different* colonless layouts** (header-cell-with-value-two-rows-below; bold-label-on-its-own-line). A fix for one is not a fix for the other. Phase 3 must assert both, and must say which it implemented.
- **`ОГРН` is 13 digits** and `_LONG_DIGIT_RUN` starts at 12. Any long-digit fix has to keep the `2b8fdd0d` acceptance case working: `Номер талона: 2026030709303211960141` is 22 digits and must still be `ticket_number`.
- **3 of the 9 corpus directories are byte-identical uploads** of 3 other directories. Counting directories instead of unique documents overstates N by 50% and would put the Finding C rate at the wrong denominator — the exact error this plan's Revision 1 corrects.
- **`raw_text` is `casefolded` and keeps markdown decoration.** Phase 9's `_MD_DECOR` exists because of this; a new rule written against `marker.md` as it sits on disk will match the file and never fire in production. Every new rule runs through the real `MarkdownNormalizer`.
- **The findings index canonicalised text, the redactor edits markdown.** Phase 12 established that offsets are a *hint* verified against the value. Any new rule that returns offsets inherits that constraint.
- **`2b8fdd0d` and `f1130ec3` are the same document with different markdown bolding** (`| ФИО: |` vs `| **ФИО:** |`). They are the cheapest available `_MD_DECOR` regression pair and M6 should use them as one.
- **`311a0a42` is the only real clean document** and carries no PII tokens at all. It is the only real negative in the corpus; the committed corpus needs a derived twin (Finding D).
- **The 2 committed canonical fixtures are `fields.note`-only** — precisely the two ORDER §13.1 leak shapes and nothing else. Any statement about the guard's behaviour on `institution.*`, `performed_by[]` or `fields.results[]` is currently unsupported by evidence.
- **`PII_FIXTURES_DIR` already exists and is already env-overridable** (`fixtures.py:34`); M4 built the seam and nothing has used it since. M6 does not add a second one.
- **`.dev` is gitignored; `apps/ai-worker/reports/` is gitignored** (`.gitignore:36`, `:41`). Both corpora and both report artifacts are already outside version control by construction — verify, do not assume.

### Open decisions (defaults chosen)

- **Dataset model:** hybrid — real local-only for calibration, derived synthetic committed for CI. **Ruled** (user, 2026-09-30). Default chosen: one `EvaluationDataset` protocol, two implementations, no metrics branch.
- **Report separation:** `synthetic_regression_metrics` and `real_corpus_evaluation_metrics` as sibling blocks, never merged. **Ruled.** Default: absent means no key.
- **Combination rule:** measure and report; do not change. **Ruled** — `PENDING_PRODUCT_DECISION`. Default: frozen at `3.0.0`.
- **Calibration width:** detector-layer only, findings-cited, one change per finding. **Ruled** (measure + calibrate detectors and policy, with decision changes gated on a product ruling). Default: no policy change without a ruling.
- **Report artifact location:** `apps/ai-worker/reports/pii-eval-<yyyymmdd>.md` (gitignored, produced by `--report`), mirroring M3. Default chosen.
- **Regression gate style:** counts over percentages; the real corpus is 6 documents, so **every real-corpus rate is report-grade and none becomes a gate**. Default chosen.
- **Real-corpus assembly:** symlink or copy from `.dev/flow_upload_test/` into `.dev/pii-fixtures/`. Default: symlinks, so the local manifest is stable and the corpus is a view, not a second copy of patient data.
- **Whether a derived fixture can faithfully reproduce an OCR quirk.** If the Phase 3 pass finds a real failure caused by an OCR artifact rather than a layout one, a hand-derived fixture may not reproduce it. **Open — come back rather than quietly weaken the fixture.**

### Risks (mitigations in place)

- **Publishing synthetic numbers as if they were real-world recall** is the top M6 risk, and it is the exact failure the kickoff ruling was written against. Mitigated by the two-block report shape, the absent-key rule, and `test_dataset_isolation.py`.
- **Committing real patient data through the back door** via a derived fixture that a mechanical substitution failed to clean. Mitigated by `test_no_real_pii_in_fixtures.py` asserting values individually, and by a documentation test naming the classification dataset as debt rather than precedent.
- **Over-tuning on 6 documents** — the M3 risk at even smaller N. Mitigated by the findings-citation rule, count-based gates, and the fact that no real-corpus rate is gated at all.
- **Calibrating a decision instead of a detector.** A `REDACT` that fires on `ОГРН` is a policy change wearing a detector change's clothes. Mitigated by the §4.8 rule, by `EVALUATION_VERSION` + the version bump being explicit in every status block, and by the out-of-scope block in §1.
- **The guard regressing on the one path it was built for.** Mitigated by `2b8fdd0d` staying a committed fixture and by the three-direction acceptance assertions (`Петров И. С.` and `document_date` preserved, `[PERSON_NAME]` present — a guard that dropped the note instead of masking it must still fail).
- **Version drift between constants / tests / report / manifest.** Mitigated by the lockstep rule naming `detectors.py` + `test_pipeline.py` + the manifest + the report together, as M3 Phase 3 did.
- **Eval crossing into pipeline state.** Mitigated by the offline/dev-only invariant (§0): no S3/RabbitMQ/DB in `evaluate.py`.
- **The real corpus silently becoming a CI dependency** through a gate that assumes it. Mitigated by `test_dataset_isolation.py` and by Phase 4's explicit accept criterion ("CI green with the local corpus **absent**").

### Conventions

- Follow `docs/development/operational/CONTRIBUTING.md`. M6 changes are localized to `apps/ai-worker/app/pii/` (`evaluate.py`, `fixtures.py`, `detectors.py`), `apps/ai-worker/tests/**`, the root `Makefile`, and the four docs. **M6 does not leave the PII footprint** — no `app/pipeline/`, no `packages/`, no migration. The M5 milestone's expansion of scope into `app/pipeline/pipeline.py` and `packages/storage` is not repeated; M6 observes the pipeline, it does not change it.
- Reuse the existing files rather than renaming: `detectors.py`, `policy.py`, `models.py`, `fixtures.py`, `masking.py`, `canonical_guard.py` all exist. New in M6: `evaluate.py` only.
- Flat layout, mirroring `app/classification/` and STRUCTURE §5 — not `pii/domain/`. Same deviation as M1 and M5; recorded so M6 does not re-litigate it.
- Pydantic v2, `extra="forbid"` on every boundary model, `str, Enum` for enums, `Protocol` for interfaces, string annotations + `TYPE_CHECKING` for cross-package types. `evaluate.py` adds no runtime dependency: stdlib + Pydantic, same as M5.
- The two companion docs live **inside the app package** next to the code, as in M3 (`app/classification/EVAL_FLOW.md`, `MANIFEST_AUDIT.md`) → `app/pii/EVAL_FLOW.md`, `app/pii/MANIFEST_AUDIT.md`. The plan lives in `docs/`.
- Status mirrored in three places: §1 table, §3 heading, §6 list.
- Deviations from this plan, if any, are labeled `Deviation:` in a phase's Implementation Status paragraph when signed off.

---

## Deliverables (M6)

1. `app/pii/evaluate.py` — CLI (`--json`, `--report`), `EvaluationDataset` + two implementations, two-boundary evaluation
2. Multi-label metrics helpers + domain rates + detector attribution (Phase 2)
3. `app/pii/fixtures.py` widened — two corpora behind one seam, `PIIFixture` +`id`/`expected_detector_source`, manifest `2.0.0`
4. `app/pii/EVAL_FLOW.md` (how the eval runs, both corpora) + `app/pii/MANIFEST_AUDIT.md` (ground truth + the findings register + both `PENDING_PRODUCT_DECISION` items)
5. Derived committed fixtures — 5 `marker.md` + 4 `canonical.json`, structurally faithful, every value invented
6. Calibrated `detectors.py` with cited findings (A, B) → `DETECTOR_VERSION` bump; `PII_POLICY_VERSION` unchanged at `3.0.0`
7. `test_evaluate.py` + `test_dataset_isolation.py` + `test_no_real_pii_in_fixtures.py` + source-aware gates + `make eval-pii`
8. Eval report artifact (`reports/pii-eval-<yyyymmdd>.md`, gitignored) + `IMPL_PLAN.md` Revision 4 M6 addendum + `IMPL_RPRT.md` §17
