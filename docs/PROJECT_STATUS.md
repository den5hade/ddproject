# Текущее состояние проекта
## Медицинская платформа персональной медицинской истории

**Версия документа:** 1.0  
**Дата:** 4 сентября 2026  
**Статус:** актуальный снимок проекта  
**Назначение:** зафиксировать, на какой стадии фактически находится проект, что уже реализовано, что спроектировано, но ещё не реализовано, и какие продуктовые возможности должны стать следующим этапом развития.

---

# 1. Executive Summary

Проект уже находится **не на стадии концепции и не на стадии чистого технического прототипа**.

На текущий момент реализован значительный фундамент платформы:

- разделены `Account`, `Person`, `Patient` и `Specialist`;
- реализована ролевая модель;
- реализованы организации и membership;
- реализована сущность `MedicalRecord`;
- реализованы медицинские документы и их версии;
- реализованы `Encounter`;
- реализованы processing jobs;
- реализована модель структурированных extraction-данных;
- реализован контроль доступа к медицинской карте;
- реализован audit log;
- реализован полноценный development document-processing pipeline;
- реализована генерация `canonical.json`;
- `canonical.json` является source of truth;
- реализована Pydantic-валидация;
- реализована детерминированная генерация `structured.md`;
- реализована передача metadata через события;
- реализовано хранение canonical data в PostgreSQL;
- реализованы API для получения structured/canonical данных;
- реализована контейнеризация `ai-worker` для development environment.

То есть сегодня проект уже имеет **работающее техническое ядро для сценария "медицинский документ → структурированные медицинские данные"**.

Документ обработки прямо фиксирует, что canonical pipeline A–F завершён, а затем был добавлен отдельный API endpoint для canonical data и Docker/Compose-поддержка для `ai-worker`.

Одновременно продукт в целом ещё не достиг состояния законченного медицинского кабинета.

Основные ещё не завершённые продуктовые части:

- полноценный пользовательский frontend;
- завершённый UX регистрации/login через email/phone OTP;
- полноценный client document cabinet;
- UI управления доступом;
- полноценный specialist workflow;
- полноценный organisation workflow;
- передача документов от организации клиенту;
- notifications;
- нормализованная медицинская модель `observations / diagnoses / medications`;
- полноценная медицинская история поверх документов;
- расширенная аналитика;
- AI-анализ продольной медицинской истории;
- specialist AI assistant.

Таким образом, наиболее точное определение текущей стадии:

> **Проект находится на стадии формирования и реализации MVP-фундамента с уже работающим вертикальным document-processing pipeline. Backend/domain foundation в значительной степени сформирован; следующий основной этап — превратить это ядро в законченный пользовательский продукт и реализовать взаимодействие Client ↔ Specialist ↔ Organisation.**

---

# 2. Какой продукт мы строим

Платформа предназначена для создания **персональной цифровой медицинской истории человека**, в которой медицинские документы и данные могут поступать из разных источников.

Основная идея:

```text
                 ┌─────────────────────┐
                 │      CLIENT         │
                 │ владелец истории    │
                 └──────────┬──────────┘
                            │
                            ▼
                 ┌─────────────────────┐
                 │   MEDICAL HISTORY   │
                 │                     │
                 │ Documents           │
                 │ Encounters          │
                 │ Lab results         │
                 │ Diagnoses           │
                 │ Prescriptions       │
                 │ Studies             │
                 └──────────┬──────────┘
                            │
             ┌──────────────┼──────────────┐
             │              │              │
             ▼              ▼              ▼
        ORGANISATION    SPECIALIST      CLIENT
        клиника/лаборатория врач        сам загрузил
```

В перспективе система должна перейти от модели:

> «хранилище медицинских файлов»

к модели:

> **«единая персональная медицинская история»**.

Это важнейшее продуктовое направление проекта.

---

# 3. Что изменилось по сравнению с первоначальной концепцией

Первоначально проект можно было описать примерно так:

```text
User
  ↓
Documents
  ↓
PDF processing
  ↓
AI
```

Сейчас модель существенно глубже:

```text
Account
  ↓
Person
  ├── Patient
  │     ↓
  │   MedicalRecord
  │     ├── Documents
  │     ├── Encounters
  │     ├── DocumentVersions
  │     ├── ProcessingJobs
  │     └── DocumentExtractions
  │
  └── Specialist
        ↓
      OrganizationMembership
```

При этом доступ к медицинской информации теперь является отдельным доменом:

```text
Patient
   │
   └── PatientAccessGrant
             │
             ├── account
             ├── organization
             ├── can_view_documents
             ├── can_upload_documents
             ├── can_view_extractions
             ├── can_view_analytics
             ├── can_create_encounters
             └── can_edit_medical_data
```

Это уже гораздо ближе к полноценной медицинской платформе, чем к обычному document-management приложению.

---

# 4. Фактическое состояние доменной модели

## 4.1 Account

Техническая учётная запись пользователя уже отделена от медицинской сущности человека.

Реализованы:

- `accounts`;
- email;
- phone;
- normalized email;
- E.164 phone;
- verification timestamps;
- account status;
- `person_id`;
- login metadata.

Существуют состояния:

```text
pending
active
blocked
deleted
```

Email и phone имеют отдельные normalized identity-представления.

Это важное архитектурное решение на уровне домена:

> Account отвечает за идентичность и доступ, Person — за человека.

---

# 5. Person

`Person` является физическим лицом.

В модели уже присутствуют:

- first name;
- last name;
- middle name;
- date of birth;
- sex.

При этом один `Person` потенциально может одновременно иметь несколько ролей.

Например:

```text
Person
 ├── Patient
 └── Specialist
```

Это уже реализовано в модели.

Это позволяет не связывать медицинскую роль непосредственно с аккаунтом.

---

# 6. Patient

`Patient` является отдельной медицинской сущностью.

Реализованы:

- `id`;
- `person_id`;
- medical record number;
- status.

То есть:

```text
Account
   ↓
Person
   ↓
Patient
   ↓
MedicalRecord
```

Медицинская карта не является аккаунтом пользователя.

Это зафиксировано непосредственно в модели: `Patient → MedicalRecord` является отношением 1:1.

---

# 7. Specialist

Специалист уже выделен в отдельную доменную сущность.

Реализованы:

- `Specialist`;
- `Specialty`;
- `SpecialistSpecialty`.

Поддерживается ситуация, когда специалист имеет несколько специализаций.

Например:

```text
Specialist
 ├── cardiology
 ├── internal_medicine
 └── diagnostics
```

Модель specialist уже существует, но полноценный пользовательский workflow специалиста ещё является следующим продуктовым этапом.

---

# 8. Organisation

Организация уже является отдельной сущностью.

Поддерживаются типы:

```text
clinic
hospital
private_practice
laboratory
```

Также существует:

```text
OrganizationMembership
```

то есть специалист/пользователь может быть членом организации.

Это позволяет строить модель:

```text
Organisation
   │
   ├── Specialists
   ├── Staff
   └── Patients / medical interactions
```

В текущей БД организации и membership уже реализованы.

Это означает, что организация больше не является просто metadata у документа.

Она уже стала самостоятельным доменом продукта.

---

# 9. MedicalRecord

`MedicalRecord` является центральной медицинской сущностью.

Модель:

```text
Patient
   │
   └── MedicalRecord
          ├── Documents
          ├── Encounters
          └── Medical Data
```

Это одно из наиболее важных решений текущей модели.

Medical Record отделён от Account и Person.

Следовательно, проект уже готов к дальнейшему переходу от document-centric модели к полноценной medical-history модели.

---

# 10. Documents

Документ является одним из уже реализованных центральных объектов.

Поддерживаются типы:

```text
lab_result
doctor_report
prescription
discharge_summary
imaging_report
referral
medical_certificate
other
```

Документ содержит:

- medical record;
- encounter;
- document type;
- title;
- original filename;
- MIME type;
- storage key;
- size;
- status;
- uploader.

Особенно важен `uploaded_by_account_id`.

Это означает:

> пациент и человек, который загрузил документ, — не обязательно одно лицо.

Например:

```text
Patient = Иван
Uploaded by = Doctor
```

Это полностью соответствует будущему сценарию, когда врач или организация добавляет документ в медицинскую историю пациента.

---

# 11. Document Versioning

Документы уже имеют версионность.

```text
Document
 ├── Version 1
 ├── Version 2
 └── Version 3
```

Каждая версия содержит:

- S3 key;
- MIME type;
- size;
- checksum;
- creator;
- creation timestamp.

Версия уникальна внутри документа.

Это особенно важно для медицинских документов, поскольку содержимое должно иметь историю изменений.

Модель `DocumentVersion` уже реализована.

---

# 12. Encounter

`Encounter` уже присутствует как самостоятельная медицинская сущность.

Поддерживаются:

```text
consultation
follow_up
procedure
admission
telemedicine
other
```

Статусы:

```text
scheduled
in_progress
completed
cancelled
no_show
```

Также есть:

- specialist;
- organisation;
- reason;
- summary;
- start/end time.

Это означает, что модель уже способна представить:

```text
Patient
   ↓
Encounter
   ↓
Specialist
   ↓
Organisation
   ↓
Documents
```

То есть фундамент для сценария «врач принимает пациента и добавляет результаты визита» уже существует.

---

# 13. Processing Jobs

Обработка документов также уже представлена отдельной сущностью.

`DocumentProcessingJob` поддерживает:

```text
pdf_conversion
ai_extraction
embedding
```

и состояния:

```text
queued
running
succeeded
retrying
failed
```

Есть:

- attempts;
- started_at;
- finished_at;
- error_code;
- error_message.

Таким образом, processing уже рассматривается не как одно действие, а как самостоятельный lifecycle.

---

# 14. Document Extraction

`DocumentExtraction` — важнейшая часть текущего состояния проекта.

В ней хранятся:

- schema name;
- schema version;
- extraction status;
- structured data;
- confidence;
- timestamps.

Главный принцип:

> структурированные медицинские данные живут в PostgreSQL, а поисковый индекс не является source of truth.

Это прямо зафиксировано в текущей модели.

---

# 15. Canonical Pipeline

Это сейчас одна из наиболее зрелых частей проекта.

Фактически реализован pipeline:

```text
PDF
 ↓
images / document conversion
 ↓
marker.md
 ↓
LLM extraction
 ↓
canonical.json
 ↓
Pydantic validation
 ↓
structured.md
 ↓
PostgreSQL document_extractions
```

В текущем implementation plan этот pipeline уже отмечен как полностью реализованный для phases A–F.

---

# 16. canonical.json

На текущем этапе принято ключевое решение:

> `canonical.json` является единственным source of truth для структурированного результата обработки.

LLM не должен создавать финальный Markdown как источник данных.

Правильная модель:

```text
LLM
 ↓
canonical JSON
 ↓
validation
 ↓
rendering
 ↓
Markdown
```

а не:

```text
LLM
 ↓
Markdown
 ↓
парсинг Markdown
```

Это значительно повышает предсказуемость дальнейшей системы.

---

# 17. Pydantic Validation

После LLM extraction данные проходят через Pydantic schema.

Сейчас уже существует package:

```text
packages/canonical
```

с:

- schema registry;
- BaseCanonical;
- LaboratoryCanonical;
- PrescriptionCanonical;
- GenericCanonical;
- `build_canonical`;
- deterministic rendering;
- metadata model.

Phase A полностью завершена.

Это означает, что проект уже имеет отдельный слой canonical data contract.

---

# 18. Типизированные медицинские документы

На текущем этапе существуют специализированные canonical schemas.

## Laboratory

Поддерживаются поля результатов:

```text
name
value
unit
reference_min
reference_max
flagged
```

## Prescription

Поддерживаются:

```text
medication
dosage
frequency
duration
doctor
issued_at
```

## Generic

Для ещё не нормализованных типов используется generic schema.

В pipeline уже реализовано сопоставление:

```text
lab_result
    ↓
laboratory

prescription
    ↓
prescription

other
    ↓
default
```

Это значит, что система уже движется от generic document extraction к document-type-specific extraction.

---

# 19. Structured Markdown

`structured.md` теперь является не источником истины, а **детерминированным представлением canonical data**.

Модель:

```text
canonical.json
       │
       ├── PostgreSQL
       │
       └── structured.md
```

Это правильная концептуальная граница.

Она позволяет в дальнейшем:

- менять renderer;
- добавлять новые представления;
- строить UI непосредственно из canonical data;
- строить analytics непосредственно из canonical data;
- не зависеть от Markdown как от базы данных.

---

# 20. Metadata и Provenance

В pipeline уже предусмотрен YAML frontmatter.

В metadata входят:

```yaml
doc_id
type
subtype

document:
  language
  document_date
  uploaded_at
  page_count

source:
  type
  mime_type
  filename
  sha256
  object_key

processing:
  pipeline_version
  extraction:
    model
    prompt_version
    schema
    schema_version
    tokens

validation:
  status
  schema_valid
  warnings
  validated_at
```

Особенно важно, что metadata формируется Python/system layer, а не доверяется LLM.

Это создаёт основу для воспроизводимости обработки.

---

# 21. API для Canonical Data

Canonical data уже доступен не только внутри processing pipeline.

Реализован:

```text
GET /documents/{id}/canonical
```

Он получает последний успешный extraction из `document_extractions`.

То есть для чтения canonical data не требуется каждый раз обращаться к object storage.

Также canonical data уже был интегрирован в существующий document endpoint.

---

# 22. Document Processing — фактический end-to-end flow

На текущий момент реализованный flow выглядит так:

```text
ACCOUNT API
    │
    │ upload
    ▼
document.upload.requested
    │
    ▼
OBJECT STORAGE WORKER
    │
    │ store original
    ▼
document.stored
    │
    ▼
ACCOUNT API
    │
    │ document → PROCESSING
    │
    ▼
document.uploaded
    │
    ▼
AI WORKER
    │
    ├── conversion
    │       ↓
    │    marker.md
    │
    └── structuring
            ↓
        LLM extraction
            ↓
        canonical.json
            ↓
        Pydantic validation
            ↓
        structured.md
            ↓
        document.analysis.completed
            │
            ▼
       ACCOUNT API
            │
            ▼
 document_extractions.data
            │
            ▼
        COMPLETED
```

Этот flow уже является реализованным, а не только проектной схемой.

---

# 23. Состояния Document

У документа уже существует lifecycle:

```text
PENDING
   ↓
PROCESSING
   ↓
COMPLETED
```

или:

```text
PENDING
   ↓
PROCESSING
   ↓
FAILED
```

При этом document status изменяется централизованно в account-api, а worker не должен самостоятельно менять статус документа.

Это зафиксировано как отдельный invariant текущего pipeline.

---

# 24. Access Control

Доступ к медицинской информации уже не сводится только к роли пользователя.

В проекте реализована отдельная сущность:

```text
PatientAccessGrant
```

Она содержит permissions:

```text
can_view_documents
can_upload_documents
can_view_extractions
can_view_analytics
can_create_encounters
can_edit_medical_data
```

Также поддерживаются:

- active/revoked/expired;
- expiration;
- reason;
- кто выдал доступ;
- организация.

То есть реализована более глубокая модель:

```text
Role
+
Patient-specific Grant
```

а не:

```text
if role == doctor:
    access everything
```

Это принципиально важно для медицинского продукта.

---

# 25. RBAC

Реализована ролевая модель.

Основные роли:

```text
client
specialist
organization_admin
system_admin
support
```

Есть:

```text
Role
Permission
AccountRole
RolePermission
```

Permissions уже включают:

```text
medical_record.read
medical_record.write
document.read
document.upload
document.download
encounter.read
encounter.create
encounter.update
analytics.read
user.manage
organization.manage
```

Таким образом, RBAC-фундамент уже создан.

---

# 26. Audit

Audit log уже присутствует в модели.

Фиксируются действия вроде:

```text
LOGIN
LOGOUT
VIEW_PATIENT
VIEW_MEDICAL_RECORD
VIEW_DOCUMENT
DOWNLOAD_DOCUMENT
UPLOAD_DOCUMENT
CREATE_ENCOUNTER
UPDATE_ENCOUNTER
GRANT_ACCESS
REVOKE_ACCESS
VIEW_ANALYTICS
```

Это особенно важно для будущего specialist/organisation workflow.

Audit уже является частью текущей модели, а не будущей концепцией.

---

# 27. Что уже можно считать реализованным MVP-фундаментом

На основании текущих документов можно уверенно считать реализованными следующие части.

| Область | Состояние |
|---|---|
| Account model | ✅ Реализовано |
| Person model | ✅ Реализовано |
| Patient model | ✅ Реализовано |
| Specialist model | ✅ Реализовано |
| Organisation model | ✅ Реализовано |
| Organisation membership | ✅ Реализовано |
| RBAC | ✅ Реализовано |
| Medical Record | ✅ Реализовано |
| Encounter | ✅ Реализовано |
| Document | ✅ Реализовано |
| Document Version | ✅ Реализовано |
| Processing Job | ✅ Реализовано |
| Document Extraction | ✅ Реализовано |
| Patient Access Grant | ✅ Реализовано |
| Audit Log | ✅ Реализовано |
| Marker/document conversion flow | ✅ Реализовано |
| LLM extraction | ✅ Реализовано |
| canonical.json | ✅ Реализовано |
| Pydantic validation | ✅ Реализовано |
| structured.md | ✅ Реализовано |
| Canonical metadata | ✅ Реализовано |
| Canonical persistence | ✅ Реализовано |
| Canonical API | ✅ Реализовано |
| ai-worker container | ✅ Реализовано |

Текущий implementation plan подтверждает завершение всех основных перечисленных processing phases.

---

# 28. Что уже спроектировано, но ещё не является полноценной функциональностью продукта

Здесь находится следующий большой слой.

## 28.1 Client experience

Необходимо превратить существующее backend-ядро в полноценный пользовательский сценарий:

```text
Registration
   ↓
OTP login
   ↓
Client cabinet
   ↓
Medical Record
   ↓
Documents
   ↓
Document details
   ↓
Structured medical data
   ↓
Analytics
```

Backend-модель для этого уже во многом подготовлена.

---

# 29. Specialist workflow

На уровне данных фундамент уже существует:

```text
Specialist
   ↓
Organisation
   ↓
Patient
   ↓
AccessGrant
   ↓
MedicalRecord
   ↓
Encounter
   ↓
Documents
```

Следующий этап — полноценный workflow:

```text
Doctor opens patient
        ↓
sees permitted medical history
        ↓
opens documents
        ↓
creates encounter
        ↓
adds conclusion/document
        ↓
document becomes part of patient history
```

То есть проблема теперь уже не в отсутствии доменной основы.

Основная задача — реализовать полноценный product workflow поверх неё.

---

# 30. Organisation workflow

Организация должна иметь два основных сценария.

## Сценарий A — источник документа

```text
Organisation
      ↓
patient identification
      ↓
document submission
      ↓
platform
      ↓
processing
      ↓
patient notification
```

## Сценарий B — рабочее пространство

```text
Organisation
      ↓
Staff / Specialists
      ↓
Patients
      ↓
Medical Records
      ↓
Encounters
      ↓
Documents
```

База данных уже содержит Organization и OrganizationMembership, поэтому этот сценарий концептуально поддержан.

---

# 31. Patient Access

Модель доступа уже значительно глубже MVP-флажка.

Но пользовательский продукт должен дать возможность:

```text
Client
  ↓
Access management
  ├── give access
  ├── view active access
  ├── revoke access
  └── set permissions
```

Специалист в свою очередь должен видеть только разрешённый объём истории.

Это должно стать одной из центральных функций Client Cabinet.

---

# 32. Notification Layer

В продуктовой концепции notification является отдельным доменом.

Ключевой сценарий:

```text
Organisation
   ↓
new document
   ↓
platform
   ↓
notification
   ↓
Client
```

При этом notification не должна раскрывать медицинское содержимое.

Например, пользователь должен получить сообщение уровня:

> «В вашей медицинской истории появился новый документ.»

а не:

> «Ваш анализ крови показал ...»

Notification domain ещё не представлен среди реализованных таблиц текущей DB-модели, поэтому эту часть следует считать следующим продуктовым этапом.

---

# 33. Нормализованные медицинские данные

Это следующий большой переход.

Сейчас:

```text
Document
   ↓
canonical JSON
```

Следующий уровень:

```text
canonical JSON
      ↓
normalization
      ↓
medical entities
```

В частности:

```text
observations
diagnoses
medications
```

Сейчас эти таблицы обозначены как `DEFERRED`.

---

# 34. Observations

`observations` должны стать основой аналитики.

Например:

```text
Hemoglobin
2025-01-10 → 132
2025-05-12 → 138
2026-01-04 → 141
```

Или:

```text
Glucose
2025-01 → ...
2025-06 → ...
2026-01 → ...
```

Таким образом:

```text
Document
   ↓
Canonical
   ↓
Observation
   ↓
Time series
   ↓
Analytics
```

Именно здесь продукт начнёт превращаться из document storage в medical history platform.

---

# 35. Diagnoses

Следующий слой:

```text
Diagnosis
```

с потенциальными:

- code system;
- code;
- name;
- onset;
- resolved;
- source document;
- source encounter.

Это позволит в дальнейшем строить longitudinal history.

---

# 36. Medications

Аналогично:

```text
Medication
```

может представлять:

- препарат;
- active ingredient;
- dosage;
- frequency;
- start date;
- end date;
- source document.

Это даст возможность строить историю лечения независимо от конкретного PDF.

---

# 37. Consents

Отдельно запланированы:

```text
PatientConsent
```

с purpose:

```text
CONSULTATION
DOCUMENT_ACCESS
AI_ANALYSIS
DATA_SHARING
```

Это важно концептуально отделять от технического `AccessGrant`.

То есть:

```text
Access
≠
Consent
```

`AccessGrant` отвечает за возможность действия.

`Consent` — за отдельный смысл/основание согласия.

В текущей модели consent ещё не создан и находится в deferred.

---

# 38. Analytics

Сегодня фундамент аналитики уже подготовлен:

```text
Document
 ↓
Canonical
 ↓
Structured data
```

Но полноценный analytics layer требует:

```text
Canonical
 ↓
Normalization
 ↓
Observations
 ↓
Time series
 ↓
Analytics
```

Поэтому текущую аналитику правильнее рассматривать как **следующий продуктовый слой**, а не как часть document processing pipeline.

---

# 39. AI

AI уже используется для extraction.

Но это ещё не тот AI-продукт, который является конечной ценностью платформы.

Сегодня:

```text
AI
 ↓
extract data from document
```

В будущем:

```text
AI
 ↓
understand longitudinal medical history
 ↓
summarize
 ↓
find trends
 ↓
answer questions
 ↓
prepare patient for consultation
 ↓
assist specialist
```

То есть AI сейчас является прежде всего **processing capability**, а в будущем должен стать **product capability**.

Это принципиально разные стадии.

---

# 40. Разница между текущим AI и будущим AI

## Сейчас

```text
PDF
 ↓
AI
 ↓
canonical JSON
```

AI отвечает на вопрос:

> «Что написано в этом документе?»

## В будущем

```text
Medical History
       ↓
AI
       ↓
Longitudinal understanding
       ↓
Trends
       ↓
Summary
       ↓
Questions
       ↓
Specialist assistance
```

AI будет отвечать на вопрос:

> «Что происходит с медицинской историей этого человека во времени?»

Именно второй сценарий является долгосрочной продуктовой целью.

---

# 41. Что является настоящим Source of Truth

В проекте сейчас появляется правильная многоуровневая модель.

## Original document

Источник первичной информации.

```text
PDF / JPEG / PNG
```

## canonical.json

Источник структурированного представления конкретного документа.

```text
canonical.json
```

## PostgreSQL

Источник состояния системы и structured medical data.

```text
documents
document_versions
document_extractions
medical_records
encounters
...
```

## structured.md

Читаемое представление canonical data.

## Search/vector index

В будущем — индекс для поиска/retrieval, но не source of truth.

Эта граница уже явно закреплена в текущей модели.

---

# 42. Текущий уровень зрелости проекта

Если разделить проект на несколько уровней, получится следующая картина.

| Уровень | Состояние |
|---|---|
| Product concept | ✅ Сформирован |
| Domain model | ✅ Сформирован |
| Database model | 🟢 Реализован в значительной степени |
| Document lifecycle | 🟢 Реализован |
| Document versioning | 🟢 Реализован |
| Access model | 🟢 Реализован |
| Processing pipeline | 🟢 Реализован |
| Canonical data model | 🟢 Реализован |
| AI extraction | 🟢 Реализован |
| Structured representation | 🟢 Реализован |
| Client product UX | 🟡 В развитии |
| Specialist workflow | 🟡 Основа есть, workflow требует реализации |
| Organisation workflow | 🟡 Основа есть, workflow требует реализации |
| Notifications | 🟡 Следующий этап |
| Medical normalization | 🟡 Спроектировано |
| Analytics | 🟡 Следующий этап |
| Longitudinal AI | 🔵 Будущее |
| Specialist AI assistant | 🔵 Будущее |

---

# 43. Где проект находится относительно MVP

Важно не считать проект «готовым MVP» только потому, что processing pipeline уже работает.

С точки зрения продукта MVP должен позволять человеку получить законченную ценность.

Минимальный пользовательский сценарий:

```text
User
 ↓
login
 ↓
upload medical document
 ↓
document processed
 ↓
structured data available
 ↓
user views document
 ↓
user sees basic medical information
```

Технический фундамент этого сценария уже существует.

Но полноценный продуктовый MVP должен добавить:

```text
Authentication
+
Client Cabinet
+
Document UX
+
Processing status
+
Structured data UX
+
Medical history
+
Basic analytics
```

Поэтому текущую стадию лучше определить как:

> **MVP backend/domain foundation + working document-processing vertical slice**

а не как полностью завершённый MVP.

---

# 44. Самая важная достигнутая точка

Наиболее существенный результат текущего этапа заключается в том, что проект уже преодолел главный риск первой версии.

Главный риск был:

> «Сможем ли мы надёжно превращать произвольный медицинский документ в структурированные данные, которые можно использовать дальше?»

Теперь pipeline имеет следующую модель:

```text
Original
   ↓
Marker
   ↓
LLM
   ↓
Canonical
   ↓
Validation
   ↓
Persistence
   ↓
API
```

То есть extraction больше не является одноразовой AI-операцией.

Он стал частью формализованного data lifecycle.

---

# 45. Что особенно важно не потерять дальше

На следующем этапе не следует возвращаться к модели:

```text
User
 ↓
PDF
 ↓
Markdown
```

Проект уже вырос из неё.

Правильная модель:

```text
Person
 ↓
Patient
 ↓
MedicalRecord
 ↓
Medical Data
```

где документы являются одним из источников медицинской информации.

---

# 46. Текущая conceptual model

Сегодня проект можно описать так:

```text
                           PLATFORM
                               │
          ┌────────────────────┼────────────────────┐
          │                    │                    │
          ▼                    ▼                    ▼
       CLIENT             SPECIALIST          ORGANISATION
          │                    │                    │
          │                    │                    │
          └──────────────┬─────┴────────────────────┘
                         │
                         ▼
                       PATIENT
                         │
                         ▼
                   MEDICAL RECORD
                         │
              ┌──────────┼──────────┐
              │          │          │
              ▼          ▼          ▼
          DOCUMENT    ENCOUNTER   MEDICAL DATA
              │                       │
              │                       ├── Observations
              │                       ├── Diagnoses
              │                       └── Medications
              │
              ▼
        DOCUMENT VERSION
              │
              ▼
       DOCUMENT PROCESSING
              │
              ▼
          MARKER DATA
              │
              ▼
         AI EXTRACTION
              │
              ▼
        CANONICAL JSON
              │
              ▼
          VALIDATION
              │
        ┌─────┴──────┐
        ▼            ▼
   STRUCTURED MD   DATABASE
```

---

# 47. Следующий основной этап

Следующий этап проекта должен быть не «ещё больше infrastructure».

Он должен быть направлен на **productization уже созданного ядра**.

Приоритет:

```text
1. Client experience
2. Document experience
3. Processing experience
4. Specialist workflow
5. Organisation workflow
6. Notifications
7. Medical normalization
8. Analytics
```

---

# 48. Следующая продуктовая вертикаль

Рекомендуемый следующий законченный vertical slice:

```text
CLIENT
  ↓
Login
  ↓
Medical Record
  ↓
Upload document
  ↓
Processing
  ↓
Canonical data
  ↓
Document details
  ↓
Structured medical information
  ↓
Basic analytics
```

Этот сценарий должен быть полностью завершён от UI до БД.

После него:

```text
SPECIALIST
  ↓
patient access
  ↓
medical record
  ↓
encounter
  ↓
upload document
  ↓
patient history
```

И только после этого:

```text
ORGANISATION
  ↓
patient delivery
  ↓
notification
  ↓
client
```

---

# 49. Recommended Product Roadmap From Current State

## Stage 1 — Current foundation

**Статус: преимущественно завершён**

```text
Account
Person
Patient
Specialist
Organisation
MedicalRecord
Documents
Versions
Encounters
Access
RBAC
Audit
Processing
Canonical
Extraction
Persistence
API
```

---

## Stage 2 — Client MVP

**Следующий приоритет**

```text
Authentication
   ↓
Client dashboard
   ↓
Medical Record
   ↓
Documents
   ↓
Upload
   ↓
Processing status
   ↓
Document details
   ↓
Canonical data
   ↓
Basic analytics
```

---

## Stage 3 — Specialist

```text
Specialist profile
   ↓
Organisation membership
   ↓
Patient access
   ↓
Patient search
   ↓
Medical record
   ↓
Encounters
   ↓
Document upload
   ↓
Medical history
```

---

## Stage 4 — Organisation

```text
Organisation workspace
   ↓
Staff
   ↓
Patients
   ↓
Document submission
   ↓
Patient matching
   ↓
New patient/account flow
   ↓
Document processing
   ↓
Notification
```

---

## Stage 5 — Medical Data Layer

```text
Canonical
   ↓
Normalization
   ├── Observations
   ├── Diagnoses
   └── Medications
```

После этого Medical Record станет не просто коллекцией документов.

---

## Stage 6 — Analytics

```text
Observations
   ↓
Time series
   ↓
Trends
   ↓
Simple analytics
```

Первый analytics MVP должен быть максимально простым и объяснимым.

---

## Stage 7 — Longitudinal AI

```text
Medical History
   ↓
AI
   ↓
Longitudinal summary
   ↓
Trends
   ↓
Questions
   ↓
Preparation for consultation
```

---

## Stage 8 — Specialist AI

```text
Patient history
      ↓
AI
      ↓
Clinical context
      ↓
Summary
      ↓
Relevant history
      ↓
Potential questions / signals
      ↓
Specialist decision support
```

---

# 50. Что НЕ следует считать текущей задачей

На текущей стадии не нужно пытаться одновременно реализовать весь будущий vision.

Не стоит сейчас делать главным приоритетом:

- сложную AI-диагностику;
- полноценного AI doctor;
- сложную vector-search систему;
- сложный clinical decision support;
- все возможные типы медицинских сущностей;
- все возможные типы медицинских организаций;
- максимальную детализацию аналитики.

Текущий фундамент уже позволяет развивать продукт постепенно.

---

# 51. Главная граница текущего этапа

Проект сейчас находится на переходе:

```text
TECHNICAL FOUNDATION
        │
        ▼
DOCUMENT PROCESSING PLATFORM
        │
        ▼
USER PRODUCT
```

Первая часть уже значительно реализована.

Теперь основной вопрос проекта меняется.

Раньше:

> «Как обработать документ?»

Теперь:

> **«Как превратить обработанный документ в полезную персональную медицинскую историю для пользователя, врача и организации?»**

Это и есть следующий большой этап.

---

# 52. Итоговая оценка

На основании текущих документов проект можно оценить следующим образом.

### Product/domain

**Сформирован хорошо.**

Основные участники, сущности и отношения уже определены:

```text
Client
Specialist
Organisation
Patient
MedicalRecord
Document
Encounter
Access
```

### Data model

**Находится на высокой степени готовности для текущего MVP.**

Реализована значительно более зрелая модель:

```text
Account
→ Person
→ Patient/Specialist
→ MedicalRecord
→ Documents/Encounters
→ Processing/Extraction
```

Фактически это уже подтверждается реализованной migration/model structure.

### Document processing

**Наиболее зрелая часть проекта.**

Canonical pipeline A–F завершён, а затем дополнен canonical API и containerized ai-worker.

### Access/security foundation

**Хорошо заложен на уровне domain model.**

Есть:

```text
RBAC
+
PatientAccessGrant
+
AuditLog
```

### Medical data

**Начальная стадия.**

Canonical data уже существует, но полноценная нормализованная medical data model ещё впереди.

### Product UX

**Следующий крупный этап.**

Именно здесь backend foundation должен превратиться в законченный пользовательский продукт.

### Analytics

**Подготовлена база, но полноценный слой ещё впереди.**

### AI

**Extraction уже реализован.**

Longitudinal medical AI пока является будущей функциональностью.

---

# 53. Финальное определение текущей стадии

Наиболее корректное название текущего состояния:

> ## Stage: MVP Foundation / Document Intelligence Core

или по-русски:

> ## Стадия: фундамент MVP и ядро интеллектуальной обработки медицинских документов

Проект уже прошёл стадии:

```text
Идея
  ↓
Концепция
  ↓
Domain design
  ↓
Database foundation
  ↓
Document processing prototype
  ↓
Canonical data pipeline
  ↓
Working processing core
  ↓
★ ТЕКУЩАЯ СТАДИЯ
```

Следующий переход:

```text
Working processing core
        ↓
Client MVP
        ↓
Specialist workflow
        ↓
Organisation workflow
        ↓
Unified Medical History
        ↓
Analytics
        ↓
Longitudinal AI
```

---

# 54. Главный вывод

Проект уже имеет **достаточно серьёзную основу, чтобы перестать воспринимать его как эксперимент с PDF + LLM**.

Сейчас это уже зачаток полноценной медицинской платформы:

```text
PERSON
   ↓
PATIENT
   ↓
MEDICAL RECORD
   ↓
MEDICAL HISTORY
   ├── Documents
   ├── Encounters
   ├── Structured Data
   ├── Observations
   ├── Diagnoses
   └── Medications
```

А документы стали механизмом поступления медицинской информации:

```text
Client ──────────────┐
                     │
Specialist ──────────┼──→ Medical Record
                     │
Organisation ────────┘
```

При этом текущая реализация уже закрывает один из самых сложных технических участков — надёжное получение структурированного canonical представления документа, его валидацию, сохранение и выдачу через API.

**Следующий шаг поэтому должен быть не пересмотром уже сделанного фундамента, а последовательным построением пользовательских вертикалей поверх него.**

Иными словами:

> **ядро уже построено; теперь проекту нужно превратить это ядро в законченный продукт.**