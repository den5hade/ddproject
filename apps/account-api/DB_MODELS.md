# DB_MODELS.md — Реализованная модель данных account-api

> Это справочник по **реализованной** схеме БД (`migrations/0002_medical_models.py`),
> а не только проектные рассуждения. Модели — SQLAlchemy 2.0 (`app/models/*`),
> UUID PK, UTC-таймстампы, enum-колонки хранятся как VARCHAR (`native_enum=False`).

Легенда статусов:

- ✅ **IMPLEMENTED** — создано миграцией `0002`, модель в `app/models/`.
- ⏳ **DEFERRED** — заложено в дизайне (DB_MODELS.md §36), реализуется позже.

---

# 1. Главный принцип (реализован)

Аккаунт и пациент разделены:

```text
Account
   │ 1:1
   ▼
 Person
   │
   ├── Patient
   │     │
   │     └── MedicalRecord
   │            ├── Documents
   │            ├── Encounters
   │            └── DocumentExtractions / ProcessingJobs
   │
   └── Specialist
         ├── SpecialistSpecialty ── Specialty
         └── OrganizationMembership ── Organization

Account ── AccountIdentity (email / phone)
Account ── AccountRole ── Role ── RolePermission ── Permission   (RBAC)
Patient ── PatientAccessGrant ── Account (specialist)            (ABAC-ish)
Account ── AuditLog                                               (audit)
```

Один человек может быть одновременно пациентом и специалистом
(`persons` → `patients` и `specialists` — отдельные строки).

---

# 2. Статус таблиц

## ✅ MVP (реализовано в `0002`)

```text
accounts                    account_identities            persons
roles                       permissions                   account_roles        role_permissions
patients                    specialists                   specialties          specialist_specialties
organizations               organization_memberships
medical_records             encounters
documents                   document_versions
document_processing_jobs    document_extractions
patient_access_grants       audit_logs
```

## ⏳ Deferred (следующие итерации, §36/§21-23/§26)

```text
observations   diagnoses   medications   patient_consents
```

---

# 3. Справочник таблиц

## accounts — техническая учётная запись ✅

`app/models/account.py` → `Account`

| column            | type                | constraints / notes                          |
|-------------------|---------------------|----------------------------------------------|
| id                | UUID                | PK, `uuid4()`                                |
| email             | VARCHAR(255) NULL   | исходное значение                           |
| email_normalized  | VARCHAR(255) NULL   | **UNIQUE** (`uq_accounts_email_normalized`)  |
| email_verified_at | TIMESTAMPTZ NULL    |                                              |
| phone             | VARCHAR(32) NULL    | исходное значение                           |
| phone_e164        | VARCHAR(32) NULL    | **UNIQUE** (`uq_accounts_phone_e164`)        |
| phone_verified_at | TIMESTAMPTZ NULL    |                                              |
| status            | VARCHAR(32)         | `pending / active / blocked / deleted`, default `pending` |
| person_id         | UUID NULL           | **UNIQUE**, FK → `persons.id` ON DELETE SET NULL |
| is_subscribed     | BOOLEAN             | default `false` (сохранено из старой схемы, квота загрузок) |
| last_login_at     | TIMESTAMPTZ NULL    |                                              |
| created_at / updated_at | TIMESTAMPTZ  |                                              |

Примечания:
- `email_normalized` = `lower(btrim(email))`, `phone_e164` = телефон в E.164.
- `.user_type` удалён из `0001` — роли переехали в `account_roles`.
- `auth_sessions.user_id` переименован в `account_id` (FK → `accounts.id`).

## account_identities — нормализованная идентичность ✅

`app/models/account_identity.py` → `AccountIdentity`; относится к `accounts.id` (CASCADE).

| column          | notes                                      |
|-----------------|--------------------------------------------|
| id, account_id  | PK; FK → accounts, index                   |
| kind            | `email / phone` (`IdentityKind`)           |
| value           | как ввёл пользователь                      |
| value_normalized| **UNIQUE**                                 |
| verified_at     | NULL до подтверждения                      |
| created_at      |                                            |

## persons — физическое лицо ✅

`app/models/person.py` → `Person`

| column       | type            | notes                                   |
|--------------|-----------------|-----------------------------------------|
| id           | UUID            | PK                                      |
| first_name / last_name | VARCHAR(255) | default `''`                     |
| middle_name  | VARCHAR(255) NULL|                                         |
| date_of_birth| DATE NULL       |                                         |
| sex          | VARCHAR(16) NULL| `male / female / unspecified` (`Sex`)   |
| created_at / updated_at | TIMESTAMPTZ |                                   |

---

# 4. RBAC: роли и права ✅

`app/models/role.py`

| table             | columns                          | constraints                       |
|-------------------|----------------------------------|-----------------------------------|
| `roles`           | id, code (VARCHAR(64) **UNIQUE**), name | `Role`                     |
| `permissions`     | id, code (VARCHAR(128) **UNIQUE**), name | `Permission`             |
| `account_roles`   | id, account_id, role_id          | **UNIQUE(account_id, role_id)**, FK CASCADE |
| `role_permissions`| id, role_id, permission_id       | **UNIQUE(role_id, permission_id)**, FK CASCADE |

Роли первого этапа (`RoleCode`): `client`, `specialist`, `organization_admin`,
`system_admin`, `support`.

Права (`PermissionCode`):
`medical_record.read/write`, `document.read/upload/download`,
`encounter.read/create/update`, `analytics.read`, `user.manage`, `organization.manage`.

RBAC-флагов **недостаточно** для медданных — доступ к конкретному пациенту
всегда проверяется через `patient_access_grants`.

---

# 5. Медицинские роли и организации ✅

## patients

`app/models/patient.py` → `Patient`

| column | notes |
|--------|-------|
| id | PK, внутренний immutable UUID |
| person_id | **UNIQUE**, FK → persons CASCADE |
| medical_record_number | VARCHAR(64) NULL |
| status | `active / inactive` (`PatientStatus`), default `active` |

## specialists

`app/models/specialist.py` → `Specialist`, `Specialty`, `SpecialistSpecialty`

- `specialists`: id, person_id (FK → persons, index), status;
- `specialties`: id, code (**UNIQUE**), name — справочник;
- `specialist_specialties`: id, specialist_id, specialty_id —
  **UNIQUE(specialist_id, specialty_id)** (врач может иметь несколько специализаций).

## organizations / organization_memberships

`app/models/organization.py` → `Organization`, `OrganizationMembership`

- `organizations`: id, name, type (`OrganizationType`: clinic/hospital/private_practice/laboratory), status;
- `organization_memberships`: id, organization_id, account_id —
  **UNIQUE(organization_id, account_id)**, position, status, joined_at, left_at
  (FK → organizations/accounts, CASCADE).

---

# 6. Medical Record — центральная сущность ✅

`app/models/medical_record.py` → `MedicalRecord`

| column | notes |
|--------|-------|
| id | PK |
| patient_id | **UNIQUE**, FK → patients CASCADE |
| created_at / updated_at | |

> **Medical Record ≠ Account.** У пациента может быть account, но карта — отдельная сущность.
> Patient → MedicalRecord — 1:1; все документы/приёмы сосредоточены вокруг `medical_records.id`.

---

# 7. Encounters — приём/контакт с врачом ✅

`app/models/encounter.py` → `Encounter`

| column | notes |
|--------|-------|
| id | PK |
| medical_record_id | FK → medical_records CASCADE, index |
| specialist_id | FK → specialists SET NULL, index, **nullable** |
| organization_id | FK → organizations SET NULL, index, **nullable** |
| type | `EncounterType`: consultation/follow_up/procedure/admission/telemedicine/other |
| status | `EncounterStatus`: scheduled/in_progress/completed/cancelled/no_show |
| started_at / ended_at | TIMESTAMPTZ; ended nullable |
| reason / summary | TEXT, nullable |
| created_at / updated_at | |

---

# 8. Documents и версии ✅

`app/models/document.py` → `Document`, `DocumentVersion`

**documents**

| column | notes |
|--------|-------|
| id | PK |
| medical_record_id | FK → medical_records CASCADE, index |
| encounter_id | FK → encounters SET NULL, index, **nullable** (пациент может загрузить сам) |
| document_type | `DocumentType`: lab_result/doctor_report/prescription/discharge_summary/imaging_report/referral/medical_certificate/other |
| title, original_filename, mime_type, storage_key | VARCHAR |
| size_bytes | BIGINT |
| status | `DocumentStatus`: pending/uploaded/processing/completed/failed/deleted |
| uploaded_by_account_id | FK → accounts SET NULL, index, **nullable** — загрузивший ≠ пациент |
| created_at / updated_at | |

`uploaded_by_account_id` ≠ `patient`: документ загружает и пациент, и врач после приёма,
но `medical_record_id` всегда = карта пациента.

**document_versions** — неизменяемые версии содержимого (врач исправил заключение → v1, v2, ...):

| column | notes |
|--------|-------|
| id | PK |
| document_id | FK → documents CASCADE, index |
| version | INTEGER, **UNIQUE(document_id, version)** |
| s3_key, mime_type | VARCHAR |
| size_bytes | BIGINT |
| checksum | VARCHAR(256) NULL |
| created_by_account_id | FK → accounts SET NULL |
| created_at | |

---

# 9. Обработка и AI-извлечение ✅

## document_processing_jobs

`app/models/processing_job.py` → `DocumentProcessingJob`

| column | notes |
|--------|-------|
| id | PK |
| document_id | FK → documents CASCADE, index |
| document_version_id | FK → document_versions CASCADE, index, nullable |
| job_type | `ProcessingJobType`: pdf_conversion / ai_extraction / embedding |
| status | `ProcessingJobStatus`: queued/running/succeeded/retrying/failed |
| attempts | INTEGER |
| started_at / finished_at | nullable |
| error_code / error_message | nullable |

## document_extractions — структурированные данные из документа

`app/models/extraction.py` → `DocumentExtraction`

| column | notes |
|--------|-------|
| id | PK |
| document_id / document_version_id | FK (version nullable) |
| schema_name, schema_version | VARCHAR |
| status | `ExtractionStatus`: pending/extracting/succeeded/failed |
| data | JSON (портативный; на PG — JSON, при необходимости заменить на JSONB) |
| confidence | FLOAT NULL |
| created_at / updated_at | |

> Qdrant — поисковый индекс; **структурированные данные живут в PostgreSQL** (`data` JSONB/JSON).

---

# 10. Доступ врача к карте ✅

## patient_access_grants

`app/models/access_grant.py` → `PatientAccessGrant`

| column | notes |
|--------|-------|
| id | PK |
| patient_id | FK → patients CASCADE, index |
| account_id | FK → accounts CASCADE, index (аккаунт специалиста) |
| organization_id | FK → organizations SET NULL, index, nullable |
| can_view_documents / can_upload_documents / can_view_extractions / can_view_analytics / can_create_encounters / can_edit_medical_data | BOOLEAN, default false |
| status | `GrantStatus`: active/revoked/expired |
| granted_at | TIMESTAMPTZ |
| expires_at | TIMESTAMPTZ NULL |
| granted_by_account_id | FK → accounts SET NULL |
| access_reason | VARCHAR(64) NULL (`treatment/consultation/diagnosis/follow_up`) |
| created_at / updated_at | |

Реализован **развёрнутый вариант** прав (булевы флаги), а не один `access_type`.
Проверка доступа (§33): `authenticated AND account.active AND role=specialist
AND organizacija AND grant.active AND NOT expires AND grant.can_... AND resource
принадлежит карте пациента`.

---

# 11. Audit Log ✅

`app/models/audit_log.py` → `AuditLog`

| column | notes |
|--------|-------|
| id | PK |
| actor_account_id | FK → accounts SET NULL, index, nullable |
| action | `AuditAction`: LOGIN/LOGOUT/VIEW_PATIENT/VIEW_MEDICAL_RECORD/VIEW_DOCUMENT/DOWNLOAD_DOCUMENT/UPLOAD_DOCUMENT/CREATE_ENCOUNTER/UPDATE_ENCOUNTER/GRANT_ACCESS/REVOKE_ACCESS/VIEW_ANALYTICS |
| resource_type / resource_id | VARCHAR(64), UUID NULL |
| patient_id | FK → patients SET NULL, index, nullable |
| ip_address | VARCHAR(45) |
| user_agent | VARCHAR(512) |
| metadata | JSON (колонка `metadata`, атрибут модели `metadata_`) |
| created_at | |

---

# 12. Переименование из первоначальной схемы

| Было (0001) | Стало (0002) |
|-------------|--------------|
| таблица `users` | таблица `accounts` (+ person_id, status, нормализованные идентичности) |
| `users.user_type` (single role) | `account_roles` / `roles` (несколько ролей) |
| `auth_sessions.user_id` → | `auth_sessions.account_id` |
| модель `User` | модель `Account` (`app/models/account.py`) |
| `UserRepository` | `AccountRepository` (`app/repositories/account.py`) |

Схема эволюционировала от `User → Documents` к
`Account → Person → Patient/Specialist → MedicalRecord → Documents/Encounters/MedicalData`
(файл — artifact/source, а структурированные данные — отдельные сущности).

---

# 13. Deferred в следующих фазах (дизайн готов, таблицы НЕ созданы)

⏳ `observations` — нормализованные показатели (value_numeric/text/unit, reference_low/high,
observed_at, source_document_id, source_encounter_id) → аналитика по динамике.

⏳ `diagnoses` — code_system/code/name, onset/resolved, source_document_id; в будущем ICD-10/11.

⏳ `medications` — name, active_ingredient, dosage, frequency, started/ended_at, source_document_id.

⏳ `patient_consents` — purpose (`CONSULTATION/DOCUMENT_ACCESS/AI_ANALYSIS/DATA_SHARING`),
status, granted_at/revoked_at/expires_at — юридическое согласие, **отдельно от Access**.