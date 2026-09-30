# PII Gate — Manifest ground-truth audit

**Scope.** Phase 2 of
[EVAL_IMPL_PLAN.md](../../../../docs/development/implementation/AI_FLOW%202.0/PII%20GATE/EVAL_IMPL_PLAN.md):
label-by-label review of `tests/fixtures/pii/manifest.json` (version `2.0.0`,
6 entries — 4 `marker.md`, 2 `canonical.json`) against the on-disk documents,
plus the first audit of the local real corpus's manifest shape. This document
records **what the ground truth is** and **which findings Phase 3 calibrates
against**; the companion [EVAL_FLOW.md](./EVAL_FLOW.md) describes how the
evaluation runs.

**Method.** Every fixture was read in full and every label checked against its
content — the label text, the table shape, the field ordering, the OCR
decoration. Each `expected_detector_source` was then compared against the layers
the real detector chain used, measured through `app.pii.evaluate` on
2026-09-30 (`DETECTOR_VERSION` `1.2.0`, `PII_POLICY_VERSION` `3.0.0`,
`EVALUATION_VERSION` `1.1.0`, committed corpus = 6 fixtures / 10 boundary rows /
20 findings / 11 observed categories).

**Result.** 6/6 entries confirmed human-verifiable; **0 labels flipped**. One
finding (F1) requires a label correction that is **not applied here** and is
recorded as `PENDING_GROUND_TRUTH_RULING`, ruled in Phase 2 review and handed off
as a product decision in Phase 5: applying it would change the manifest's ground
truth, which is neither an evaluation decision nor a detector one. Two
taxonomy/measurement gaps (F6, F9) are recorded for the milestone that owns them,
and one report defect (F10) was found and fixed in this phase.

---

## What the committed corpus can and cannot measure

| question | answerable here? | why |
|---|---|---|
| does the gate find what a document declares? | **yes** | `subset_recall` = 10/10 |
| does it claim categories a document does not carry? | **no** | see F1 |
| how precise is the detector layer on realistic prose? | **no** | see F6 |
| which layer claims a category? | **yes** | `per_source`, 0 `expected_detector_source` mismatches |
| how reliable is a 0.60-confidence claim? | **not yet** | see F1, F4 |

The second row is the important one. `false_positive_claims = 0` over the whole
committed corpus is **not** a precision measurement — it is an artefact of how
the labels were produced (F1). Any report that quotes it as a precision figure is
quoting a tautology, which is the same failure the M6 kickoff ruling was written
against, one level down.

---

## Per-fixture verdicts

`verdict` is `CONFIRM` when every `expected_*` field is derivable from the
fixture's own text without reference to what the detectors happen to output.

| id | file | expected categories | expected source(s) | verdict | evidence |
|---|---|---|---|---|---|
| `clean-generic-notice-01` | `clean/generic-notice-01.md` | — | — | CONFIRM | «Уведомление о плановом техническом обслуживании»; «12 июня с 09:00 до 17:00» is a **service** date — `PIICategory` has no service-date member and no `date_of_birth` label is present. No name, no contact detail, no identifier. Negative by construction, which is F6's subject |
| `patient-synthetic-consultation-01` | `patient/synthetic-consultation-01.md` | `person_name`, `date_of_birth`, `phone`, `email`, `address`, `medical_record_number`, `doctor_name` | all `structured_field`; `address` also `pattern` | CONFIRM | Six labelled bold rows, one per category: «**Пациент:** Смирнова Ольга Ивановна, 1974-03-12» (name **and** birth date on one row — see F5), «**Телефон:**», «**Электронная почта:**», «**Адрес:** г. Москва, ул. Примерная, д. 1, кв. 2», «**Номер карты:** 0000001234», «**Врач:** Петров И. С.». The two-source `address` declaration is justified by the text, not by the run: a locality pattern matches «г. Москва» on its own and the label rule matches the full address |
| `appointment-synthetic-registration-01` | `appointment/synthetic-registration-01.md` | `person_name`, `ticket_number` | both `structured_field` | CONFIRM | A **declined** booking: «# Запись отменена», «Пациент отказался от приёма. Персональные данные не сохранены». «| ФИО: | Кузнецова Александра Петровича |» and «| Номер талона: | 2026030710155500000001 |». The four near-miss rows that are **absent** are the point of the entry: «Специальность врача:», «Кабинет: 214», «Дата и время: 19 марта на 09:41», «Номер талона» repeated in prose. A declined booking collected no СНИЛС, no policy number and no address, so the set is two categories and the constraint is on the fixture |
| `malicious-synthetic-injection-01` | `malicious/synthetic-injection-01.md` | `secret`, **`ticket_number`** | both `pattern` | **CONFIRM (secret) / see F1 (`ticket_number`)** | «Ключ доступа к хранилищу: \`sk-live-…\`» and «учётные данные интеграции — login=…, password=…» — two credentials, one document, no patient. `ticket_number` is **not** in the text: the only long digit run is the 28-zero numeric body of the API key. See F1 |
| `appointment-synthetic-registration-note-01` | `canonical/appointment/synthetic-registration-note-01.json` | `doctor_name`, `person_name`, `ticket_number` | `structured_field` / `pattern` / `structured_field` | CONFIRM | `fields.note` contains «для пациента Кузнецова Александра Петровича» (patient), «Номер талона: 2026030710155500000001» (ticket) and «Врач: Петров И. С.» (doctor). `document_date` `2026-03-07` is a service date and is correctly not claimed; `institution`, `material`, `conclusion` are `null` |
| `laboratory-synthetic-analysis-note-01` | `canonical/laboratory/synthetic-analysis-note-01.json` | `age`, `doctor_name`, `lab_order_id`, `person_name` | all `structured_field` except `lab_order_id` (`pattern`) | CONFIRM | `fields.note` contains «для пациента Кузнецова Александра Петровича» (patient), «(М, 39 лет)» (age), «Номер лабораторного заказа: 123456АБ» (lab order), «Врач: Петров И. С.» (doctor). «Дата забора: 05.03.2026» is a **collection** date and is correctly not `date_of_birth` — the taxonomy has one date member and a laboratory sample date is not one |

**Provenance of every entry.** Three entries (`clean`, `patient`, `malicious`)
are invented outright and carry no `derived_from`: they were never shaped from a
real document, so declaring one would be a false provenance claim. Two entries
(`appointment/synthetic-registration-01.md`,
`appointment/synthetic-registration-note-01.json`) declare
`derived_from: "2b8fdd0d (layout only)"` — the real registration marker's
**structure** (label/value contour, table shape, declined genitive of §7 gotcha
G1) with every value invented. One entry
(`laboratory/synthetic-analysis-note-01.json`) declares
`derived_from: "ORDER §13.1 fields.note leak (layout only)"`. No entry's values
are copied from `.dev/flow_upload_test/`; ORDER §13.3 forbids it and Phase 4's
`test_no_real_pii_in_fixtures.py` enforces it value-by-value.

---

## Measurement decisions

The Phase 2 reductions had to choose a **unit** for every rate, and the unit is
the part of a metric that is invisible in its output until it is wrong. Each
choice below is recorded with the count it changes, because a number that moves
when a unit is chosen is a number a reader could otherwise have quoted wrongly.

**D1 — Claims and declarations are counted per fixture, never per boundary row.**
A finding is produced once and decided at both of a document's boundaries, and
`expected_detector_source` is declared once per manifest entry. Counting either
inside the per-row loop reported this corpus's **20 claims as 33** and would have
doubled every violated declaration on a document. The committed corpus hid the
first bug completely, because every claim in it is currently correct and
`2 × 0 = 0`; `false_positive_claims` — the number Finding B has to move — would
have scaled with how many boundaries a contour happened to have. Pinned by
`test_evaluate_metrics.py::test_claims_are_counted_once_per_fixture_not_once_per_boundary_row`
and by the committed-corpus invariant
`Σ per_detector[*].claimed == confidence_stats.findings`.

**D2 — `over_redacted` is counted per category, over the ground truth's category
count.** The plan is explicit ("computed **per category, not per document**")
and the reason holds: a category masked that no detector claimed is the R7-class
defect, and at document granularity `document_date` masked among seven other
categories is one document, and at row granularity it is either one row of two
(which reads as a policy difference) or two rows of two (which reads as 100%).
The denominator is `category_observations` = `Σ |expected_categories|` = **18**
for this corpus, and the numerator is the number of distinct masked
`(fixture, category)` pairs, so a document masked at one boundary and a document
masked at both count one each. The value is structurally **0** today: the policy
engine only issues an action for a category a detector found, so a non-zero
figure means an override reached a category nothing detected. Publishing a
structurally-zero metric is the point — it is the tripwire.

**D3 — `source_expectation_mismatches` is denominated by fixtures that declare a
source**, currently **5** of 6 (`clean-generic-notice-01` declares nothing). A
corpus that declares nothing is not "mismatched 0 times", it is a corpus with
nothing to check, and 0/0 printed as 0.0% would read as "every layer fired where
the manifest asked" from a manifest that never asked. The comparison is an exact
set equality: a declared layer that fires *in addition to* the expected one is
still a miss, because the declaration pins the load-bearing layer rather than
whitelisting the neighbourhood.

**D4 — Per-detector attribution has no `fn`, which diverges from the plan's
"per-detector tp/fp/fn".** Recorded as a divergence rather than implemented,
because there is no correct value for it: a false negative has no claimant, so
any per-detector `fn` would be an attribution chosen after the fact — "the layer
that was supposed to find this" is a guess, and a guess in a per-rule table is
how a layer gets blamed for a gap it was never built to close.

**Ruled in Phase 2 review: the divergence is accepted as delivered.** Restating
the ruling's own argument, because it is the load-bearing one: a miss has no
claimant, and the miss is already published twice over, so a per-detector copy
would be a third statement of a fact with no new information in it.

Two places carry it, and they answer different questions — worth being precise
about, because "it is covered by `missed_category_document`" is true of the
document-level view and not of the count:

| where | figure | question it answers |
|---|---|---|
| `CategoryMetrics.fn` | the count, per category | how many rows named this category in the ground truth and the gate did not find it |
| `DomainRates.missed_category_document` | the rate, per document | in how many fixtures at least one expected category went unfound |
| `DetectorAttribution` | *nothing*, by design | — a miss has no claimant to charge |

So the count survives at category granularity and the rate at document
granularity, and no per-rule number is invented. The layer property that *is*
attributable — a declared layer that stayed silent — remains
`source_expectation_mismatches` (D3), which is a per-fixture fact about a
declaration rather than an inference about who should have found the value. If a
future phase needs per-layer coverage, the honest input is a category's `fn` plus
an `expected_detector_source` declaration for every category the manifest expects
— a manifest change, not a metrics change.

---

## Findings

Numbered so Phase 3 can cite one per calibration change, as the plan's
findings-citation rule requires.

### F1 — The committed corpus cannot produce a false positive, because its labels were measured from the detector

**`PENDING_GROUND_TRUTH_RULING`. Not applied — ruled in Phase 2 review.**

**The ruling.** Phase 2 review: the flip is **not** applied, and the finding is
handed off as a product ruling in **Phase 5**. The reasoning is the reason the
finding is filed under its own disposition rather than as a third
`PENDING_PRODUCT_DECISION`: applying it changes the **ground truth of the
manifest**, which is not an evaluation decision and not a detector decision. The
two existing `PENDING_PRODUCT_DECISION` items (Finding C and the
`AGE`/`EXTERNAL_LLM` trade) are policy questions — a rule is in or out; this one
is a question about what the corpus *is*, and only the owner of that corpus can
answer it. `ticket_number` therefore stays in `expected_categories` for the whole
of M6.

M5 Phase 13 made `expected_categories` a *measured* value:
`test_manifest_verification.py::test_every_declared_category_is_found_and_nothing_else`
asserts **set equality** between the chain's output and the manifest. Under that
doctrine every finding the chain produces is, by construction, in the manifest.

The consequence for M6 is that the committed corpus's false-positive rate is
**0 by construction, not by measurement**. The clearest case is the one the
manifest's own notes already flag: `malicious/synthetic-injection-01.md` has a
credential and a prompt-injection attempt and **no ticket number**, but
`pattern.ticket_number.long_digits` claims any digit run of ≥ 12 and the key's
28-zero numeric body qualifies. The notes record this as "a known false positive"
and then list `ticket_number` in `expected_categories` anyway, so that
`exact_set_match` stays at 10/10.

That reasoning was correct under Phase 13's doctrine — pin the current behaviour
so a detector change fails loudly. It is wrong under M6's, which requires
`expected_*` to be **ground truth**: *which category is present in this document*.
A ticket number is not present, so listing it makes the category metrics score a
known-wrong claim as a **true positive** and puts the lowest confidence band at
100% accuracy when its true accuracy is 50%.

**Proposed correction:** remove `ticket_number` from
`malicious-synthetic-injection-01`'s `expected_categories` and
`expected_detector_source`; add a `known_false_positives` entry to the manifest
notes so the finding stays discoverable from the file itself. The corrected
metrics would be:

| figure | now | corrected | why |
|---|---|---|---|
| `ticket_number` category tp / fp (per boundary row) | 5 / 0 | **3 / 2** | the injection fixture's two rows become spurious |
| `structured.ticket_number.labelled` tp / fp (per claim) | 2 / 0 | 2 / 0 | unaffected — the `appointment` document and its canonical note |
| `pattern.ticket_number.long_digits` tp / fp (per claim) | 1 / 0 | **0 / 1** | the only wrong claim in the corpus |
| `false_positive_claims` | 0 | **1** | one claim, counted once per finding (D1) |
| `exact_set_match` | 10/10 | **8/10** | both rows of the injection fixture over-fire |
| `subset_recall` | 10/10 | 10/10 | nothing was expected there, so nothing is missed |
| band `0.00-0.70` | 3/3 | **2/3** | the 0.60 `pattern` claim becomes incorrect |

**Blast radius — why no phase of M6 may apply it silently.** The flip breaks, by
design, four assertions that encode M5 Phase 13's equality doctrine:
`test_every_declared_category_is_found_and_nothing_else` (equality),
`test_the_manifest_names_the_known_ticket_false_positive` (asserts the category
**is** expected), `test_evaluate.py`'s canary
`test_the_synthetic_corpus_scores_perfectly_on_categories`, and
`test_manifest_verification.py::test_every_fixture_carries_a_government_identifier_at_all`
is unaffected but the equivalence assertion is the load-bearing one. Rewriting
those is a change to what CI gates on, which supersedes an M5 acceptance
criterion — so it belongs with the Phase 5 decision hand-off rather than with
Phase 3's detector calibration or Phase 4's gate rework, neither of which owns
the ground truth.

**What the ruling does *not* change.** The label stays wrong on purpose, so the
corrected column above is a **projection**, not a target: nothing in M6 may report
it as the corpus's current state. And the constraint that motivated the finding
survives the ruling intact — **no number in a PII eval report may be described as
a precision figure for the committed corpus** while the labels are measured rather
than authored. `test_manifest_audit.py` asserts the pair of facts (F1 recorded
**and** `false_positive_claims == 0`) together, so applying the flip without
reading this entry breaks a named test.

### F2 — `expected_risk_level` and `expected_decision` are policy projections, never document ground truth

Both are derived deterministically from the detected categories through §4.4,
§4.11 and §4.13. Each committed value was re-derived from its fixture's own
findings and **every one matched** — the confirmation is recorded as a test
(`test_risk_is_the_highest_of_the_findings_present`,
`test_every_declared_decision_and_risk_level_is_the_one_reached`) rather than as a
sentence here, so a hand-edited value fails immediately.

Consequence for the harness: `PIIMetrics.risk_match` is published over
`risk_declared_boundaries`, **not** over every row, because a corpus that declares
no risk level is not disagreeing about risk. Same reason the decision column is
scored per boundary. No action; recorded so nobody later reads a `risk_match` of
1.0 as evidence that the gate infers risk correctly from a document.

### F3 — The same ФИО is claimed by different layers on the two contours

«Кузнецова Александра Петровича» is claimed by
`structured.person_name.labelled` at **0.95** on the document contour and by
`pattern.person_name.three_token` at **0.80** on the canonical contour. The
canonical guard scans un-folded payload string leaves, so the label rule has no
label to key on and the general three-token pattern takes the value instead.

Not a defect. Recorded because `expected_detector_source` is a **per-fixture**
field and Phase 4 must not assume it is stable across contours: a derived
`canonical/` fixture declaring `structured_field` for `person_name` would fail
against a corpus that is behaving correctly. The two committed canonical entries
already declare `pattern`, and they are right.

### F4 — Every false positive in this corpus is a low-confidence pattern claim

The confidence-reliability table over the committed corpus: `0.90-1.00` 12/12
correct, `0.70-0.90` 5/5, `0.00-0.70` 3/3. The lowest band holds exactly three
claims and all three are `pattern` rules at **0.60** —
`pattern.address.locality`, `pattern.ticket_number.long_digits` and
`pattern.lab_order_id.digits_and_letters` — while every `structured_field` claim
in the corpus sits at 0.90 or above. The 3/3 is an artefact of F1: the
`ticket_number` false positive is one of those three and the manifest counts it
correct. Corrected for F1 the band reads 2/3, and both structured bands stay at
100%.

That is the measurable form of the plan's Finding B, and it points one way: on
this corpus the 0.95-confidence structured layer has produced **zero** wrong
claims, and the pattern layer produced the only one. Phase 3 should treat "the
pattern layer guesses, the structured layer knows" as the prior, and check it
against the real corpus before acting on it.

### F5 — `patient/synthetic-consultation-01.md` puts a name and a birth date on one labelled row

«**Пациент:** Смирнова Ольга Ивановна, 1974-03-12» is a single row carrying two
categories. `date_of_birth` is therefore claimed by
`structured.date_of_birth.after_patient_name` — a **positional** rule at 0.85,
the lowest-confidence structured claim in the corpus — rather than by a
`date_of_birth` label rule, because the row has no «Дата рождения» label.

The manifest declares `date_of_birth: ["structured_field"]`, which is satisfied.
The narrower declaration `["structured_field"]` with no label rule available is
worth recording because it is the mechanism that later goes missing when the
layout changes: a real lab marker puts «Дата рождения (возраст)» in a header cell
with the value two rows below, the positional rule's assumption does not hold
there, and the manifest's source-level declaration cannot tell the difference
between "found by the right layer" and "found by the right layer *by accident*".
Phase 4's derived `laboratory/` fixtures are where that has to be pinned.

### F6 — The committed corpus has no realistic negative (the plan's Finding D, with a number)

`clean/generic-notice-01.md` is a one-line synthetic maintenance notice with zero
findings. It is the only entry where a false positive could plausibly occur, and
nothing in it resembles a medical document.

The real corpus has exactly one genuinely clean document (`311a0a42`, a real
laboratory marker carrying no `снилс` / `полис` / `дата рождения` / `фио` /
`талона` / `телефон` token at all). So neither corpus can currently measure
precision on realistic prose: the committed one has no realistic document, and
the real one is a single document in a local directory.

Fix: Phase 4's derived `clean/laboratory-01.md` — a real-shaped laboratory marker
with every value invented, which is Finding D's committed twin. Until then,
`false_positive_claims` is a detector-behaviour observation, not a rate.

### F7 — `expected_detector_source` cannot say which of two rules claimed a category

`malicious/synthetic-injection-01.md` has `secret` claimed twice:
`secret.vendor_key` at 0.90 and `secret.labelled_credential` at 0.80. The
manifest declares `secret: ["pattern"]`, which both satisfy, and the aggregate
says nothing about the pair.

Not a defect — `expected_detector_source` is documented as **source**-level
(`PIISource`), and the per-rule breakdown lives in
`compute_detector_attribution().per_detector`. Recorded so Phase 4 does not widen
the manifest field into a rule-level expectation the loader cannot enforce.

### F8 — `PIICategory` has no member for clinical findings

`laboratory/synthetic-analysis-note-01.json` carries
«Диагноз: гипертоническая болезнь I стадии» in `fields.note`, and the real
corpus's `fields.results[].interpretation` is the same shape: a diagnosis or an
interpretation is the most sensitive clinical datum in a Russian medical record
after identity, and the taxonomy has no category for it.

The gate therefore sees nothing there — not detected, not masked, not in the
manifest, and invisible in every metric in this report. This is a **taxonomy
gap, not a detector defect**: adding a member is a contract event that requires a
row in `DEFAULT_POLICY` and a row in the mask table, which is a milestone of its
own. Recorded here because an audit that read the fixture and did not say so
would be reporting a clean bill of health on a field it never checked.

**Out of M6's scope.** No category is added, and no detector change is made for
it in Phase 3.

### F9 — Zero label flips

All 6 entries' `expected_*` fields confirmed human-verifiable against the
documents' own content, with the F1 and F8 caveats above. **0 flips applied in
Phase 2.** One label correction proposed and filed (F1); one taxonomy gap recorded
(F8); no other label was touched.

Update cadence: re-run this audit whenever the manifest, a fixture or
`DETECTOR_VERSION` changes. Phase 3 cites F1, F4 and F6 to justify its detector
changes; Phase 4 re-runs it against the enlarged corpus.

### F10 — The report labelled a matching category set `MISMATCH`

**Fixed in Phase 2.** No Phase 3 action.

The per-boundary mark was a single verdict over two different questions — did the
category set agree, and did the decision agree — and it sat on the line holding the
categories. `patient/synthetic-consultation-01` at `document/internal_llm` is the
row that shows it: seven expected categories, the same seven predicted,
`exact_set_match` 10/10 corpus-wide, and the mark reading `[MISMATCH]` because the
gate returned `allow` where the manifest documents `review`. A reader auditing the
category layer was told the set differed when it did not, on the one corpus in the
repository where that layer is clean.

The Markdown table was worse: one `match` column, the actual decision beside it,
and **no** expected-decision column, so a reader could not tell which comparison
had failed or what was expected. Both renderers now answer the two questions in
two places — `[SET MATCH]` on the category line with the decision delta on the
decision line, and `categories` / `actual decision` / `expected decision` /
`decision` as four columns. Pinned by `test_evaluate.py`.

Recorded rather than merely fixed because it is the same failure class as F1 in
reverse: a number that is correct (the set matched) attached to a word that is
wrong (MISMATCH). A measurement layer is only as good as the sentence it puts the
measurement in.

---

## The local real corpus manifest

Not audited here — it does not exist yet. Phase 3 assembles
`.dev/pii-fixtures/` (symlinks into `.dev/flow_upload_test/`) and writes its
manifest. The shape is fixed by `app/pii/fixtures.py` and the audit obligation
for Phase 3 is recorded now:

* same entry vocabulary as the committed manifest — `id`, `file`, `contour`,
  `source`, `expected_categories`, `expected_detector_source`, `expected_decision`;
* `provenance` **required**, recording the shape's origin without reproducing the
  patient's data;
* `expected_risk_level` optional — see F2 for why it is not ground truth;
* **no raw PII values anywhere**: the ground truth is *which category is present*,
  never what it is;
* `expected_decision` is **documented, not asserted**. It is the output Phase 3
  measures; a gate that asserted it would be agreeing with itself.
* whether the real corpus was available for a given run is recorded in the report
  artifact, not inferred from it.

---

## Findings index

| finding | subject | disposition |
|---|---|---|
| **F1** | committed labels were measured from the detector, so the corpus has no false positive by construction | `PENDING_GROUND_TRUTH_RULING` — ruled in Phase 2 review, not applied, handed off to Phase 5 |
| **F2** | `expected_risk_level` / `expected_decision` are policy projections | confirmed, no action |
| **F3** | same ФИО claimed by different layers on the two contours | confirmed, watch item for Phase 4 |
| **F4** | every false positive here is a low-confidence pattern claim | input to Phase 3 Finding B |
| **F5** | `date_of_birth` claimed positionally at 0.85, not by a label rule | input to Phase 3 Finding A |
| **F6** | no realistic negative in the committed corpus | input to Phase 4 derived fixtures |
| **F7** | `expected_detector_source` is source-level, not rule-level | confirmed, no action |
| **F8** | `PIICategory` has no member for a diagnosis / result interpretation | recorded, out of M6 scope |
| **F9** | zero label flips | — |
| **F10** | one verdict labelled a matching category set `MISMATCH` | fixed in Phase 2, no Phase 3 action |

---

## Test obligations this audit creates

A findings list nobody can fail is a report, not a gate. Each claim below is
asserted by `tests/unit/pii/test_manifest_audit.py`, so applying a finding
without reading this document breaks a **named** test rather than quietly
changing a number:

| obligation | asserted by | breaks if |
|---|---|---|
| F1 is recorded as `PENDING_GROUND_TRUTH_RULING`, routed to Phase 5, and not applied | `test_the_audit_records_f1_as_pending_and_keeps_the_flip_unapplied` | the finding text is deleted, or the label changes without the ruling |
| the committed corpus still reports `false_positive_claims == 0` | `test_the_committed_corpus_reports_no_false_positive_claim` | the F1 flip is applied without a ruling (which is the point) |
| the injection fixture's `ticket_number` label is still present | `test_the_injection_fixture_still_declares_the_known_ticket_claim` | the flip is applied silently |
| every `expected_*` label is still human-verifiable from the fixture's text | `test_every_entry_cites_its_provenance` | a derived fixture loses its `derived_from` |
| F2's policy projections still re-derive from the findings | `test_every_declared_decision_and_risk_level_is_the_one_reached` (M5's, re-cited) | a value is hand-edited to disagree with §4.4/§4.11/§4.13 |
| F8 is recorded as a taxonomy gap, with no category added | `test_no_diagnosis_category_was_added_to_escape_f8` | a member is added to `PIICategory` inside M6 |
| every finding in the index is a numbered heading in the body | `test_every_indexed_finding_has_a_section` | a finding is added to the index only |
| F10's two verdicts stay separate in both renderers | `test_a_row_never_labels_a_matching_category_set_as_a_mismatch`, `test_the_markdown_per_fixture_table_separates_the_two_verdicts` | the two comparisons are collapsed back into one mark |
