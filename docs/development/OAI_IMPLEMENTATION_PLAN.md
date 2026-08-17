Да. С учётом всей архитектуры, которую мы уже обсудили, я бы строил приложение **не как набор CRUD-эндпоинтов вокруг пользователей и файлов**, а как workflow-driven medical platform: `identity → patient → medical record → document → processing pipeline → structured medical data → analytics → specialist access`.

Ниже — план реализации, который я бы предложил команде Python/FastAPI разработчиков.

## 1. Целевая архитектура

```text
                         ┌──────────────────────┐
                         │       Web / App       │
                         └──────────┬───────────┘
                                    │ HTTPS
                                    ▼
                    ┌────────────────────────────┐
                    │       Account API          │
                    │         FastAPI            │
                    │                            │
                    │ Auth                       │
                    │ Patients                   │
                    │ Medical Records            │
                    │ Documents                  │
                    │ Specialists                │
                    │ Access Control             │
                    │ Analytics                  │
                    └──────┬─────────┬───────────┘
                           │         │
                    PostgreSQL       │
                           │         │
                           ▼         ▼
                      RabbitMQ       S3
                           │
              ┌────────────┴─────────────┐
              │                          │
              ▼                          ▼
       Marker Orchestrator          AI Worker
              │                          │
              │ START GPU VPS            │
              ▼                          │
        ┌───────────────┐                │
        │  GPU VPS      │                │
        │ marker-worker │                │
        └───────┬───────┘                │
                │                        │
                └──────────┬─────────────┘
                           ▼
                       PostgreSQL
                           +
                         Qdrant
```

Ключевая идея:

**Account API всегда работает. Marker GPU worker — ephemeral.**

---

# 2. Я бы разделил разработку на 8 фаз

Не стоит сразу писать всё: RBAC, врачей, AI, аналитику, Qdrant и т.д.

Правильный порядок:

```text
Phase 0  Foundation
Phase 1  Identity & Auth
Phase 2  Patient & Medical Record
Phase 3  Documents & S3
Phase 4  Processing Pipeline
Phase 5  AI Extraction
Phase 6  Specialist Access
Phase 7  Analytics
Phase 8  Production hardening
```

Причём каждая фаза должна заканчиваться **работающим вертикальным срезом**, а не просто набором таблиц.

---

# 3. Phase 0 — Foundation

Сначала создаём monorepo.

```text
pdf-medical-platform/
├── apps/
│   ├── account-api/
│   ├── marker-worker/
│   ├── marker-orchestrator/
│   └── ai-worker/
│
├── packages/
│   ├── contracts/
│   ├── messaging/
│   ├── storage/
│   └── observability/
│
├── infrastructure/
│   ├── development/
│   ├── main-vps/
│   └── marker-vps/
│
├── migrations/
├── tests/
└── pyproject.toml
```

### Технологии

Я бы использовал:

```text
Python 3.12+
FastAPI
SQLAlchemy 2.x
Alembic
Pydantic v2
PostgreSQL
RabbitMQ
boto3 / aioboto3
Redis — опционально
Qdrant
Docker
pytest
```

Для dependency management:

```text
uv
```

вместо отдельных `requirements.txt`.

---

# 4. Phase 1 — Identity & Authentication

Первый рабочий vertical slice:

```text
Register
   ↓
Login
   ↓
JWT/session
   ↓
GET /me
```

### Endpoints

```text
POST /api/v1/auth/register
POST /api/v1/auth/login
POST /api/v1/auth/refresh
POST /api/v1/auth/logout

GET  /api/v1/me
PATCH /api/v1/me
```

Регистрация:

```text
email OR phone
+
password
```

Позже:

```text
email verification
SMS verification
password reset
2FA
social login
```

не надо смешивать с первым MVP.

---

# 5. Identity model

Создаём:

```text
accounts
account_identities
persons
roles
permissions
account_roles
role_permissions
```

После регистрации:

```text
Account
   │
   ├── Identity(email/phone)
   │
   └── Person
          │
          └── Patient
```

По умолчанию:

```text
CLIENT
```

---

# 6. Phase 2 — Patient + Medical Record

После авторизации пользователь должен получить:

```text
GET /me
GET /me/patient
GET /me/medical-record
```

Создаётся:

```text
patients
medical_records
```

Важно: **medical record создаётся один раз**, а не на каждый документ.

```text
Patient #123
    │
    └── MedicalRecord #456
```

---

# 7. Phase 3 — Upload documents

Это первый действительно важный workflow.

Пользователь:

```text
POST /documents/upload
```

но я **не стал бы проксировать большие PDF через FastAPI**.

Лучше:

```text
                    Account API
                         │
                         │ generate presigned URL
                         ▼
                       S3
                         ▲
                         │
                    Browser/App
```

То есть:

### Step 1

```text
POST /documents/upload/init
```

API создаёт:

```text
document
document_version
```

и возвращает:

```text
presigned_upload_url
```

### Step 2

Client загружает:

```text
PDF/JPEG/PNG
```

напрямую в S3.

### Step 3

Client:

```text
POST /documents/{id}/complete
```

API проверяет наличие объекта.

### Step 4

Создаётся:

```text
document_processing_job
```

и публикуется RabbitMQ message.

---

# 8. S3 structure

Я бы не делал:

```text
pdfs/user_123/file.pdf
```

Лучше immutable IDs:

```text
tenants/{tenant_id}/
    patients/{patient_id}/
        documents/{document_id}/
            versions/{version_id}/
                original.pdf
```

Например:

```text
patients/
  01JABC.../
    documents/
      01JDEF.../
        versions/
          01JXYZ.../
            original.pdf
```

Это уменьшает проблемы с переименованием и безопасностью.

---

# 9. Document state machine

Очень важно не использовать только:

```text
status = "processing"
```

Нужна state machine.

Например:

```text
UPLOADING
    │
    ▼
UPLOADED
    │
    ▼
QUEUED
    │
    ▼
CONVERTING
    │
    ▼
CONVERTED
    │
    ▼
EXTRACTING
    │
    ▼
EXTRACTED
    │
    ▼
INDEXING
    │
    ▼
COMPLETED
```

При ошибке:

```text
           ┌──── FAILED
           │
PROCESS ───┤
           │
           └──── RETRY
```

Это позволит пользователю видеть:

```text
Blood test.pdf

✓ Uploaded
✓ Converted
✓ Analyzed
✓ Added to medical record
```

---

# 10. RabbitMQ

Не передавать через RabbitMQ PDF.

RabbitMQ передаёт **commands/events**.

Например:

```json
{
  "event_id": "...",
  "event_type": "document.processing.requested",
  "document_id": "...",
  "version_id": "...",
  "patient_id": "...",
  "storage_key": "...",
  "created_at": "..."
}
```

### Очереди

Я бы сделал:

```text
document.convert
document.extract
document.index
```

и dead-letter queues:

```text
document.convert.dlq
document.extract.dlq
document.index.dlq
```

---

# 11. Очень важный момент — idempotency

Каждый worker должен быть рассчитан на то, что сообщение может прийти повторно.

Например Marker получил:

```text
document_id = X
version_id = Y
```

Если уже есть:

```text
conversion.status = COMPLETED
```

он **не должен повторно конвертировать документ**.

Это обязательно для production RabbitMQ workflow.

---

# 12. Phase 4 — Marker pipeline

Теперь отдельный GPU VPS.

```text
RabbitMQ
    │
    ▼
marker-worker
    │
    ├── download from S3
    │
    ├── Marker
    │
    ├── validate output
    │
    ├── upload markdown/json
    │
    └── publish document.converted
```

Marker worker не должен знать ничего о пользователях кроме необходимых IDs.

Он получает:

```text
document_id
version_id
storage_key
```

---

# 13. Marker Orchestrator

Отдельный сервис на Main VPS.

Он постоянно следит:

```text
queue depth
worker heartbeat
GPU instance status
```

Например политика:

```text
queue < 20
    ↓
GPU OFF

queue >= 20
    ↓
START GPU

GPU READY
    ↓
process

queue = 0
    ↓
wait 10 minutes

still 0
    ↓
STOP GPU
```

Я бы **не зашивал `20` непосредственно в код**.

Конфигурация:

```text
MARKER_SCALE_UP_THRESHOLD=20
MARKER_SCALE_DOWN_IDLE_SECONDS=600
MARKER_MAX_WORKERS=1
```

---

# 14. Почему threshold 20 не обязательно оптимален

Здесь я бы сделал немного умнее.

Не только:

```text
queue >= 20
```

но учитывать:

```text
queue_size
estimated_processing_time
GPU_startup_time
```

Например:

```text
10 документов × 2 min = 20 min work
GPU startup = 5 min
```

может быть выгоднее запустить GPU уже при 10 документах.

Позже можно перейти к:

```text
estimated_work_seconds > threshold
```

Но для MVP:

```text
queue >= 20
```

абсолютно нормально.

---

# 15. Phase 5 — AI Extraction

После Marker:

```text
PDF
 ↓
Markdown/JSON
 ↓
AI worker
```

AI pipeline:

```text
load artifact
      ↓
normalize
      ↓
detect document type
      ↓
split/chunk
      ↓
LLM structured extraction
      ↓
Pydantic validation
      ↓
PostgreSQL
      ↓
embeddings
      ↓
Qdrant
```

---

# 16. AI output должен быть строго typed

Не стоит делать:

```python
result = llm(...)
db.save(result)
```

Лучше:

```text
LLM
 ↓
JSON
 ↓
Pydantic model
 ↓
validation
 ↓
domain model
 ↓
PostgreSQL
```

Например:

```python
class LabResult(BaseModel):
    test_name: str
    value: float | None
    unit: str | None
    reference_min: float | None
    reference_max: float | None
```

И для разных типов документов:

```text
LabResultSchema
ConsultationSchema
PrescriptionSchema
DiagnosisSchema
ImagingReportSchema
```

---

# 17. AI не должен напрямую писать в PostgreSQL

Это важный architectural boundary.

Плохо:

```text
LLM → SQLAlchemy → DB
```

Лучше:

```text
LLM
 ↓
structured output
 ↓
Pydantic
 ↓
domain service
 ↓
repository
 ↓
PostgreSQL
```

Так вы контролируете, **какие именно данные могут попасть в медицинскую БД**.

---

# 18. Medical data model

После extraction:

```text
DocumentExtraction
        │
        ├── Observation
        ├── Diagnosis
        ├── Medication
        └── Encounter data
```

Например лабораторный документ:

```text
CBC.pdf
```

становится:

```text
Observation
----------------
Hemoglobin
135
g/L

Observation
----------------
Leukocytes
6.2
10^9/L
```

Это уже основа аналитики.

---

# 19. PostgreSQL vs Qdrant

Я бы жёстко разделил назначение.

### PostgreSQL

Хранит:

```text
patients
encounters
documents
diagnoses
observations
medications
extractions
```

То есть **источник истины**.

### Qdrant

Хранит:

```text
chunks
embeddings
metadata
```

для:

```text
semantic search
RAG
similar documents
AI assistant
```

Qdrant не должен быть source of truth.

---

# 20. Phase 6 — Specialist portal

После того как pipeline работает для клиента, добавляем врача.

Сценарий:

```text
Specialist
   │
   ▼
GET /patients
   │
   ▼
Patient
   │
   ├── Medical record
   ├── Documents
   ├── Encounters
   ├── Observations
   └── Analytics
```

Но **каждый endpoint должен проходить authorization layer**.

Например:

```python
await access_service.require_permission(
    specialist=current_user,
    patient=patient,
    permission="medical_record.read",
)
```

Я бы вынес это в отдельный application service, а не размазывал проверки по каждому endpoint.

---

# 21. Specialist workflow

```text
Specialist
    │
    ▼
Search/select patient
    │
    ▼
Check access
    │
    ▼
Medical record
    │
    ├── timeline
    ├── documents
    ├── lab results
    ├── diagnoses
    └── analytics
```

После приёма:

```text
Create Encounter
      ↓
Add notes
      ↓
Upload document
      ↓
Document processing
      ↓
AI extraction
      ↓
Medical record updated
```

---

# 22. Medical timeline

Я бы сделал timeline одним из центральных UI/API concepts.

Например:

```text
2026-08-15
│
├── Consultation
│   Dr. Ivanov
│
├── Blood test
│
└── Prescription
│
2026-07-20
│
├── Blood test
└── Consultation
```

API:

```text
GET /patients/{patient_id}/timeline
```

Но timeline не обязательно хранить отдельной таблицей.

Его можно собирать из:

```text
encounters
documents
observations
diagnoses
medications
```

---

# 23. Phase 7 — Analytics

Я бы **не начинал с AI analytics**.

Сначала deterministic analytics.

Например:

```text
Hemoglobin

Jan     125
Mar     131
Jun     135
Aug     138
```

API:

```text
GET /patients/{id}/analytics/observations
```

Frontend строит график.

После этого AI может добавить:

```text
"Гемоглобин постепенно увеличивается..."
```

Но AI не должен быть единственным источником числовой аналитики.

---

# 24. Analytics architecture

```text
Documents
    ↓
Extraction
    ↓
Observations
    ↓
Analytics Service
    ↓
time series
    ↓
Frontend
```

AI summary:

```text
Observations
+
Encounters
+
Diagnoses
+
Documents
       ↓
      LLM
       ↓
"Summary"
```

---

# 25. Security я бы вынес в отдельный слой

Структура Account API:

```text
app/
├── api/
├── application/
├── domain/
├── infrastructure/
└── security/
```

Например:

```text
application/
    documents/
    patients/
    encounters/
    analytics/
    access/

domain/
    patient.py
    medical_record.py
    document.py
    encounter.py

security/
    authentication.py
    authorization.py
    permissions.py
```

Не стоит превращать FastAPI endpoints в огромные функции:

```python
@router.post(...)
async def upload(...):
    # 300 lines
```

---

# 26. Я бы использовал Clean/Hexagonal-ish architecture

Не надо делать академическую архитектуру на 200 классов.

Достаточно:

```text
API
 ↓
Application Service
 ↓
Domain
 ↓
Repository / Infrastructure
```

Например:

```text
POST /documents
       │
       ▼
DocumentService
       │
       ├── DocumentRepository
       ├── StorageService
       └── JobPublisher
```

Это позволит потом менять:

```text
S3 provider
RabbitMQ library
PostgreSQL implementation
LLM provider
```

без переписывания business logic.

---

# 27. Event contracts

В `packages/contracts` определить стабильные события:

```text
DocumentUploaded
DocumentConversionRequested
DocumentConverted
DocumentExtractionRequested
DocumentExtracted
DocumentIndexRequested
DocumentProcessingFailed
```

Например:

```python
class DocumentConverted(BaseModel):
    event_id: UUID
    document_id: UUID
    document_version_id: UUID
    patient_id: UUID

    output_storage_key: str

    occurred_at: datetime
```

**Все сервисы используют одинаковые contracts.**

---

# 28. Нужна correlation ID

Для каждого document workflow:

```text
request
  ↓
document_id
  ↓
conversion job
  ↓
AI extraction
  ↓
embedding
```

должен существовать:

```text
correlation_id
```

Тогда по логам можно найти весь pipeline одного документа.

---

# 29. Observability

Сразу добавить:

```text
structured JSON logs
request_id
correlation_id
document_id
job_id
```

Metrics:

```text
documents_uploaded_total
documents_processing_total
documents_failed_total

marker_queue_size
marker_processing_seconds

ai_processing_seconds

llm_requests_total
llm_tokens_total

document_pipeline_latency
```

Это особенно важно для GPU, потому что вы хотите оптимизировать его стоимость.

---

# 30. Failure handling

Нужно заранее определить:

### Marker failed

```text
retry 1
retry 2
retry 3
    ↓
DLQ
```

### LLM failed

То же самое.

### Invalid extraction

```text
EXTRACTION_REVIEW_REQUIRED
```

а не:

```text
COMPLETED
```

---

# 31. Human review — я бы предусмотрел сейчас

Поскольку это медицинские документы, AI иногда будет не уверен.

Добавить:

```text
extraction.status:

PENDING
PROCESSING
COMPLETED
FAILED
REVIEW_REQUIRED
REVIEWED
```

И specialist/admin сможет исправить extraction.

Например:

```text
AI:
Hemoglobin = 135

confidence = 0.97
```

или:

```text
AI:
Hemoglobin = 185
confidence = 0.42

→ REVIEW_REQUIRED
```

---

# 32. Что не надо делать в первой версии

Я бы **не делал сразу**:

* полноценный FHIR server;
* сложный medical ontology;
* собственную LLM;
* собственные embeddings;
* real-time collaboration;
* сложную multi-tenant архитектуру;
* mobile apps;
* микросервис для каждой таблицы;
* Kubernetes.

Это сильно увеличит стоимость и время разработки.

---

# 33. MVP deployment

На первом production этапе:

```text
                    Main VPS
               ┌──────────────────┐
               │                  │
               │ Account API      │
               │ AI Worker        │
               │ Orchestrator     │
               │ RabbitMQ         │
               │ PostgreSQL       │
               │ Qdrant           │
               │                  │
               └────────┬─────────┘
                        │
                        │ S3
                        ▼
                  Object Storage


                 GPU VPS
                 OFF by default
                      │
                queue >= 20
                      │
                      ▼
                 START
                      │
                marker-worker
                      │
                      ▼
                 queue empty
                      │
                  idle 10m
                      │
                      ▼
                    STOP
```

---

# 34. Порядок реализации конкретными milestones

Я бы поставил задачи именно так:

### Milestone 1 — Infrastructure

* monorepo;
* Docker;
* PostgreSQL;
* RabbitMQ;
* local S3/MinIO;
* Qdrant;
* Alembic;
* CI;
* logging.

### Milestone 2 — Authentication

* account;
* email/phone;
* password;
* JWT/session;
* roles;
* permissions;
* `/me`.

### Milestone 3 — Patient

* person;
* patient;
* medical record;
* basic profile.

### Milestone 4 — Documents

* upload initialization;
* presigned S3 upload;
* document/version;
* document status;
* download;
* delete;
* RabbitMQ job.

### Milestone 5 — Marker

* marker-worker;
* S3 download;
* conversion;
* artifact upload;
* RabbitMQ events;
* retry/DLQ.

### Milestone 6 — GPU orchestration

* queue monitoring;
* GPU provider API;
* start/stop;
* heartbeat;
* scale threshold;
* idle shutdown.

### Milestone 7 — AI

* Markdown parser;
* document classification;
* structured extraction;
* Pydantic validation;
* PostgreSQL persistence;
* embeddings;
* Qdrant.

### Milestone 8 — Specialist

* specialist profile;
* organizations;
* memberships;
* patient access grants;
* medical record access;
* encounter creation;
* specialist document upload.

### Milestone 9 — Analytics

* observations;
* trends;
* timeline;
* basic charts/API;
* AI summaries.

### Milestone 10 — Security/production

* audit logs;
* rate limiting;
* encryption;
* backups;
* monitoring;
* alerting;
* retention;
* access reviews;
* disaster recovery.

---

# 35. Самый первый vertical slice

Я бы не начинал с реализации всех моделей.

Первый end-to-end сценарий должен быть:

```text
Register
   ↓
Login
   ↓
Create Patient
   ↓
Create Medical Record
   ↓
Upload PDF
   ↓
S3
   ↓
RabbitMQ
   ↓
Marker
   ↓
Markdown
   ↓
AI extraction
   ↓
PostgreSQL
   ↓
Qdrant
   ↓
GET /medical-record
   ↓
User sees extracted result
```

Если этот путь работает — у вас уже есть **ядро продукта**.

Затем:

```text
Patient
   ↓
grant access
   ↓
Specialist
   ↓
view medical record
   ↓
create encounter
   ↓
upload document
   ↓
same pipeline
```

И только после этого я бы делал полноценную аналитику.

---

## 36. Самое важное архитектурное решение

Я бы зафиксировал четыре принципа перед началом кодирования:

**1. PostgreSQL — source of truth.**

```text
medical data → PostgreSQL
```

**2. S3 — source of binary artifacts.**

```text
PDF/images/Markdown/JSON → S3
```

**3. Qdrant — search/index layer.**

```text
embeddings/chunks → Qdrant
```

**4. RabbitMQ — transport, а не database.**

```text
commands/events → RabbitMQ
```

И пятый:

**5. AI не является source of truth.**

AI предлагает структурированные данные:

```text
Document
   ↓
AI
   ↓
Pydantic validation
   ↓
Domain rules
   ↓
PostgreSQL
```

Это особенно важно для медицинского продукта.

---

### И я бы добавил ещё один архитектурный уровень

Не смешивать **"документ"** и **"медицинское событие"**.

Например:

```text
consultation.pdf
```

— это документ.

А:

```text
2026-08-17
Consultation with cardiologist
Diagnosis: ...
Blood pressure: ...
Recommendation: ...
```

— это медицинское событие/данные.

Один `Encounter` может иметь 5 документов, а один документ может быть источником десятков `Observations`.

Именно это разделение позволит в будущем получить нормальную **электронную медицинскую карту**, а не просто "папку с PDF, которую AI умеет искать".
