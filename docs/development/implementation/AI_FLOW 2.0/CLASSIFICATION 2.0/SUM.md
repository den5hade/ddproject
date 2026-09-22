Да. Я бы проектировал **Classification 2.0 не как “ещё один LLM-запрос”**, а как самостоятельный deterministic classification layer между Marker и extraction. Главная цель — чтобы ошибка вроде `laboratory → generic` не проходила незаметно в extraction.

Ниже — спецификация, которую уже можно использовать как основу для implementation plan агенту.

# Classification 2.0

## 1. Цели

Classification 2.0 должна решать пять задач:

1. Определять `document_type`.
2. По возможности определять `document_subtype`.
3. Возвращать `confidence`.
4. Объяснять решение через `reasons`.
5. Не допускать передачи явно неподходящей schema в extraction.

Пример:

```json
{
  "document_type": "laboratory",
  "document_subtype": "hematology",
  "confidence": 0.96,
  "method": "rule_score",
  "reasons": [
    "laboratory_section_detected",
    "reference_ranges_detected",
    "measurement_units_detected",
    "hematology_markers_detected"
  ]
}
```

Главный принцип:

> Classification определяет **какой schema нужен**, но не извлекает медицинские данные.

---

# 2. Classification не должна зависеть от LLM на первом этапе

Я бы не делал:

```text
Marker
  ↓
LLM: classify
  ↓
LLM: extract
```

Это увеличивает:

* latency;
* стоимость;
* nondeterminism;
* сложность debugging;
* количество мест, где может возникнуть hallucination.

Для текущего набора документов значительно лучше:

```text
Marker
   ↓
Text normalization
   ↓
Signal extraction
   ↓
Rule scoring
   ↓
Classification
```

LLM можно добавить позже как **fallback для ambiguous documents**, но не использовать как основной классификатор.

---

# 3. Архитектура

Я бы выделил Classification в отдельный application/domain component внутри `ai-worker`.

Не отдельный микросервис.

```text
ai-worker
│
├── ingestion/
│
├── classification/
│   ├── domain/
│   │   ├── models.py
│   │   ├── enums.py
│   │   └── result.py
│   │
│   ├── normalization/
│   │   ├── text.py
│   │   └── sections.py
│   │
│   ├── signals/
│   │   ├── base.py
│   │   ├── laboratory.py
│   │   ├── appointment.py
│   │   ├── prescription.py
│   │   └── generic.py
│   │
│   ├── scoring/
│   │   └── classifier.py
│   │
│   └── service.py
│
└── extraction/
```

Важно:

**Classification не должна импортировать extraction schemas.**

Она должна возвращать собственный результат:

```python
ClassificationResult
```

а уже orchestration layer преобразует его в:

```text
document_type → extraction schema
```

---

# 4. Domain model

## DocumentType

На первом этапе:

```python
class DocumentType(str, Enum):
    LABORATORY = "laboratory"
    APPOINTMENT = "appointment"
    PRESCRIPTION = "prescription"
    DISCHARGE = "discharge"
    DIAGNOSIS = "diagnosis"
    IMAGING = "imaging"
    CONSULTATION = "consultation"
    OTHER = "other"
```

Не нужно сразу реализовывать extraction schemas для всех типов.

Classification может знать больше типов, чем extraction.

Например:

```text
classification:
    imaging

extraction:
    GenericCanonical
```

пока `ImagingCanonical` не реализован.

---

# 5. DocumentSubtype

Subtype должен быть optional.

```python
class LaboratorySubtype(str, Enum):
    HEMATOLOGY = "hematology"
    BIOCHEMISTRY = "biochemistry"
    URINALYSIS = "urinalysis"
    HORMONES = "hormones"
    MICROBIOLOGY = "microbiology"
    UNKNOWN = "unknown"
```

Например:

```json
{
  "document_type": "laboratory",
  "document_subtype": "hematology"
}
```

Но:

```json
{
  "document_type": "laboratory",
  "document_subtype": null
}
```

тоже является валидным результатом.

Не нужно заставлять classifier угадывать subtype.

---

# 6. ClassificationResult

Рекомендую такую модель:

```python
class ClassificationResult(BaseModel):
    document_type: DocumentType
    document_subtype: str | None

    confidence: float

    method: Literal[
        "rule_score",
        "llm_fallback",
        "manual"
    ]

    reasons: list[ClassificationReason]

    signals: list[ClassificationSignal]

    classifier_version: str

    warnings: list[str]
```

Например:

```json
{
  "document_type": "laboratory",
  "document_subtype": "hematology",
  "confidence": 0.96,
  "method": "rule_score",

  "reasons": [
    "laboratory_section_detected",
    "reference_ranges_detected",
    "measurement_units_detected",
    "hematology_markers_detected"
  ],

  "signals": [
    {
      "name": "reference_range",
      "weight": 2.0,
      "matched": true
    },
    {
      "name": "hematology_marker",
      "weight": 3.0,
      "matched": true
    }
  ],

  "classifier_version": "2.0.0",

  "warnings": []
}
```

---

# 7. Не хранить только `reasons`

Для debugging я бы хранил два уровня:

### Human-readable

```json
"reasons": [
  "reference_ranges_detected"
]
```

### Machine-readable

```json
"signals": [
  {
    "name": "reference_range",
    "matches": 14,
    "weight": 2.0,
    "score": 28
  }
]
```

Это позволит потом анализировать classifier статистически.

---

# 8. Signal extraction

Это центральная часть Classification 2.0.

Вместо:

```python
if "анализ" in text:
    laboratory
```

создаём набор независимых detectors.

Например:

```python
class SignalDetector(Protocol):
    def detect(self, document: NormalizedDocument) -> list[Signal]:
        ...
```

Каждый detector отвечает только на один вопрос.

---

# 9. Laboratory signals

Например:

```text
laboratory_section
reference_range
measurement_unit
result_value
laboratory_parameter
abnormal_flag
specimen
laboratory_number
biomarker
hematology_marker
```

### Сильные сигналы

```text
WBC
RBC
HGB
HCT
MCV
MCH
MCHC
PLT
NEUT
LYM
MON
EOS
BAS
```

Но важно:

**не полагаться только на конкретные английские аббревиатуры.**

Нужны варианты:

```text
гемоглобин
HGB
Hb
гематокрит
HCT
эритроциты
RBC
лейкоциты
WBC
```

---

# 10. Structural signals для лаборатории

Это важнее keywords.

Например, обнаружена таблица:

```text
Показатель | Результат | Ед. изм. | Референс
```

Это сильный laboratory signal.

Также:

```text
Показатель
Результат
Референсные значения
Единицы измерения
Норма
Отклонение
```

В итоге:

```text
"reference range" × 14
"unit" × 17
"numeric result" × 17
```

намного сильнее, чем одно слово:

```text
"исследование"
```

---

# 11. Appointment signals

Для второго проблемного документа:

```text
appointment
reception
visit
doctor
specialist
specialty
cabinet
room
appointment time
talon
ticket
запись
приём
врач
специалист
кабинет
талон
```

Но опять же structural signals важнее.

Например:

```text
Врач: ...
Специальность: ...
Дата приема: ...
Время: ...
Кабинет: ...
```

Это очень сильный appointment pattern.

---

# 12. Prescription signals

Например:

```text
назначение
препарат
лекарственный препарат
дозировка
dose
frequency
курс
принимать
таблетки
мл
мг
```

И структурные:

```text
Medication
Dose
Frequency
Duration
Route
```

---

# 13. Score model

Я бы не использовал просто:

```python
if matches > 0
```

Нужен score.

Например:

```text
Laboratory:

strong signal       +5
medium signal       +3
weak signal         +1

contradicting       -4
```

Пример:

```text
laboratory_section       +5
reference_range × 10    +10
measurement_unit × 8    +8
hematology_marker × 5  +15
appointment_marker      -4

TOTAL = 34
```

---

# 14. Normalization

Перед scoring:

```text
Marker.md
   ↓
remove formatting noise
   ↓
Unicode normalization
   ↓
lowercase
   ↓
normalize whitespace
   ↓
normalize punctuation
   ↓
language-independent tokenization
```

Например:

```text
"РЕФЕРЕНСНЫЕ ЗНАЧЕНИЯ"
"Референсные значения"
"референсные   значения"
```

должны приводиться к одному виду.

---

# 15. Не удалять структуру Markdown

Это важный момент.

Нельзя делать просто:

```python
plain_text = markdown_to_text(marker)
```

и терять:

```text
headings
tables
lists
```

Нужно иметь:

```python
NormalizedDocument(
    raw_text=...,
    headings=[...],
    tables=[...],
    paragraphs=[...],
    metadata={...}
)
```

Тогда classifier может понимать:

```text
table_count = 3
```

и анализировать table headers.

---

# 16. Classification pipeline

Полный алгоритм:

```text
marker.md
   │
   ▼
NormalizedDocument
   │
   ▼
Signal detectors
   │
   ├── laboratory signals
   ├── appointment signals
   ├── prescription signals
   ├── discharge signals
   └── ...
   │
   ▼
Score aggregation
   │
   ▼
Candidate ranking
   │
   ▼
Confidence calculation
   │
   ▼
ClassificationResult
```

---

# 17. Confidence

Я бы не делал:

```python
confidence = score / 100
```

Это не настоящий confidence.

Лучше учитывать:

1. абсолютный score;
2. разницу между первым и вторым candidate;
3. количество сильных signals;
4. наличие contradicting signals.

Например:

```text
laboratory = 34
appointment = 4
```

→ high confidence.

А:

```text
laboratory = 12
appointment = 10
```

→ low confidence.

---

# 18. Три confidence levels

Вместо зависимости от конкретного float:

```text
HIGH
MEDIUM
LOW
```

Например:

```python
class ClassificationConfidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
```

И:

```json
{
  "confidence": 0.94,
  "confidence_level": "high"
}
```

---

# 19. Classification policy

Я бы ввёл policy:

```text
HIGH
→ automatically select schema

MEDIUM
→ select schema + warning

LOW
→ generic / review
```

Например:

```text
0.90–1.00 → HIGH
0.70–0.89 → MEDIUM
< 0.70     → LOW
```

Но эти thresholds **не стоит считать окончательными**.

Их нужно откалибровать на реальном dataset.

---

# 20. Очень важная защита от неправильного classification

Нужно проверять не только:

```text
top_score
```

но:

```text
top_score - second_score
```

Например:

```text
laboratory = 18
appointment = 17
```

Даже если 18 кажется достаточно высоким, classifier должен сказать:

```text
AMBIGUOUS
```

а не:

```text
laboratory
```

---

# 21. Поэтому ClassificationDecision

Я бы ввёл:

```python
class ClassificationDecision(str, Enum):
    ACCEPT = "accept"
    AMBIGUOUS = "ambiguous"
    FALLBACK = "fallback"
```

Результат:

```json
{
  "document_type": "laboratory",
  "confidence": 0.81,
  "decision": "accept"
}
```

или:

```json
{
  "document_type": "laboratory",
  "confidence": 0.63,
  "decision": "ambiguous"
}
```

---

# 22. Schema resolver

После classification должен быть отдельный компонент:

```text
ClassificationResult
       │
       ▼
SchemaResolver
       │
       ▼
ExtractionSchema
```

Например:

```python
resolve_schema(
    document_type="laboratory",
    subtype="hematology"
)
```

→

```text
LaboratoryCanonical v1
```

Это лучше, чем:

```python
if type == "laboratory":
    ...
```

разбросанный по pipeline.

---

# 23. Schema registry

Я бы сразу сделал registry:

```python
SCHEMA_REGISTRY = {
    ("laboratory", "hematology"): "laboratory.v1",
    ("laboratory", None): "laboratory.v1",
    ("appointment", None): "appointment.v1",
    ("prescription", None): "prescription.v1",
    ("other", None): "generic.v1",
}
```

В будущем это позволит Organization создавать свои schemas.

---

# 24. Что записывать в БД

Я бы не создавал отдельную таблицу `classifications` на первом этапе.

У вас уже есть processing/extraction entities.

Можно добавить в processing result:

```text
document_processing_jobs
```

или отдельный JSON metadata:

```json
{
  "classification": {
    "type": "laboratory",
    "subtype": "hematology",
    "confidence": 0.96,
    "confidence_level": "high",
    "decision": "accept",
    "method": "rule_score",
    "classifier_version": "2.0.0"
  }
}
```

Если потом потребуется аналитика классификатора, тогда вынести в отдельную таблицу.

---

# 25. S3 artifacts

Я бы сохранял classification result вместе с processing artifacts:

```text
documents/
    {document_id}/
        original/
            source.pdf

        marker/
            document.md

        classification/
            result.json

        canonical/
            canonical.json

        structured/
            document.md
```

`classification/result.json` должен быть immutable для конкретного processing attempt.

---

# 26. Versioning

Classification должен иметь собственную версию:

```text
classifier_version = "2.0.0"
```

Например:

```text
2.0.0
```

изменили scoring.

```text
2.1.0
```

добавили appointment signals.

```text
3.0.0
```

изменили algorithm.

Это позволит понять:

> почему старые документы классифицировались иначе?

---

# 27. Regression dataset

Это, пожалуй, самая важная часть реализации.

Нужно создать:

```text
tests/fixtures/classification/
```

Например:

```text
classification/
├── laboratory/
│   ├── cbc_001.md
│   ├── cbc_002.md
│   ├── chemistry_001.md
│   └── lab_without_keywords_001.md
│
├── appointment/
│   ├── appointment_001.md
│   └── appointment_002.md
│
├── prescription/
│   └── prescription_001.md
│
└── other/
    └── generic_001.md
```

Для каждого:

```json
{
  "expected_type": "laboratory",
  "expected_subtype": "hematology"
}
```

---

# 28. Обязательно добавить ваши два реальных regression cases

Первый:

```text
гематологический анализ
```

должен гарантированно давать:

```text
laboratory
```

Второй:

```text
запись на приём
```

должен давать:

```text
appointment
```

И эти два теста должны стать permanent regression tests.

---

# 29. Evaluation metrics

После появления dataset нужно считать:

```text
accuracy
precision
recall
F1
```

но самое важное для вас:

### False generic

```text
real laboratory
→ generic
```

### Wrong schema

```text
real laboratory
→ appointment
```

### False positive

```text
real other
→ laboratory
```

Я бы отдельно отслеживал:

```text
generic_rate
wrong_schema_rate
ambiguous_rate
```

---

# 30. Цели первой версии

Не ставил бы сразу слишком амбициозные цели.

Для Classification 2.0:

```text
Laboratory recall       > 95%
Appointment recall      > 95%
Wrong schema             < 2%
False laboratory         < 2%
Unexpected generic       < 5%
```

Но эти значения должны быть **целями для regression dataset**, а не обещанием production accuracy.

---

# 31. Unit tests

Минимальный набор:

```text
test_normalize_text
test_normalize_tables

test_detect_laboratory_signals
test_detect_appointment_signals

test_laboratory_score
test_appointment_score

test_confidence_high
test_confidence_low

test_ambiguous_classification

test_schema_resolution

test_classifier_version

test_laboratory_regression
test_appointment_regression
```

---

# 32. Integration test

Нужен тест уже на уровне AI worker:

```text
marker.md
 ↓
classification
 ↓
schema resolver
 ↓
extraction
```

Например:

```text
CBC marker.md
        ↓
laboratory
        ↓
laboratory.v1
        ↓
LaboratoryCanonical
```

А не:

```text
CBC
 ↓
generic
```

---

# 33. План имплементации

## Phase 1 — Domain contract

Создать:

```text
classification/domain/enums.py
classification/domain/models.py
```

Реализовать:

* `DocumentType`
* `DocumentSubtype`
* `ClassificationResult`
* `ClassificationConfidence`
* `ClassificationDecision`
* `ClassificationSignal`

**Без изменения pipeline.**

---

## Phase 2 — Normalization

Создать:

```text
classification/normalization/
```

Реализовать:

* Unicode normalization;
* whitespace normalization;
* case normalization;
* Markdown structure parsing;
* table extraction;
* heading extraction.

Output:

```python
NormalizedDocument
```

---

## Phase 3 — Signal detectors

Создать:

```text
signals/laboratory.py
signals/appointment.py
signals/prescription.py
```

Каждый detector:

```python
detect(document) -> list[Signal]
```

---

## Phase 4 — Scoring engine

Создать:

```text
scoring/classifier.py
```

Он:

1. собирает signals;
2. рассчитывает score;
3. определяет top candidate;
4. считает margin;
5. определяет confidence;
6. формирует reasons;
7. формирует decision.

---

## Phase 5 — SchemaResolver

Создать:

```text
schema_registry.py
schema_resolver.py
```

Flow:

```text
ClassificationResult
        ↓
SchemaResolver
        ↓
ExtractionSchema
```

---

## Phase 6 — Integration

Изменить существующий AI pipeline:

```text
Marker
 ↓
Classification 2.0
 ↓
SchemaResolver
 ↓
LLM extraction
```

Убрать старую:

```text
keyword classification
```

---

## Phase 7 — Persistence

Добавить:

```text
classification metadata
```

к processing result.

Сохранять:

```text
type
subtype
confidence
decision
method
reasons
classifier_version
```

---

## Phase 8 — Regression dataset

Добавить реальные Marker outputs:

```text
CBC
appointment
prescription
other
```

и ожидаемые результаты.

---

## Phase 9 — Evaluation CLI

Очень рекомендую сделать команду:

```bash
python -m app.classification.evaluate
```

которая выдаёт:

```text
Documents: 120

Accuracy:          96.7%
Laboratory recall: 98.2%
Appointment recall: 95.1%

Wrong schema:       1.7%
Generic fallback:   3.3%
Ambiguous:          4.2%
```

Это станет основным инструментом развития classifier.

---

# 34. Что я бы НЕ включал в Classification 2.0

Пока не надо:

* LLM classification;
* embeddings;
* vector search;
* RAG;
* отдельный classification microservice;
* ML training;
* fine-tuning;
* organization-specific classifiers.

Для вашего текущего объёма документов это преждевременно.

---

# 35. Следующая версия

Когда накопится несколько тысяч реальных документов, можно сделать:

```text
                 Rule Classifier
                       │
                  confidence
                       │
             ┌─────────┴─────────┐
             │                   │
           HIGH              LOW/MEDIUM
             │                   │
             ▼                   ▼
          accept            LLM classifier
                                 │
                           final decision
```

То есть LLM используется только там, где deterministic classifier не уверен.

Это даст хороший баланс:

```text
обычные документы
→ быстро + дёшево

необычные документы
→ более дорогой intelligent fallback
```

---

# 36. Итоговая архитектура Classification 2.0

```text
                    Marker.md
                       │
                       ▼
              ┌─────────────────┐
              │ Text Normalizer │
              └────────┬────────┘
                       │
                       ▼
             NormalizedDocument
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
     Laboratory   Appointment   Prescription
      Detector      Detector      Detector
          │            │            │
          └────────────┼────────────┘
                       ▼
                Signal Collection
                       │
                       ▼
                Scoring Engine
                       │
             ┌─────────┴─────────┐
             ▼                   ▼
        Classification      Candidate Scores
             │
             ▼
       Confidence/Decision
             │
      ┌──────┼──────────┐
      ▼      ▼          ▼
     HIGH   MEDIUM      LOW
      │      │           │
      │      │           ▼
      │      │        Generic/
      │      │        Review
      │      │
      └──────┴───────────┐
                         ▼
                  Schema Resolver
                         │
                         ▼
                 Extraction Schema
                         │
                         ▼
                    LLM Extractor
```

### Самое принципиальное изменение

Я бы зафиксировал в документации проекта такую границу:

> **Classification answers “what kind of document is this?”; Extraction answers “what structured medical information is contained in this document?”**

Это разделение позволит дальше независимо развивать classifier, canonical schemas и LLM extraction.

И ещё один принцип:

> **Classification 2.0 должен быть полностью воспроизводимым.** Один и тот же `marker.md` + одна версия classifier должны всегда давать одинаковый classification result.

Именно поэтому для текущего этапа я бы выбрал **rules + structural signals + scoring + confidence**, а не LLM. LLM fallback можно добавить после того, как появится реальный evaluation dataset.
