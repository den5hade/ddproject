Да. Я бы здесь немного изменил концепцию: YAML-заголовок должен быть не просто «технической информацией о генерации», а **metadata envelope документа**, который позволит вам потом версионировать, переобрабатывать, валидировать и связывать документы между собой.

Особенно важно разделить:

1. **идентичность документа**;
2. **происхождение (provenance)**;
3. **LLM processing**;
4. **schema/versioning**;
5. **качество и validation**;
6. **медицинский контекст**;
7. **поиск и индексацию**.

## Предлагаемый YAML header

Я бы начал примерно с такой структуры:

```yaml
---
doc_id: "01JXXXXXXXXXXXXXXX"
user_id: "01JYYYYYYYYYYYYYYY"

type: "laboratory"
subtype: "blood_test"

source:
  filename: "blood_test_2026-08-15.pdf"
  mime_type: "application/pdf"
  object_key: "users/.../documents/.../original.pdf"
  sha256: "..."
  uploaded_at: "2026-08-15T12:31:00Z"

processing:
  pipeline_version: "1.0.0"
  marker:
    version: "1.x.x"
    processed_at: "2026-08-15T12:35:00Z"

  extraction:
    model: "gpt-5.6"
    prompt_version: "extraction-2.1"
    schema: "laboratory-v1"
    schema_version: "1.0.0"

    tokens:
      input: 12500
      output: 3200
      total: 15700

    processed_at: "2026-08-15T12:36:00Z"

  metadata_generation:
    model: "gpt-5.6"
    prompt_version: "metadata-1.0"
    processed_at: "2026-08-15T12:37:00Z"

validation:
  status: "valid"
  schema_valid: true
  validated_at: "2026-08-15T12:37:30Z"

document:
  language: "ru"
  date: "2026-08-15"
  document_date: "2026-08-14"
  source_type: "laboratory"
  page_count: 4

---
```

Но я бы **не добавлял всё сразу**. Есть несколько полей, которые я считаю особенно важными для будущей архитектуры.

---

# 1. `document_id` / `doc_id`

У вас уже есть:

```yaml
doc_id: "..."
```

Это обязательно.

Я бы использовал **UUID/ULID**, а не имя файла.

Например:

```yaml
doc_id: "01J8M7K..."
```

ULID особенно удобен, потому что он sortable по времени.

---

# 2. `user_id`

Очень рекомендую добавить:

```yaml
user_id: "..."
```

Но есть важный архитектурный нюанс.

Если Markdown может когда-либо покинуть ваше внутреннее защищённое хранилище, я бы подумал, нужно ли вообще помещать туда реальный внутренний `user_id`.

Можно вместо этого использовать:

```yaml
owner_id: "..."
```

или вообще хранить связь:

```text
doc_id → user_id
```

только в PostgreSQL.

**Для медицинских документов я бы предпочёл второй вариант.**

То есть YAML:

```yaml
doc_id: "..."
```

а принадлежность:

```text
PostgreSQL
Document.id → User.id
```

Это уменьшает количество PII в самих артефактах.

---

# 3. `type`

Ваше:

```yaml
type:
  лабораторные исследования
  выписка
  диагноз
```

я бы сделал machine-readable.

Например:

```yaml
type: laboratory
```

и отдельно:

```yaml
subtype: blood_test
```

или:

```yaml
type: medical_report
subtype: discharge_summary
```

Потому что потом будет очень удобно:

```python
if document.type == DocumentType.LABORATORY:
    ...
```

а не работать со строками на русском.

Например:

```yaml
type: laboratory
subtype: blood_test
```

В UI:

```text
Лабораторные исследования
Анализ крови
```

---

# 4. `schema`

Ваше поле:

```yaml
schema: ...
```

очень правильное.

Но я бы обязательно разделил:

```yaml
schema:
  name: laboratory
  version: "1.2.0"
```

или компактно:

```yaml
schema: "laboratory"
schema_version: "1.2.0"
```

Это критично.

Представьте:

```text
2026
laboratory-v1

2027
laboratory-v2
```

Ваши старые документы должны продолжать корректно обрабатываться.

---

# 5. `pipeline_version`

Я бы обязательно добавил:

```yaml
pipeline_version: "1.4.0"
```

Потому что со временем у вас будет меняться не только LLM.

Например:

```text
Marker
   ↓
normalization
   ↓
LLM extraction
   ↓
validation
   ↓
embedding
```

И через год вы захотите понять:

> Как этот документ был получен?

Одного `model` для этого недостаточно.

Поэтому:

```yaml
pipeline_version: "1.4.0"
```

очень полезен.

---

# 6. `prompt_version`

Ваше поле:

```yaml
prompt_version: "2.3"
```

оставляем.

Но я бы делал отдельно для каждого LLM pipeline stage.

Например:

```yaml
processing:

  extraction:
    model: "..."
    prompt_version: "extraction-2.3"

  classification:
    model: "..."
    prompt_version: "classification-1.2"

  normalization:
    model: "..."
    prompt_version: "normalization-3.0"
```

Не стоит иметь один глобальный:

```yaml
prompt_version: "2.3"
```

если в будущем будет несколько LLM-запросов.

---

# 7. Model

Ваш:

```yaml
model: ...
```

тоже нужен.

Но лучше:

```yaml
model:
  provider: "openai"
  name: "..."
```

Например:

```yaml
model:
  provider: openai
  name: gpt-5.6
```

Потому что потом может появиться:

```text
OpenAI
Anthropic
Gemini
local Ollama
```

---

# 8. `tokens`

Очень полезно, особенно для контроля стоимости.

Я бы не делал:

```yaml
tokens: 12345
```

а:

```yaml
tokens:
  input: 12000
  output: 3400
  total: 15400
```

А если хотите нормально анализировать стоимость:

```yaml
usage:
  tokens:
    input: 12000
    output: 3400
    total: 15400

  cost_usd: 0.042
```

**`cost_usd` я бы добавил.**

Это позволит потом увидеть:

```text
Average processing cost
Cost per document type
Cost per model
Cost per user
Cost per month
```

---

# 9. `created_at` и `processed_at`

Обязательно разделить:

```yaml
created_at:
```

и:

```yaml
processed_at:
```

Потому что:

```text
документ создан 15 августа
обработан 20 августа
```

— вполне нормальная ситуация.

Я бы использовал:

```yaml
created_at: "..."
updated_at: "..."
```

для самого документа.

А внутри processing:

```yaml
processed_at: "..."
```

---

# 10. Original document hash

Это одна из вещей, которую я **очень рекомендую**.

```yaml
source:
  sha256: "..."
```

Зачем?

Допустим пользователь загрузил:

```text
analysis.pdf
```

а через год тот же файл загружается ещё раз.

Можно вычислить:

```text
SHA-256
```

и понять:

```text
это тот же самый файл
```

Это полезно для:

* deduplication;
* повторной обработки;
* проверки целостности;
* audit trail.

---

# 11. Source information

Я бы добавил:

```yaml
source:
  type: "user_upload"
```

В будущем появятся:

```text
user_upload
specialist_upload
hospital_import
api
mobile_camera
```

Например:

```yaml
source:
  type: user_upload
  mime_type: application/pdf
  filename: "blood_test.pdf"
  sha256: "..."
```

---

# 12. `language`

Обязательно:

```yaml
language: "ru"
```

Потому что потом у вас могут появиться:

```text
ru
en
de
```

И это будет важно и для LLM, и для поиска.

---

# 13. `page_count`

Если Marker уже знает количество страниц:

```yaml
page_count: 5
```

Полезное техническое metadata.

---

# 14. Extraction quality

Я бы добавил:

```yaml
quality:
  status: "verified"
```

Но лучше не придумывать псевдоточность вроде:

```yaml
confidence: 0.97
```

если LLM реально не предоставляет статистически валидную confidence measure.

Лучше:

```yaml
quality:
  status: valid
  warnings: []
```

или:

```yaml
quality:
  status: warning
  warnings:
    - "reference_range_missing"
    - "doctor_name_unclear"
```

---

# 15. Validation

Это очень важная часть вашего pipeline.

После LLM:

```text
LLM
 ↓
Pydantic validation
 ↓
JSON Schema validation
 ↓
Markdown generation
```

Поэтому:

```yaml
validation:
  status: valid
  schema_valid: true
```

очень полезно.

Я бы добавил:

```yaml
validation:
  status: valid
  schema: laboratory
  schema_version: "1.2.0"
  validated_at: "..."
```

---

# 16. `processing_status`

Можно добавить:

```yaml
status: completed
```

Но я бы не дублировал это с database.

В вашем случае **RabbitMQ + PostgreSQL являются source of truth для pipeline status**.

Markdown — это artifact.

Поэтому не стоит превращать YAML внутри MD в полноценную БД.

---

# 17. `parent_document_id`

Это может оказаться очень полезным.

Например:

```text
Первичный анализ
      ↓
Повторный анализ
      ↓
Заключение врача
```

Можно связывать документы:

```yaml
parent_doc_id: "01J..."
```

или:

```yaml
related_documents:
  - "01J..."
  - "01J..."
```

Но я бы не перегружал YAML.

Связи лучше хранить в PostgreSQL:

```text
document_relations
```

а в YAML оставлять только идентификатор документа.

---

# 18. `encounter_id`

Для вашей архитектуры это особенно интересно.

У вас будет:

```text
User
  │
  ├── Documents
  │
  └── Medical encounters
```

Например:

```text
15 Aug
Cardiologist appointment
       │
       ├── Doctor report
       ├── ECG
       └── Prescription
```

Поэтому я бы предусмотрел:

```yaml
encounter_id: "01J..."
```

если документ связан с конкретным посещением специалиста.

---

# 19. `specialist_id`

Если документ добавил врач:

```yaml
created_by:
  type: specialist
  id: "..."
```

Но опять же, я бы предпочёл:

```yaml
source:
  type: specialist_upload
```

а конкретную связь хранить в БД.

---

# 20. Очень важное поле — `document_date`

Это отличается от:

```yaml
created_at
```

Например файл загружен:

```text
2026-09-01
```

но анализ сделан:

```text
2026-08-15
```

Поэтому:

```yaml
document_date: "2026-08-15"
uploaded_at: "2026-09-01T..."
```

Это будет крайне важно для timeline и аналитики.

---

# 21. `document_datetime`

Иногда анализ/приём имеет время:

```yaml
document_date: "2026-08-15"
document_datetime: "2026-08-15T09:30:00+03:00"
```

Но если время неизвестно, не надо его выдумывать.

---

# 22. `classification`

Поскольку первый LLM у вас фактически может классифицировать документ, можно сохранять:

```yaml
classification:
  type: laboratory
  subtype: blood_test
```

Но я бы разделил:

```text
classification
```

и:

```text
final type
```

если classification является промежуточным этапом.

---

# 23. Версия самого документа

Очень рекомендую:

```yaml
document_version: 1
```

Например вы повторно обработали исходный PDF новой моделью:

```text
document v1
→ GPT X

document v2
→ GPT Y
```

При этом:

```text
doc_id
```

остаётся тем же.

Это намного лучше, чем создавать новый `doc_id`.

---

# 24. Processing lineage

Для серьёзной системы я бы постепенно пришёл к:

```yaml
processing:
  pipeline_version: "1.4.0"

  stages:
    - name: marker
      version: "1.2.1"

    - name: extraction
      model: "..."
      prompt_version: "2.3"

    - name: normalization
      model: "..."
      prompt_version: "1.1"

    - name: validation
      schema: "laboratory"
      schema_version: "1.2"
```

Это даст вам практически полноценный **data lineage**.

---

# 25. Embedding metadata

Если после этого Markdown отправляется в vector DB, я бы **не помещал embedding information непосредственно в медицинский документ**, кроме версии embedding pipeline.

Например:

```yaml
embedding:
  model: "..."
  version: "1.0"
```

Но сам vector ID:

```yaml
vector_id: ...
```

я бы хранил в БД.

Например:

```text
PostgreSQL
document_id
chunk_id
vector_id
```

---

# 26. Я бы разделил metadata на 4 уровня

Это, на мой взгляд, самое важное архитектурное решение.

Не делать один огромный YAML:

```yaml
---
everything:
...
---
```

а концептуально разделить:

```text
DOCUMENT
SOURCE
PROCESSING
VALIDATION
```

Например:

```yaml
---
doc_id: "01J..."
type: "laboratory"
subtype: "blood_test"

document:
  language: "ru"
  document_date: "2026-08-15"
  page_count: 4

source:
  type: "user_upload"
  mime_type: "application/pdf"
  filename: "blood_test.pdf"
  sha256: "..."

processing:
  pipeline_version: "1.4.0"

  extraction:
    model:
      provider: "openai"
      name: "..."
    prompt_version: "extraction-2.3"
    schema: "laboratory"
    schema_version: "1.2.0"

    usage:
      input_tokens: 12000
      output_tokens: 3000
      total_tokens: 15000
      cost_usd: 0.04

validation:
  status: "valid"
  schema_valid: true
  validated_at: "2026-08-15T12:40:00Z"

---
```

---

# 27. Но есть ещё более важный момент

Я бы **не заставлял второй LLM генерировать YAML header**.

Это кажется логичным:

```text
Marker
 ↓
LLM #1 → structured Markdown
 ↓
LLM #2 → YAML metadata
```

но технически это не лучший вариант.

Большая часть metadata **не должна определяться LLM**.

Например:

```yaml
doc_id
model
prompt_version
schema_version
tokens
date
sha256
filename
mime_type
page_count
pipeline_version
```

— это известные вашей системе данные.

Их должен создавать **Python pipeline**, а не LLM.

То есть:

```text
                    ┌───────────────┐
PDF                 │     Marker    │
 │                  └───────┬───────┘
 ▼                          │
marker.md                   ▼
                     ┌───────────────┐
                     │     LLM #1    │
                     │ extraction    │
                     └───────┬───────┘
                             │
                             ▼
                     structured JSON
                             │
                             ▼
                    Pydantic validation
                             │
                             ▼
                    structured Markdown
                             │
                             ▼
                  Python Metadata Builder
                             │
                             ▼
                       YAML frontmatter
```

А не:

```text
LLM #2
  ↓
"generate YAML"
```

---

# 28. Более того — я бы вообще хранил canonical JSON

Это будет особенно полезно для вашей будущей аналитики.

Я бы сделал pipeline:

```text
PDF
 ↓
Marker
 ↓
marker.md
 ↓
LLM
 ↓
CANONICAL JSON
 ↓
Pydantic validation
 ↓
structured.md
 ↓
YAML frontmatter
 ↓
Vectorization
```

То есть **структурированный JSON должен быть source of truth**, а Markdown — удобным представлением.

Например:

```json
{
  "document_type": "laboratory",
  "laboratory": {
    "test_date": "2026-08-15",
    "results": [
      {
        "name": "hemoglobin",
        "value": 135,
        "unit": "g/L",
        "reference_min": 120,
        "reference_max": 160
      }
    ]
  }
}
```

И уже из этого Python генерирует:

```text
---
doc_id: ...
type: laboratory
...
---

# Laboratory results

## Hemoglobin

**135 g/L**

Reference range: 120–160 g/L
```

Это намного надёжнее.

---

# 29. Итоговая архитектура pipeline

Я бы в итоге строил так:

```text
                    ORIGINAL
                       PDF
                        │
                        ▼
                 ┌──────────────┐
                 │    Marker    │
                 └──────┬───────┘
                        │
                        ▼
                    marker.md
                        │
                        ▼
                 ┌──────────────┐
                 │    LLM #1    │
                 │ extraction   │
                 └──────┬───────┘
                        │
                        ▼
                 canonical.json
                        │
                        ▼
                 ┌──────────────┐
                 │  Pydantic    │
                 │  validation  │
                 └──────┬───────┘
                        │
                 ┌──────┴───────┐
                 │              │
                 ▼              ▼
          structured.md    PostgreSQL
                 │              │
                 ▼              │
          YAML frontmatter      │
                 │              │
                 └──────┬───────┘
                        ▼
                 Chunking / Embed
                        │
                        ▼
                    Vector DB
```

### И YAML тогда становится именно **техническим паспортом артефакта**, а не ещё одним результатом работы LLM.

Я бы зафиксировал обязательными полями первой версии:

```yaml
doc_id
type
subtype

document_date
language

source:
  type
  mime_type
  filename
  sha256

processing:
  pipeline_version

  extraction:
    model
    prompt_version
    schema
    schema_version
    tokens
    cost

validation:
  status
  schema_valid
  validated_at
```

А `user_id`, `encounter_id`, `specialist_id`, `vector_id` и другие связи оставил бы преимущественно **в PostgreSQL**, чтобы Markdown оставался переносимым artifact'ом и не превращался в копию вашей базы данных.

Для медицинского продукта я бы также сразу проектировал **immutable original PDF + versioned derived artifacts**: исходный файл никогда не меняется, а `structured.json`/`structured.md` могут иметь версии при повторной обработке новой моделью или новым prompt/schema. Это сильно упростит аудит и миграцию LLM в будущем.
