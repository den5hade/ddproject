# Текущее состояние проекта — анализ из кода

## Медицинская платформа персональной медицинской истории

**Версия документа:** 2.0
**Дата:** 5 сентября 2026
**Основание:** этот документ написан по результатам фактического анализа исходного кода monorepo (`apps/`, `packages/`, `migrations/`, `infrastructure/`, `docs/`), а не по продуктовой концепции.
**Продуктовая концепция:** `docs/DDPROJECT.md`
**Предыдущий снимок:** `docs/PROJECT_STATUS.md` (4 сентября 2026, создан LLM без доступа к коду)

> **Метка состояния:**
> - `[x]` — реализовано и работает в коде
> - `[~]` — почти готово (есть рабочий фундамент, не хватает последнего слоя / части workflow)
> - `[ ]` — не реализовано / отложено

---

# 1. Executive Summary

Анализ кода подтверждает: проект находится на уровне **рабочего MVP-фундамента с работающим вертикальным сценарием** «OTP-вход → загрузка документа → S3 → AI-обработка → canonical.json + structured.md → PostgreSQL → просмотр в веб-кабинете».

Ключевые выводы по факту кода (отличия от снимка от 4 сентября):

1. **Backend и доменная модель полностью реализованы.** 21 таблица, 34 API-эндпоинта, OTP-авторизация (Redis), RBAC + ABAC (`PatientAccessGrant`), audit log, presigned download, событийная шина RabbitMQ.
2. **Веб-кабинет клиента реализован (MVP-1).** OTP-вход, дашборд, список/детали документов, загрузка с прогрессом, просмотр извлечённых данных (лаборатория/рецепт), медкарта (overview), профиль. Покрыт unit-тестами (16 файлов) и Playwright E2E (проходят).
3. **AI-конвейер реализован внутри `ai-worker`** (PyMuPDF OCR → эвристическая классификация → LLM extraction → Pydantic-валидация через `packages/canonical` → canonical.json + structured.md). `marker-worker` (GPU Marker) **не реализован** — это заглушки 0 байт; инфраструктура под него готова (Dockerfile, compose, systemd, GPU-VPS).
4. **Qdrant / embeddings / chunking не реализованы** — папка `apps/ai-worker/app/pipeline/*` пустая.
5. **`marker-orchestrator` (GPU-оркестрация) — заглушка** (0 байт).
6. **`notification-worker` реализован, но только для OTP.** Уведомления о новых документах и любые продуктовые уведомления — следующий этап.
7. **Нормализованная медмодель (observations / diagnoses / medications / consents) — спроектирована, не мигрирована** (`DEFERRED`), аналитика отсутствует.
8. **Специалист и организация на уровне БД и прав существуют**, но нет ни продуктового API (кроме внутренних выборок в EncounterService), ни UI.

Стадия проекта наиболее точно описывается как:

> **«Работающий Client MVP (vertical slice: auth → upload → AI extraction → кабинет) + сформированный domain/БД-фундамент; не закрыты specialist workflow, organisation workflow, notifications, medical normalization, analytics, embeddings/Qdrant, GPU-конвейер Marker.»**

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

---

# 3. Фактическое состояние по слоям

## 3.1 Миграции и БД

Миграции `migrations/alembic/versions/` — 5 штук (`0001_initial` … `0005_document_date_backfill`).

| Проверка | Статус |
|---|---|
| `0001_initial` — `users`, `auth_sessions` | `[x]` |
| `0002_medical_models` — вся MVP-модель (~20 таблиц), `users`→`accounts` | `[x]` |
| `0003_simplify_person` — `persons` (single `name`, city/profession/height/weight) | `[x]` |
| `0004_document_date` + `0005_document_date_backfill` (фикс бага lowercase-статуса) | `[x]` |
| `observations` / `diagnoses` / `medications` / `patient_consents` (deferred) | `[ ]` |

## 3.2 Доменная модель (`apps/account-api/app/models/`, 21 модель)

| Сущность | Таблица | Статус |
|---|---|---|
| Account | `accounts` (email/phone normalized, status, person_id, last_login_at) | `[x]` |
| AccountIdentity | `account_identities` (создана, в auth-флоу не используется) | `[x]` (модель) / `[~]` (в проде не задействована) |
| Person | `persons` (name, dob, sex, city, profession, height, weight) | `[x]` |
| Patient | `patients` (1:1 person, medical_record_number) | `[x]` |
| Specialist + Specialty + SpecialistSpecialty | `specialists`, `specialties`, `specialist_specialties` | `[x]` (модель) / `[ ]` (API/UI) |
| Organization + OrganizationMembership | `organizations`, `organization_memberships` | `[x]` (модель) / `[ ]` (API/UI) |
| MedicalRecord | `medical_records` (1:1 с Patient) | `[x]` |
| Document | `documents` (типы, статусы, document_date, uploaded_by_account_id) | `[x]` |
| DocumentVersion | `document_versions` (версии, s3_key, checksum) | `[x]` |
| DocumentExtraction | `document_extractions` (schema, data JSON, status, confidence) | `[x]` |
| DocumentProcessingJob | `document_processing_jobs` (pdf_conversion / ai_extraction / embedding) | `[x]` |
| Encounter | `encounters` (типы, статусы, specialist, organization) | `[x]` |
| PatientAccessGrant | `patient_access_grants` (6 флагов, status, expires_at) | `[x]` |
| Role / Permission / AccountRole / RolePermission | RBAC | `[x]` |
| AuditLog | `audit_logs` | `[x]` |
| AuthSession | `auth_sessions` (refresh_token_hmac, rotation) | `[x]` |

**Вывод:** доменная основа (Account ≠ Person ≠ Patient ≠ Specialist) полностью реализована в коде и продублирована в миграциях.

## 3.3 API (`apps/account-api/app/api/v1/`, префикс `/api/v1`) — 34 эндпоинта

| Контур | Эндпоинты | Статус |
|---|---|---|
| Auth | `POST /auth/request-otp`, `POST /auth/verify`, `POST /auth/refresh`, `POST /auth/logout`, `GET /auth/me` | `[x]` |
| Patients | `POST /patients`, `GET/PATCH /patients/me`, `GET /patients/{id}` | `[x]` |
| Documents | list / create (upload) / get / versions (list+new) / extractions / jobs / download (presigned) / markdown / canonical | `[x]` |
| Encounters | create / list / get / patch / documents-by-encounter | `[x]` |
| Access grants | create / list / patch / revoke (`/patients/{id}/access-grants*`) | `[x]` |
| Jobs | `GET /jobs/{id}` | `[x]` |
| Audit | `GET /audit-logs` (system_admin) | `[x]` |
| Admin/RBAC | seed, assign roles, list roles/permissions | `[x]` |
| Users | `users.py` — пустой файл, роутер не подключён | `[ ]` |

Отсутствуют: org CRUD, специалист API, medical-record API, delete document.

## 3.4 Авторизация и доступ

| Компонент | Статус |
|---|---|
| OTP (6 цифр, Redis, TTL 300s, 5 попыток, rate-limit 1/60s) | `[x]` |
| Доставка OTP через RabbitMQ → notification-worker (console/SMTP) | `[x]` |
| JWT access (HS256, 15 мин) + opaque refresh (HMAC в БД, ротация при refresh) | `[x]` |
| RBAC: роли client / specialist / organization_admin / system_admin / support, seed на старте | `[x]` |
| ABAC: `PatientAccessGrant` + флаги (view/upload/extractions/analytics/encounters/edit) | `[x]` |
| Audit allow/deny по всем accessdependency | `[x]` |

## 3.5 Обработка документов — фактический конвейер

Реализована **двухстадийная схема без Marker**: `objectstorage-worker` → S3 → `ai-worker` (OCR + extraction) → `account-api` (persistence).

| Звено | Компонент | Статус |
|---|---|---|
| 1 | `POST /patients/{id}/documents` (staging + Document + v1 + job, событие `document.upload.requested`) | `[x]` |
| 2 | `objectstorage-worker` — валидация mime/size (≤50 МБ), SHA-256, S3 immutable key, `document.stored` | `[x]` |
| 3 | `account-api` consumer `document.stored` → статус PROCESSING, re-publish `document.uploaded` | `[x]` |
| 4 | `ai-worker` конвертация: PyMuPDF (300 dpi) → OCR через vision-LLM → `marker.md` (S3), `document.converted` | `[x]` |
| 5 | `ai-worker` structuring: эвристическая классификация → LLM canonical extraction → Pydantic-валидация → `canonical.json` + `structured.md` (S3), `document.analysis.completed` | `[x]` |
| 6 | `account-api` consumer — сохранение `document_extractions.data`, статус COMPLETED/FAILED, `document_date` | `[x]` |
| 7 | Ошибки → `document.processing.failed` (job FAILED) | `[x]` |
| — | `marker-worker` (Marker GPU conversion) | `[ ]` заглушка, конвертация сейчас в ai-worker |
| — | `marker-orchestrator` (GPU start/stop) | `[ ]` заглушка |
| — | chunking / embeddings / Qdrant | `[ ]` (папка `pipeline/` пустая) |
| — | retry/DLQ redrive (DLQ создаётся, redrive нет) | `[ ]` |

## 3.6 Пакеты (`packages/`)

| Пакет | Статус |
|---|---|
| `canonical` — registry, LaboratoryCanonical / PrescriptionCanonical / GenericCanonical, metadata (Python-built), детерминированный render | `[x]` |
| `contracts` — все 9 событий (OTP, upload requested/stored/uploaded, convert, converted, analysis requested/completed, processing failed) | `[x]` |
| `messaging` — Publisher/Consumer, topic `pdf.events`, durable queues + DLQ, prefetch 10 | `[x]` |
| `storage` — CloudS3 (boto3, cloud.ru), immutable keys, presigned get, markdown-артефакты | `[x]` |
| `observability` — structlog/metrics | `[ ]` заглушка (0 байт) |

## 3.7 Веб-фронтенд (`apps/web`, React + Vite, RU-only)

| Элемент | Статус |
|---|---|
| OTP: `/login` → `/login/verify` (6 ячеек, auto-submit, cooldown, resend) | `[x]` |
| Токены: access в памяти, refresh в localStorage, silent-refresh single-flight | `[x]` |
| Дашборд (приветствие, сводка медкарты, последние документы) | `[x]` |
| Документы: список по месяцам, фильтры по типу, статусы обработки | `[x]` |
| Загрузка: mobile bottom-sheet / desktop drag&drop, XHR-прогресс, cancel/retry | `[x]` |
| Детали документа: статус, Stepper, вкладки «Оригинал / Извлечённая информация», download (presigned) | `[x]` |
| Просмотр canonical: лаборатория (карточки показателей, реф. диапазоны, флаги) и рецепт | `[x]` |
| Медкарта: read-only overview (возраст/пол/рост/вес/etc.) + вкладка «Документы» | `[x]` |
| Профиль: редактирование person (PATCH), выход | `[x]` |
| Поллинг обработки 4s до терминального статуса | `[x]` |
| Управление доступом (access grants) UI | `[ ]` (эндпоинты есть, UI нет) |
| Специалист / организация UI | `[ ]` |
| Уведомления в UI / delete document | `[ ]` (намеренно вне MVP-1) |

**Покрытие тестами фронтенда:** 16 unit-файлов vitest (session, forms, upload machine, canonical/extraction нормализаторы, компоненты), 2 Playwright E2E-spec (happy-path с axe a11y + 320px; isolation для чужого документа) — проходят.

## 3.8 Уведомления

| Канал | Статус |
|---|---|
| OTP-доставка (console / SMTP через notification-worker) | `[x]` |
| Уведомление клиента о новом документе (из `DDPROJECT.md` §25) | `[ ]` — инфраструктура (RabbitMQ + worker) готова, событий и провайдера для документов нет |

## 3.9 Инфраструктура

| Слой | Статус |
|---|---|
| Dev compose (`infrastructure/development`): postgres, rabbitmq, redis, db-migrate, account-api, notification-worker, objectstorage-worker, ai-worker (profile `ai-worker`, opt-in) | `[x]` |
| Main VPS compose: nginx (SPA+proxy `/api`), account-api, orchestrator (*stub*), ai-worker (depends qdrant), notification-worker, objectstorage-worker, postgres, qdrant | `[~]` — qdrant подключён, но кодом не используется |
| Rabbit VPS compose (broker-only, tailnet-only binding) | `[x]` |
| GPU (Marker) VPS: compose, systemd unit, startup/shutdown scripts | `[x]` (инфра) / `[ ]` (приложение-заглушка) |
| CI/CD: test.yml, build.yml, deploy-main.yml, deploy-marker.yml | `[x]` |

---

# 4. Что почти готово (checkboxes «хочется добить»)

Здесь то, что уже имеет рабочий фундамент, но не закрыто полностью до продуктовой функциональности.

- [~] **Специалист:** модели + RBAC-роль `specialist` + ABAC-гранат + audit готовы. Не хватает: CRUD-API специалиста/профиля, API организации, UI специалиста, workflow «открыть пациента → encounter → добавить документ».
- [~] **Организация:** модели `organizations`/`organization_memberships` + auto-resolve в EncounterService готовы. Не хватает: CRUD-API, ролевого контура `organization_admin`, UI организации, сценария «организация → доставка документа клиенту».
- [~] **Уведомления:** инфраструктура (RabbitMQ-события, `notification-worker`, console/SMTP-провайдер) полностью готова. Не хватает: событие о новом документе, таблица/домен уведомлений, интеграция в веб.
- [~] **Управление доступом (UI):** полный backend-контур (`PatientAccessGrant` CRUD + ABAC + audit) готов. Не хватает: экрана в кабинете клиента (кто имеет доступ / выдать / отозвать / права).
- [~] **Encounters в продукте:** API + модель готовы. Не хватает: UI просмотра/создания приёмов.
- [~] **Удаление документа:** в вебе есть кнопка (disabled «Появится позже»). Не хватает: backend-эндпоинта delete + soft-delete lifecycle.
- [~] **`AccountIdentity`:** модель создана, но auth-флоу использует колонки `accounts.email/phone`. Либо задействовать, либо задокументировать как неиспользуемую.
- [~] **VPS-продакшн:** compose и CI/CD готовы, но `marker-orchestrator` и `marker-worker` — заглушки, бэкапы/мониторинг/retention — TODO.

---

# 5. Что не реализовано (следующие этапы)

- `[ ]` Medical normalization: `observations`, `diagnoses`, `medications` (аналитика-фундамент, deferred в миграциях) — см. `DDPROJECT.md` §34–36.
- `[ ]` `patient_consents` (access ≠ consent, deferred) — §37.
- `[ ]` Analytics: тайм-серии показателей (гемоглобин/глюкоза), тренды, простые графики.
- `[ ]` Embeddings + chunking + Qdrant (поиск/retrieval, не source of truth).
- `[ ]` Retry/DLQ redrive политика (DLQ декларируется, redrive нет).
- `[ ]` Longitudinal AI: понимание истории во времени, сводки, тренды.
- `[ ]` AI assistant для специалиста.
- `[ ]` `packages/observability` (structlog/metrics) — заглушка.
- `[ ]` Integration-тесты (`tests/integration/` пустая, только `.gitkeep`).

---

# 6. Оценка зрелости по слоям

| Уровень | Состояние |
|---|---|
| Product concept | `[x]` сформирован (`DDPROJECT.md`) |
| Domain model / DB | `[x]` реализовано (21 таблица, 5 миграций) |
| OTP Auth + RBAC + ABAC + Audit | `[x]` |
| Documents / Versions / Jobs / Extraction | `[x]` |
| Access Grants (backend) | `[x]` |
| Encounters (backend) | `[x]` |
| Processing pipeline (S3 → OCR → canonical → PostgreSQL → API) | `[x]` (реализован в ai-worker) |
| Canonical data model + validation + structured.md | `[x]` |
| Веб-кабинет клиента (MVP-1) | `[x]` |
| E2E/unit тесты | `[x]` (базовый слой) |
| Specialist workflow | `[~]` (фундамент есть) |
| Organisation workflow | `[~]` (фундамент есть) |
| Notifications (не-OTP) | `[~]` (инфра готова) |
| Access management UI | `[~]` (backend готов) |
| Medical normalization + Analytics | `[ ]` |
| Embeddings / Qdrant | `[ ]` |
| GPU-конвейер (Marker + orchestrator) | `[ ]` |
| Longitudinal AI / AI assistant | `[ ]` |
| Integration-тесты | `[ ]` |

---

# 7. Главный вывод

Проект **прошёл главный технический риск** — надёжное превращение произвольного медицинского документа в структурированные данные с детерминированным представлением:

```text
Original → OCR/конвертация → canonical.json → Pydantic validation → structured.md → PostgreSQL → API
```

и уже имеет **работающий пользовательский vertical slice** (OTP-вход → загрузка → обработка → просмотр в кабинете).

Следующий большой этап по продуктовой приоритетности (`DDPROJECT.md` §47–49):

```text
1. Client UX (в основном готово, добить доступ/уведомления)
2. Specialist workflow
3. Organisation workflow + доставка документов
4. Notifications
5. Medical normalization (observations/diagnoses/medications)
6. Analytics (тайм-серии)
7. Longitudinal AI
```

---

# 8. Источники фактов (карта кода)

| Слой | Где смотреть |
|---|---|
| Модели | `apps/account-api/app/models/*.py` |
| API | `apps/account-api/app/api/v1/*.py` |
| Auth/OTP | `apps/account-api/app/services/{auth,otp}.py`, `core/security.py` |
| Доступ | `services/access.py`, `dependencies/{access,rbac}.py`, `repositories/{access,rbac}.py` |
| Документы | `services/documents.py`, `services/storage.py` |
| Events | `consumers/document_events.py`, `core/bus.py` |
| AI-конвейер | `apps/ai-worker/app/{main,processor,ai_client,doc_classifier,pdf_converter}.py`, `prompts/*.yaml` |
| Canonical | `packages/canonical/canonical/{schemas,metadata,render}.py` |
| Upload в S3 | `apps/objectstorage-worker/app/processor.py` |
| OTP-доставка | `apps/notification-worker/app/{main.py,providers/*}` |
| Web | `apps/web/src/{app,features,lib}/` |
| Миграции | `migrations/alembic/versions/0001..0005*.py` |
| Инфра | `infrastructure/*`, `Makefile`, `.github/workflows/` |
| Заглушки (0 байт) | `apps/marker-worker/app/*`, `apps/marker-orchestrator/app/*`, `apps/ai-worker/app/{queue,worker}.py`, `apps/ai-worker/app/pipeline/*`, `packages/observability/*` |