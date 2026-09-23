# Classification 2.0 — Manifest ground-truth audit

**Scope.** Phase 2 of [EVAL_IMPL_PLAN.md](../../../../docs/development/implementation/AI_FLOW%202.0/CLASSIFICATION%202.0/EVAL_IMPL_PLAN.md):
label-by-label review of `tests/fixtures/classification/manifest.json`
(version `1.0.0`, 11 entries) against the on-disk documents. The audit
confirms each `expected_*` is human-verifiable ground truth and records
findings for the Phase 3 calibration pass ("finding → change" citations).

This document lives beside the evaluation code (`evaluate.py`, `fixtures.py`)
and complements [EVAL_FLOW.md](./EVAL_FLOW.md): EVAL_FLOW describes *how* the
evaluation pipeline runs, this audit records *what* the ground truth is and
*which* findings drove every calibration change.

**Method.** Every fixture markdown was read in full; the label was matched
against its content (headers, assay names, table structure, source text).
Decision expectations were checked against the scoring semantics: `accept` for
documents that are unambiguously a recognized schema, `fallback` for documents
with no scoring support (`top < SCORE_FLOOR`).

**Result.** 11/11 labels confirmed during Phase 2 as human-verifiable ground
truth; **0 labels flipped** in that pass. Phase 3 applied exactly one flip —
Helix `laboratory/datalab-output-helix_3_photo.jpeg.md`: subtype
`null → microbiology` — in lockstep with the `microbiology` subtype rule and
version bump to `2.1.0` (Finding → Change table below).

---

## Per-fixture verdicts

| file | source | expected type/subtype/decision | verdict | evidence |
|---|---|---|---|---|
| `laboratory/fbbcb675.md` | real | laboratory / **hematology** / accept | CONFIRM | «Гематологические исследования»; CBC panel (WBC, RBC, HGB, HCT, MCV, MCH…); «Лаб. номер», врач клинической лабораторной диагностики |
| `laboratory/b8f07559.md` | real | laboratory / **biochemistry** / accept | CONFIRM | «Протокол лабораторного исследования»; GGT, ЩФ, АСТ, АЛТ, креатинин, СКФ (CKD-EPI), билирубин — serum/plasma assays («…в сыворотке или плазме крови», 7×) |
| `laboratory/datalab-output-27022026.pdf.md` | real | laboratory / **hematology** / accept | CONFIRM | «Гематологические исследования»; CBC panel; «Лаб. номер», подпись врача КЛД |
| `laboratory/datalab-output-gemotest_1_photo.jpg.md` | real | laboratory / **hematology** / accept | CONFIRM | «Общий анализ крови с лейкоцитарной формулой и СОЭ»; parameter table (гемоглобин, эритроциты, MCV…); label applies to the captured panel (see F5) |
| `laboratory/datalab-output-helix_3_photo.jpeg.md` | real | laboratory / **microbiology** / accept | **APPLIED (F2)** | «Посев на аэробную и факультативно-анаэробную флору», «Метод: Микробиологический», culture + antibiotic/phage sensitivity. Phase 2 logged subtype `null` as a **projection**; Phase 3 applied the `microbiology` subtype rule (2.1.0) and flipped the manifest to human truth (see Findings → Change below) |
| `laboratory/datalab-output-invitro_3_prscreen.jpg.md` | real | laboratory / **hematology** / accept | CONFIRM | «Клинический анализ крови»; CBC with differential incl. СОЭ; INVITRO result sheet |
| `appointment/2b8fdd0d.md` | real | appointment / null / accept | CONFIRM | «Запись успешно выполнена», «Электронная регистратура Югры»; талон, дата/время приема, врач, кабинет |
| `appointment/appointment_002.md` | synthetic | appointment / null / accept | CONFIRM | «Запись на прием»; nurse/physician, cabinet, date/time, talon — same structure as the real appointment |
| `prescription/prescription_001.md` | synthetic | prescription / null / accept | CONFIRM | «Рецепт», «Rp:», drug list with dosage («1 таблетке 3 раза в день») |
| `other/lab_without_keywords_001.md` | synthetic | other / null / **fallback** | CONFIRM (F3) | «Бланк результатов» + numbered bare values («1) 5,2…») + «Лаборант». Human reading suggests a lab sheet, but the document deliberately carries **no** laboratory keyword signals — the intentional false-generic probe |
| `other/generic_001.md` | synthetic | other / null / **fallback** | CONFIRM | «Справка», «Текстовое письмо без медицинских маркеров» — no schema signals by design |

---

## Findings (cited by Phase 3)

- **F1 — Confidence saturation at 1.00.** `compute_confidence_stats` reports
  6/11 documents at exactly 1.00 (7 display as “1.00” after rounding). The
  clamp01 blend of dominance+strength saturates on unambiguous real markers.
  Phase 3 candidate: a gradation rework (blend/`STRENGTH_REF`), **only if** the
  report shows it hides meaningful differences between clear and merely-strong
  documents — saturation on clear documents is otherwise expected.
- **F2 — Helix subtype is a projection, not ground truth.** The helix document
  is a microbiology culture result (microbiology markers fired 20×). The
  subtype rule in `service.py` only emitted `hematology`/`biochemistry`, hence
  `expected_subtype: null`. Not flipped in Phase 2 — flipping alone would
  (wrongly) break the regression gate. **APPLIED in Phase 3** (see below).
- **F3 — `lab_without_keywords_001` is the designed false-generic probe.**
  Expected `other`/`fallback` records current designed behavior, not human
  truth (the document is lab-shaped). It is synthetic and **exempt** from the
  “unexpected generic” gate (EVAL_IMPL_PLAN §4, converted to counts at N=11);
  its purpose is to make the
  keyword-blind spot visible in `generic_rate` as the dataset grows.
- **F4 — Biochemistry assay-phrase over-fire (watch item).** The assay phrase
  «в сыворотке или плазме крови» appears only in `b8f07559` — a genuine
  biochemistry document — so the biochemistry detector firing is correct on
  the current dataset. No fixture shows a spurious biochemistry/biomarker
  misclassification. **No Phase 3 change** unless future data demonstrates it;
  keep as a watch item.
- **F5 — Gemotest header mentions urinalysis (note only).** The document title
  reads «…общего анализа крови и общего анализа мочи», but the captured OCR
  contains only the blood panel. `hematology` is correct for the current
  content; a `urinalysis` subtype would only matter if a urine table appears in
  the marker. No action.
- **F6 — Zero label flips.** All 11 `expected_*` values confirmed human-
  verifiable against document content (with the F2/F3 caveats above). Decision
  expectations verified under Phase 1 scoring semantics (`accept` = recognized
  schema with `top >= 5.0`; `fallback` = two signal-less documents, `top = 0.0`).
  0 flips recorded.

Update cadence: re-run this audit whenever the manifest or `source` set
changes; Phase 3 consumes F1–F6 to justify every calibration change.

---

## Phase 3 — Findings → Change (2.1.0)

Applied in lockstep per the §0 invariant (`expected_*` flips only with a rule
change + cited rationale). Scoring constants (`0.90`/`0.70`, `SCORE_FLOOR=5.0`,
`AMBIGUITY_MARGIN_RATIO=0.25`, client-hint +5) are unchanged.

| finding | change | impact |
|---|---|---|
| **F2** (Helix subtype is a projection) | `service._laboratory_subtype` gains a `microbiology` branch (strict dominance over hematology/biomarker); helix manifest `expected_subtype` → `microbiology`; `CLASSIFIER_VERSION` → `2.1.0`; locked-constant + pipeline + CLI tests updated | Only helix-style culture documents change subtype; hematology/biochemistry behavior preserved |
| F1 (saturation at 1.00) | none — saturation on unambiguous real markers is expected, not a defect | confidence bands unchanged |
| F4 (biochemistry over-fire) | none — no fixture evidences a spurious firing; watch item | unchanged |
| F5 (gemotest urinalysis note) | none — captured content is blood-only | unchanged |

Resulting eval dataset state: 11/11 correct, accuracy 1.0, helix now materializes
`laboratory / microbiology / accept`, `saturated_at_one = 6`.