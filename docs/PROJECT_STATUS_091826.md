# Текущее состояние проекта — анализ из кода

## Медицинская платформа персональной медицинской истории

**Версия документа:** 3.0
**Дата:** 18 сентября 2026
**Основание:** документ написан по результатам фактического анализа исходного кода monorepo (`apps/`, `packages/`, `migrations/`, `docs/`) после реализации организационно-интеграционного контура (фазы 1–4i), а не по продуктовой концепции.
**Продуктовая концепция:** `docs/DDPROJECT.md`
**Предыдущий снимок:** `docs/PROJECT_STATUS_090526.md` (5 сентября 2026, анализ по коду)
**Профильные документы:** `docs/development/ORGS/IMPL_ARCH.md`, `IMPL_SPEC.md`, `IMPL_PLAN.md`, `IMPL_RPRT.md`

> **Метка состояния:**
> - `[x]` — реализовано и работает в коде
> - `[~]` — почти готово (есть рабочий фундамент, не хватает последнего слоя / части workflow)
> - `[ ]` — не реализовано / отложено

---

# 1. Executive Summary

С прошлого снимка (5 сентября) проект сделал крупный шаг: **полностью реализован backend-контур «Организация → Интеграция»** (фазы 1–4i, коммиты `9b683b7` → `04041cc`, миграции `0006`–`0016`). Доменная модель `Organization` превращена в полноценный продуктовый срез: онбординг администратором платформы, организационно-ролевая авторизация, управление филиалами/лицензиями/API-ключами/схемами документов, машинная интеграция загрузки документов и серверные уведомления.

Общее состояние:

1. **Backend и доменная модель развиты.** ~29 таблиц, **68 API-эндпоинтов** (было 34), OTP-авторизация (Redis), RBAC + ABAC (`PatientAccessGrant`), организационно-ролевой контур (`OrganizationMembership.role`), audit log, presigned download, событийная шина RabbitMQ.
2. **Организационный контур закрыт на уровне backend** (фазы 1–4i): legal data (ИНН/ОГРН с checksum), филиалы, лицензии, machine-to-machine API-ключи, admin-онбординг организаций, контекст/членство, integration API (single + bulk), схемы документов, мониторинг/usage, точка расширения верификации.
3. **Уведомления реализованы на сервере.** Таблица `notifications`, домен `NotificationType` (document_received / document_processed / document_processing_failed), отправка через `notification-worker` (console/SMTP), round-trip доставки; клиент получает письмо с названием организации и защищённой ссылкой — **без медицинских данных**.
4. **Веб-кабинет клиента (MVP-1) без изменений** — OTP-вход, дашборд, документы, просмотр извлечённых данных, медкарта, профиль. **UI организации / администратора платформы и UI уведомлений отсутствуют** — это следующая фронтенд-задача (см. `IMPL_RPRT.md` §7).
5. **AI-конвейер без изменений** (PyMuPDF OCR → классификация → LLM extraction → `canonical.json` + `structured.md`). `marker-worker` / `marker-orchestrator` — по-прежнему заглушки 0 байт.
6. **Qdrant / embeddings / chunking, medical normalization, analytics — не реализованы** (`ai-worker/app/pipeline/*` пуст, deferred-таблицы не миграциированы).
7. **Специалист — фундамент есть, продуктового API/UI нет.** Уведомления, org-модель и оргавторизация при этом уже готовы.
8. **`packages/observability`, integration-тесты, retry/DLQ redrive — не реализованы.**

Стадия проекта наиболее точно описывается как:

> **«Client MVP + закрытый backend-контур Organisation/Integration; не закрыты: UI организационного управления, specialist workflow, UI управления доступом, уведомления в веб-интерфейсе, medical normalization, analytics, embeddings/Qdrant, GPU-конвейер Marker.»**

---

# 2. Какой продукт мы строим (из `DDPROJECT.md`)

Платформа — единое цифровое пространство для персональной медицинской истории:

```text
CLIENT ──► MEDICAL HISTORY ◄── ORGANISATION
              │                    │
              ▼                    ▼
          DOCUMENTS           SPECIALIST
          ENCOUNTERS
          LAB/STUDIES
          DIAGNOSES
          PRESCRIPTIONS
```

Финальные продуктовые этапы (по `DDPROJECT.md` §41):
1. Login + Document storage + Processing
2. Structured medical data + Simple analytics
3. Specialists + Access control + Organisation
4. Organisation → Client document delivery + Notifications
5. Unified medical history
6. AI analysis
7. AI assistant for specialists

Снимок показывает: этапы 1 и 4 закрыты преимущественно на backend; этап 3 частично (Organisation backend готов, Specialists — нет).

---

# 3. Фактическое состояние по слоям

## 3.1 Миграции и БД

Миграции `migrations/alembic/versions/` — **16 штук** (`0001_initial` … `0016_organization_api_request_usage_index`).

| Проверка | Статус |
|---|---|
| `0001_initial` — `users`, `auth_sessions` | `[x]` |
| `0002_medical_models` — вся MVP-модель, `users`→`accounts`, `organizations`/`organization_memberships` | `[x]` |
| `0003_simplify_person` — `persons` | `[x]` |
| `0004_document_date` + `0005_document_date_backfill` | `[x]` |
| `0006`–`0016` — организационно-интеграционный контур (см. §3.2) | `[x]` |
| `observations` / `diagnoses` / `medications` / `patient_consents` (deferred) | `[ ]` |

Итого ~29 таблиц; `0006`–`0016` добавили 8 новых таблиц (branches, licenses, api_keys, api_requests, upload_batches, upload_batch_items, document_schemas, notifications) и расширили `organizations`/`organization_memberships`/`documents`.

## 3.2 Доменная модель (`apps/account-api/app/models/`, 17 файлов-моделей)

| Сущность | Таблица | Статус |
|---|---|---|
| Account | `accounts` | `[x]` |
| AccountIdentity | `account_identities` (создана, в auth-флоу не используется) | `[x]` (модель) / `[~]` |
| Person / Patient / MedicalRecord | `persons`, `patients`, `medical_records` | `[x]` |
| Specialist + Specialty + SpecialistSpecialty | `specialists`, `specialties`, `specialist_specialties` | `[x]` (модель) / `[ ]` (API/UI) |
| Organization + OrganizationMembership | `organizations`, `organization_memberships` (+ `role`, `created_by_account_id`) | `[x]` (backend) / `[ ]` (UI) |
| **OrganizationBranch** (фаза 2) | `organization_branches` | `[x]` |
| **OrganizationLicense** (фаза 3) | `organization_licenses` | `[x]` |
| **OrganizationApiKey** (фаза 4) | `organization_api_keys` | `[x]` |
| **OrganizationApiRequest** (фаза 4c) | `organization_api_requests` | `[x]` |
| **OrganizationUploadBatch / Item** (фаза 4e) | `organization_upload_batches`, `…_items` | `[x]` |
| **OrganizationDocumentSchema** (фаза 4g) | `organization_document_schemas` (versioned, immutable publish) | `[x]` |
| **Notification** (фаза 4f) | `notifications` (type/status/channel) | `[x]` |
| Document / DocumentVersion / DocumentExtraction / DocumentProcessingJob | `documents`, `document_versions`, `document_extractions`, `document_processing_jobs` (+ org source columns: `organization_id`, `organization_branch_id`, `external_id`, `idempotency_key`, `provided_document_type`) | `[x]` |
| Encounter | `encounters` | `[x]` |
| PatientAccessGrant | `patient_access_grants` | `[x]` |
| Role / Permission / AccountRole / RolePermission | RBAC | `[x]` |
| AuditLog / AuthSession | `audit_logs`, `auth_sessions` | `[x]` |

**Вывод:** доменная модель организации полностью реализована и продублирована в миграциях; `organization_admin` как глобальная RBAC-роль **намеренно не используется** — управление идёт через `OrganizationMembership.role ∈ {owner, admin, member}`.

## 3.3 API (`apps/account-api/app/api/v1/`, префикс `/api/v1`) — 68 эндпоинтов

| Контур | Эндпоинты | Статус |
|---|---|---|
| Auth | `POST /auth/request-otp`, `POST /auth/verify`, `POST /auth/refresh`, `POST /auth/logout`, `GET /auth/me` | `[x]` |
| Patients | `POST /patients`, `GET/PATCH /patients/me`, `GET /patients/{id}` | `[x]` |
| Documents | list / create (upload) / get / versions / extractions / jobs / download / markdown / canonical | `[x]` |
| Encounters | create / list / get / patch / documents-by-encounter | `[x]` |
| Access grants | create / list / patch / revoke (`/patients/{id}/access-grants*`) | `[x]` |
| Jobs / Audit / Admin-RBAC | `GET /jobs/{id}`; `GET /audit-logs`; seed/assign/list roles | `[x]` |
| **Admin organizations** (4a) | `POST|GET /admin/organizations`, `GET /admin/organizations/{id}`, `POST|GET /admin/organizations/{id}/members` (`system_admin`) | `[x]` |
| **Organization context** (4b) | `GET /organizations`, `GET /organizations/{id}`, `GET /organizations/{id}/members` | `[x]` |
| **Organization management** (1–3, 4g, 4h) | `/organizations/me` (get/patch), `/me/branches*`, `/me/licenses*`, `/me/api-keys*` (+rotate), `/me/schemas*` (+publish), `/me/api-usage` | `[x]` |
| **Integration** (4c–4e) | `POST /integration/documents`, `POST /integration/documents/bulk`, `GET /integration/documents/{id}`, `GET /integration/batches/{id}` (+`/items`) | `[x]` |
| Users | `users.py` — пустой файл (0 байт), роутер не подключён | `[ ]` |

Итого 34 базовых + 34 организационных/интеграционных. Отсутствуют: специалист API, medical-record API, delete document, notification read API.

## 3.4 Авторизация и доступ

| Компонент | Статус |
|---|---|
| OTP (6 цифр, Redis, TTL 300s, 5 попыток, rate-limit 1/60s) | `[x]` |
| Доставка OTP через RabbitMQ → notification-worker (console/SMTP) | `[x]` |
| JWT access (HS256, 15 мин) + opaque refresh (HMAC в БД, ротация) | `[x]` |
| RBAC: client / specialist / system_admin / support; `organization_admin` глобально не выдаётся | `[x]` |
| **Организационно-ролевой контур:** `OrganizationMembership.role` (owner/admin/member) — источник прав на `/organizations/me/*` | `[x]` |
| **Выбор текущей организации:** `X-Organization-Id` при нескольких членствах (ambiguous → 400, unknown → 404) | `[x]` |
| **Policy интеграции:** `status = active` необходимо, но недостаточно; `verification_status = rejected` блокирует | `[x]` |
| **Machine-to-machine:** `Bearer <api-key>` + 4 scope (`documents.upload`, `documents.bulk_upload`, `documents.read`, `jobs.read`), rate-limit 120/мин → 429 | `[x]` |
| ABAC: `PatientAccessGrant` + флаги (view/upload/extractions/analytics/encounters/edit) | `[x]` |
| Audit allow/deny по всем access dependency | `[x]` |

## 3.5 Обработка документов — фактический конвейер

Реализована двухстадийная схема без Marker: `objectstorage-worker` → S3 → `ai-worker` (OCR + extraction) → `account-api` (persistence). Организационные документы проходят **тот же** конвейер и дополнительно резолвят пациента по email и обогащаются org-source полями.

| Звено | Компонент | Статус |
|---|---|---|
| 1 | upload (client) или `POST /integration/documents` (machine) → staging + Document + job | `[x]` |
| 2 | `objectstorage-worker` — валидация mime/size (≤50 МБ), SHA-256, S3 immutable key, `document.stored` | `[x]` |
| 3 | `account-api` consumer → PROCESSING, re-publish `document.uploaded` | `[x]` |
| 4 | `ai-worker` PyMuPDF (300 dpi) → OCR → `marker.md` (S3), `document.converted` | `[x]` |
| 5 | `ai-worker` классификация → LLM extraction → Pydantic → `canonical.json` + `structured.md`, `document.analysis.completed` | `[x]` |
| 6 | `account-api` consumer → `document_extractions.data`, COMPLETED/FAILED, `document_date` | `[x]` |
| 7 | Терминальный статус → `NotificationService` уведомляет клиента (org-документы, 4f) | `[x]` |
| — | Bulk: `POST /integration/documents/bulk` (≤100) → batch/items → те же звенья | `[x]` |
| — | `marker-worker` / `marker-orchestrator` | `[ ]` заглушки 0 байт |
| — | chunking / embeddings / Qdrant | `[ ]` (`pipeline/*` пуст) |
| — | retry/DLQ redrive (DLQ создаётся, redrive нет) | `[ ]` |

## 3.6 Пакеты (`packages/`)

| Пакет | Статус |
|---|---|
| `canonical` — registry, Laboratory/Prescription/Generic, metadata, детерминированный render | `[x]` |
| `contracts` — события (OTP, upload, convert/analysis, processing failed, **org document submitted/processed, batch events**) | `[x]` |
| `messaging` — Publisher/Consumer, durable queues + DLQ, prefetch 10 | `[x]` |
| `storage` — CloudS3 (boto3, cloud.ru), immutable keys, presigned, markdown-артефакты | `[x]` |
| `observability` — structlog/metrics | `[ ]` заглушка (0 байт) |

## 3.7 Веб-фронтенд (`apps/web`, React + Vite, RU-only)

| Элемент | Статус |
|---|---|
| OTP: `/login` → `/login/verify` | `[x]` |
| Токены: access в памяти, refresh в localStorage, silent-refresh | `[x]` |
| Дашборд / Документы / Загрузка (XHR-прогресс) / Детали документа | `[x]` |
| Просмотр canonical: лаборатория и рецепт | `[x]` |
| Медкарта: read-only overview + вкладка «Документы» | `[x]` |
| Профиль: редактирование person (PATCH), выход | `[x]` |
| Поллинг обработки до терминального статуса | `[x]` |
| UI управления доступом (access grants) | `[ ]` (эндпоинты есть, UI нет) |
| **UI специалиста** | `[ ]` |
| **UI администратора платформы (онбординг организаций)** | `[ ]` — контракт готов в `IMPL_RPRT.md` §7.1 |
| **UI управления организацией (owner/admin)** | `[ ]` — контракт готов в `IMPL_RPRT.md` §7.2 |
| **UI уведомлений / delete document** | `[ ]` (намеренно вне MVP-1) |

Текущие маршруты: `login`, `login/verify`, `/` (дашборд), `documents`, `documents/:documentId`, `medical-record`, `profile`. Организационных/admin-маршрутов нет. UI-примитивы: button, input, card, select, tabs, badge, menu, label, separator, skeleton.
`apps/web/src/lib/api/schema.d.ts` устарел (сгенерирован до org-работ) — перед фронтендом нужен `npm run generate:api`.

**Покрытие тестами фронтенда:** 16 unit-файлов vitest + 2 Playwright E2E — без изменений.

## 3.8 Уведомления

| Канал | Статус |
|---|---|
| OTP-доставка (console / SMTP через notification-worker) | `[x]` |
| **Продуктовые уведомления о документах** (`document_received`, `document_processed`, `document_processing_failed`): таблица `notifications`, домен, `NotificationService`, round-trip доставки `notification.delivered` | `[x]` |
| UI уведомлений в кабинете | `[ ]` |
| Уведомления о прочих событиях (encounters, grants, specialist) | `[ ]` |

## 3.9 Инфраструктура

| Слой | Статус |
|---|---|
| Dev compose: postgres, rabbitmq, redis, db-migrate, account-api, notification-worker, objectstorage-worker, ai-worker (opt-in) | `[x]` |
| Main VPS compose: nginx (SPA + `/api`), account-api, orchestrator (*stub*), ai-worker, notification-worker, objectstorage-worker, postgres, qdrant | `[~]` — qdrant подключён, кодом не используется |
| Rabbit VPS compose (broker-only, tailnet-only) | `[x]` |
| GPU (Marker) VPS: compose, systemd, скрипты | `[x]` (инфра) / `[ ]` (приложение-заглушка) |
| CI/CD: test.yml, build.yml, deploy-main.yml, deploy-marker.yml | `[x]` |

## 3.10 Организационно-интеграционный контур (фазы 1–4i)

Реализовано с 5 сентября (11 миграций, 15 коммитов):

| Фаза | Что закрыто |
|---|---|
| 1 (`0006`) | Legal data: ИНН/ОГРН, канонизация + checksum, enums, `GET/PATCH /organizations/me` |
| 2 (`0007`) | Филиалы: CRUD `/organizations/me/branches`, soft-deactivate, уникальный `code` |
| 3 (`0008`) | Лицензии: CRUD, статусы, авто-`expired` при чтении |
| 4 (`0009`) | API-ключи: CRUD + rotate, raw-ключ показывается один раз |
| 4a (`0010`) | Admin-онбординг: `POST /admin/organizations` («Create and connect»), члены, audit |
| 4b | Org-context API, membership-role авторизация, `X-Organization-Id` |
| 4c (`0011`) | API-key auth middleware, policy верификации, rate-limit, request log |
| 4d (`0012`) | Integration single upload + patient resolver по email, org-source колонки |
| 4e (`0013`) | Bulk upload (≤100), batches/items, batch-события, org-scoped чтения |
| 4f (`0015`) | Notifications: таблица/домен/сервис, worker send_message, delivery round-trip |
| 4g (`0014`) | Document schemas: versioned CRUD + immutable publish |
| 4h (`0016`) | API usage monitoring: daily aggregates + retention purge, `/me/api-usage` |
| 4i | Точка расширения верификации (`OrganizationRegistryProvider` Protocol), ownership anchor |

**Тесты:** account-api **501 passed** (было 490), notification-worker 11; `ruff` чист по org-путям. Новые тест-файлы: admin/context/integration/monitoring/schemas/bulk upload + unit (patient resolver, registry, INN/ОГРН, notifications, api usage).
Документация контура консолидирована в `docs/development/ORGS/` (ARCH/SPEC/PLAN/**RPRT**).

---

# 4. Что почти готово (checkboxes «хочется добить»)

- [~] **Специалист:** модели + RBAC-роль + ABAC-грант + audit + org-авторизация готовы. Не хватает: CRUD-API профиля специалиста, UI, workflow «пациент → encounter → документ».
- [~] **Уведомления:** серверный контур документных уведомлений полностью готов; не хватает UI и уведомлений по не-документным событиям.
- [~] **Управление доступом (UI):** полный backend (`PatientAccessGrant` CRUD + ABAC + audit) готов. Не хватает экрана в кабинете клиента.
- [~] **Encounters в продукте:** API + модель + авто-резолв организации готовы. Не хватает UI.
- [~] **Удаление документа:** в вебе есть disabled-кнопка. Не хватает backend-эндпоинта delete + soft-delete lifecycle.
- [~] **`AccountIdentity`:** модель создана, auth-флоу по-прежнему использует колонки `accounts`.
- [~] **VPS-продакшн:** compose и CI/CD готовы; `marker-*` — заглушки, бэкапы/мониторинг/retention — TODO (retention usage-данных уже реализован в 4h).

---

# 5. Что не реализовано (следующие этапы)

- `[ ]` **UI администратора платформы и UI управления организацией** — backend полностью готов, требуется фронтенд (контракт: `IMPL_RPRT.md` §7).
- `[ ]` **UI управления доступом, UI уведомлений, delete document** в кабинете.
- `[ ]` **Specialist workflow:** API специалиста, UI, продуктовые сценарии.
- `[ ]` Medical normalization: `observations`, `diagnoses`, `medications` (deferred) — `DDPROJECT.md` §34–36.
- `[ ]` `patient_consents` (access ≠ consent, deferred) — §37.
- `[ ]` Analytics: тайм-серии показателей, тренды, графики.
- `[ ]` Embeddings + chunking + Qdrant.
- `[ ]` Retry/DLQ redrive (DLQ декларируется, redrive нет).
- `[ ]` Longitudinal AI, AI assistant для специалиста.
- `[ ]` `packages/observability` — заглушка.
- `[ ]` Integration-тесты (`tests/integration/` пуста, только `.gitkeep`).

---

# 6. Оценка зрелости по слоям

| Уровень | Состояние |
|---|---|
| Product concept | `[x]` (`DDPROJECT.md`) |
| Domain model / DB | `[x]` (~29 таблиц, 16 миграций) |
| OTP Auth + RBAC + ABAC + Audit | `[x]` |
| Documents / Versions / Jobs / Extraction | `[x]` |
| Access Grants (backend) | `[x]` |
| Encounters (backend) | `[x]` |
| Processing pipeline (S3 → OCR → canonical → PostgreSQL → API) | `[x]` |
| Canonical data model + validation + structured.md | `[x]` |
| Веб-кабинет клиента (MVP-1) | `[x]` |
| **Organisation / Integration (backend, фазы 1–4i)** | `[x]` |
| **Notifications (server-side, продуктовые)** | `[x]` |
| Specialist workflow | `[~]` (фундамент есть, API/UI нет) |
| Access management UI | `[~]` (backend готов) |
| **Organisation UI (admin + management)** | `[ ]` (backend готов, нужен фронтенд) |
| Notifications UI | `[ ]` |
| Medical normalization + Analytics | `[ ]` |
| Embeddings / Qdrant | `[ ]` |
| GPU-конвейер (Marker + orchestrator) | `[ ]` |
| Longitudinal AI / AI assistant | `[ ]` |
| Integration-тесты | `[ ]` |

---

# 7. Главный вывод

Проект прошёл ещё один крупный этап: **организационно-интеграционный контур закрыт на backend** и переиспользует уже проверенный конвейер обработки документов.

```text
Клиент:      OTP → upload → S3 → OCR → canonical.json → PostgreSQL → кабинет
Организация: admin-онбординг → membership-role → branches/licenses/keys/schemas
             └─ Integration API (machine, api-key) → тот же конвейер → уведомление клиенту
```

Следующий большой этап по продуктовой приоритетности (`DDPROJECT.md` §47–49):

```text
1. Организационный UI (кабинет владельца/админа) + UI администратора платформы
2. Specialist workflow (API + UI)
3. Access management UI + уведомления в кабинете
4. Medical normalization (observations/diagnoses/medications)
5. Analytics (тайм-серии)
6. Embeddings/Qdrant + GPU-конвейер Marker
7. Longitudinal AI / AI assistant
```

---

# 8. Источники фактов (карта кода)

| Слой | Где смотреть |
|---|---|
| Модели | `apps/account-api/app/models/*.py` (organization.py, notification.py — новые) |
| API | `apps/account-api/app/api/v1/*.py` (admin_organizations.py, organizations.py, integration.py) |
| Auth/OTP | `apps/account-api/app/services/{auth,otp}.py`, `core/security.py` |
| Доступ | `services/access.py`, `services/notifications.py`, `dependencies/{access,rbac}.py` |
| Организация | `services/` (organization/branches/licenses/api_keys/schemas/api_usage), `repositories/` |
| Документы | `services/documents.py`, `services/storage.py`, `services/patient_resolver.py` |
| Events | `consumers/document_events.py`, `consumers/notification_result.py`, `core/bus.py` |
| AI-конвейер | `apps/ai-worker/app/{main,processor,ai_client,doc_classifier,pdf_converter}.py` |
| Canonical | `packages/canonical/canonical/{schemas,metadata,render}.py` |
| Уведомления | `apps/notification-worker/app/{main.py,providers/*}` |
| Web | `apps/web/src/{app,features,lib}/` |
| Миграции | `migrations/alembic/versions/0001..0016*.py` |
| Профильные док-ты | `docs/development/ORGS/{IMPL_ARCH,IMPL_SPEC,IMPL_PLAN,IMPL_RPRT}.md` |
| Инфра | `infrastructure/*`, `Makefile`, `.github/workflows/` |
| Заглушки (0 байт) | `apps/marker-worker/app/*`, `apps/marker-orchestrator/app/*`, `apps/ai-worker/app/pipeline/*`, `packages/observability/*`, `apps/account-api/app/api/v1/users.py` |
