# Marker как сервис для организаций

- **Status**: Proposed
- **Date**: 2026-08-26

## Контекст

Необходимо предоставить организациям возможность регистрироваться, получать API ключи
и использовать marker-сервис для конвертации PDF по прямым HTTP-запросам от их
инфраструктуры, минуя веб-интерфейс.

## Текущее состояние

- **marker-worker** и **marker-orchestrator** — полные заглушки (все `.py` файлы пустые).
  Архитектура описана в документации, но ноль реализации.
- **account-api** — модель `Organization` существует (`models/organization.py`),
  но CRUD для организаций отсутствует.
- **API ключей нет** — авторизация только через OTP + JWT.
- Текущий пайплайн полностью event-driven:
  ```
  account-api → RabbitMQ → objectstorage-worker → S3 → RabbitMQ
  → marker-orchestrator → RabbitMQ → marker-worker (GPU VPS) → RabbitMQ → account-api
  ```

## Трудности реализации

### 1. Нет системы API ключей

Нужна модель `ApiKey` в БД (хэш ключа, org_id, scope, rate limits, expiry),
эндпоинты для генерации/отзыва, middleware для проверки.
JWT-сессии текущей авторизации не подходят для machine-to-machine.

### 2. marker-worker не имеет HTTP-интерфейса

Спроектирован как чистый RabbitMQ consumer на GPU VPS.
GPU VPS — эфемерная (включается/выключается оркестратором по очереди).
Прямой HTTP-доступ к ней затруднён (Tailscale, NAT, ephemeral IP).

### 3. Синхронный HTTP vs async-пайплайн

Текущий пайплайн полностью асинхронный (RabbitMQ). HTTP-запрос организации
ожидает ответ, а конвертация PDF на GPU может занимать минуты.
Нужен паттерн: принять запрос → вернуть task_id → polling/webhook для результата.

### 4. Webhook-доставка результатов

Нужна очередь на исходящих HTTP-вызовах (webhook delivery с retry,
dead letter, signature verification). Это нетривиальный компонент.

### 5. Квоты и rate limiting

Нужен механизм подсчёта запросов по org_id (Redis counter или БД),
лимиты на размер файла, количество конвертаций в день.

### 6. tenant_id не пробрасывается через pipeline

`tenant_id` есть только в `DocumentUploadRequested`, во всех последующих
событиях его нет. Для мульти-тенантности нужно добавить в `DocumentEvent` base.

## Решение: API Gateway как отдельный сервис

### Почему не HTTP в marker-worker

| Критерий | HTTP в marker-worker | Отдельный API Gateway |
|---|---|---|
| Связанность | Смешивает GPU-обработку с HTTP-логикой | Чистое разделение ответственности |
| Эфемерность GPU | HTTP-сервис на эфемерной VPS — недоступен когда GPU выключен | Gateway на Main VPS — всегда доступен |
| Масштабирование | Gateway и worker масштабируются независимо | То же |
| Безопасность | API ключи + rate limiting на GPU VPS — лишний attack surface | Вся auth-логика на Main VPS, за firewall |
| Простота | Нужно менять архитектуру worker'а | Gateway публикует в RabbitMQ, существующий pipeline работает |

### Архитектура

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Организация     │────▶│  API Gateway      │────▶│  RabbitMQ       │
│  (внешний API)   │◀────│  (новый FastAPI)  │◀────│  (pdf.events)   │
└─────────────────┘     └──────────────────┘     └────────┬────────┘
                                    │                      │
                              ┌─────┴─────┐        ┌──────┴──────┐
                              │  account-  │        │  marker-    │
                              │  api (БД)  │        │  worker     │
                              └───────────┘        └─────────────┘
```

**Преимущества:**
- Существующий event-driven pipeline не меняется
- marker-worker остаётся чистым GPU consumer
- API Gateway — thin proxy с auth + квотами + webhook delivery
- GPU VPS по-прежнему эфемерная, но организациям это неважно — они работают с Gateway

## План реализации

### Шаг 1: API Key система в account-api

**Файлы:**

| Файл | Назначение |
|------|-----------|
| `apps/account-api/app/models/api_key.py` | Модель `ApiKey` (org_id, key_hash, prefix, scopes, rate_limit, expires_at, status) |
| `apps/account-api/app/repositories/api_keys.py` | CRUD операции |
| `apps/account-api/app/services/api_keys.py` | Генерация (prefix + `secrets.token_urlsafe`), хэширование (SHA-256), отзыв |
| `apps/account-api/app/api/v1/api_keys.py` | Эндпоинты: `POST /api-keys`, `GET /api-keys`, `DELETE /api-keys/{id}` |
| `apps/account-api/app/dependencies/api_key.py` | FastAPI dependency для проверки API key |
| Миграция | Добавить таблицу `api_keys` |

### Шаг 2: CRUD организаций в account-api

**Файлы:**

| Файл | Назначение |
|------|-----------|
| `apps/account-api/app/api/v1/organizations.py` | `POST /organizations`, `GET /organizations/me`, `PATCH /organizations/me` |
| `apps/account-api/app/services/organizations.py` | Логика создания org + привязка создателя как `organization_admin` |

### Шаг 3: API Gateway (новый сервис)

**Структура:**

```
apps/api-gateway/
├── app/
│   ├── main.py              # FastAPI app, lifespan
│   ├── config.py            # pydantic-settings (DB, RabbitMQ, S3, webhook URLs)
│   ├── dependencies/
│   │   ├── auth.py          # API key → org_id verification
│   │   └── rate_limit.py    # Redis-based rate limiting per org_id
│   ├── api/v1/
│   │   ├── convert.py       # POST /convert (upload PDF → task_id)
│   │   ├── tasks.py         # GET /tasks/{task_id} (polling status + result)
│   │   └── webhooks.py      # CRUD webhook URLs
│   ├── services/
│   │   ├── convert.py       # orchestrate: S3 temp upload → RabbitMQ publish → return task_id
│   │   ├── tasks.py         # query job status from DB
│   │   ├── webhooks.py      # webhook CRUD + delivery
│   │   └── delivery.py      # background webhook delivery with retry
│   └── models/
│       └── webhook.py       # WebhookSubscription model
├── pyproject.toml
├── Dockerfile
└── docker-compose.yml
```

**Эндпоинты:**

| Метод | Путь | Описание |
|-------|------|----------|
| `POST` | `/api/v1/convert` | Загрузить PDF, вернуть `{ task_id, status }` |
| `GET` | `/api/v1/tasks/{task_id}` | Статус + результат (presigned URL на markdown) |
| `POST` | `/api/v1/webhooks` | Зарегистрировать callback URL |
| `GET` | `/api/v1/webhooks` | Список webhook'ов организации |
| `DELETE` | `/api/v1/webhooks/{id}` | Удалить webhook |

**Ключевые особенности:**
- Gateway подключается к той же БД что и account-api (общий PostgreSQL)
- Верификация API key: хэш ключа → lookup в `api_keys` таблице → `org_id` в `request.state`
- Rate limiting через Redis (sliding window counter по `org_id`)
- Webhook delivery: фоновая задача с exponential backoff, подпись HMAC, 3 retry, DLQ

### Шаг 4: Проброс tenant_id через pipeline

- Добавить `organization_id: UUID | None = None` в `DocumentEvent` base
  (`packages/contracts/contracts/schemas/events.py`)
- Gateway при публикации `document.upload.requested` заполняет `organization_id`
- Все последующие события наследуют его автоматически

### Шаг 5: Webhook delivery worker

- Фоновая задача внутри Gateway или отдельный процесс
- При `document.converted` → поиск webhook subscription по org_id → POST на callback URL
  с HMAC подписью
- Retry: 3 попытки с exponential backoff (10s, 60s, 300s)
- Мёртвые webhook'и помечаются как `disabled`

## Итог: ключевые трудности и решения

| Трудность | Решение |
|-----------|---------|
| API ключей нет | Модель `ApiKey` + хэширование + middleware |
| marker-worker без HTTP | Gateway публикует в RabbitMQ, pipeline не меняется |
| Sync HTTP + async pipeline | Task ID + polling + webhook |
| tenant_id не пробрасывается | Добавить в `DocumentEvent` base |
| Webhook reliability | Delivery worker с retry + DLQ + HMAC подпись |
| Rate limiting | Redis sliding window per org |
| GPU VPS эфемерная | Gateway всегда доступен, GPU — нет |
