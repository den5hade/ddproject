# ACC_IMPLEMTATION.md — план реализации account-api: schemas, routes, services

> Статус: реализованы M1 (RBAC), M2 (Person/Patient/MR) и M3 (Documents+Storage+Jobs).
> Схема БД уже реализована (`../../migrations/alembic/versions/0002`, см. [DB_MODELS.md](../data/DB_MODELS.md)),
> auth-флоу работает. Этот документ — инструкция по слоям: домен → schema (Pydantic)
> → repository → service → route → dependency, с порядком милестоунов и тестами.

---

# 1. Текущее состояние

**Готово и работает:**
- Auth: `POST /auth/request-otp`, `POST /auth/verify`, `POST /auth/refresh`,
  `POST /auth/logout`, `GET /auth/me` (OTP email/phone по Redis + RabbitMQ-нотификации).
- **M1 RBAC** (§3): seed ролей/прав (идемпотентно, на старте + `POST /admin/rbac/seed`),
  выдача ролей, `require_roles` / `require_permission` (403), admin-руты.
- **M2 Person/Patient/MR** (§4): `POST /patients`, `GET|PATCH /patients/me`,
  `GET /patients/{id}` (владелец или активный access grant, иначе `404`).
- **M3 Documents+Storage+Jobs** (§5): `POST /patients/{patient_id}/documents` (multipart),
  `GET /documents/{id}`, `POST|GET /documents/{id}/versions`,
  `GET /documents/{id}/extractions`, `GET /documents/{id}/jobs`,
  `GET /documents/{id}/download`, `GET /jobs/{id}`; пайплайн
  upload→S3→convert→analysis через события RabbitMQ (см. §5) и
  фоновый consumer событий в `account-api`.
- **objectstorage-worker**: новый сервис `apps/objectstorage-worker` — консумит
  `document.upload.requested`, валидирует, считает sha256 и загружает файл в S3
  под immutable-ключом (`packages/storage` → `CloudS3`, `build_key`),
  публикует `document.stored` / `document.processing.failed`.
- `Account`, `AccountIdentity`, `Role`, `Permission`, `AccountRole`, `RolePermission`,
  `Patient`, `Specialist`, `Specialty`, `SpecialistSpecialty`, `Organization`,
  `OrganizationMembership`, `MedicalRecord`, `Document`, `DocumentVersion`,
  `DocumentProcessingJob`, `DocumentExtraction`, `PatientAccessGrant`, `AuditLog` —
  модели SQLAlchemy + миграция `0002` (проверена на PG, downgrade-safe).
- Конвенции: `Base` из `apps/account-api/app/core/database.py`; enums в `apps/account-api/app/domain/`; `utcnow()`
  из `apps/account-api/app/models/utils.py`; репозиторий = класс на `AsyncSession`; сервис = бизнес-логика.

**Пустые заглушки (создать):** `apps/account-api/app/api/v1/users.py`.

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
- **Enum-значения** переиспользуются из `apps/account-api/app/domain/*` (тип-безопасно).
- **Доступ** к чужим данным всегда через dependency `require_patient_access` (§7), не вручную.
- **JSON-колонки** (`data`, `metadata`) — `sa.JSON` (портативно, тесты на sqlite).
- **DI (FastAPI)**: провайдеры `get_*` живут в `apps/account-api/app/dependencies/*`.
  Внизу файла объявляется `Annotated`-алиас `<Name> = Annotated[<Class>, Depends(get_*)]`;
  роутеры в сигнатуре используют только имя алиаса (`account: CurrentAccount`,
  `service: PatientServiceDep`) без `Depends(...)`. Фабрики с аргументами
  (`require_roles`, `require_permission`) остаются `Depends(...)` в `dependencies=[...]`
  роутера. Обязательные `Annotated`-параметры ставятся до параметров со значением
  по умолчанию (синтаксис Python).

---

# 3. Milestone M1 — RBAC: seed ролей/прав + админ-управление

> **Статус: реализован.** `schemas/rbac.py`, `repositories/rbac.py`,
> `services/rbac.py`, `api/v1/admin.py`, `dependencies/rbac.py`, seed на старте
> (`main.py` lifespan) + unit/API-тесты (`test_rbac_repository.py`,
> `test_rbac_api.py`).

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

> **Статус: реализован.** `schemas/profile.py`, `schemas/patient.py`,
> `repositories/person.py`, `repositories/patient.py`, `services/patient.py`,
> `dependencies/patient.py`, `api/v1/patients.py` + unit/API-тесты
> (`test_patient_service.py`, `test_patients_api.py`).
> Отличия от плана: добавлен явный `POST /patients` (201 / 409;
> `PatientAlreadyExistsError`); `GET /patients/{id}` для не-владельца без гранта
> возвращает `404` (не раскрывает существование пациента). Inline-проверка гранта
> здесь — временная замена `require_patient_access` из M5 (см. §7).

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

> **Статус: реализован.** `schemas/document.py`, `repositories/document.py`,
> `services/documents.py`, `services/jobs.py`, `services/storage.py`,
> `dependencies/documents.py`, `api/v1/documents.py`, `api/v1/jobs.py`,
> `consumers/document_events.py` + тесты (`test_documents_api.py`,
> `unit/test_document_events.py`).
> Также созданы пакеты: `packages/storage` (`CloudS3`, `build_key`,
> `original_filename_for`, `ALLOWED_MIME_TYPES`), события в `packages/contracts`
> и новый сервис `apps/objectstorage-worker`.
>
> Отличия от плана: вместо presigned **upload**-URL загрузка идёт напрямую
> multipart-файлом в `account-api` (стейджится в общий temp-каталог
> `storage_temp_dir`), а в S3 его кладёт `objectstorage-worker` по событию
> `document.upload.requested`. Presigned **download**-URL выдаётся отдельным
> рутом. Инлайн-проверка гранта (owner или активный grant с
> `can_view_documents`/`can_upload_documents`) — временная замена
> `require_patient_access` из M5 (см. §7).

Цель: пациент/врач загружают файл, создаётся `Document`, `DocumentVersion`,
ставится `DocumentProcessingJob`, файл попадает в S3, публикуются события
пайплайна.

### Схема жизненного цикла документа
`pending` (после загрузки) → `processing` (файл сохранён в S3) →
`completed` (extraction успешна) / `failed` (ошибка пайплайна). Извлечения —
`DocumentExtraction` со `status`, `confidence`, `data` (JSON).

### Schemas — `apps/account-api/app/schemas/document.py`
`DocumentCreateRequest` (multipart-поля: document_type, title, encounter_id?),
`DocumentResponse`, `DocumentVersionResponse`, `DocumentExtractionResponse`,
`JobResponse`, `DownloadUrlResponse` (download_url, expires_in=900).

### Repositories — `apps/account-api/app/repositories/document.py`
`DocumentRepository`: `create(...)`, `get(id)`, `list_by_medical_record(mr_id)`,
`list_by_encounter(enc_id)`, `count_owned(medical_record_id)` (для квоты).
`DocumentVersionRepository`: `create(document_id, version, s3_key, ...)`,
`list_by_document`, `latest(document_id)`.
`ProcessingJobRepository`: `create(document_id, version_id, job_type)`, `get`,
`get_by_version`, `list_by_document`.
`ExtractionRepository`: `save(extraction)`, `get`, `list_by_document`.

### Service — `apps/account-api/app/services/documents.py`
`DocumentService` (замыкается на `packages/storage` + `packages/contracts` +
`messaging`):
- `create_document(account, patient_id, data, upload)` — проверка доступа
  (owner/grant `can_upload_documents`), квота 10 документов для не-подписчиков
  (`FREE_DOCUMENT_LIMIT`), валидация mime (`ALLOWED_MIME_TYPES`, иначе `415`) и
  размера (`max_upload_bytes`, иначе `413`), стейджинг в `storage_temp_dir`,
  создание `Document(pending)` + `DocumentVersion` v1 + `DocumentProcessingJob`,
  публикация `document.upload.requested`.
- `add_version(account, document_id, data, upload)` — новая версия
  (v = latest+1) + job, статус документа снова `pending`.
- `get_document(account, id)` — owner или grant `can_view_documents`, иначе `403`.
- `get_versions`, `get_extractions`, `get_download_url(account, id, version_id?)`
  — presigned GET (TTL 900 c), без `s3_key` → `404`.
- Обработчики событий: `on_document_stored` (пишет `s3_key`/`checksum`,
  статус → `processing`, публикует `document.uploaded`),
  `on_document_converted` (job → succeeded),
  `on_document_analysis_completed` (extraction + статус документа
  → `completed`/`failed`), `on_document_processing_failed` (job + документ → failed).
- Исключения: `DocumentNotFoundError`, `DocumentAccessDeniedError`,
  `DocumentQuotaExceededError` (429), `FileTooLargeError` (413),
  `UnsupportedFileTypeError` (415), `JobNotFoundError`.

### Service — `apps/account-api/app/services/jobs.py`
`JobService`: `get_job(account, id)`, `list_jobs(account, document_id)` —
проверка доступа делегирована `DocumentService.get_document`.

### Service — `apps/account-api/app/services/storage.py`
`StorageService` — адаптер над `packages/storage`; без настроек S3 поднимает
`StorageUnavailableError` (503 на руте download). `tenant_id()` из
`settings.s3_tenant_id`.

### Routes — `apps/account-api/app/api/v1/documents.py`
- `POST /patients/{patient_id}/documents` (multipart) → `201 DocumentResponse`
- `GET /documents/{id}` , `GET /documents/{id}/versions`
- `POST /documents/{id}/versions` (multipart) → `DocumentVersionResponse`
- `GET /documents/{id}/extractions`
- `GET /documents/{id}/jobs`
- `GET /documents/{id}/download?version_id=` → `DownloadUrlResponse`

### Jobs — `apps/account-api/app/api/v1/jobs.py`
- `GET /jobs/{id}` — статус обработки (`document_processing_jobs`).

### Consumers — `apps/account-api/app/consumers/document_events.py`
Фоновый consumer (стартует в `main.py` lifespan): подписка на
`document.stored`, `document.converted`, `document.analysis.completed`,
`document.processing.failed` (queue `document_events`, из
`settings.document_events_routing_keys`).

### Objectstorage-worker — `apps/objectstorage-worker`
Новый сервис (Docker-сервис в `infrastructure/main-vps/docker-compose.yml`,
общий temp volume): консумит `document.upload.requested`, проверяет mime/size,
считает sha256, кладёт файл в S3 под immutable-ключом
`tenants/<tenant>/patients/<patient>/documents/<doc>/versions/<version>/original.<ext>`
(`packages/storage.build_key`), публикует `document.stored`, при ошибке —
`document.processing.failed`. `CloudS3.ensure_bucket()` идемпотентно создаёт бакет.

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
  Сейчас в M3 проверка доступа инлайн в `DocumentService` (owner или активный grant) —
  при M5 заменить на `require_patient_access` (§7).
- Storage/шина из пакетов: `packages/storage` (`CloudS3`, presigned GET),
  `messaging` (publisher/consumer), `packages/contracts` (события
  `document.upload.requested`, `document.uploaded`, `document.stored`,
  `document.converted`, `document.analysis.completed`,
  `document.processing.failed`). Загрузку в S3 выполняет `objectstorage-worker`.

---

# 10. Тестирование

- **unit (domain + service)**: state-машины статусов, инварианты Patient⇒MedicalRecord,
  правила grants, ротация версий документа. sqlite `create_all` (без миграций).
- **API (fixture `app_client`)**: по образцу `tests/test_auth_flow.py` —
  регистрация пациента, загрузка документа, создание encounter, выдача/отзыв гранта,
  отказ по `403` у специалиста без гранта.
- **Documents**: `tests/test_documents_api.py` (upload/read-back, версии, jobs,
  quota `429`, `415` unsupported, `403` без гранта, download URL),
  `tests/unit/test_document_events.py` (sinks `document.stored`/`converted`/
  `analysis.completed`/`processing.failed`). objectstorage-worker:
  `apps/objectstorage-worker/tests/test_processor.py`; storage: `packages/storage/tests/test_keys.py`;
  contracts: `packages/contracts/tests/test_events.py`.
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
- [ ] Загруженный (pending) документ не отдаётся на download, пока не сохранён
      в S3 (`s3_key` заполняется только событием `document.stored`).