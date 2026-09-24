# Текущее состояние проекта — анализ из кода

## Медицинская платформа персональной медицинской истории

**Версия документа:** 4.0
**Дата:** 26 сентября 2026
**Основание:** документ написан по результатам фактического анализа исходного кода monorepo (`apps/`, `packages/`, `migrations/`, `docs/`) после закрытия контура «Классификация 2.0» (M0–M3, коммиты `431f329` → `33af39f`), а также профильных доработок профиля и messaging-топологии.
**Продуктовая концепция:** `docs/DDPROJECT.md`
**Предыдущий снимок:** `docs/archive/PROJECT_STATUS_091826.md` (18 сентября 2026, организационно-интеграционный контур)
**Профильные документы:** `docs/development/ORGS/IMPL_ARCH.md`, `IMPL_SPEC.md`, `IMPL_PLAN.md`, `IMPL_RPRT.md`; `docs/development/implementation/AI_FLOW 2.0/CLASSIFICATION 2.0/{CONTRACT_IMPL_PLAN,IMPL_PLAN,EVAL_IMPL_PLAN,IMPL_RPRT}.md`; `apps/ai-worker/app/classification/{EVAL_FLOW.md, MANIFEST_AUDIT.md}`

> **Метка состояния:**
> - `[x]` — реализовано и работает в коде
> - `[~]` — почти готово (есть рабочий фундамент, не хватает последнего слоя / части workflow)
> - `[ ]` — не реализовано / отложено

---

# 1. Executive Summary

С прошлого снимка (18 сентября) закрыт ещё один контур: **«Классификация 2.0»** — детерминированный rule-based классификатор документов с регрессионным датасетом и оценочным CLI (M1 контракты → M2 имплементация + пайплайн-интеграция → M3 оценка + калибровка `2.1.0`). Плюс доработки профиля и messaging.

Общее состояние:

1. **Backend и доменная модель — без изменений по существу.** ~29 таблиц (16 миграций), **69 API-эндпоинтов** (добавлен `GET /patients/me/summary` по контуру профиля), OTP-авторизация (Redis), RBAC + ABAC, организационно-ролевой контур, audit, событийная шина RabbitMQ.
2. **Классификация 2.0 закрыта полностью (M0–M3).** Контрактные типы (`NormalizedDocument`, `TextNormalizer`, `ClassificationSignal`, единый decision tuple), детерминированный движок `MarkdownNormalizer → detectors → RuleScoringEngine → ClassificationService` с типами laboratory/appointment/prescription/generic и подтипами лаборатории (гематология/биохимия/микробиология/…), интеграция в пайплайн `ai-worker` вместо вызовов LLM для определения типа, регрессионный датасет на 11 фикстур (`manifest.json` v1.0.0), оценочный CLI `evaluate.py` (`--json`/`--report`), калибровка `2.1.0` (ветка строгого доминирования микробиологии в подтипе), аудит манифеста (F1–F6), регрессионные гейты (`wrong_schema == 0`, `false_laboratory == 0`, recall ≥ 0.95, CLI-метрики == ground-truth).
3. **AI-конвейер:** определение типа документа теперь **детерминированное (rule-based, версия 2.1.0)**; LLM остаётся только на извлечение (`canonical.json` + `structured.md`). `marker-worker` / `marker-orchestrator` — по-прежнему заглушки 0 байт; в классификации LMM не используется (сознательное решение, `IMPL_RPRT.md` §4).
4. **Веб-кабинет клиента (MVP-1)+:** добавлены `GET /patients/me/summary` со статистикой (кол-во документов, выданных доступов) и экран `/profile/edit`; переработан профиль, скруглённая кнопка выхода. **UI организации / администратора платформы и UI уведомлений отсутствуют** — следующая фронтенд-задача.
5. **Messaging:** топология `document.convert` теперь декларируется через `rabbit-setup`; исправлен publisher при первом старте приложения; в Makefile добавлен `test-api`.
6. **Qdrant / embeddings / chunking, medical normalization, analytics — не реализованы** (`ai-worker/app/pipeline/*` пуст, deferred-таблицы не миграциированы).
7. **Специалист — фундамент есть, продуктового API/UI нет.**
8. **`packages/observability`, integration-тесты, retry/DLQ redrive — не реализованы.**

Стадия проекта наиболее точно описывается как:

> **«Client MVP (+ профиль со статистикой) + закрытые backend-контуры Organisation/Integration и Classification 2.0 (детерминированный, с оценкой); не закрыты: UI организационного управления, specialist workflow, UI управления доступом, уведомления в веб-интерфейсе, medical normalization, analytics, embeddings/Qdrant, GPU-конвейер Marker.»**

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

Снимок показывает: этапы 1 и 4 — преимущественно backend; этап 3 частично (Organisation backend готов, Specialists — нет); по этапу 6 под фундамент сделана детерминированная rule-based классификация документов (надёжность без LMM).

---

# 3. Фактическое состояние по слоям

## 3.1 Миграции и БД

Без изменений с прошлого снимка: миграции `0001_initial` … `0016_organization_api_request_usage_index` — **16 штук**, ~29 таблиц. Deferred: `observations` / `diagnoses` / `medications` / `patient_consents` (`[ ]`).

## 3.2 Доменная модель

Без изменений. Полный org-контур (branches/licenses/api_keys/api_requests/upload_batches/document_schemas/notifications), Document + org-source колонки, Encounter, AccessGrant, RBAC, Audit. Вывод из прошлого снимка действителен: `organization_admin` как глобальная роль намеренно не используется — управление через `OrganizationMembership.role ∈ {owner, admin, member}`.

## 3.3 API (`apps/account-api/app/api/v1/`, префикс `/api/v1`) — 69 эндпоинтов

| Контур | Эндпоинты | Статус |
|---|---|---|
| Auth | OTP-запрос/верификация, refresh, logout, me | `[x]` |
| Patients | `POST /patients`, `GET/PATCH /patients/me`, `GET /patients/{id}`, **`GET /patients/me/summary` (новое: статистика профиля)** | `[x]` |
| Documents | list / create / get / versions / extractions / jobs / download / markdown / canonical | `[x]` |
| Encounters | create / list / get / patch / documents-by-encounter | `[x]` |
| Access grants | create / list / patch / revoke | `[x]` |
| Jobs / Audit / Admin-RBAC | jobs, audit-logs, роли | `[x]` |
| **Admin organizations** (4a) | онбординг организаций + члены (`system_admin`) | `[x]` |
| **Organization context / management** (4b, 1–3, 4g, 4h) | `/organizations`, `/organizations/me`, branches/licenses/api-keys/schemas/usage | `[x]` |
| **Integration** (4c–4e) | single + bulk загрузка, чтения документов/батчей | `[x]` |
| Users | `users.py` — пустой (0 байт), роутер не подключён | `[ ]` |

Отсутствуют: специалист API, medical-record API, delete document, notification read API.

## 3.4 Авторизация и доступ

Без изменений: OTP (Redis), JWT + opaque refresh (ротация), RBAC (client/specialist/system_admin/support), org-membership роли, `X-Organization-Id`, policy верификации для API-ключей, m2m (`Bearer <api-key>` + 4 scope, rate-limit 120/мин), ABAC `PatientAccessGrant`, audit allow/deny.

## 3.5 Обработка документов — фактический конвейер

| Звено | Компонент | Статус |
|---|---|---|
| 1 | upload (client / machine `/integration/documents`) → staging + Document + job | `[x]` |
| 2 | `objectstorage-worker` — mime/size (≤50 МБ), SHA-256, S3 immutable key, `document.stored` | `[x]` |
| 3 | `account-api` consumer → PROCESSING, re-publish `document.uploaded` | `[x]` |
| 4 | `ai-worker` PyMuPDF (300 dpi) → OCR → `marker.md`, `document.converted` | `[x]` |
| 5 | `ai-worker` **классификация 2.0 (rule-based, детерминированная)** → LLM extraction → Pydantic → `canonical.json` + `structured.md`, `document.analysis.completed` | `[x]` |
| 6 | `account-api` consumer → `document_extractions.data`, COMPLETED/FAILED, `document_date` | `[x]` |
| 7 | Терминальный статус → `NotificationService` (org-документы) | `[x]` |
| — | Bulk: `POST /integration/documents/bulk` (≤100) | `[x]` |
| — | `marker-worker` / `marker-orchestrator` | `[ ]` заглушки 0 байт |
| — | chunking / embeddings / Qdrant | `[ ]` (`pipeline/*` пуст) |
| — | retry/DLQ redrive (DLQ создаётся, redrive нет) | `[ ]` |

## 3.6 Пакеты (`packages/`)

| Пакет | Статус |
|---|---|
| `canonical` — registry, Laboratory/Prescription/Generic, metadata, детерминированный render | `[x]` |
| `contracts` — события (OTP, upload, convert/analysis, документные, org, batch) | `[x]` |
| `messaging` — Publisher/Consumer, durable queues + DLQ, **топология `document.convert` через `rabbit-setup`, фикс publisher при первом старте** | `[x]` |
| `storage` — CloudS3, immutable keys, presigned, markdown-артефакты | `[x]` |
| `observability` — structlog/metrics | `[ ]` заглушка (0 байт) |

## 3.7 Веб-фронтенд (`apps/web`, React + Vite, RU-only)

| Элемент | Статус |
|---|---|
| OTP: `/login` → `/login/verify` | `[x]` |
| Токены: access в памяти, refresh в localStorage, silent-refresh | `[x]` |
| Дашборд / Документы / Загрузка (XHR-прогресс) / Детали документа | `[x]` |
| Просмотр canonical: лаборатория и рецепт | `[x]` |
| Медкарта: read-only overview + вкладка «Документы» | `[x]` |
| Профиль: редактирование (PATCH), **статистика (`/patients/me/summary`), экран `/profile/edit`, скруглённая кнопка выхода** | `[x]` |
| Поллинг обработки до терминального статуса | `[x]` |
| UI управления доступом (access grants) | `[ ]` (эндпоинты есть, UI нет) |
| **UI специалиста / администратора платформы / управления организацией / уведомлений / delete document** | `[ ]` |

Текущие маршруты: `login`, `login/verify`, `/`, `documents`, `documents/:documentId`, `medical-record`, `profile`, **`profile/edit`**. Организационных/admin-маршрутов нет. `schema.d.ts` устарел (сгенерирован до org-работ) — перед фронтендом нужен `npm run generate:api`. Тесты: 16 unit-файлов vitest + 2 Playwright E2E.

## 3.8 Уведомления

Без изменений: серверный контур документных уведомлений (`document_received/processed/failed`) + round-trip доставки `[x]`; UI уведомлений и не-документные события `[ ]`.

## 3.9 Инфраструктура

| Слой | Статус |
|---|---|
| Dev compose: postgres, rabbitmq, redis, db-migrate, account-api, notification-worker, objectstorage-worker, ai-worker (opt-in) | `[x]` |
| Main VPS compose: nginx, account-api, orchestrator (*stub*), ai-worker, notification-worker, objectstorage-worker, postgres, qdrant | `[~]` — qdrant подключён, кодом не используется |
| Rabbit VPS compose (broker-only, tailnet-only) | `[x]` |
| GPU (Marker) VPS: compose, systemd, скрипты | `[x]` (инфра) / `[ ]` (приложение-заглушка) |
| CI/CD: test.yml, build.yml, deploy-main.yml, deploy-marker.yml | `[x]` |
| Makefile: `test-api`, `eval-classification` (оценочный CLI классификации) | `[x]` |

## 3.10 Организационно-интеграционный контур (фазы 1–4i)

Без изменений с прошлого снимка — закрыт на backend: legal data (ИНН/ОГРН), филиалы, лицензии, API-ключи, admin-онбординг, org-context/роли, integration API (single + bulk), документные схемы, usage-мониторинг (4h), точка расширения верификации (4i). Документация в `docs/development/ORGS/` (ARCH/SPEC/PLAN/RPRT).

## 3.11 Классификация 2.0 (M0–M3)

Закрытый контур `apps/ai-worker/app/classification/`:

| Элемент | Статус |
|---|---|
| **M0** — структурный рефакторинг разделов AI_FLOW 2.0 | `[x]` |
| **M1** — контрактные типы: `NormalizedDocument`, `TextNormalizer` (прокол), `ClassificationSignal`, decision tuple, политика версионирования (policy M1 §7) | `[x]` |
| **M2** — детерминированный движок: `MarkdownNormalizer` (структура сохраняется, не флаттенится) → сигнатуры (laboratory/appointment/prescription/generic) → `RuleScoringEngine` → `ClassificationService`; пайплайн-интеграция (убирает полагание на LLM для типа); регрессионный датасет 11 фикстур | `[x]` |
| **M3** — оценка + калибровка: `evaluate.py` CLI (`--json`/`--report`), `fixtures.py` (загрузчик манифеста в приложении), `test_evaluate.py`; версия **`2.1.0`** (калибровка F2: строгое доминирование микробиологии в подтипе лаборатории); аудит манифеста; гейты; eval-отчёт | `[x]` |
| Версионирование | `CLASSIFIER_VERSION = "2.1.0"` (`scoring.py:31`); 2.0.0 → 2.1.0 при output-altering калибровке |
| Регрессионные гейты | `wrong_schema == 0`, `false_laboratory == 0`, recall ≥ 0.95; CLI-метрики == ground-truth counts (`{lab:6, appointment:2, prescription:1, other:2}`, tp==support, fp/fn==0); доля `ambiguous` — только в отчёте (N=11) |
| Детерминизм | два прогона CLI `--json` байт-идентичны |
| Тесты | ai-worker: **139 classification + 9 pipeline passed**; `ruff` чист |
| Документация | `docs/.../CLASSIFICATION 2.0/{CONTRACT_IMPL_PLAN,IMPL_PLAN,EVAL_IMPL_PLAN,IMPL_RPRT}.md` (SUM.md дизайн-спека заменена отчётом); `apps/ai-worker/app/classification/{EVAL_FLOW.md, MANIFEST_AUDIT.md}` |
| Ограничение | N=11 → гейты count-based; %-таргеты (дизайн-спека §30) возобновляются при real-markers > ~50 (оценка масштабируемости в `IMPL_RPRT.md` §12) |

**Известные не-блокеры (зафиксированы, проверены на базисе):** pipeline-тесты проходят из `apps/ai-worker`, но не из корня изменений (pre-existing); `--all-packages` локально блокируется отсутствием torch-wheel для x86_64 macOS (CI = linux, не затронут); `uv run --project apps/ai-worker ...` из корня не находит пакет `app` (используется `cd apps/ai-worker`).

---

# 4. Что почти готово (checkboxes «хочется добить»)

- [~] **Специалист:** модели + RBAC + ABAC + audit + org-авторизация готовы. Не хватает: CRUD-API профиля специалиста, UI, workflow «пациент → encounter → документ».
- [~] **Уведомления:** серверный контур готов; не хватает UI и событий по не-документным эвентам.
- [~] **Управление доступом (UI):** backend готов; не хватает экрана в кабинете.
- [~] **Encounters в продукте:** API + модель готовы; не хватает UI.
- [~] **Удаление документа:** кнопка в вебе disabled; нет backend-эндпоинта delete + lifecycle.
- [~] **Организационный UI / платформенный admin UI:** backend полностью готов (контракт `ORGS/IMPL_RPRT.md` §7); нужен фронтенд.
- [~] **Классификация — масштабирование:** rule-based детерминированная и оценённая на N=11; %-таргеты и расширение real-markers > ~50 — следующий шаг.
- [~] **VPS-продакшн:** compose и CI/CD готовы; `marker-*` — заглушки, бэкапы/мониторинг/retention — TODO (retention usage уже реализован в 4h).

---

# 5. Что не реализовано (следующие этапы)

- `[ ]` **UI администратора платформы и UI управления организацией** — backend готов, требуется фронтенд.
- `[ ]` **UI управления доступом, UI уведомлений, delete document**.
- `[ ]` **Specialist workflow:** API специалиста, UI, продуктовые сценарии.
- `[ ]` Medical normalization: `observations`, `diagnoses`, `medications` (deferred) — `DDPROJECT.md` §34–36.
- `[ ]` `patient_consents` (access ≠ consent, deferred) — §37.
- `[ ]` Analytics: тайм-серии показателей, тренды, графики.
- `[ ]` Embeddings + chunking + Qdrant.
- `[ ]` Retry/DLQ redrive (DLQ декларируется, redrive нет).
- `[ ]` Longitudinal AI, AI assistant для специалиста.
- `[ ]` LMM/GPU-классификация документов (сейчас — детерминированный rule-based контур 2.1.0; Marker — заглушка).
- `[ ]` `packages/observability` — заглушка.
- `[ ]` Integration-тесты (`tests/integration/` пуста).

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
| **Classification 2.0 (rule-based, М1–М3, версия 2.1.0, оценённый)** | `[x]` |
| Canonical data model + validation + structured.md | `[x]` |
| Веб-кабинет клиента (MVP-1) + профиль со статистикой | `[x]` |
| **Organisation / Integration (backend, фазы 1–4i)** | `[x]` |
| **Notifications (server-side, продуктовые)** | `[x]` |
| Specialist workflow | `[~]` (фундамент есть, API/UI нет) |
| Access management UI | `[~]` (backend готов) |
| **Organisation UI (admin + management)** | `[ ]` (backend готов, нужен фронтенд) |
| Notifications UI | `[ ]` |
| Medical normalization + Analytics | `[ ]` |
| Embeddings / Qdrant | `[ ]` |
| GPU-конвейер (Marker + orchestrator) / LMM-классификация | `[ ]` |
| Longitudinal AI / AI assistant | `[ ]` |
| Integration-тесты | `[ ]` |

---

# 7. Главный вывод

Проект закрыл очередной бэкенд-контур: **Классификация 2.0** — детерминированная, versioned (`2.1.0`), с регрессионным датасетом, аудитом манифеста и оценочным CLI. Теперь определение типа документа не зависит от LLM, что повышает надёжность и воспроизводимость конвейера.

```text
Клиент:      OTP → upload → S3 → OCR → классификация 2.0 (rule-based) → canonical.json → PostgreSQL → кабинет
                                             └─ 2.1.0, гейты, eval CLI, 11 фикстур
```
```text
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
6. Embeddings/Qdrant + GPU-конвейер Marker (LMM → закрыть rule-based классификацию)
7. Longitudinal AI / AI assistant
```

---

# 8. Источники фактов (карта кода)

| Слой | Где смотреть |
|---|---|
| Модели | `apps/account-api/app/models/*.py` (organization.py, notification.py) |
| API | `apps/account-api/app/api/v1/*.py` (admin_organizations.py, organizations.py, integration.py, patients.py) |
| Auth/OTP | `apps/account-api/app/services/{auth,otp}.py`, `core/security.py` |
| Доступ | `apps/account-api/app/services/access.py`, `dependencies/{access,rbac}.py` |
| Организация | `apps/account-api/app/services/{organization,branches,licenses,api_keys,schemas,api_usage}.py` |
| Документы | `apps/account-api/app/services/{documents,storage,patient_resolver}.py` |
| Events / Messaging | `apps/account-api/app/consumers/document_events.py`, `notification_result.py`, `core/bus.py`; `rabbit-setup` (топология `document.convert`) |
| **Классификация** | `apps/ai-worker/app/classification/{contracts(models),signals/*,scoring,resolver,service,normalize,evaluate,fixtures}.py`; `EVAL_FLOW.md`, `MANIFEST_AUDIT.md` |
| AI-конвейер | `apps/ai-worker/app/{processor,ai_client,doc_classifier,pdf_converter}.py` |
| Canonical | `packages/canonical/canonical/{schemas,metadata,render}.py` |
| Upload | `apps/objectstorage-worker/app/processor.py` |
| Уведомления | `apps/notification-worker/app/{main.py,providers/*}` |
| Web | `apps/web/src/{app,features,lib}/` (маршруты incl. `profile/edit`) |
| Миграции | `migrations/alembic/versions/0001..0016*.py` |
| Профильные док-ты | `docs/development/ORGS/{IMPL_ARCH,IMPL_SPEC,IMPL_PLAN,IMPL_RPRT}.md`; `docs/development/implementation/AI_FLOW 2.0/CLASSIFICATION 2.0/*` |
| Инфра | `infrastructure/*`, `Makefile` (incl. `test-api`, `eval-classification`), `.github/workflows/` |
| Заглушки (0 байт) | `apps/marker-worker/app/*`, `apps/marker-orchestrator/app/*`, `apps/ai-worker/app/pipeline/*`, `packages/observability/*`, `apps/account-api/app/api/v1/users.py` |