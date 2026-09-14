# План реализации Organization Domain и API-интеграции медицинских организаций

## 1. Цель этапа

Цель данного этапа — превратить существующую модель `Organization` из базовой доменной сущности в полноценный контур интеграции медицинских организаций с платформой.

Организация должна получить возможность:

1. хранить юридические и регистрационные данные;
2. хранить несколько лицензий;
3. хранить несколько филиалов;
4. управлять API-ключами;
5. отправлять медицинские документы в платформу напрямую из собственной инфраструктуры;
6. отправлять документы как единично, так и bulk;
7. указывать тип медицинского документа;
8. в будущем создавать собственные схемы документов;
9. отправлять документ пациенту по email;
10. автоматически создавать пациента, если его ещё нет в платформе;
11. получать статус обработки документов;
12. видеть статистику и аудит использования API;
13. в будущем проходить автоматическую проверку организации по государственному реестру медицинских организаций.

При этом существующий пользовательский сценарий клиента не должен ломаться.

---

# 2. Текущее состояние, от которого начинаем

На данный момент в проекте уже существуют:

* `Organization`;
* `OrganizationMembership`;
* `organization_admin` role;
* связь `Encounter → Organization`;
* `Document`;
* `DocumentVersion`;
* `DocumentExtraction`;
* `DocumentProcessingJob`;
* RBAC;
* `PatientAccessGrant`;
* `AuditLog`;
* RabbitMQ;
* S3;
* document processing pipeline;
* canonical extraction;
* PostgreSQL persistence.

То есть нам **не нужно строить организационный домен с нуля**.

Текущий проект уже имеет рабочий client vertical slice:

```text
OTP
 ↓
Client
 ↓
Document upload
 ↓
S3
 ↓
AI processing
 ↓
canonical.json
 ↓
PostgreSQL
 ↓
Client cabinet
```

Организационный контур должен добавить второй полноценный vertical slice:

```text
Organization
      ↓
API Key
      ↓
Organization API
      ↓
Patient resolution
      ↓
Document creation
      ↓
S3
      ↓
Processing pipeline
      ↓
canonical.json
      ↓
PostgreSQL
      ↓
Notification
      ↓
Client
```

Текущий статус прямо указывает, что следующий незакрытый слой — `Organisation workflow + доставка документов + notifications`.

---

# 3. Главное архитектурное решение

Не стоит превращать `organizations` в огромную таблицу.

Предлагаемая модель:

```text
Organization
│
├── OrganizationBranch
│
├── OrganizationLicense
│
├── OrganizationApiKey
│
├── OrganizationDocumentSchema
│
├── OrganizationMembership
│
├── Encounters
│
└── API Usage / Audit
```

То есть:

```text
organizations
    │
    ├── organization_branches
    │
    ├── organization_licenses
    │
    ├── organization_api_keys
    │
    └── organization_document_schemas
```

Это позволит не перегружать `Organization` и даст возможность расширять домен независимо.

---

# 4. Изменение Organization

## 4.1. Текущая модель

Сейчас:

```text
Organization
- id
- name
- type
- status
```

`OrganizationType` уже содержит:

```text
clinic
hospital
private_practice
laboratory
```

Это существующий фундамент.

---

# 5. Новые поля Organization

Предлагается добавить:

```text
Organization
-----------------------------
id
name
type
status

inn
ogrn

legal_address
email
phone
website

created_at
updated_at
```

## 5.1. ИНН

```text
inn VARCHAR(...)
```

Требования:

* нормализованное значение;
* проверка формата;
* unique;
* индекс;
* возможность `NULL` на этапе миграции.

Почему не делать `NOT NULL` сразу:

существующие организации уже могут находиться в БД.

Поэтому миграция:

```text
1. добавить nullable inn
2. заполнить существующие организации
3. добавить unique index
4. после data migration при необходимости сделать NOT NULL
```

Если предполагается поддержка физических лиц/ИП как отдельных типов организации в будущем, правило валидации ИНН лучше сделать domain-level, а не жестко зашить только в SQL.

---

# 6. ОГРН

Добавить:

```text
ogrn VARCHAR(...)
```

Также:

* nullable на первой миграции;
* unique;
* индекс;
* domain validation.

Важно: не смешивать `ИНН` и `ОГРН` в одно поле `registration_number`.

Это разные идентификаторы и в будущем будут использоваться для разных сценариев:

```text
ИНН
    ↓
идентификация организации

ОГРН
    ↓
идентификация юридического лица / регистрационные проверки
```

---

# 7. Юридический адрес

В `Organization` можно хранить:

```text
legal_address TEXT
```

На первом этапе этого достаточно.

Не стоит пока делать сложную адресную модель:

```text
country
region
city
street
house
building
...
```

если эти данные пока не используются отдельно.

Но адрес филиала уже нужно моделировать отдельно.

---

# 8. OrganizationBranch

Одна организация может иметь несколько филиалов.

Поэтому адрес филиала не должен находиться в `organizations`.

Новая таблица:

```text
organization_branches
```

Предлагаемая модель:

```text
OrganizationBranch
-----------------------------
id
organization_id
name
code

address

phone
email

is_active

created_at
updated_at
```

Связь:

```text
Organization 1 ─── N OrganizationBranch
```

Например:

```text
Organization
ООО "Медицинский центр"

    ├── Branch
    │   Москва, ул. Ленина 10
    │
    ├── Branch
    │   Москва, ул. Пушкина 25
    │
    └── Branch
        Санкт-Петербург, Невский проспект 100
```

## 8.1. Зачем нужен `code`

Очень рекомендую добавить:

```text
code VARCHAR(64)
```

Например:

```text
MOSCOW_MAIN
MOSCOW_NORTH
SPB_01
LAB_01
```

Он пригодится API-клиенту:

```json
{
  "branch_code": "SPB_01"
}
```

Это значительно лучше, чем передавать UUID филиала из внешней системы без возможности человеку его сопоставить.

---

# 9. Связь документов с филиалом

Это важное решение.

Если организация отправляет документ:

```text
Organization
    ↓
Branch
    ↓
Patient
    ↓
Document
```

то желательно сохранить источник документа.

Предлагаю добавить в `documents`:

```text
organization_id UUID NULL
organization_branch_id UUID NULL
```

Хотя `organization_id` технически можно вывести через branch, я бы всё равно рассматривал хранение organization как explicit source.

Почему:

1. филиал может быть удалён/деактивирован;
2. документ должен сохранять исторический источник;
3. branch может быть NULL;
4. организации могут отправлять документы из центральной системы без конкретного филиала.

В итоге:

```text
Document
----------------
medical_record_id
encounter_id

uploaded_by_account_id

organization_id
organization_branch_id

document_type
...
```

---

# 10. Лицензии

Лицензию нельзя хранить непосредственно в `Organization`.

Причина:

```text
Organization
    ↓
License #1
License #2
License #3
```

Одна организация может иметь несколько лицензий.

Создать:

```text
organization_licenses
```

---

# 11. OrganizationLicense

Предлагаемая модель:

```text
OrganizationLicense
--------------------------------
id
organization_id

license_number
license_type

issued_at
expires_at

status

issuer_name
issuer_code

scope
metadata

created_at
updated_at
```

Минимально:

```text
id
organization_id
license_number
license_type
issued_at
expires_at
status
created_at
updated_at
```

---

# 12. Почему license_type нужен сразу

Медицинская организация может иметь несколько направлений деятельности.

Например:

```text
License
    стоматология

License
    лабораторная диагностика

License
    терапия

License
    radiology
```

Поэтому:

```text
license_number
```

недостаточно.

Нужно иметь возможность описать:

```text
license_type
```

или в будущем отдельную таблицу:

```text
organization_license_scopes
```

На первом этапе можно оставить:

```text
scope JSONB
```

либо отдельную строку.

Если лицензирование станет важной частью бизнес-логики, тогда перейти к нормализованной модели.

---

# 13. API Keys

Это отдельный security domain.

Не добавлять:

```text
api_key VARCHAR(...)
```

в `organizations`.

Создать:

```text
organization_api_keys
```

---

# 14. OrganizationApiKey

Предлагаемая модель:

```text
OrganizationApiKey
--------------------------------
id
organization_id

name

key_prefix
key_hash

status

created_at
last_used_at
expires_at
revoked_at

created_by_account_id

permissions
```

Например:

```text
organization_api_keys

id
organization_id
name = "Production integration"

key_prefix = "med_prod_8f2a"
key_hash = SHA256(...)
status = active
created_at
last_used_at
expires_at
revoked_at
created_by_account_id
```

---

# 15. API Key никогда не хранить в открытом виде

Это принципиальное решение.

После создания:

```text
API key
    ↓
показывается один раз
    ↓
hash
    ↓
database
```

В БД:

```text
key_hash
```

а не:

```text
key
```

В ответе:

```json
{
  "id": "...",
  "name": "Production",
  "key": "med_prod_xxxxxxxxx"
}
```

после этого полный ключ больше не показывается.

---

# 16. Prefix

Очень желательно хранить:

```text
key_prefix
```

Например:

```text
med_prod_7f21
```

Это позволит:

* быстро идентифицировать ключ;
* показывать его в UI;
* искать ключ;
* не раскрывать секрет.

Например UI:

```text
Production
med_prod_7f21••••••••
Active
Last used: 5 min ago
```

---

# 17. API Key permissions

Не следует делать API key просто:

```text
organization = X
```

Нужна возможность ограничивать его права.

Например:

```text
documents.upload
documents.read
patients.resolve
documents.bulk_upload
schemas.read
schemas.write
```

Но на первой версии можно значительно упростить:

```text
documents.upload
```

и затем расширять.

Главный принцип:

```text
API Key
    ↓
Organization
    ↓
Allowed permissions
```

---

# 18. Важное решение: API Key ≠ пользовательская авторизация

Я бы **не делал API Key обязательным для административных web-endpoints организации**.

Нужно разделить два контура.

## Organization Web API

Для администратора организации:

```text
JWT
+
organization_admin role
+
organization membership
```

Например:

```http
GET /organizations/{id}
POST /organizations/{id}/api-keys
DELETE /organizations/{id}/api-keys/{key_id}
GET /organizations/{id}/licenses
POST /organizations/{id}/licenses
```

## Organization Integration API

Для инфраструктуры медицинской организации:

```text
API Key
```

Например:

```http
POST /api/v1/integration/documents
POST /api/v1/integration/documents/bulk
GET  /api/v1/integration/documents/{id}
GET  /api/v1/integration/jobs/{id}
```

Это принципиально разные сценарии.

---

# 19. Почему нельзя использовать API Key для управления API Keys

Иначе возникает проблема:

```text
API Key
    ↓
создать API Key
    ↓
получить ещё один API Key
```

Это плохая security-модель.

Создание/revoke API keys должен делать:

```text
organization_admin
```

через обычную авторизацию пользователя.

А API key предназначен для:

```text
machine → platform
```

---

# 20. API Key authentication dependency

В FastAPI следует создать отдельную dependency:

```python
get_current_organization_from_api_key()
```

Логика:

```text
Authorization: Bearer <api-key>
             ↓
extract key
             ↓
hash
             ↓
find organization_api_key
             ↓
status == active
             ↓
not expired
             ↓
organization.status == active
             ↓
check permission
             ↓
OrganizationContext
```

Например:

```python
OrganizationAPIContext(
    organization_id=...,
    api_key_id=...,
    permissions={...},
)
```

После этого endpoint не должен самостоятельно разбирать API key.

---

# 21. API Key формат

Рекомендую сразу использовать namespace:

```text
med_live_xxxxxxxxx
med_test_xxxxxxxxx
```

или:

```text
org_live_xxxxxxxxx
org_test_xxxxxxxxx
```

Это позволит в будущем иметь:

```text
test API key
production API key
```

и не смешивать окружения.

---

# 22. Monitoring API Keys

Да, мониторинг использования API key я считаю необходимым.

Но не нужно сразу строить сложную observability-систему.

На первом этапе достаточно:

```text
OrganizationApiKey
    last_used_at
```

и отдельного usage log.

---

# 23. OrganizationApiRequestLog

Создать:

```text
organization_api_requests
```

Например:

```text
id

organization_id
api_key_id

request_id

method
path

status_code

ip_address

user_agent

started_at
finished_at
duration_ms

request_size
response_size

error_code

created_at
```

Не хранить body запроса целиком, потому что там будут медицинские данные.

---

# 24. Что логировать нельзя

Нельзя писать в API monitoring:

```text
email пациента
ФИО пациента
PDF content
canonical JSON
diagnosis
lab values
medical history
```

В monitoring должны попадать:

```text
organization_id
api_key_id
endpoint
status
duration
request_id
timestamp
```

При необходимости:

```text
patient_id
document_id
```

но только если это необходимо для технического аудита и с учётом политики доступа.

---

# 25. Два разных вида audit

Нужно разделить:

### Security Audit

```text
API key created
API key revoked
API key expired
API key authentication failed
```

### API Usage

```text
POST /integration/documents
POST /integration/documents/bulk
GET /integration/jobs/...
```

### Medical Audit

Уже существующий:

```text
AuditLog
```

Он должен продолжить использоваться для действий с медицинскими данными.

В существующей системе `AuditLog` уже существует и содержит actor/resource/patient/IP/user-agent/metadata.

Не нужно превращать `AuditLog` в огромный HTTP access log.

---

# 26. Rate limiting

API Key должен иметь rate limit.

Например:

```text
per API key
per organization
per IP
```

На первом этапе:

```text
100 requests/minute/key
```

но конкретное значение лучше сделать configuration-based.

Для bulk upload:

```text
100 documents/request
```

например.

Важно: rate limit не должен быть захардкожен в endpoint.

---

# 27. Bulk upload

Организация должна иметь два API:

```text
single upload
bulk upload
```

Например:

```http
POST /api/v1/integration/documents
```

и:

```http
POST /api/v1/integration/documents/bulk
```

---

# 28. Не делать bulk upload как один огромный multipart request

Я бы не делал:

```text
POST /documents/bulk

1000 PDF файлов
```

одним синхронным запросом.

Лучше:

```text
POST /documents/bulk
```

создаёт batch.

Ответ:

```json
{
  "batch_id": "...",
  "status": "accepted",
  "total": 150
}
```

Затем:

```text
batch
    ↓
items
    ↓
individual document jobs
```

---

# 29. OrganizationUploadBatch

Создать:

```text
organization_upload_batches
```

Модель:

```text
OrganizationUploadBatch
--------------------------------
id
organization_id
api_key_id

status

total_count
accepted_count
processed_count
failed_count

created_at
started_at
completed_at
```

Статусы:

```text
pending
processing
completed
completed_with_errors
failed
cancelled
```

---

# 30. OrganizationUploadBatchItem

Если batch содержит много документов, нужен item-level status.

```text
organization_upload_batch_items
```

:

```text
id
batch_id

document_id

status

external_id

error_code
error_message

created_at
updated_at
```

Это позволит получить:

```text
Batch 123

100 documents
-------------------
92 completed
5 processing
3 failed
```

---

# 31. External ID

Очень рекомендую добавить:

```text
external_id
```

на уровне integration document/batch item.

Например клиника отправляет:

```json
{
  "external_id": "LAB-2026-000018293"
}
```

Платформа возвращает:

```json
{
  "document_id": "...",
  "external_id": "LAB-2026-000018293"
}
```

Это критически важно для idempotency.

---

# 32. Idempotency

Организация может повторно отправить тот же запрос из-за:

* timeout;
* network failure;
* retry;
* RabbitMQ retry;
* падения своей системы.

Поэтому API должен поддерживать:

```http
Idempotency-Key: <uuid>
```

или комбинацию:

```text
organization_id
+
external_id
```

Рекомендую поддержать оба механизма.

---

# 33. Поток single upload

Предлагаемый workflow:

```text
Organization Infrastructure
          │
          │ API Key
          ▼
POST /integration/documents
          │
          ▼
Authentication
          │
          ▼
Organization context
          │
          ▼
Validate request
          │
          ▼
Resolve patient
          │
          ▼
Create Document
          │
          ▼
Create DocumentVersion
          │
          ▼
Create ProcessingJob
          │
          ▼
S3
          │
          ▼
RabbitMQ
          │
          ▼
Existing AI pipeline
```

Это позволяет повторно использовать существующий document processing pipeline, который уже реализован.

---

# 34. Patient Resolution

Это один из самых важных компонентов нового этапа.

Организация отправляет:

```json
{
  "patient": {
    "email": "patient@example.com"
  }
}
```

Сервис:

```text
email
 ↓
normalize
 ↓
find Account
```

Если существует:

```text
Account found
```

Если нет:

```text
create Account
create Person
create Patient
create MedicalRecord
```

---

# 35. Автоматическое создание клиента

Важно: не создавать полноценного активного пользователя так, будто человек уже подтвердил владение email.

Правильная модель:

```text
Account
status = pending
email_verified_at = NULL
```

Существующая модель уже поддерживает `pending / active / blocked / deleted`, а первый успешный OTP переводит `pending` в `active`.

Это идеально подходит под этот сценарий.

---

# 36. Новый клиент после отправки документа

Workflow:

```text
Organization
      │
      │ email
      ▼
Account lookup
      │
 ┌────┴─────┐
 │          │
exists    not exists
 │          │
 ▼          ▼
Patient   create Account
exists    create Person
 │        create Patient
 │        create MedicalRecord
 │
 └────┬─────┘
      ▼
Create Document
      ▼
Process
      ▼
Notification
```

---

# 37. Что отправлять в notification

После успешной обработки:

```text
Ваше медицинское учреждение отправило вам документ.

Учреждение:
<Organization>

Тип документа:
Лабораторное исследование

Дата:
14.09.2026

Документ обработан.
Войдите в личный кабинет, чтобы посмотреть подробную информацию.
```

Ссылка:

```text
/login?email=...
```

или безопаснее:

```text
/login
```

с предварительно заполненным email через одноразовый flow.

Не передавать медицинские данные в email.

---

# 38. Notification architecture

Существующий `notification-worker` уже работает для OTP, но уведомления о новых документах пока не реализованы.

Поэтому расширяем существующую архитектуру:

```text
document.analysis.completed
          ↓
notification service
          ↓
document.available
          ↓
notification-worker
          ↓
email
```

В дальнейшем:

```text
email
push
SMS
in-app
```

---

# 39. Document Source

Рекомендую явно добавить источник документа.

Например:

```text
DocumentSource
----------------
patient
specialist
organization
system
```

Либо:

```text
uploaded_by_account_id
organization_id
```

уже достаточно для первой версии.

Но для будущего домена лучше иметь:

```text
source_type
```

потому что организация может отправлять документ не от конкретного сотрудника.

---

# 40. Кто является uploader

При API integration:

```text
uploaded_by_account_id = NULL
organization_id = X
organization_branch_id = Y
```

Это нормально.

Нельзя искусственно создавать `Account` для каждого API request.

Существующая модель уже допускает nullable `uploaded_by_account_id`, именно потому что загрузивший субъект не обязательно пациент.

---

# 41. Organization Document Schema

Это следующий уровень после базового API.

Организация в будущем должна иметь возможность объявить:

```text
"Laboratory Result"
"Discharge Summary"
"Medical History"
"Anamnesis"
"Prescription"
"Imaging Report"
```

Но здесь я бы **не разрешал организации произвольно менять системный canonical schema**.

Нужно разделить:

```text
Platform Document Type
```

и:

```text
Organization Document Schema
```

---

# 42. Системный DocumentType

Существующий enum уже содержит:

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

Его нужно сохранить.

---

# 43. OrganizationDocumentSchema

Новая таблица:

```text
organization_document_schemas
```

Предлагаемая модель:

```text
OrganizationDocumentSchema
--------------------------------
id
organization_id

code
name
description

document_type

schema_version

schema_json

status

created_by_account_id

created_at
updated_at
```

Например:

```json
{
  "code": "lab_blood_general",
  "name": "Общий анализ крови",
  "document_type": "lab_result",
  "schema_version": 1,
  "schema": {
    "hemoglobin": {
      "type": "number"
    },
    "wbc": {
      "type": "number"
    },
    "platelets": {
      "type": "number"
    }
  }
}
```

---

# 44. Но schema нельзя сразу отдавать LLM напрямую

Правильный pipeline:

```text
Organization Schema
        ↓
Platform validation
        ↓
Schema Registry
        ↓
AI extraction
        ↓
Pydantic validation
        ↓
canonical / extraction
```

Иначе организация сможет отправить:

```text
"schema": "do whatever you want"
```

и pipeline станет неконтролируемым.

---

# 45. Versioning schemas

Schema должна быть immutable после публикации.

Например:

```text
lab_result
v1
```

затем:

```text
lab_result
v2
```

Документ должен ссылаться на конкретную версию:

```text
schema_name
schema_version
```

Существующий `DocumentExtraction` уже содержит:

```text
schema_name
schema_version
```

что хорошо подходит под эту архитектуру.

---

# 46. Связь Organization Schema с Document

Рекомендую:

```text
Document
    ↓
document_schema_id nullable
```

либо хранить schema reference только в extraction.

Лучше:

```text
Document
    document_type
    organization_schema_id
```

если организация явно передала schema.

Например:

```json
{
  "document_type": "lab_result",
  "schema_code": "cbc",
  "schema_version": 2
}
```

---

# 47. Document type при отправке

API должен позволять организации явно указать:

```json
{
  "document_type": "lab_result"
}
```

Если не указан:

```text
platform classifier
```

может определить тип самостоятельно.

Таким образом:

```text
organization hint
        +
AI classifier
        ↓
final document type
```

---

# 48. Не доверять document_type полностью

Если организация отправила:

```text
document_type = prescription
```

а AI определил:

```text
lab_result
```

не следует молча менять данные.

Нужно хранить:

```text
provided_document_type
detected_document_type
final_document_type
```

или хотя бы metadata:

```json
{
  "source": "organization",
  "provided_type": "prescription",
  "detected_type": "lab_result"
}
```

Это позволит анализировать ошибки интеграций.

---

# 49. Organization API — структура

Я бы не смешивал integration API с существующими patient endpoints.

Предлагаю:

```text
/api/v1/integration/
```

Например:

```text
POST /api/v1/integration/documents
POST /api/v1/integration/documents/bulk

GET /api/v1/integration/documents/{id}

GET /api/v1/integration/batches/{id}
GET /api/v1/integration/batches/{id}/items

GET /api/v1/integration/jobs/{id}
```

Позже:

```text
GET /api/v1/integration/patients/{external_id}
GET /api/v1/integration/schemas
```

---

# 50. Organization management API

Отдельно:

```text
/api/v1/organizations/
```

Например:

```text
GET    /organizations/me
PATCH  /organizations/me

GET    /organizations/me/branches
POST   /organizations/me/branches
PATCH  /organizations/me/branches/{id}

GET    /organizations/me/licenses
POST   /organizations/me/licenses
PATCH  /organizations/me/licenses/{id}

GET    /organizations/me/api-keys
POST   /organizations/me/api-keys
DELETE /organizations/me/api-keys/{id}
```

Authentication:

```text
JWT
+
organization_admin
+
membership
```

---

# 51. API integration response

API должен быть асинхронным.

Не нужно ждать AI extraction.

Например:

```http
POST /integration/documents
```

ответ:

```json
{
  "document_id": "uuid",
  "status": "processing",
  "patient_id": "uuid",
  "batch_id": null,
  "external_id": "LAB-12345"
}
```

---

# 52. Status endpoint

Организация должна иметь возможность:

```http
GET /integration/documents/{id}
```

Ответ:

```json
{
  "document_id": "...",
  "status": "completed",
  "document_type": "lab_result",
  "document_date": "2026-09-14",
  "processing": {
    "status": "succeeded"
  }
}
```

Но API не должен возвращать медицинскую информацию пациента без специально предусмотренного permission.

Для первой версии integration API можно ограничить его:

```text
upload
status
```

---

# 53. External identifiers

Для интеграции с медицинскими системами стоит заранее предусмотреть:

```text
organization_external_id
patient_external_id
document_external_id
encounter_external_id
```

Но не нужно сразу создавать десять полей.

Минимально:

```text
document.external_id
```

и:

```text
organization + external_id
```

должны быть уникальны.

---

# 54. Пациент и внешний ID

Очень желательно в будущем иметь:

```text
organization_patient_references
```

или:

```text
PatientExternalIdentifier
```

Потому что клиника может иметь своего пациента:

```text
patient_number = 123456
```

а платформа:

```text
patient_id = UUID
```

Связь:

```text
Organization
    ↓
ExternalPatientReference
    ↓
Patient
```

Это следует заложить в архитектуру, но я бы **не включал в первую миграцию**, если текущий use case требует только email.

---

# 55. Auto-create по email — security

Автоматическое создание пациента по email допустимо как integration workflow, но нужно очень аккуратно определить ownership.

Организация сообщает:

```text
email = patient@example.com
```

Это ещё не означает, что пользователь подтвердил email.

Поэтому:

```text
Account.status = pending
email_verified_at = NULL
```

и пациент получает приглашение/уведомление.

Первый OTP login:

```text
verify email
      ↓
Account active
```

Это соответствует существующей auth-модели.

---

# 56. Duplicate patient problem

Нельзя делать:

```text
email → всегда create patient
```

Нужно:

```text
normalize email
        ↓
Account
        ↓
Person
        ↓
Patient
```

Если Account существует, использовать существующий Patient.

Если Account существует, но Patient отсутствует:

```text
create Patient
create MedicalRecord
```

Если Account не существует:

```text
create Account
create Person
create Patient
create MedicalRecord
```

---

# 57. Конкурентное создание

Это обязательно покрыть database constraints.

Например одновременно две заявки:

```text
Organization A
POST email=x@example.com

Organization B
POST email=x@example.com
```

Обе не должны создать два Account.

Уже существующий `accounts.email_normalized` UNIQUE является правильным фундаментом для этого.

Service должен корректно обрабатывать:

```text
IntegrityError
→ reload existing account
```

---

# 58. Организационный access к пациенту

Здесь важно не нарушить существующую модель.

Сейчас доступ специалиста к медицинским данным реализован через:

```text
PatientAccessGrant
```

с permission flags.

Организация, отправляющая документ, должна иметь право создать документ от своего имени.

Я бы **не создавал автоматически полноценный permanent access grant организации к пациенту только потому, что организация отправила документ**.

Нужно разделить:

```text
document submission authority
```

и:

```text
ongoing access to medical history
```

Это разные права.

---

# 59. Предлагаемый Organization Access

На первом этапе:

```text
API Key
    ↓
Organization
    ↓
can_upload_documents
```

Организация может:

* отправить документ;
* получить статус;
* получить собственный submission result.

Но это не означает:

```text
organization can read patient's entire history
```

Это должно быть отдельным permission/use case.

---

# 60. Organization API permissions

Предлагаемый минимальный набор:

```text
organization.documents.upload
organization.documents.bulk_upload
organization.documents.read
organization.jobs.read
```

В будущем:

```text
organization.patients.resolve
organization.patients.read
organization.encounters.create
organization.schemas.read
organization.schemas.write
organization.analytics.read
```

---

# 61. Database migration plan

Не делать одну гигантскую migration.

Предлагаю разделить:

### Migration 1

```text
Organization fields

inn
ogrn
legal_address
email
phone
website
```

### Migration 2

```text
organization_branches
```

### Migration 3

```text
organization_licenses
```

### Migration 4

```text
organization_api_keys
```

### Migration 5

```text
organization_api_request_logs
```

### Migration 6

```text
organization_upload_batches
organization_upload_batch_items
```

### Migration 7

```text
organization_document_schemas
```

### Migration 8

```text
documents.organization_id
documents.organization_branch_id
documents.external_id
```

Так проще делать rollback, тестирование и code review.

---

# 62. Domain models

Добавить:

```text
organization.py
organization_branch.py
organization_license.py
organization_api_key.py
organization_api_request.py
organization_upload_batch.py
organization_upload_batch_item.py
organization_document_schema.py
```

Не делать всё внутри `organization.py`.

---

# 63. Repositories

Добавить:

```text
OrganizationRepository
OrganizationBranchRepository
OrganizationLicenseRepository
OrganizationApiKeyRepository
OrganizationApiRequestRepository
OrganizationUploadBatchRepository
OrganizationDocumentSchemaRepository
```

Для API key repository нужны операции:

```text
find_by_hash()
create()
revoke()
expire()
update_last_used()
```

---

# 64. Services

Основные services:

```text
OrganizationService
OrganizationBranchService
OrganizationLicenseService
OrganizationApiKeyService
OrganizationIntegrationService
OrganizationPatientResolver
OrganizationDocumentService
OrganizationBulkUploadService
OrganizationSchemaService
OrganizationApiMonitoringService
```

Особенно важно не помещать бизнес-логику в FastAPI routers.

Router:

```text
validate HTTP
 ↓
service
```

Service:

```text
business logic
```

Repository:

```text
database
```

---

# 65. PatientResolver

Отдельный сервис:

```python
OrganizationPatientResolver
```

API:

```python
resolve_by_email(
    organization_id,
    email,
) -> Patient
```

Логика:

```text
normalize email
 ↓
find account
 ↓
find patient
 ↓
create missing entities
 ↓
return patient
```

Это станет важной переиспользуемой частью integration domain.

---

# 66. Document ingestion service

Не дублировать существующий `DocumentService`.

Лучше:

```text
OrganizationDocumentService
          ↓
existing DocumentService
          ↓
Document
DocumentVersion
ProcessingJob
```

Таким образом два источника:

```text
Client
   ↓
DocumentService

Organization API
   ↓
OrganizationDocumentService
   ↓
DocumentService
```

а не два разных pipeline.

---

# 67. Bulk processing

Bulk API:

```text
create batch
    ↓
validate items
    ↓
resolve patients
    ↓
create documents
    ↓
publish events
    ↓
return batch
```

Не обрабатывать 100 документов в одной DB transaction.

Каждый документ должен быть независимой единицей.

---

# 68. Transaction boundaries

Для single document:

```text
transaction:
    resolve/create patient
    create document
    create version
    create processing job

commit

publish event
```

Для bulk:

```text
create batch
commit

for each item:
    process independently
```

Иначе одна ошибка испортит весь batch.

---

# 69. Event model

Существующий проект уже использует RabbitMQ и события document processing.

Нужно добавить integration events:

```text
organization.document.submitted
organization.document.accepted
organization.document.rejected

organization.batch.created
organization.batch.completed

organization.patient.created
```

Но не обязательно создавать отдельный RabbitMQ topic.

Можно использовать существующую event infrastructure.

---

# 70. Idempotent events

Для каждого события:

```text
event_id
event_type
event_version
occurred_at
organization_id
document_id
batch_id
```

Consumer должен быть idempotent.

Это особенно важно для bulk.

---

# 71. Notification events

После завершения обработки:

```text
document.analysis.completed
        ↓
notification decision
        ↓
notification.created
        ↓
notification-worker
```

Важно: уведомление клиенту должно создаваться даже если:

```text
canonical extraction failed
```

?

Здесь нужно определить бизнес-правило.

Я бы разделил:

```text
document received
```

и:

```text
document processed
```

Например:

```text
Документ получен от медицинской организации.
```

можно отправлять сразу.

А затем:

```text
Документ обработан, подробная информация доступна.
```

после AI processing.

---

# 72. Notification domain

С учётом будущих каналов желательно добавить:

```text
notifications
```

с:

```text
id
account_id
type
channel
status
title
template
resource_type
resource_id
created_at
sent_at
read_at
```

Это соответствует ранее определённому product roadmap: notifications являются отдельным следующим слоем, а текущий worker пока покрывает только OTP.

---

# 73. Organization onboarding

После реализации API нужен onboarding:

```text
Create organization
       ↓
Organization admin
       ↓
Fill:
    name
    INN
    OGRN
    legal address
       ↓
Add branches
       ↓
Add licenses
       ↓
Create API key
       ↓
Integration ready
```

---

# 74. Verification status

Не стоит сразу делать:

```text
organization.verified = true
```

Нужна более расширяемая модель:

```text
verification_status
```

например:

```text
unverified
pending
verified
rejected
```

И отдельные источники проверки в будущем:

```text
manual
federal_registry
license_registry
```

---

# 75. Federal registry integration

На этом этапе **не нужно реализовывать саму интеграцию**, но модель нужно подготовить.

Будущая архитектура:

```text
Organization
      ↓
VerificationService
      ↓
RegistryProvider
      ↓
Federal Medical Organizations Registry
```

Интерфейс:

```python
class OrganizationRegistryProvider(Protocol):
    async def verify(
        self,
        inn: str,
        ogrn: str,
    ) -> OrganizationVerificationResult:
        ...
```

В будущем:

```text
FederalRegistryProvider
```

может быть подключён без изменения `OrganizationService`.

---

# 76. Organization verification result

Будущая сущность:

```text
organization_verifications
```

например:

```text
id
organization_id

provider
status

requested_at
verified_at

inn
ogrn

raw_response_reference
normalized_data
error_code
```

Не хранить необязательно полный raw response, особенно если он большой.

---

# 77. License verification

Та же архитектура:

```text
License
   ↓
LicenseVerificationService
   ↓
RegistryProvider
```

Это позволит в будущем автоматически проверять:

```text
license number
license status
license scope
validity
```

---

# 78. API documentation

После реализации API обязательно предоставить OpenAPI contract.

Основные группы:

```text
Organization Management
Organization Branches
Organization Licenses
Organization API Keys
Organization Integration
Organization Bulk Upload
Organization Schemas
Organization Monitoring
```

Для внешних организаций это будет главным integration contract.

---

# 79. Security requirements

Минимальный security checklist:

### API Key

* secret хранится только в hash;
* полный key показывается один раз;
* revoke;
* expiration;
* active/inactive;
* prefix;
* permissions;
* last_used_at.

### API

* HTTPS;
* rate limit;
* request size limit;
* file MIME validation;
* file size limit;
* idempotency;
* request ID;
* audit;
* no medical data in logs.

### Organization isolation

Каждый query:

```text
organization_id = authenticated_organization
```

Никогда:

```text
GET document by UUID
```

без проверки ownership/organization context.

---

# 80. Защита от IDOR

Особенно важно для:

```text
GET /integration/documents/{id}
GET /integration/batches/{id}
GET /integration/jobs/{id}
```

Проверка должна быть:

```text
resource.organization_id
        ==
api_key.organization_id
```

а не просто:

```text
document.id == requested_id
```

---

# 81. API monitoring dashboard

Не нужно делать полноценный UI сразу.

Минимально endpoint:

```text
GET /organizations/me/api-keys
```

должен показывать:

```text
key prefix
status
created_at
last_used_at
expires_at
```

Второй этап:

```text
GET /organizations/me/api-usage
```

с агрегатами:

```text
requests/day
success rate
error rate
documents uploaded
bulk batches
processing failures
```

---

# 82. Метрики

Добавить:

```text
organization_api_requests_total
organization_api_request_errors_total
organization_documents_uploaded_total
organization_bulk_documents_total
organization_api_auth_failures_total
organization_api_request_duration
```

В текущем проекте `packages/observability` пока является заглушкой, поэтому полноценную observability-инфраструктуру можно развивать параллельно с этим этапом.

---

# 83. Что не следует делать в этом этапе

Не рекомендую одновременно реализовывать:

```text
Qdrant
embeddings
Marker GPU
Longitudinal AI
AI assistant
```

Это отдельные следующие этапы.

Текущий pipeline уже работает без Marker: `ai-worker` выполняет конвертацию/OCR/extraction и сохраняет canonical data.

Поэтому Organization Integration должна использовать существующий pipeline, а не ждать завершения GPU-конвейера.

---

# 84. Этапы разработки

## Phase 1 — Organization core

### DB

Добавить:

```text
Organization
    inn
    ogrn
    legal_address
    email
    phone
    website
```

### API

```text
GET /organizations/me
PATCH /organizations/me
```

### Tests

* validation;
* uniqueness;
* permissions;
* migration;
* serialization.

---

# 85. Phase 2 — Branches

Создать:

```text
organization_branches
```

API:

```text
GET
POST
PATCH
DELETE/deactivate
```

Добавить:

```text
organization_branch_id
```

в document source.

---

# 86. Phase 3 — Licenses

Создать:

```text
organization_licenses
```

API:

```text
GET
POST
PATCH
DELETE/deactivate
```

Добавить:

```text
license_number
status
validity
scope
```

---

# 87. Phase 4 — API Keys

Создать:

```text
organization_api_keys
```

Реализовать:

```text
create
list
revoke
rotate
expire
```

Security:

```text
hash
prefix
permissions
expiration
```

---

# 88. Phase 5 — API Key authentication

Создать:

```text
get_current_organization_from_api_key
```

Реализовать:

```text
authentication
organization isolation
permissions
rate limiting
request ID
audit
```

На этом этапе внешний API пока может иметь один endpoint:

```text
POST /integration/documents
```

---

# 89. Phase 6 — Single document integration

Реализовать:

```text
POST /integration/documents
```

Request:

```json
{
  "patient": {
    "email": "patient@example.com"
  },
  "document_type": "lab_result",
  "external_id": "LAB-123",
  "branch_code": "MAIN"
}
```

File:

```text
multipart/form-data
```

Response:

```json
{
  "document_id": "...",
  "status": "processing",
  "external_id": "LAB-123"
}
```

---

# 90. Phase 7 — Patient resolver

Реализовать:

```text
email → Account → Patient → MedicalRecord
```

С поддержкой:

```text
existing account
existing patient
pending account
new account
```

И обязательно:

```text
unique constraint
race condition handling
```

---

# 91. Phase 8 — Notifications

Добавить:

```text
notifications
```

и событие:

```text
document.available
```

Интегрировать с существующим:

```text
notification-worker
```

Сценарий:

```text
Organization
    ↓
Document
    ↓
Processing
    ↓
Completed
    ↓
Notification
    ↓
Email
    ↓
Client
```

---

# 92. Phase 9 — Bulk upload

Добавить:

```text
organization_upload_batches
organization_upload_batch_items
```

API:

```text
POST /integration/documents/bulk
GET /integration/batches/{id}
GET /integration/batches/{id}/items
```

Обязательно:

```text
partial failure
idempotency
item status
retry
```

---

# 93. Phase 10 — Organization schemas

Добавить:

```text
organization_document_schemas
```

API:

```text
GET /organizations/me/schemas
POST /organizations/me/schemas
PATCH /organizations/me/schemas/{id}
POST /organizations/me/schemas/{id}/publish
```

С versioning:

```text
schema v1
schema v2
schema v3
```

После публикации версия immutable.

---

# 94. Phase 11 — Monitoring

Добавить:

```text
organization_api_requests
```

и агрегированные метрики.

Минимальный UI:

```text
API Keys

Production
med_live_82f1•••
Active
Last used: 2 minutes ago

Requests:
12 481

Errors:
17

Documents:
3 421
```

---

# 95. Phase 12 — Registry verification

Это отдельная последующая фаза:

```text
Organization
    ↓
VerificationService
    ↓
RegistryProvider
```

В первой версии:

```text
manual verification
```

В следующей:

```text
FederalRegistryProvider
```

Не связывать domain model напрямую с конкретным государственным API.

---

# 96. Предлагаемая итоговая модель

```text
                         Organization
                              │
             ┌────────────────┼─────────────────┐
             │                │                 │
             ▼                ▼                 ▼
       Branches           Licenses          API Keys
             │                                  │
             │                                  ▼
             │                            Integration API
             │                                  │
             └──────────────┐                   │
                            ▼                   ▼
                         Document ◄──── Patient Resolver
                            │                   │
                            ▼                   ▼
                    Processing Pipeline      Patient
                            │                   │
                            ▼                   ▼
                     canonical.json       MedicalRecord
                            │
                            ▼
                       Notification
                            │
                            ▼
                          Client
```

---

# 97. Итоговая DB-модель

После этого этапа:

```text
organizations
├── organization_memberships
├── organization_branches
├── organization_licenses
├── organization_api_keys
├── organization_api_requests
├── organization_upload_batches
├── organization_upload_batch_items
└── organization_document_schemas


organizations
      │
      ├── documents
      │      ├── document_versions
      │      ├── document_processing_jobs
      │      └── document_extractions
      │
      └── encounters
               │
               ▼
             patient
               │
               ▼
          medical_record
```

---

# 98. Приоритеты

Я бы реализовывал не все задачи одинаково.

### P0 — обязательно

```text
Organization legal data
INN
OGRN
legal address

Branches

Licenses

API Keys

API Key authentication

Single document integration

Patient resolver

Document source organization/branch

Notification after document submission
```

### P1 — следующий слой

```text
Bulk upload

Idempotency

External IDs

API usage monitoring

Rate limiting

API key permissions

Organization schemas
```

### P2 — после стабилизации

```text
Organization UI

API analytics dashboard

Patient external identifiers

Registry verification

License verification
```

---

# 99. Рекомендуемый первый vertical slice

Не стоит сначала делать все таблицы, а потом все API.

Лучше реализовать вертикально.

### Vertical Slice #1

```text
Organization
    ↓
INN / OGRN
    ↓
Branch
    ↓
API Key
    ↓
POST /integration/documents
    ↓
email patient resolver
    ↓
create/find patient
    ↓
Document
    ↓
existing processing pipeline
    ↓
notification
    ↓
client sees document
```

Если этот сценарий работает end-to-end — мы получаем первую реально полезную версию Organization Integration.

---

# 100. Vertical Slice #2

```text
Organization
    ↓
API Key
    ↓
Bulk Batch
    ↓
100 documents
    ↓
individual processing
    ↓
partial failures
    ↓
batch status
```

---

# 101. Vertical Slice #3

```text
Organization
    ↓
Schema
    ↓
Document type
    ↓
LLM extraction
    ↓
Pydantic validation
    ↓
canonical
```

---

# 102. Vertical Slice #4

```text
Organization
    ↓
API usage
    ↓
API Key monitoring
    ↓
metrics
    ↓
dashboard
```

---

# 103. Тестовая стратегия

Для этого этапа тестирование должно быть значительно серьёзнее обычного CRUD.

## Unit

```text
INN validation
OGRN validation
API key hashing
API key expiration
patient resolver
document type validation
schema validation
batch state machine
```

## Integration

```text
Organization → API Key
API Key → Organization context
Organization → Patient
Organization → Document
Organization → S3
Organization → RabbitMQ
Organization → Notification
```

## Security

Обязательно:

```text
API key A cannot access organization B

document A cannot be accessed through organization B key

batch A cannot be accessed through organization B key

revoked key → 401/403

expired key → 401/403

inactive organization → reject

missing permission → 403
```

## E2E

Минимальный сценарий:

```text
Create organization
 ↓
Create API key
 ↓
Send document with unknown email
 ↓
Account created
 ↓
Patient created
 ↓
Document created
 ↓
Processing
 ↓
Completed
 ↓
Notification
 ↓
Client login
 ↓
Document visible
```

---

# 104. Что считать Definition of Done

Этап нельзя считать завершённым просто потому, что:

```text
organizations table exists
```

Definition of Done:

### Organization

* [ ] INN
* [ ] OGRN
* [ ] legal address
* [ ] validation
* [ ] unique indexes

### Branch

* [ ] CRUD
* [ ] organization isolation
* [ ] active/inactive
* [ ] code

### License

* [ ] multiple licenses
* [ ] CRUD
* [ ] status
* [ ] validity

### API Key

* [ ] create
* [ ] hash
* [ ] prefix
* [ ] revoke
* [ ] expiration
* [ ] permissions
* [ ] last_used_at

### Integration API

* [ ] API Key authentication
* [ ] organization context
* [ ] rate limiting
* [ ] request ID
* [ ] idempotency
* [ ] single upload
* [ ] status endpoint

### Patient

* [ ] resolve by normalized email
* [ ] create Account
* [ ] create Person
* [ ] create Patient
* [ ] create MedicalRecord
* [ ] race-condition protection

### Document

* [ ] organization source
* [ ] branch source
* [ ] document type
* [ ] external ID
* [ ] existing processing pipeline

### Notification

* [ ] document received
* [ ] document processed
* [ ] email notification
* [ ] login link
* [ ] no medical data in email

### Bulk

* [ ] batch
* [ ] items
* [ ] partial failures
* [ ] retry
* [ ] idempotency

### Monitoring

* [ ] API request log
* [ ] API key usage
* [ ] auth failures
* [ ] latency
* [ ] success/error metrics

### Schemas

* [ ] organization schema
* [ ] versioning
* [ ] validation
* [ ] publish
* [ ] immutable versions

---

# 105. Главный архитектурный результат этапа

После реализации этого этапа платформа перестаёт быть системой:

```text
Client → uploads medical document
```

и становится:

```text
                    ┌── Client
                    │
Medical Platform ───┼── Specialist
                    │
                    └── Organization
                           │
                           ▼
                     Integration API
                           │
                           ▼
                     Medical History
```

То есть `Organization` становится не просто сущностью БД, а полноценным **источником медицинских данных платформы**.

Это очень важный переход для продукта.

## При этом существующая архитектура хорошо поддерживает такой переход: `Document` уже отделён от конкретного uploader account, структурированные extraction-данные уже хранятся отдельно в PostgreSQL, а processing pipeline событийно отделён от API.

# 106. Итоговая последовательность реализации

Рекомендую следующий порядок:

```text
01. Organization fields
        ↓
02. Branches
        ↓
03. Licenses
        ↓
04. Organization management API
        ↓
05. API Keys
        ↓
06. API Key authentication
        ↓
07. Organization integration API
        ↓
08. Patient resolver
        ↓
09. Organization → Document
        ↓
10. Notification
        ↓
11. Bulk upload
        ↓
12. Idempotency / external IDs
        ↓
13. API monitoring
        ↓
14. Organization document schemas
        ↓
15. Registry verification
```

Именно такой порядок я считаю оптимальным для текущей стадии проекта: сначала закрыть **реальный Organization → Client document delivery workflow**, затем масштабировать его bulk/API/schema/monitoring возможностями.

Это также не конфликтует с текущим roadmap проекта, где Organization workflow и document delivery являются ближайшими незакрытыми продуктовыми слоями, а medical normalization, analytics, Qdrant и Longitudinal AI остаются последующими этапами.
