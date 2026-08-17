# ACC_IMPLEMTATION.md — план реализации account-api: schemas, routes, services

> Статус: план. Схема БД уже реализована (`../../migrations/alembic/versions/0002`, см. [DB_MODELS.md](../data/DB_MODELS.md)),
> auth-флоу работает. Этот документ — инструкция по слоям: домен → schema (Pydantic)
> → repository → service → route → dependency, с порядком милестоунов и тестами.

---

# 1. Текущее состояние

**Готово и работает:**
- Auth: `POST /auth/request-otp`, `POST /auth/verify`, `POST /auth/refresh`,
  `POST /auth/logout`, `GET /auth/me` (OTP email/phone по Redis + RabbitMQ-нотификации).
- `Account`, `AccountIdentity`, `Role`, `Permission`, `AccountRole`, `RolePermission`,
  `Patient`, `Specialist`, `Specialty`, `SpecialistSpecialty`, `Organization`,
  `OrganizationMembership`, `MedicalRecord`, `Document`, `DocumentVersion`,
  `DocumentProcessingJob`, `DocumentExtraction`, `PatientAccessGrant`, `AuditLog` —
  модели SQLAlchemy + миграция `0002` (проверена на PG, downgrade-safe).
- Конвенции: `Base` из `apps/account-api/app/core/database.py`; enums в `apps/account-api/app/domain/`; `utcnow()`
  из `apps/account-api/app/models/utils.py`; репозиторий = класс на `AsyncSession`; сервис = бизнес-логика.

**Пустые заглушки (создать):** `apps/account-api/app/api/v1/documents.py`, `jobs.py`, `users.py`;
`apps/account-api/app/services/documents.py`, `jobs.py`, `storage.py`.

---

# 2. Слои и правила добавления кода

```text
domain (enums, aggregate-правила)         apps/account-api/app/domain/*
  │
Pydantic schema (request/response)        apps/account-api/app/schemas/<domain>.py
  │
repository (только SQL, без логики)       apps/account-api/app/repositories/<entity>.py
  │
service (инварианты, события, commit)     apps/account-api/app/services/<domain>.py
  │
router (HTTP, Depends, ошибки→HTTP)       apps/account-api/app/api/v1/<resource>.py
  │
dependencies (auth/ABAC/RBAC)             apps/account-api/app/dependencies/*
```

Правила:
- **Репозиторий не коммитит** — только select/insert/flush, возвращает модели или ORM-объекты.
- **Сервис коммитит** один раз в конце операции, поднимает доменные исключения
  (например `PatientAccessDeniedError`), которые router преобразует в `HTTPException`.
- **Enum-значения** переиспользуются из `apps/account-api/apps/account-api/app/domain/*` (тип-безопасно).
- **Доступ** к чужим данным всегда через dependency `require_patient_access` (§7), не вручную.
- **JSON-колонки** (`data`, `metadata`) — `sa.JSON` (портативно, тесты на sqlite).

---

# 3. Milestone M1 — RBAC: seed ролей/прав + админ-управление

Цель: роли и права существуют в БД, выдаются аккаунтам, проверяются зависимостями.

### Schemas — `apps/account-api/app/schemas/rbac.py`
`RoleResponse`, `PermissionResponse`, `RoleCreate`, `PermissionCreate`,
`AccountRoleAssignRequest` (role_codes: list[str]), `AccountRolesResponse`.

### Repositories — `apps/account-api/app/repositories/rbac.py` (новый)
`RbacRepository`:
- `list_roles() / list_permissions()`
- `get_role_by_code(code) / get_permission_by_code(code)`
- `seed_defaults()` — идемпотентно создаёт роли (`RoleCode`) и права (`PermissionCode`),
  связи `RolePermission` (client → document.read/upload/download, medical_record.read;
  specialist → + encounter.*, medical_record.write, analytics.read; system_admin → всё).
- `assign_roles(account_id, role_codes)`, `list_account_roles(account_id)`
- `account_permissions(account_id) -> set[PermissionCode]` (join через role_permissions).

### Service — `apps/account-api/app/services/rbac.py`
`RbacService`: `seed()` (вызывается в `lifespan` при старте), `assign_roles`, `get_permissions`.
Исключения: `RoleNotFoundError`, `PermissionNotFoundError`.

### Routes — `apps/account-api/app/api/v1/admin.py` (+ регистрация в `api/v1/__init__.py`)
- `POST /admin/rbac/seed` (вручную/для тестов)
- `POST /admin/accounts/{id}/roles` — выдать роли
- `GET /admin/accounts/{id}/roles`
- `GET /admin/accounts/{id}/permissions`

### Dependencies — `apps/account-api/app/dependencies/rbac.py`
- `require_roles(*codes)` — проверяет `AccountRole` текущего аккаунта → иначе `403`.
- `require_permission(code)` — проверяет права через RBAC → `403`.

---

# 4. Milestone M2 — Person + Patient + MedicalRecord (регистрация пациента)

### Schemas — `apps/account-api/app/schemas/profile.py`, `apps/account-api/app/schemas/patient.py`
`PersonResponse`, `PersonUpdate` (first/last/middle_name, date_of_birth, sex);
`PatientResponse` (id, person, medical_record_id, status);
`PatientCreateRequest` (брать person из аккаунта или создать).

### Repositories
- `apps/account-api/app/repositories/person.py` → `PersonRepository(session)`: `get(id)`, `save(person)`.
- `apps/account-api/app/repositories/patient.py` → `PatientRepository(session)`: `create(person_id)`,
  `get_by_id`, `get_by_person_id`, `get_by_account(account_id)` (через account.person_id)
  + фабричный метод `PatientRepository.create_with_medical_record(...)`, создающий
  `Patient` **и** `MedicalRecord` в одной транзакции (инвариант: пациент ⇒ есть карта).

### Service — `apps/account-api/app/services/patient.py`
`PatientService`:
- `ensure_patient_for_account(account)` — если у аккаунта ещё нет пациента, создать
  `Person` (из данных аккаунта, имя можно пустое), привязать `account.person_id`,
  создать `Patient` + `MedicalRecord`. Идемпотентно.
- `get_patient(account)` — доступ только к "своему" пациенту.
- `update_person(account, data)`.
Исключения: `PatientAlreadyExistsError`, `PersonNotFoundError`.

### Routes — `apps/account-api/app/api/v1/patients.py`
- `GET /patients/me` → `PatientResponse` (создаёт при первом обращении)
- `PATCH /patients/me` → обновить person
- `GET /patients/{id}` — только владелец (account.person_id == patient.person_id)
  **или** специалист с access grant.

---

# 5. Milestone M3 — Documents + Versions + Storage + Processing Jobs

Цель: пациент/врач загружают файл, создаётся `Document`, `DocumentVersion`,
ставится `DocumentProcessingJob`, публикуется `document_uploaded` в шину.

### Schemas — `apps/account-api/app/schemas/document.py`
`DocumentCreate` (medical_record_id, encounter_id?, document_type, title,
original_filename, mime_type, size_bytes), `DocumentResponse`,
`DocumentVersionResponse`, `UploadUrlResponse` (upload_url, storage_key),
`DocumentExtractionResponse`, `JobResponse`.

### Repositories — `apps/account-api/app/repositories/document.py`
`DocumentRepository`: `create(...)`, `get(id)`, `list_by_medical_record(mr_id)`,
`list_by_encounter(enc_id)`, `count_owned(medical_record_id)` (для квоты).
`DocumentVersionRepository`: `create(document_id, version, s3_key, ...)`,
`list_by_document`, `latest(document_id)`.
`ProcessingJobRepository`: `create(document_id, version_id, job_type)`, `get`, `update_status`.
`ExtractionRepository`: `save(extraction)`, `list_by_document`.

### Service — `apps/account-api/app/services/documents.py` (заполнить заглушку)
`DocumentService` (замыкается на `pdf-storage` + `pdf-messaging` + `pdf-contracts`):
- `create_upload(document, account)` — сохранить метаданные, сформировать
  `storage_key` (`medical-records/<mr>/<doc>/v1.<ext>`), вернуть presigned upload URL.
- `finalize_upload(document_id, account)` — создать `DocumentVersion` v1, статус
  `uploaded`, создать `DocumentProcessingJob(PDF_CONVERSION)`, опубликовать
  `DocumentUploaded` (контракт из `pdf-contracts`), установить `Document.status=processing`.
- `add_version(document_id, account)` — новая версия + job.
- `get_document(account, id)`, `list_documents(account, mr_id)` — с проверкой доступа.
- Квота: `is_subscribed` — лимит 10 документов (как в README) для не-подписчиков.

Врачи-специалисты после приёма: документ с `uploaded_by_account_id=специалист`,
`encounter_id=<приём>` — права проверяются через access grant (`can_upload_documents`).

### Routes — `apps/account-api/app/api/v1/documents.py` (заполнить заглушку)
- `POST /patients/{patient_id}/documents` → `UploadUrlResponse`
- `POST /documents/{id}/upload-confirm` → финализация (+ событие в шину)
- `GET /documents/{id}` , `GET /documents/{id}/versions`
- `POST /documents/{id}/versions`
- `GET /documents/{id}/extractions`

### Jobs status — `apps/account-api/app/api/v1/jobs.py`, `apps/account-api/app/services/jobs.py`
- `GET /jobs/{id}` — статус обработки (`document_processing_jobs`).
- `GET /documents/{id}/jobs` — список job'ов документа.
(Ответы ai-worker/marker-worker приходят событиями `document_converted`,
`document_analysis_requested` → обработчик обновляет `DocumentProcessingJob` / `DocumentExtraction`.)

---

# 6. Milestone M4 — Encounters

### Schemas — `apps/account-api/app/schemas/encounter.py`
`EncounterCreate` (type, started_at, reason, summary?), `EncounterResponse`,
`EncounterUpdate` (status, ended_at, summary).

### Repository — `apps/account-api/app/repositories/encounter.py`
`EncounterRepository`: `create`, `get`, `list_by_medical_record(mr_id)`, `update`.

### Service — `apps/account-api/app/services/encounter.py`
`EncounterService`:
- `create_encounter(account, patient_id, data)` — только специалист с
  `can_create_encounters` или владелец; заполняет `specialist_id` из аккаунта
  (аккаунт → person → specialist), `organization_id` из членства (если есть).
- `get_encounter(account, id)` — владелец или grant-получатель.
- `update_encounter(account, id, data)` (status/ended_at/summary) — владелец пациента
  или специалист с grant `can_edit_medical_data`.
Исключения: `EncounterNotFoundError`, `EncounterAccessDeniedError`.

### Routes — `apps/account-api/app/api/v1/encounters.py`
- `POST /patients/{id}/encounters`
- `GET /patients/{id}/encounters`
- `GET /encounters/{id}`
- `PATCH /encounters/{id}`
- `GET /encounters/{id}/documents` — документы приёма

---

# 7. Milestone M5 — Access Grants + ABAC + Audit Log

Цель: "Dr. Ivanov имеет право видеть карту пациента №123" — явная таблица + аудит.

### Schemes — `apps/account-api/app/schemas/access.py`, `apps/account-api/app/schemas/audit.py`
`AccessGrantCreate` (account_id/специалист, organization_id?, flags, access_reason,
expires_at?), `AccessGrantResponse`, `AccessGrantUpdate`; `AuditLogResponse`.

### Repository — `apps/account-api/app/repositories/access.py`, `apps/account-api/app/repositories/audit.py`
`AccessGrantRepository`: `create`, `get`, `list_by_patient(patient_id)`,
`find_active_for(patient_id, account_id)`, `revoke`.
`AuditLogRepository`: `record(entry)`, `query(patient_id, actor, action, limit, offset)`.

### Service — `apps/account-api/app/services/access.py`, `apps/account-api/app/services/audit.py`
`AccessService`: `grant(patient_id, account_id, flags, ...)`,
`revoke(grant_id)`, `check(patient_id, account_id, *perms) -> bool`
(правило: `status=active AND (expires_at IS NULL OR expires_at>now) AND flag`).
`AuditService`: обёртка — `record(action, resource_type, resource_id, patient_id, actor, request)`;

### Dependencies — `apps/account-api/app/dependencies/access.py` (ядро ABAC)
`require_patient_access(patient_id, *, can_view_documents=False, can_upload_documents=False,
can_view_extractions=False, can_view_analytics=False, can_create_encounters=False,
can_edit_medical_data=False)` — логика проверки (§33):

```text
authenticated                (get_current_account)
AND account.status==active
AND (role in {specialist} ИЛИ владелец пациента)
AND patient_access_grant существует
AND grant.status==active
AND (grant.expires_at IS NULL OR grant.expires_at > now())
AND grant.required_flag == True
AND resource принадлежит medical_record пациента
```

Несоблюдение → `403` (или `404`, чтобы не раскрывать существование пациента).

### Routes — `apps/account-api/app/api/v1/access.py`
- `POST /patients/{id}/access-grants` (владелец пациента)
- `GET /patients/{id}/access-grants`
- `PATCH /patients/{id}/access-grants/{gid}`
- `DELETE /patients/{id}/access-grants/{gid}` — отзыв (status=revoked)

### Audit wall
- В `dependencies/access.py` каждый успешный/отказанный доступ пишет `AuditLog`
  (action `VIEW_PATIENT`, `VIEW_DOCUMENT`, `VIEW_MEDICAL_RECORD`, `GRANT_ACCESS`...).
- `POST /auth/verify|refresh` → `LOGIN`; `POST /auth/logout` → `LOGOUT`.
- Router `apps/account-api/app/api/v1/audit.py`: `GET /audit-logs?patient_id=&actor_id=&limit=` (admin).

---

# 8. Milestone M6 — аналитика (деferred)

Добавить по мере развития (модели НЕ созданы; дизайн в [DB_MODELS.md](../data/DB_MODELS.md) §deferred):
- `observations`, `diagnoses`, `medications`, `patient_consents` — миграция `0003`.
- Сервисы: из `DocumentExtraction.data` выплескивать нормализованные `Observation`
  (value_numeric/text/unit, reference_low/high, observed_at, source_document/encounter),
  затем `analytics.read` + графики.
- `patient_consents` — отдельно от Access (`ConsentService`).

---

# 9. Порядок реализации и зависимости

```text
M1 RBAC ──▶ M2 Person/Patient/MR ──▶ M3 Documents+Storage ──▶ M4 Encounters
                                                        │
M5 AccessGrant+Audit ◀───────────────────────────────────┘   (ABAC-зависимость
    │                                                         обязательна до выпуска M3/M4)
M6 analytics (deferred)
```

Зависимости:
- M3 и M4 **не публиковать** без M5-dependency `require_patient_access`
  (иначе утечка данных). M5 можно реализовывать параллельно.
- Storage/шина из пакетов: `pdf-storage` (presign), `pdf-messaging`, `pdf-contracts`
  (события `document_uploaded`, `document_converted`, `document_analysis_requested`).

---

# 10. Тестирование

- **unit (domain + service)**: state-машины статусов, инварианты Patient⇒MedicalRecord,
  правила grants, ротация версий документа. sqlite `create_all` (без миграций).
- **API (fixture `app_client`)**: по образцу `tests/test_auth_flow.py` —
  регистрация пациента, загрузка документа, создание encounter, выдача/отзыв гранта,
  отказ по `403` у специалиста без гранта.
- **RBAC**: seed идемпотентен; account без роли → `403` на admin.
- **path**: `uv run --project apps/account-api pytest apps/account-api` + `uvx ruff check apps`.
- Переключатель `ai_feature`/мессенджеры — мокать в тестах (как `RabbitNotificationGateway(None)`).

---

# 11. Чек-лист правил безопасности (инварианты RV)

- [ ] Ни один route медицинских данных не отдаёт чужие карты без `require_patient_access`.
- [ ] `PatientAccessGrant` проверяется и по `expires_at`, и по `status`.
- [ ] `system_admin` **не** получает автоматический доступ к медкартам (least privilege);
      при необходимости — отдельный `medical_data_admin` + audit.
- [ ] Каждый доступ/отказ пишется в `audit_logs` (actor, patient, action, ip, user_agent).
- [ ] Refresh-токены хранятся только как HMAC (`hash_refresh_token`), никогда в plain. (Уже так.)
- [ ] Presigned upload без подтверждения `upload-confirm` не создаёт активный «просматриваемый» документ.