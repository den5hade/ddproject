Да. Я посмотрел загруженную документацию и сопоставил её с архитектурой, которую мы выработали. Сейчас у вас уже есть **хорошая основа**, но документацию я бы немного перестроил: сейчас `DOCS_STRUCTURE.md`, `ACC_IMPLEMTATION.md` и `DB_MODELS.md` частично пересекаются, а главное — документации для **межсервисного pipeline, Marker VPS, RabbitMQ contracts и AI worker** пока недостаточно.

В частности, текущая документация уже хорошо фиксирует разделение `Account → Person → Patient/Specialist`, RBAC, Access Grants, Documents/Versions, Processing Jobs и Audit Log. 

## 1. Я бы разделил документацию на 4 уровня

Не делать один огромный `ARCHITECTURE.md`.

Предлагаю:

```text
docs/
│
├── README.md
│
├── architecture/
│   ├── OVERVIEW.md
│   ├── COMPONENTS.md
│   ├── DATA_FLOW.md
│   ├── PROCESSING_PIPELINE.md
│   └── SCALING.md
│
├── backend/
│   ├── ACCOUNT_API.md
│   ├── DOMAIN.md
│   ├── API.md
│   └── ERROR_HANDLING.md
│
├── data/
│   ├── DATABASE.md
│   ├── DB_MODELS.md
│   ├── STORAGE.md
│   └── DATA_LIFECYCLE.md
│
├── security/
│   ├── AUTHENTICATION.md
│   ├── AUTHORIZATION.md
│   ├── RBAC.md
│   ├── ACCESS_CONTROL.md
│   ├── AUDIT.md
│   └── PRIVACY.md
│
├── services/
│   ├── ACCOUNT_API.md
│   ├── MARKER_WORKER.md
│   ├── MARKER_ORCHESTRATOR.md
│   └── AI_WORKER.md
│
├── messaging/
│   ├── RABBITMQ.md
│   └── EVENTS.md
│
├── api/
│   ├── authentication.md
│   ├── patients.md
│   ├── documents.md
│   ├── encounters.md
│   ├── access.md
│   └── analytics.md
│
├── deployment/
│   ├── LOCAL.md
│   ├── STAGING.md
│   ├── PRODUCTION.md
│   └── GPU_WORKER.md
│
├── development/
│   ├── SETUP.md
│   ├── CONTRIBUTING.md
│   ├── TESTING.md
│   └── MIGRATIONS.md
│
└── decisions/
    ├── ADR-001-monorepo.md
    ├── ADR-002-rabbitmq.md
    ├── ADR-003-ephemeral-gpu-worker.md
    ├── ADR-004-postgres-as-source-of-truth.md
    └── ADR-005-access-control.md
```

Это будет существенно лучше текущей структуры.

---

# 2. `docs/README.md` — главный entry point

Сейчас у вас уже предусмотрен `docs/README.md` как главная точка входа. 

Я бы сделал его **не технической документацией**, а картой проекта.

Например:

```markdown
# Medical Platform Documentation

## What is this project?

Short description.

## Architecture

- [System Architecture](architecture/OVERVIEW.md)
- [Data Flow](architecture/DATA_FLOW.md)
- [Processing Pipeline](architecture/PROCESSING_PIPELINE.md)

## Backend

- [Account API](services/ACCOUNT_API.md)
- [Marker Worker](services/MARKER_WORKER.md)
- [AI Worker](services/AI_WORKER.md)

## Data

- [Database](data/DATABASE.md)
- [Storage](data/STORAGE.md)

## Security

- [Authentication](security/AUTHENTICATION.md)
- [Authorization](security/AUTHORIZATION.md)
- [RBAC](security/RBAC.md)
- [Audit](security/AUDIT.md)

## Development

- [Local Setup](development/SETUP.md)
- [Testing](development/TESTING.md)
- [Migrations](development/MIGRATIONS.md)
```

Разработчик должен открыть README и за 2 минуты понять:

> где API, где worker, где БД, где документация по безопасности и как запустить проект.

---

# 3. `architecture/OVERVIEW.md`

Это **самый важный документ архитектуры**.

Здесь не надо описывать таблицы.

Только компоненты:

```text
                         Internet
                            │
                            ▼
                     Account API
                            │
               ┌────────────┼────────────┐
               ▼            ▼            ▼
          PostgreSQL      S3        RabbitMQ
                                         │
                           ┌─────────────┴────────────┐
                           ▼                          ▼
                    Marker Worker                 AI Worker
                    GPU VPS                       CPU/GPU VPS
                           │
                           ▼
                          S3
                           │
                           ▼
                       AI Worker
                           │
                     ┌─────┴─────┐
                     ▼           ▼
                PostgreSQL     Qdrant
```

И здесь обязательно объяснить:

* что постоянно работает;
* что запускается динамически;
* где находится source of truth;
* где хранятся binary files;
* где находится vector index.

---

# 4. Очень важно: `services/` отдельно

Поскольку вы уже определились, что **Marker находится на отдельном VPS**, документация должна отражать это явно.

Не писать:

```text
Marker — часть Account API
```

или:

```text
monorepo = один deployment
```

Monorepo ≠ deployment unit.

Нужно написать:

```text
Repository
    │
    ├── account-api
    ├── marker-worker
    ├── marker-orchestrator
    └── ai-worker
```

но deployment:

```text
Main VPS
├── account-api
├── ai-worker
└── marker-orchestrator

GPU VPS
└── marker-worker
```

---

# 5. `services/ACCOUNT_API.md`

Здесь описываем только Account API.

Например:

```text
Responsibilities
----------------
Authentication
Authorization
Patients
Medical Records
Documents metadata
Encounters
Access grants
Audit
Analytics API
```

И отдельно:

```text
Does NOT:
----------------
run Marker
process PDFs
run LLM
generate embeddings
store binary files locally
```

Это очень полезно для предотвращения архитектурного drift.

---

# 6. `services/MARKER_WORKER.md`

Вот этого сейчас документации явно не хватает.

Нужно описать:

```text
Purpose
Input
Output
Dependencies
Runtime
GPU requirements
RabbitMQ queues
S3 buckets
Failure handling
Idempotency
Shutdown behavior
```

Например:

```text
RabbitMQ
    │
    │ document.convert
    ▼
Marker Worker
    │
    ├── S3 GET original.pdf
    │
    ├── Marker
    │
    ├── validate result
    │
    ├── S3 PUT result.md
    │
    └── publish document.converted
```

---

# 7. Отдельно `MARKER_ORCHESTRATOR.md`

Это принципиально важно для вашей экономической модели.

Документация должна описывать:

```text
Queue depth >= 20
        │
        ▼
Request GPU start
        │
        ▼
Wait for heartbeat
        │
        ▼
Worker processes queue
        │
        ▼
Queue empty
        │
        ▼
Idle timeout
        │
        ▼
Stop GPU VPS
```

И configuration:

```env
MARKER_SCALE_UP_THRESHOLD=20
MARKER_IDLE_TIMEOUT_SECONDS=600
MARKER_START_TIMEOUT_SECONDS=600
MARKER_HEALTHCHECK_INTERVAL_SECONDS=15
```

Причём здесь я бы **зафиксировал, что `20` — operational parameter, а не business rule**.

---

# 8. `services/AI_WORKER.md`

Отдельно описать AI pipeline:

```text
Markdown/JSON
      │
      ▼
Document classification
      │
      ▼
Schema selection
      │
      ▼
LLM structured extraction
      │
      ▼
Pydantic validation
      │
      ▼
DocumentExtraction
      │
      ├───────────────┐
      ▼               ▼
PostgreSQL          Embeddings
                      │
                      ▼
                    Qdrant
```

И очень важно зафиксировать:

> AI worker не является владельцем медицинской БД.

`PostgreSQL` — source of truth; Qdrant используется как поисковый индекс. Это уже правильно отражено в вашей модели данных. 

---

# 9. `architecture/PROCESSING_PIPELINE.md`

Это я бы сделал отдельным документом.

Потому что сейчас pipeline разбросан между implementation docs.

Должна быть одна canonical схема:

```text
Upload
  │
  ▼
S3
  │
  ▼
document_uploaded
  │
  ▼
Marker
  │
  ▼
document_converted
  │
  ▼
AI extraction
  │
  ▼
document_analysis_completed
  │
  ▼
PostgreSQL
  │
  ▼
Embedding
  │
  ▼
Qdrant
```

И для каждого шага:

```text
Input
Output
Owner
Queue
Retry policy
Failure state
Idempotency key
```

---

# 10. Messaging documentation

Я бы сделал:

```text
messaging/
├── RABBITMQ.md
└── EVENTS.md
```

`RABBITMQ.md`:

```text
exchanges
queues
routing keys
DLQ
retry
TTL
consumer behavior
```

`EVENTS.md`:

```text
document.uploaded
document.conversion.requested
document.converted
document.analysis.requested
document.analysis.completed
document.processing.failed
```

Например:

```json
{
  "event_id": "uuid",
  "event_type": "document.converted",
  "schema_version": 1,
  "document_id": "uuid",
  "document_version_id": "uuid",
  "patient_id": "uuid",
  "storage_key": "...",
  "occurred_at": "..."
}
```

---

# 11. Версионирование event contracts

Это я бы добавил обязательно.

У события:

```text
schema_version = 1
```

Потому что через год Marker Worker может отправлять:

```text
document.converted v2
```

а AI Worker ещё некоторое время работать с v1.

Без versioned contracts микросервисная архитектура начинает ломаться при каждом изменении schema.

---

# 12. `data/DATABASE.md` и `DB_MODELS.md`

Здесь ваши существующие документы уже хорошие.

`DB_MODELS.md` правильно фиксирует:

```text
Account
Person
Patient
MedicalRecord
Specialist
Organization
Documents
Versions
ProcessingJobs
Extraction
AccessGrant
AuditLog
```

и даже явно указывает, что `observations`, `diagnoses`, `medications`, `patient_consents` пока deferred. 

Я бы только разделил:

### `DATABASE.md`

Архитектура БД:

```text
Why PostgreSQL
Boundaries
Aggregates
Relationships
Indexes
Transactions
Migrations
Backup
Retention
```

### `DB_MODELS.md`

Конкретная schema:

```text
table
columns
types
FK
indexes
constraints
```

То есть:

```text
DATABASE.md = WHY
DB_MODELS.md = WHAT
```

---

# 13. `data/STORAGE.md`

Очень не хватает такого документа.

Там надо описать S3.

Например:

```text
S3
│
├── original/
│
├── converted/
│
└── derived/
```

И naming convention:

```text
medical-records/{medical_record_id}/
    documents/{document_id}/
        versions/{version_id}/
            original.pdf
            marker.md
            marker.json
```

И отдельно:

```text
Never expose S3 key directly to client.
Use presigned URLs.
```

Ваш текущий implementation уже правильно предусматривает presigned upload и `upload-confirm`. 

---

# 14. `security/ACCESS_CONTROL.md`

Я бы сделал этот документ **центральным security contract**.

У вас уже есть хорошая основа: `require_patient_access`, AccessGrant, `expires_at`, audit и запрет автоматического доступа `system_admin`. 

Но нужно описать decision algorithm.

Например:

```text
Can actor access patient record?

1. Is account authenticated?
2. Is account active?
3. Does account have required permission?
4. Is actor the patient?
       YES → allow
5. Does active PatientAccessGrant exist?
       NO → deny
6. Is grant expired?
       YES → deny
7. Does grant contain required permission?
       NO → deny
8. ALLOW
9. Write audit event
```

Это должен быть **не просто README**, а архитектурный контракт.

---

# 15. RBAC и ABAC нужно документировать отдельно

Это две разные вещи.

### RBAC

```text
CLIENT
SPECIALIST
ORGANIZATION_ADMIN
SYSTEM_ADMIN
```

### ABAC / resource authorization

```text
Specialist
    │
    └── PatientAccessGrant
              │
              ├── can_view_documents
              ├── can_upload_documents
              ├── can_view_analytics
              └── can_edit_medical_data
```

Ваш implementation уже именно так и построен: роль определяет capabilities, а `PatientAccessGrant` — доступ конкретного специалиста к конкретному пациенту. 

---

# 16. API documentation

Здесь я бы **не дублировал OpenAPI вручную полностью**.

FastAPI уже генерирует:

```text
/openapi.json
/docs
/redoc
```

Поэтому Markdown должен описывать **business behavior**, а не каждое поле response.

Например:

```text
api/
├── auth.md
├── patients.md
├── documents.md
├── encounters.md
├── access.md
├── jobs.md
└── analytics.md
```

`documents.md`:

```markdown
# Documents API

## Upload

POST /patients/{patient_id}/documents

### Authorization

Patient:
- own patient only

Specialist:
- requires can_upload_documents

### Workflow

1. Create document
2. Generate presigned URL
3. Client uploads to S3
4. upload-confirm
5. Create processing job
6. Publish document.uploaded
```

Это намного полезнее, чем просто копия Swagger.

---

# 17. `DATA_LIFECYCLE.md`

Для медицинского приложения я бы обязательно сделал отдельный документ:

```text
User registration
       ↓
Personal data
       ↓
Document upload
       ↓
S3
       ↓
Processing
       ↓
Extracted medical data
       ↓
Analytics
       ↓
Archive
       ↓
Deletion / retention
```

И для каждого объекта:

```text
Where stored?
Who can access?
How long?
Can it be deleted?
Who can delete?
Is it audited?
```

Это будет полезно не только разработчикам, но и при дальнейшем compliance review.

---

# 18. ADR — очень рекомендую

У вас достаточно архитектурных решений, которые потом команда начнёт пересматривать.

Поэтому:

```text
docs/decisions/
```

### ADR-001

```text
Why monorepo?
```

### ADR-002

```text
Why RabbitMQ?
```

### ADR-003

```text
Why Marker on ephemeral GPU VPS?
```

### ADR-004

```text
Why PostgreSQL is source of truth and Qdrant isn't?
```

### ADR-005

```text
Why Account != Patient?
```

### ADR-006

```text
Why access grants instead of specialist_id on Patient?
```

### ADR-007

```text
Why documents are versioned?
```

Это особенно важно, потому что ваши архитектурные решения уже довольно специфичные.

---

# 19. Что делать с `ACC_IMPLEMTATION.md`

Вот здесь я бы внёс самое существенное изменение.

Сейчас он одновременно содержит:

* implementation plan;
* security rules;
* milestones;
* tests;
* services;
* routes;
* database behavior.

Например, в нём уже описаны M1 RBAC → M2 Patient/MR → M3 Documents → M4 Encounters → M5 Access → M6 analytics. 

Это полезно, но со временем файл превратится в огромный changelog.

Я бы разделил:

```text
ACC_IMPLEMENTATION.md
        ↓
docs/ROADMAP.md
docs/backend/...
docs/services/...
docs/security/...
docs/messaging/...
```

А `ACC_IMPLEMENTATION.md` либо удалить, либо оставить как исторический implementation plan.

---

# 20. И ещё одна важная вещь: documentation ≠ task tracker

Не надо писать:

```text
- [x] create model
- [x] create endpoint
- [ ] add test
```

в архитектурной документации.

Для этого лучше:

```text
GitHub Issues
GitLab Issues
Linear
Jira
```

Документация должна отвечать:

> **Как система должна работать?**

Issue должна отвечать:

> **Что конкретно сейчас нужно сделать?**

---

# 21. Предлагаемая окончательная структура

Я бы остановился примерно на такой:

```text
docs/
│
├── README.md
├── ROADMAP.md
│
├── architecture/
│   ├── OVERVIEW.md
│   ├── COMPONENTS.md
│   ├── DATA_FLOW.md
│   ├── PROCESSING_PIPELINE.md
│   └── SCALING.md
│
├── services/
│   ├── ACCOUNT_API.md
│   ├── MARKER_WORKER.md
│   ├── MARKER_ORCHESTRATOR.md
│   └── AI_WORKER.md
│
├── data/
│   ├── DATABASE.md
│   ├── DB_MODELS.md
│   ├── STORAGE.md
│   └── DATA_LIFECYCLE.md
│
├── security/
│   ├── AUTHENTICATION.md
│   ├── AUTHORIZATION.md
│   ├── RBAC.md
│   ├── ACCESS_CONTROL.md
│   ├── AUDIT.md
│   └── PRIVACY.md
│
├── messaging/
│   ├── RABBITMQ.md
│   └── EVENTS.md
│
├── api/
│   ├── auth.md
│   ├── patients.md
│   ├── documents.md
│   ├── encounters.md
│   ├── access.md
│   ├── jobs.md
│   └── analytics.md
│
├── deployment/
│   ├── LOCAL.md
│   ├── STAGING.md
│   ├── PRODUCTION.md
│   └── GPU_WORKER.md
│
├── development/
│   ├── SETUP.md
│   ├── CONTRIBUTING.md
│   ├── TESTING.md
│   └── MIGRATIONS.md
│
└── decisions/
    ├── ADR-001-monorepo.md
    ├── ADR-002-rabbitmq.md
    ├── ADR-003-ephemeral-gpu.md
    ├── ADR-004-storage-boundaries.md
    ├── ADR-005-postgres-source-of-truth.md
    └── ADR-006-medical-access-control.md
```

## 22. Что я бы изменил прямо сейчас

На основании ваших текущих файлов я бы не переписывал всё с нуля.

У вас уже есть три хороших основы:

* `DOCS_STRUCTURE.md` — первоначальная карта документации;
* `DB_MODELS.md` — достаточно детальное описание реализованной БД;
* `ACC_IMPLEMTATION.md` — текущий implementation roadmap.  

Но сейчас я бы сделал **рефакторинг документации перед дальнейшей разработкой**:

```text
ACC_IMPLEMENTATION.md
        │
        ├── architecture → architecture/*
        ├── DB → data/*
        ├── security → security/*
        ├── RabbitMQ → messaging/*
        ├── Marker → services/MARKER_WORKER.md
        ├── AI → services/AI_WORKER.md
        └── milestones → ROADMAP.md
```

И самое главное — добавить отсутствующий слой:

```text
              ┌─────────────────────┐
              │   ARCHITECTURE      │
              │       docs          │
              └──────────┬──────────┘
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
      ACCOUNT API     MARKER        AI WORKER
          │           WORKER             │
          └──────────────┬───────────────┘
                         ▼
                   MESSAGE CONTRACTS
                         │
                         ▼
                    DATA STORAGE
```

То есть документация должна описывать **не только внутренности Account API**, которые сейчас уже достаточно хорошо расписаны, но и **контракт между тремя runtime-сервисами**. Это следующий наиболее важный пробел.

И я бы сделал `ARCHITECTURE.md`, `PROCESSING_PIPELINE.md`, `EVENTS.md` и `GPU_WORKER.md` обязательными документами перед тем, как начинать полноценную реализацию Marker/AI pipeline. Это предотвратит ситуацию, когда три сервиса начинают развиваться независимо и через пару месяцев у каждого оказывается своя трактовка `document status`, RabbitMQ message и результата обработки. 
