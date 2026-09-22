Да. По двум последним прогонам — **гематологический PDF и JPEG с записью на приём** — я бы уже не рассматривал проблему как отдельные ошибки классификатора. Они показывают, что текущий `data upload flow` нужно немного переосмыслить: **не как линейную цепочку “upload → OCR → classify → extract → complete”, а как управляемый pipeline с quality gates, provenance и повторной обработкой**.

При этом базовый pipeline уже достаточно хорошо организован: `account-api → objectstorage-worker → ai-worker → account-api`, canonical JSON является source of truth, а `structured.md` строится детерминированно Python-кодом. 

## 1. Что показывают два прогона

### Прогон лаборатории

OCR фактически извлёк нужную информацию, но классификатор отправил документ в `generic`, потому что использовались слишком точные keywords. В результате **17 лабораторных показателей превратились в один `note`**. 

То есть:

```text
PDF
 ↓
OCR       ✅
 ↓
classification ❌
 ↓
wrong schema
 ↓
LLM extraction technically succeeds
 ↓
bad canonical
```

Это очень важный момент:

> **ошибка произошла не на extraction, а до extraction.**

### Прогон JPEG

Здесь OCR был практически идеальным, но `generic` снова оказался слишком слабой схемой: данные о враче, учреждении, времени приёма и кабинете были сведены в один `note`; кроме того, модель выбрала дату формирования документа вместо даты приёма. 

То есть второй документ показывает уже другую проблему:

```text
OCR             ✅
classification  ✅
schema          ❌
extraction      ⚠️
semantic dates  ⚠️
PII policy      ❌
```

---

# 2. Главный вывод

Я бы сейчас изменил flow примерно так:

```text
UPLOAD
  │
  ▼
STORAGE
  │
  ▼
SOURCE VALIDATION
  │
  ▼
OCR / MARKER
  │
  ▼
OCR QUALITY CHECK
  │
  ▼
DOCUMENT CLASSIFICATION
  │
  ├── confidence/high signal
  │       ↓
  │   selected schema
  │
  └── uncertain
          ↓
       generic / review
  │
  ▼
LLM EXTRACTION
  │
  ▼
PYDANTIC VALIDATION
  │
  ├── invalid ──→ retry / failed
  │
  └── valid
        │
        ▼
   PII / SAFETY CHECK
        │
        ▼
   SEMANTIC VALIDATION
        │
        ▼
   canonical.json
        │
        ├── DB
        ├── S3
        └── structured.md
```

Сейчас часть этих шагов существует, но **не все являются quality gates**.

---

# 3. Самое важное улучшение — разделить `document_type` и `schema`

Сейчас у вас есть:

```text
domain document_type
        ↓
canonical schema
```

и mapping:

```text
lab_result → laboratory
prescription → prescription
else → default
```

Это уже реализовано. 

Но я бы теперь сделал:

```text
Document
 ├── document_type
 ├── document_subtype
 ├── classification_confidence
 └── classification_method
```

Например:

```json
{
  "document_type": "laboratory",
  "document_subtype": "cbc",
  "classification_confidence": 0.97,
  "classification_method": "rule_score"
}
```

Для записи:

```json
{
  "document_type": "appointment",
  "document_subtype": "appointment_confirmation",
  "classification_confidence": 0.94,
  "classification_method": "rule_score"
}
```

Это позволит не превращать `generic` в мусорный bucket.

---

# 4. `generic` должен стать fallback, а не schema для всего

Это, пожалуй, самое важное изменение после двух прогонов.

Сейчас:

```text
laboratory
prescription
generic
```

Но реальных категорий будет больше:

```text
laboratory
prescription
appointment
discharge
diagnosis
consultation
imaging
pathology
vaccination
medical_certificate
other
```

Я бы постепенно двигался к:

```text
BaseCanonical
    │
    ├── LaboratoryCanonical
    ├── PrescriptionCanonical
    ├── AppointmentCanonical
    ├── ConsultationCanonical
    ├── DischargeCanonical
    ├── ImagingCanonical
    └── GenericCanonical
```

А `GenericCanonical`:

```json
{
  "type": "other",
  "title": "...",
  "summary": "...",
  "institution": {...},
  "document_date": "...",
  "fields": {...}
}
```

не должен использоваться для лабораторных данных только потому, что keyword не совпал.

---

# 5. Улучшить classification без второго LLM

Я бы пока **не добавлял отдельный LLM classification call**.

Ваши два прогона очень хорошо показывают, что проблема решается дешевле.

Сейчас:

```python
if keyword in text:
    laboratory
else:
    generic
```

Нужно перейти на:

```text
                    marker.md
                       │
             ┌─────────┴─────────┐
             │                   │
         lexical              structural
         signals                signals
             │                   │
             └─────────┬─────────┘
                       ▼
                     score
                       │
             ┌─────────┴─────────┐
             ▼                   ▼
          high score          low score
             │                   │
        laboratory            generic
```

Например лаборатория:

```text
+3  лабораторный / исследование
+3  таблица параметр/результат
+2  единицы измерения
+2  референсные значения
+3  WBC/RBC/HGB/PLT
+2  лейкоцитарная формула
+2  "гематологические исследования"
```

Именно такой structural scoring уже предлагается в анализе второго прогона и лучше подходит для вариаций реальных лабораторных шаблонов. 

Я бы сделал ещё лучше:

```text
classification score
classification reasons[]
```

Например:

```json
{
  "type": "laboratory",
  "confidence": 0.94,
  "reasons": [
    "laboratory_section",
    "reference_values_table",
    "numeric_results_with_units",
    "hematology_markers"
  ]
}
```

Это очень пригодится для debugging.

---

# 6. Добавить `classification` как отдельный pipeline artifact

Сейчас classification фактически является внутренним решением.

Я бы сделал его частью processing metadata:

```json
{
  "classification": {
    "type": "laboratory",
    "subtype": "hematology",
    "confidence": 0.94,
    "method": "deterministic_score",
    "reasons": [...]
  }
}
```

Тогда через полгода можно будет ответить:

> Почему этот документ попал в laboratory?

А не разбираться по логам.

---

# 7. Второй важный quality gate — OCR quality

Это особенно важно для медицинских документов.

Сейчас Marker/OCR может вернуть:

```text
marker.md
```

и pipeline сразу идёт дальше.

Но нужно ввести:

```text
OCR
 ↓
OCR Quality Assessment
```

Например:

```json
{
  "quality": {
    "status": "good",
    "score": 0.94,
    "page_count": 3,
    "text_length": 18234,
    "table_count": 4,
    "warnings": []
  }
}
```

В вашем JPEG прогоне quality фактически был отличным: чистый текст, таблица, 1 страница. 

А PDF-прогоны показывают, что pipeline может столкнуться с артефактами рендеринга. 

Поэтому я бы не позволял плохому OCR незаметно проходить дальше.

---

# 8. Ввести `processing_attempt`

Сейчас для будущего production это будет очень полезно.

Например:

```text
document_processing_attempts
```

или расширить существующий `document_processing_jobs`.

Ваша текущая модель уже имеет `document_processing_jobs` и `document_extractions`. 

Для каждого processing attempt:

```text
attempt_id
document_id
version_id
pipeline_version
started_at
finished_at

ocr_model
extraction_model

classification_type
classification_confidence

status

input_tokens
output_tokens
cost

error_code
error_message
```

Тогда:

```text
Document
   │
   ├── ProcessingAttempt #1 → failed
   ├── ProcessingAttempt #2 → succeeded
   └── ProcessingAttempt #3 → succeeded
```

Это гораздо лучше, чем перезаписывать единственный статус.

---

# 9. Очень важно: `document_version` должен быть immutable

Ваш pipeline уже имеет:

```text
documents
document_versions
```

что является хорошей основой. 

Я бы зафиксировал:

> Original uploaded file никогда не изменяется.

Если пользователь загружает новый файл:

```text
Document
 ├── Version 1
 │     └── original.pdf
 │
 ├── Version 2
 │     └── original_v2.pdf
 │
 └── Version 3
       └── corrected.pdf
```

И processing всегда относится к:

```text
document_id + version_id
```

а не просто к `document_id`.

---

# 10. Ввести явный `source lineage`

Сейчас canonical frontmatter уже содержит:

```text
source:
    type
    mime_type
    filename
    sha256
    object_key
```

и это собирается Python, а не LLM. 

Это правильное решение.

Но я бы расширил lineage:

```json
{
  "source": {
    "document_id": "...",
    "version_id": "...",
    "original_object_key": "...",
    "marker_object_key": "...",
    "canonical_object_key": "...",
    "structured_object_key": "...",
    "sha256": "..."
  }
}
```

Особенно важно исправить уже замеченную проблему:

> `source.object_key` сейчас указывает на `marker.md`, а не на original upload. 

Нужно различать:

```text
original_object_key
ocr_object_key
canonical_object_key
structured_object_key
```

---

# 11. PII нужно вынести из LLM prompt protection в отдельный gate

Это уже **не просто проблема prompt**.

Оба прогона показывают:

```text
generic extraction
        ↓
PII в note
```

В лабораторном документе PII попала в `note`, а в JPEG — ФИО пациента также оказалась внутри canonical data.  

Да, нужно добавить PII policy во все prompts.

Но я бы **не доверял только prompt**.

После Pydantic:

```text
LLM
 ↓
Pydantic
 ↓
PII detection
 ↓
canonical
```

То есть:

```python
validate_no_patient_identity(canonical)
```

И если найдено:

```text
PII detected
    ↓
warning / sanitize / retry
```

Для medical platform это существенно надёжнее.

---

# 12. Но я бы разделил PII и medical identity

Здесь есть важный нюанс.

В документе могут быть:

```text
patient name
birth date
SNILS
policy number
phone
```

Но нам в будущем необходимо **сопоставить документ с Patient**.

Поэтому не надо просто уничтожать PII везде.

Нужно разделить:

```text
Raw document
      │
      ├── original → encrypted/private storage
      │
      ├── OCR → restricted
      │
      ├── identity extraction → restricted
      │
      └── canonical medical data → application
```

Например:

```json
{
  "patient_reference": {
    "patient_id": "internal UUID"
  }
}
```

вместо:

```json
{
  "patient": {
    "name": "Иванов Иван Иванович",
    "snils": "..."
  }
}
```

Это будет гораздо полезнее для дальнейшего поиска и RAG.

---

# 13. Очень важное улучшение — `patient matching` как отдельная стадия

С учётом будущего Organization Domain я бы уже сейчас закладывал:

```text
upload
 ↓
document
 ↓
processing
 ↓
patient matching
 ↓
extraction
```

Но для user upload:

```text
Account → Patient
```

обычно известно заранее.

Для organization API upload в будущем:

```text
Organization
     │
     ▼
incoming document
     │
     ▼
patient identification
     │
     ├── exact match
     ├── possible match
     └── unresolved
```

Это очень важно.

Я бы не хотел, чтобы organization document автоматически становился частью MedicalRecord только потому, что LLM увидела ФИО.

---

# 14. Поэтому вводим `DocumentOwnership / Assignment`

В будущем:

```text
Document
   │
   ├── uploaded_by
   ├── source_organization
   ├── patient_id
   └── assignment_status
```

Например:

```text
assignment_status:

resolved
ambiguous
unresolved
rejected
```

Для текущего user upload:

```text
resolved
```

Для будущего organization API:

```text
unresolved → human/system matching
```

---

# 15. LLM extraction должен получать не только `marker.md`

В перспективе я бы давал модели:

```text
marker.md
+
document_type
+
classification
+
known patient context
+
schema definition
```

Например:

```text
Known document type:
laboratory

Schema:
LaboratoryCanonical v1.1

Known patient:
patient UUID only

Task:
Extract laboratory observations.

Do not return:
patient name
SNILS
insurance number
phone
```

Это уменьшит вероятность того, что модель будет пытаться «пересказать документ».

---

# 16. Добавить extraction confidence на уровне поля

Сейчас у вас есть общий:

```text
confidence
```

в `CanonicalDataResponse`. 

Для медицинских данных этого мало.

Например:

```json
{
  "results": [
    {
      "name": "HGB",
      "value": 147,
      "unit": "g/L",
      "reference_min": 130,
      "reference_max": 160,
      "flagged": false,
      "confidence": 0.99
    }
  ]
}
```

Но я бы **не добавлял это прямо сейчас в каждую schema**, если модель не умеет давать meaningful confidence.

Можно начать с:

```text
extraction.confidence
validation.warnings[]
```

а field-level confidence добавить позже.

---

# 17. `document_date` надо заменить на semantic dates

Третий прогон показал проблему очень хорошо.

Документ содержит:

```text
created_at
appointment_date
```

и модель выбрала не ту дату. 

Поэтому не стоит пытаться всё хранить в:

```json
"document_date": "..."
```

Лучше:

```json
{
  "document_date": "...",
  "event_date": "...",
  "issued_at": "...",
  "performed_at": "...",
  "appointment_at": "..."
}
```

Но поля должны быть schema-specific.

Для лаборатории:

```text
performed_at
issued_at
```

Для appointment:

```text
appointment_at
created_at
```

Для discharge:

```text
admission_at
discharge_at
issued_at
```

---

# 18. Generic schema нужно оставить, но сделать полезной

Я бы не удалял `GenericCanonical`.

Он нужен как safety net.

Но:

```text
GenericCanonical
    fields.note
```

слишком примитивен.

Минимально:

```json
{
  "type": "other",
  "subtype": "unknown",
  "document_date": null,

  "institution": {
    "name": null,
    "address": null
  },

  "title": null,
  "summary": null,

  "events": [],
  "fields": {}
}
```

То есть даже неизвестный документ сохраняет базовую структуру.

---

# 19. Я бы изменил статусную модель Document

Сейчас статус:

```text
PENDING
PROCESSING
COMPLETED
FAILED
```

уже централизован в `account-api`, что является правильным решением. 

Но для UI я бы добавил **processing stage**, не превращая его в огромное количество document statuses.

Например:

```text
document.status:
    PENDING
    PROCESSING
    COMPLETED
    FAILED
```

и отдельно:

```text
processing_stage:
    UPLOAD
    STORAGE
    OCR
    CLASSIFICATION
    EXTRACTION
    VALIDATION
    FINALIZATION
```

Тогда UI сможет показывать:

> Анализируем документ...

и backend знает:

> `EXTRACTION`.

---

# 20. Добавить human-review state

Не сейчас обязательно UI, но в модель стоит заложить:

```text
validation_status:

valid
warning
needs_review
invalid
```

У вас уже есть metadata:

```text
validation:
    status
    schema_valid
    warnings[]
    validated_at
```

что является хорошей основой. 

Я бы расширил:

```text
needs_review
```

для случаев:

```text
classification confidence low
PII detected
schema warning
ambiguous date
patient matching ambiguous
```

---

# 21. Новый рекомендуемый flow

Я бы зафиксировал следующий pipeline:

```text
                    ┌─────────────────┐
                    │ User / Org API  │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │ Upload Service  │
                    └────────┬────────┘
                             │
                       create Document
                             │
                             ▼
                    ┌─────────────────┐
                    │ Object Storage  │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │ Source Validate │
                    │ MIME / size     │
                    │ SHA256          │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │ Marker / OCR    │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │ OCR Quality     │
                    │ Gate            │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │ Classification  │
                    │ score + reasons │
                    └────────┬────────┘
                             │
                ┌────────────┴────────────┐
                │                         │
             confident                uncertain
                │                         │
                ▼                         ▼
           select schema             generic/review
                │                         │
                └────────────┬────────────┘
                             ▼
                    ┌─────────────────┐
                    │ LLM Extraction  │
                    │ canonical JSON  │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │ Pydantic        │
                    │ Validation      │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │ PII / Semantic  │
                    │ Quality Gates   │
                    └────────┬────────┘
                             │
                    ┌────────┴────────┐
                    │                 │
                  valid           needs review
                    │                 │
                    ▼                 ▼
               canonical          REVIEW
                    │
                    ├──────────────┐
                    ▼              ▼
               PostgreSQL          S3
                    │              │
                    │         canonical.json
                    │         structured.md
                    │
                    ▼
               COMPLETED
```

---

# 22. Что я бы реализовал первым

Не надо сейчас переписывать весь pipeline.

Я бы разбил изменения на следующие итерации.

### Phase 1 — Classification 2.0

**Priority: P0**

Убрать:

```python
keyword in marker
```

и сделать:

```text
normalized text
+
regex
+
structural signals
+
score
+
classification reasons
```

Добавить regression tests на оба лабораторных документа.

Цель:

```text
lab_3 → laboratory
lab_4 → laboratory
appointment.jpg → appointment
```

---

### Phase 2 — GenericCanonical 2.0

**Priority: P0**

Убрать концепцию:

```text
generic = note
```

Сделать:

```text
GenericCanonical
    title
    summary
    institution
    document_date
    events
    fields
```

---

### Phase 3 — AppointmentCanonical

**Priority: P1**

Добавить:

```text
AppointmentCanonical
```

с:

```text
appointment_at
doctor
specialty
institution
department
location
cabinet
ticket_number
```

При этом PII пациента не хранить в canonical.

---

### Phase 4 — PII Gate

**Priority: P0**

Не только prompt.

```text
LLM
 ↓
Pydantic
 ↓
PII validation
 ↓
canonical
```

И regression tests:

```text
generic laboratory
generic appointment
```

не должны содержать ФИО/SNILS/полис/телефон.

---

### Phase 5 — Processing metadata

**Priority: P1**

Добавить:

```text
classification
classification_confidence
classification_reasons
pipeline_version
processing_attempt
```

Это резко упростит эксплуатацию.

---

### Phase 6 — Semantic dates

**Priority: P1**

Перестать использовать `document_date` как универсальную дату события.

Добавить schema-specific semantic dates.

---

### Phase 7 — Patient assignment

**Priority: P1 / особенно перед Organization API**

```text
document
    ↓
patient assignment
    ↓
medical record
```

Это желательно сделать **до массового Organization bulk upload**, иначе потом придётся переделывать ingestion pipeline.

---

# 23. Ещё одно изменение, которое я бы сделал сейчас

В текущем pipeline canonical JSON уже является source of truth, а markdown строится Python-кодом. Это решение я бы **не менял**. 

Но я бы сделал source of truth немного шире:

```text
                    Processing Result
                           │
            ┌──────────────┼──────────────┐
            ▼              ▼              ▼
       classification   canonical      validation
                           │
                           ▼
                     structured.md
```

То есть `canonical.json` — source of truth **для медицинской структуры**, но не единственное описание результата обработки.

В БД:

```text
DocumentExtraction
 ├── schema_name
 ├── schema_version
 ├── data
 ├── confidence
 ├── validation_status
 ├── classification
 ├── processing_attempt_id
 └── created_at
```

А `canonical.json` в S3 — immutable artifact конкретного extraction.

---

# Итог

Два прогона показывают довольно позитивную картину: **OCR сейчас не является главным узким местом**. В JPEG-прогоне он извлёк таблицу полностью, а в лабораторном PDF — также сохранил все 17 показателей.  

Главная проблема сейчас находится **между OCR и финальным canonical result**:

```text
                    CURRENT
                       │
OCR ────────────────► LLM
                       │
                       ▼
                  canonical
```

Я бы превратил это в:

```text
OCR
 │
 ▼
OCR Quality Gate
 │
 ▼
Classification
 │
 ├── confidence
 ├── reasons
 └── schema selection
 │
 ▼
LLM
 │
 ▼
Pydantic
 │
 ▼
PII Gate
 │
 ▼
Semantic Validation
 │
 ▼
Canonical
 │
 ├── DB
 ├── S3
 └── Markdown
```

И **особенно важно сделать это до подключения Organization API и bulk upload**. Сейчас один ошибочно классифицированный лабораторный документ портит downstream representation; при ручной загрузке одного документа это неприятно, а при загрузке организацией 500–5000 документов это уже станет системной проблемой.

При этом существующая основа — `Document → DocumentVersion → ProcessingJob → DocumentExtraction`, централизованное управление status в `account-api` и canonical pipeline — хорошо подходит для этих изменений.  

**Мой приоритет сейчас:** `Classification 2.0 → PII Gate → GenericCanonical 2.0 → AppointmentCanonical → processing metadata → patient assignment`. После этого уже имеет смысл масштабировать ingestion через Organization API и bulk upload.
