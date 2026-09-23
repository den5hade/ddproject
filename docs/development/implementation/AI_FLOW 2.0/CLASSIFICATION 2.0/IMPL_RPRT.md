# Classification 2.0 — Implementation report

- **Date:** 2026-09-23
- **Classifier version:** `2.1.0`
- **Status:** delivered (M1 contract → M2 implementation → M3 evaluation & calibration), all gate criteria met
- **Scope:** `apps/ai-worker/app/classification/` + pipeline wiring + regression dataset + eval tooling
- **Plan docs:** [CONTRACT_IMPL_PLAN.md](./CONTRACT_IMPL_PLAN.md) (M1, all `[x]`) · [IMPL_PLAN.md](./IMPL_PLAN.md) (M2, all `[x]`, + M3 addendum §8) · [EVAL_IMPL_PLAN.md](./EVAL_IMPL_PLAN.md) (M3, all `[x]`)
- **Code-adjacent docs:** [EVAL_FLOW.md](../../../../apps/ai-worker/app/classification/EVAL_FLOW.md) (оценочный конвейер, рус.) · [MANIFEST_AUDIT.md](../../../../apps/ai-worker/app/classification/MANIFEST_AUDIT.md) (ground-truth audit)
- **Eval report artifact:** `apps/ai-worker/reports/classification-eval-20260923.md` (regenerable: `make eval-classification` + `--report`)

---

## 1. Executive summary

Classification 2.0 is a deterministic, rule-based document classifier that replaces the legacy keyword router in the ai-worker pipeline. It answers **“what kind of document is this?”** (classification) while extraction answers **“what structured medical information does it contain?”** — the layers never import each other.

**Headline result on the regression dataset (11 fixtures, 7 real):**

| metric | value |
|---|---|
| Accuracy | 100% (11/11) |
| Laboratory recall | 100% (6/6) |
| Appointment recall | 100% (2/2) |
| Prescription recall | 100% (1/1) |
| Other recall | 100% (2/2) |
| Wrong schema (real markers) | 0 |
| False laboratory | 0 |
| Ambiguous | 0 (report-only at N=11) |
| Confidence saturated at 1.00 | 6/11 (expected on unambiguous panels) |
| Determinism | byte-identical across runs (same `marker.md` + same version → same result) |

**Verification:** ai-worker unit suite **174 passed** (classification 139 incl. eval/gates + pipeline 9 + the rest), ruff clean, `make eval-classification` green.

---

## 2. Architecture & flow

```text
marker.md
   → MarkdownNormalizer → NormalizedDocument
   → signal detectors (laboratory / appointment / prescription + generic)
   → RuleScoringEngine → ClassificationResult  (method "rule_score")
   → RegistrySchemaResolver → prompt_key
   → LLM extraction (canonical.yaml) → build_canonical   (Pydantic schema-gate)
   → classification_result.json → S3         (artifact-first)
   → DocumentAnalysisCompleted (+ classification block) → RabbitMQ
```

Boundary invariants (locked):

- **Deterministic + reproducible:** same `marker.md` + same `classifier_version` → same `ClassificationResult`.
- **No classification→extraction import:** orchestration resolves the schema via `SchemaResolver`.
- **Service stays infra-free:** `ClassificationService` imports no S3/RabbitMQ; persistence/events live in `pipeline/`.
- **Artifact-first ordering:** `classification_result.json` is uploaded before `analysis-completed` is published; a failed upload is a processing failure.
- **Client hint is a boost, not an override.**

## 3. Code layout

```text
apps/ai-worker/app/classification/
├── __init__.py        # public API surface
├── models.py          # domain contract (enums, ClassificationResult, ClassificationSignal)
├── normalize.py       # MarkdownNormalizer → NormalizedDocument (structure-preserving)
├── signals/
│   ├── base.py        # SignalDetector protocol, count_literal/count_regex, table helpers
│   ├── laboratory.py  # 11 laboratory signals (incl. microbiology_marker)
│   ├── appointment.py # 5 appointment signals (+ contradictory evidence)
│   └── prescription.py# 3 prescription signals
├── scoring.py         # RuleScoringEngine, confidence/decision rules, CLASSIFIER_VERSION
├── service.py         # RuleBasedClassificationService, subtype rule, client hint, warnings
├── resolver.py        # SCHEMA_REGISTRY, RegistrySchemaResolver, prompt-key mapping
├── exceptions.py      # ClassificationError, InvalidClassificationInputError, SchemaResolutionError
├── artifact.py        # build_classification_artifact (versioned JSON)
├── classifier.py      # legacy keyword classifier (kept, tested, not piped)
├── fixtures.py        # app-owned manifest loader (M3, shared by CLI + tests)
├── evaluate.py        # eval CLI (--json/--report) + metrics helpers (M3)
├── MANIFEST_AUDIT.md  # ground-truth audit (findings F1–F6, 2.1.0 changes)
└── EVAL_FLOW.md       # EVAL_FLOW runbook (оценочный конвейер, рус.)
```

## 4. Domain model (`models.py`)

- **`DocumentType`** — `laboratory` · `appointment` · `prescription` · `discharge` · `diagnosis` · `imaging` · `consultation` · `other`. Classification knows more types than extraction has schemas; unimplemented types resolve to generic.
- **`LaboratorySubtype`** — `hematology` · `biochemistry` · `urinalysis` · `hormones` · `microbiology` · `unknown` (subtype is optional; `null` is a valid result).
- **`ClassificationConfidenceLevel`** — `high` · `medium` · `low`.
- **`ClassificationDecision`** — `accept` · `ambiguous` · `fallback`.
- **`ClassificationMethod`** — `rule_score` · `llm_fallback` · `manual` (typed on the result).
- **`ClassificationResult`** — locked wire shape: `{document_type, document_subtype, confidence, confidence_level, decision, method, reasons, signals, classifier_version, warnings}`.
- **`ClassificationSignal`** — `{name, weight, matched, matches, score}` — machine-readable evidence; `reasons[]` is the human-readable summary.

## 5. Normalization (`normalize.py`)

`MarkdownNormalizer` produces a **structure-preserving** `NormalizedDocument` (headings, tables, paragraphs, metadata — not flattened text), with Unicode/case/whitespace/punctuation normalization. Detectors read canonical text but keep structural access (table headers/rows), so structural signals (e.g. a `Показатель | Результат | Ед. изм.` table) are stronger than keywords.

## 6. Signal detectors (`signals/*.py`)

Weight classes (locked): strong **+5** · medium **+3** · weak **+1** · contradicting **−4**. Per-signal `score = weight × matches` (or `weight` when matched without counts).

### laboratory

| signal | weight | what fires it |
|---|---|---|
| `laboratory_section` | +5 | «гематологические исследования», «общий анализ крови», «протокол лабораторного исследования» … |
| `reference_range` | +5 | «референсные значения», «референтный диапазон» … |
| `result_value` | +5 | ≥3 numeric cells (`\d+[.,]\d+`) in tables |
| `hematology_marker` | +5 | WBC/RBC/HGB/HCT/MCV/(м)лейкоцит/эритроцит/тромбоцит/гемоглобин/гематокрит … |
| `microbiology_marker` | +5 | M3: посев/флора/микробиолог/микроорганизм/антибиотик/бактериофаг/биоматериал … |
| `measurement_unit` | +3 | 10^9/л, ммоль/л, г/л, ед/л … (table cells) |
| `laboratory_parameter` | +3 | table headers pairing «параметр/показатель» with «результат/значение» |
| `specimen` | +3 | «венозная кровь», «сыворотк», «плазма крови», «биоматериал» … |
| `biomarker` | +3 | АСТ/АЛТ/ГГТ/креатинин/билирубин/глюкоза/холестерин/амилаза/Т4/СРБ … (chemistry analytes) |
| `abnormal_flag` | +1 | «выше/ниже нормы», «повышено/понижено», ↑/↓ |
| `laboratory_number` | +1 | «лаб. номер», «номер заказа/исследования/пробы» … |
| `appointment_evidence` | −4 | «электронная регистратура», «номер талона», «кабинет:» … (contradicting) |

### appointment

| signal | weight | what fires it |
|---|---|---|
| `appointment_section` | +5 | «запись успешно выполнена», «электронная регистратура», «номер талона», «талон» … |
| `key_value_patterns` | +5 | structural `key:value` rows (номер талона, ФИО, кабинет, филиал …) |
| `doctor_specialty` | +3 | «специальность врача», «ФИО врача», «врач-терапевт/педиатр/хирург/…» |
| `cabinet` | +3 | «кабинет:», «кабинет приема» |
| `appointment_time` | +3 | «дата и время», «время приема», `\b\d{1,2}:\d{2}\b` |
| `laboratory_evidence` | −4 | «референсные значения», «общий анализ крови», «гематологическ» … (contradicting) |

### prescription

| signal | weight | what fires it |
|---|---|---|
| `drug_terms` | +5 | «рецепт», «назнач», «препарат», «лекарственн», «таблетк», «капсул», «мазь», «ампул» … |
| `dosage_frequency` | +3 | «дозировк», «принимат», «раз в день», «в сутки», «перед/после еды» … |
| `struct_medication_headers` | +3 | table headers containing препарат/назначение/лекарственн |

## 7. Scoring engine (`scoring.py`)

```text
score_type = Σ scores of signals with prefix "<document_type>."
top = max score; second = 2nd; margin = top − second (second=0 if solo)
dominance = margin / max(top, 1.0)
strength  = min(1.0, top / STRENGTH_REF)               # STRENGTH_REF = 20.0
confidence = clamp01(0.6*dominance + 0.4*strength)      # 0.0–1.0
level = HIGH if ≥ 0.90 else MEDIUM if ≥ 0.70 else LOW
decision: FALLBACK if top < SCORE_FLOOR (5.0)     → document_type = other
          AMBIGUOUS if margin < 0.25 × top        → decision preserved, generic extraction
          else ACCEPT
```

Reference points (locked in tests): top 34 vs 4 → ≈0.93 HIGH · 12 vs 10 → ≈0.34 LOW · solo 5 → ≈0.70 MEDIUM.

**Client hint.** Recognized `client_type` (`lab_result`/`prescription`) adds one strong signal `client_hint.*` (+5) — a boost, never an override.

## 8. Laboratory subtype rule (`service.py`, 2.1.0)

```text
laboratory subtype:
  microbiology if microbiology_marker strictly dominates hematology + biomarker
  else hematology  if hematology_marker ≥ biomarker (and > 0)   [M2: wins ties]
  else biochemistry if biomarker > 0
  else None
```

M3 (finding F2) added the `microbiology` branch — the Helix culture result previously stored `subtype=null` (a projection of the M2 rule, not truth). M2 branches are preserved backwards-compatibly.

**Warnings:** `low confidence` (LOW level) and `ambiguous classification` (AMBIGUOUS decision) surface in the result.

## 9. Schema resolution & versioning (`resolver.py`)

`SCHEMA_REGISTRY` maps `(document_type, subtype) → schema_key`; unknown subtypes fall through to `(type, None)`, then `("other", None) → generic.v1`. `SCHEMA_PROMPT_KEY` maps schema → extraction prompt. `appointment.v1`, `discharge`, `diagnosis`, `imaging`, `consultation` resolve to the generic prompt until their canonical schemas exist — classification type/subtype stay authoritative in metadata.

**Versioning policy (M1 §7, applied):** `2.0.0` = contract implementation (M2, no semantic change); `2.1.0` = M3 output-altering calibration (microbiology subtype); patch = docs/comments only.

## 10. Persistence & pipeline wiring

- Storage kind `classification` → `classification_result.json` (immutable per `document_version_id`; written only after canonical payload passes schema validation).
- `DocumentAnalysisCompleted` event + frontmatter carry the same `classification{type,subtype,confidence,confidence_level,decision,method,classifier_version,reasons,warnings}` block.
- `build_classification_artifact` serializes verdict + provenance (`prompt_key`, `schema_name`, `prompt_version`, `model`) + processing metadata.

## 11. Regression dataset (`tests/fixtures/classification/`)

`manifest.json` (version `1.0.0`) declares ground truth for **11 fixtures** — 7 real (copies from `.dev/flow_upload_test/` + datalab-produced markers) + 4 synthetic:

| type | fixtures | source |
|---|---|---|
| laboratory/hematology | `fbbcb675`, `27022026`, `gemotest_1`, `invitro_3` | real |
| laboratory/biochemistry | `b8f07559` | real |
| laboratory/microbiology | `helix_3` (flipped from `null` in M3, cited F2) | real |
| appointment | `2b8fdd0d` (+ synthetic `appointment_002`) | real + synthetic |
| prescription | `prescription_001` | synthetic |
| other/fallback | `lab_without_keywords_001` (designed false-generic probe), `generic_001` | synthetic |

The loader lives in the app (`fixtures.py`, stdlib-only, cwd-independent, `CLASSIFICATION_FIXTURES_DIR` overridable); `tests/support/classification_fixtures.py` delegates to it — CLI and tests read the same manifest.

## 12. M3 evaluation & calibration

**Tooling:** `evaluate.py` CLI (`python -m app.classification.evaluate` / `make eval-classification`, `--json`/`--report`) with Pydantic metrics: per-type TP/FP/FN → precision/recall/F1 (+ macro/micro), accuracy, domain rates (wrong_schema/generic/ambiguous/false_laboratory with counts), confidence distribution + saturation-at-1.00 + reliability-by-band.

**Findings → changes (only report-evidenced changes applied):**

| finding | change | impact |
|---|---|---|
| **F2** Helix subtype is a projection, not truth | `microbiology` subtype rule + manifest flip + version `2.1.0` | helix now `laboratory/microbiology/accept` (conf 0.92) |
| F1 saturation at 1.00 | none — expected on unambiguous panels | — |
| F4 biochemistry over-fire | none — not evidenced in the dataset; watch item | — |
| F5 gemotest urinalysis mention | none — captured content is blood-only | — |

**Regression gates (count-based at N=11):** `wrong_schema == 0` on real markers · `false_laboratory == 0` · recall ≥ 0.95 (actual 1.0) · CLI metrics equal ground-truth counts · `ambiguous` report-only.

**DoD (ORDER.md) — all verified:** versioned classification schema intact; classifier `2.1.0` + revision notes; confidence; deterministic validation (byte-identical runs); fallback at `SCORE_FLOOR=5.0`; regression dataset 11/11; real-document tests; audit/provenance unchanged.

## 13. Known limitations

- **Small dataset:** N=11 → gates are count-based; 1 document ≈ 9%. Percentage targets (design-spec §30) resume when the real-marker set grows past ~50 — **re-calibrate then**, and re-run the manifest audit before any further version bump.
- **Confidence saturation:** `clamp01(0.6·dominance + 0.4·strength)` saturates at 1.00 on unambiguous panels (6/11). Acceptable for clear documents; revisit only if future data shows it hides meaningful gradation.
- **Keyword vocabulary is M2-baseline** (informed by real markers); not over-fit further. Some state is only representable structurally (e.g., urinalysis needs a urine table).
- **Legacy `classify_document_type`** is kept intact and tested (deliberate, user decision) but has no pipeline callers.
- **Repo-root pipeline tests** require running from `apps/ai-worker` (prompt-path resolution); pre-existing, unrelated to this work. Local `uv run --all-packages` is blocked by a torch x86_64-macOS wheel absence (CI runs linux and is unaffected).

## 14. Future work

- Dataset expansion past ~50 real markers → percentage gates, re-calibration, `classifier_version` 2.2.x.
- Subtype expansion (`urinalysis`, `hormones`) driven by evidence, not enumeration.
- LLM as **fallback only** for LOW/MEDIUM or AMBIGUOUS documents (SUM spec §35): deterministic classifier stays primary.
- Organization-specific schemas via the registry, once volume justifies it.

## 15. Appendix — document tree

- `CONTRACT_IMPL_PLAN.md` — M1 contract (contracts, schemas, versioning policy)
- `IMPL_PLAN.md` — M2 implementation runbook (+ M3 addendum §8)
- `EVAL_IMPL_PLAN.md` — M3 evaluation runbook
- `apps/ai-worker/app/classification/EVAL_FLOW.md` — EVAL-конвейер в деталях (рус.)
- `apps/ai-worker/app/classification/MANIFEST_AUDIT.md` — ground-truth audit (findings F1–F6)
- `IMPL_RPRT.md` — implementation report (canonical copy of this document)
- `apps/ai-worker/reports/classification-eval-20260923.md` — eval report artifact (findings → changes → gates → DoD + scaling caveat)