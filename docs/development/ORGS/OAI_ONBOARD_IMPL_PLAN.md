# Organization Onboarding — Implementation Plan

## 1. Цель

На текущем этапе организация не создаёт себя самостоятельно.

Подключение организации выполняется через `system_admin` во время персонального onboarding:

1. Представитель организации сообщает данные организации.
2. Admin ищет организацию в системе по ИНН/ОГРН/названию.
3. Если организация уже существует — admin выбирает её.
4. Если организации нет — admin создаёт её из карточки предприятия.
5. Admin указывает email представителя организации.
6. Система создаёт или находит его `Account`.
7. Система создаёт `OrganizationMembership`.
8. Пользователь получает право администрировать организацию.
9. Пользователь после входа видит Organization и может продолжить настройку:

   * филиалов;
   * лицензий;
   * API keys;
   * сотрудников;
   * document schemas;
   * integration settings.

Главный принцип:

> Organization создаётся и подключается только через административный onboarding. Пользователь не получает право создать Organization самостоятельно.

---

# 2. Основной сценарий

## Scenario A — Organization уже существует

```text
System Admin
      │
      ▼
Search Organization
      │
      ├── INN
      ├── OGRN
      └── name
      │
      ▼
Organization found
      │
      ▼
Enter representative email
      │
      ▼
Find/Create Account
      │
      ▼
Create OrganizationMembership
      │
      ▼
role = owner/admin
      │
      ▼
User can administer Organization
```

---

# 3. Scenario B — Organization отсутствует

```text
System Admin
      │
      ▼
Search Organization
      │
      ▼
Not found
      │
      ▼
Create Organization
      │
      ├── name
      ├── type
      ├── INN
      ├── OGRN
      ├── legal_address
      ├── email
      ├── phone
      └── website
      │
      ▼
Enter representative email
      │
      ▼
Find/Create Account
      │
      ▼
Create OrganizationMembership
      │
      ▼
role = owner/admin
      │
      ▼
Organization connected
```

---

# 4. Не использовать public Organization self-registration

На этом этапе НЕ реализовывать:

```text
POST /api/v1/organizations
```

доступный обычному Account.

Также не реализовывать:

* public organization verification;
* automatic organization ownership;
* organization claim;
* self-service organization registration;
* сложный verification workflow;
* автоматическую проверку федерального реестра.

Эти возможности могут быть добавлены позже.

---

# 5. Organization остаётся отдельной сущностью

Не создавать Organization непосредственно внутри Account.

Модель:

```text
Account
   │
   │
   ▼
OrganizationMembership
   │
   │
   ▼
Organization
```

Это позволяет одному Account в будущем состоять в нескольких организациях.

Например:

```text
Account
 ├── Organization A → admin
 ├── Organization B → member
 └── Organization C → specialist
```

---

# 6. OrganizationMembership

Membership становится основным механизмом связи пользователя с Organization.

Рекомендуемые поля:

```text
id
organization_id
account_id
role
status
created_at
updated_at
```

Минимальные роли:

```text
owner
admin
member
```

Для текущего onboarding:

```text
role = owner
status = active
```

или `admin`, если ownership не нужен на этом этапе.

Рекомендуется выбрать одну семантику и зафиксировать её.

Предпочтительный вариант:

```text
first organization representative
        ↓
role = owner
```

В дальнейшем owner может добавлять administrators.

---

# 7. Не использовать глобальный AccountRole для Organization Admin

Не следует решать organization authorization через:

```text
AccountRole(
    account_id,
    role = organization_admin
)
```

поскольку роль должна быть scoped к конкретной Organization.

Правильная модель:

```text
Account
    │
    └── OrganizationMembership
            │
            ├── organization_id
            ├── account_id
            └── role = owner/admin/member
```

Глобальные роли Account:

```text
system_admin
support
...
```

остаются глобальными.

Organization-specific permissions проверяются через Membership.

---

# 8. Admin API

Для текущего этапа создать отдельный административный API.

Например:

```text
POST /api/v1/admin/organizations
```

Назначение:

Создать Organization и одновременно подключить представителя.

Возможный request:

```json
{
  "organization": {
    "name": "ООО Медицинский центр",
    "type": "clinic",
    "inn": "1234567890",
    "ogrn": "1234567890123",
    "legal_address": "...",
    "email": "info@clinic.ru",
    "phone": "...",
    "website": "..."
  },
  "administrator_email": "director@clinic.ru"
}
```

Ответ:

```text
201 Created
```

с Organization и созданным membership.

---

# 9. Не дублировать OrganizationService

Не создавать отдельную бизнес-логику только для admin API.

Рекомендуемая структура:

```text
Admin API
    │
    ▼
OrganizationService
    │
    ├── create_organization()
    ├── attach_account()
    └── create_membership()
```

То есть admin endpoint является интерфейсом, а не отдельной бизнес-логикой.

---

# 10. Два административных сценария

Лучше не делать один endpoint, который всегда создаёт Organization.

Нужны два сценария.

## Existing Organization

```text
POST /api/v1/admin/organizations/{organization_id}/members
```

Request:

```json
{
  "email": "director@clinic.ru",
  "role": "owner"
}
```

---

## New Organization

```text
POST /api/v1/admin/organizations
```

Request:

```json
{
  "organization": {...},
  "administrator": {
    "email": "director@clinic.ru",
    "role": "owner"
  }
}
```

Это делает API семантически понятным.

---

# 11. Account Resolution

При добавлении представителя по email система должна:

```text
normalize email
      │
      ▼
find Account
      │
      ├── found
      │     ↓
      │   reuse Account
      │
      └── not found
            ↓
        create Account
```

Важно:

**не создавать новый Account, если такой email уже существует.**

Email должен использовать существующую `AccountIdentity`.

---

# 12. Если Account не существует

Создаётся:

```text
Account
status = active/pending
```

в зависимости от существующей authentication модели.

Затем:

```text
Person
OrganizationMembership
```

Если Account ещё не проходил полноценную регистрацию, он должен получить invitation/onboarding notification.

Например:

```text
Organization "Медицинский центр"
has invited you as administrator.
```

Пользователь завершает регистрацию через существующий OTP flow.

Не создавать отдельную authentication систему для Organization.

---

# 13. Если Account уже существует

Ничего нового в Account не создавать.

Например:

```text
Account
email = doctor@example.ru
```

уже существует.

Добавляем:

```text
OrganizationMembership
account_id = existing account
organization_id = selected organization
role = owner
status = active
```

Пользователь после следующего входа получает доступ к Organization.

---

# 14. Duplicate protection

Необходимо защитить следующие случаи.

## Duplicate Organization

```text
UNIQUE(inn)
UNIQUE(ogrn)
```

Admin не должен случайно создать вторую Organization.

Если INN/OGRN уже существует:

```text
409 Conflict
```

с сообщением:

```text
Organization with this INN already exists.
```

UI должен предложить открыть существующую Organization.

---

## Duplicate Membership

Не создавать второе active membership:

```text
UNIQUE(
    organization_id,
    account_id
)
```

или соответствующий partial unique constraint, если модель допускает исторические membership.

---

# 15. Admin UI

На текущем этапе UI можно сделать максимально простым.

В system admin:

```text
Organizations

[ + Add organization ]

Search:
[ INN / OGRN / name ]

Results
─────────────────────────────

ООО "Медицинский центр"
INN: 1234567890
Status: Active

[ Open ]
[ Add administrator ]
```

При добавлении:

```text
Organization
ООО "Медицинский центр"

Administrator email
[ director@clinic.ru ]

Role
[ Owner ]

[ Connect ]
```

---

# 16. UX для новой Organization

Если поиск ничего не нашёл:

```text
Organization not found.

[ Create organization ]
```

Открывается форма:

```text
Organization

Name *
[........................]

Type *
[ Clinic ▼ ]

INN *
[........................]

OGRN *
[........................]

Legal address
[........................]

Email
[........................]

Phone
[........................]

Website
[........................]

Administrator email *
[........................]

[ Create and connect ]
```

Одна кнопка выполняет операцию:

```text
Create Organization
+
Create/resolve Account
+
Create Membership
```

Все операции выполняются в одной transaction.

---

# 17. Organization status

Для текущего MVP не требуется сложный verification workflow.

Можно оставить существующую модель Organization status.

Важно только не интерпретировать создание через admin как автоматическое подтверждение внешних юридических данных.

Admin фактически говорит:

> Я проверил организацию и подключил её к платформе.

Это является текущим operational verification.

Позже можно добавить:

```text
verification_status
```

без изменения основного onboarding flow.

---

# 18. Audit

Каждое административное действие должно попадать в AuditLog.

Минимально:

```text
ORGANIZATION_CREATED
ORGANIZATION_ADMIN_ADDED
```

Audit должен содержать:

```text
actor_account_id
organization_id
action
timestamp
request_id
```

Особенно важно фиксировать:

```text
who created Organization
who added administrator
when
which organization
which account
```

Не записывать API key secrets или медицинские данные.

---

# 19. Notification

После подключения существующего Account:

```text
OrganizationMembership created
        ↓
Notification
```

Пользователь получает уведомление:

> Вы получили доступ администратора к медицинской организации.

Если Account не существовал:

```text
Account created
        ↓
OrganizationMembership
        ↓
Invitation / onboarding notification
        ↓
OTP login
```

Email не должен содержать медицинские данные.

---

# 20. Future compatibility

Хотя сейчас Organization подключается только через system admin, модель должна позволять позже добавить:

```text
Self-service registration
Claim organization
Registry verification
Organization invitation
Domain verification
API-based onboarding
```

Но эти механизмы не должны быть частью текущей реализации.

Текущий процесс:

```text
System Admin
     │
     ▼
Organization
     │
     ▼
Membership
     │
     ▼
Organization Admin
```

в будущем может расшириться:

```text
                    ┌── System Admin
                    │
Organization ───────┼── Registry import
                    │
                    ├── Self-service claim
                    │
                    └── Invitation
```

---

# 21. Recommended implementation phases

## Phase 4a — Admin Organization Onboarding

Реализовать:

* создание Organization через system admin;
* INN/OGRN normalization;
* INN/OGRN validation;
* duplicate protection;
* создание OrganizationMembership;
* назначение `owner`;
* existing Account resolution;
* создание Account при необходимости;
* audit;
* notification;
* API tests;
* service tests.

---

## Phase 4b — Organization Context

После onboarding реализовать:

* current organization;
* organization-scoped authorization;
* membership role checks;
* organization isolation;
* organization switching для Account с несколькими организациями.

Например:

```text
GET /api/v1/organizations
GET /api/v1/organizations/{organization_id}
GET /api/v1/organizations/{organization_id}/members
```

---

## Phase 4c — API Keys

Только после того, как Organization context стабилен:

* create API key;
* hash;
* prefix;
* scopes;
* expiration;
* revoke;
* last_used_at;
* API key status.

---

## Phase 4d — Organization Integration API

Затем:

```text
API Key
    ↓
Organization
    ↓
Branch
    ↓
Patient
    ↓
Document
```

Реализовать single document upload.

---

## Phase 4e — Bulk Upload

После single upload:

```text
Organization
    ↓
API Key
    ↓
Upload Batch
    ↓
Batch Items
    ↓
RabbitMQ
    ↓
existing document processing
```

---

## Phase 4f — API Monitoring

После появления реального API traffic:

* request log;
* API key usage;
* last used;
* errors;
* rate limits;
* quotas;
* metrics.

---

# 22. Definition of Done для Phase 4a

Phase 4a считается завершённой, если:

### Existing Organization

```text
System Admin
    ↓
select Organization
    ↓
enter email
    ↓
existing Account resolved
    ↓
Membership created
    ↓
user has organization admin access
```

работает.

### New Organization

```text
System Admin
    ↓
enter organization data
    ↓
Organization created
    ↓
enter email
    ↓
Account resolved/created
    ↓
Membership created
    ↓
user has organization admin access
```

работает.

### Security

Обычный Account не может:

```text
POST /admin/organizations
POST /admin/organizations/{id}/members
```

System admin может.

Organization admin не должен автоматически получать system-admin capabilities.

### Data integrity

Невозможно создать:

```text
duplicate INN
duplicate OGRN
duplicate active membership
```

### Audit

Зафиксированы:

```text
ORGANIZATION_CREATED
ORGANIZATION_ADMIN_ADDED
```

### Notification

Представитель получает корректное onboarding notification.

---

# 23. Что сейчас НЕ делать

Не реализовывать пока:

* public organization registration;
* automatic registry synchronization;
* organization claim;
* organization verification service;
* organization domain verification;
* complex ownership transfer;
* self-service organization creation;
* automatic license verification;
* API onboarding;
* bulk upload;
* organization document schemas.

Они должны появиться после стабилизации базового Organization lifecycle.

---

# 24. Итоговая модель текущего этапа

```text
                     SYSTEM ADMIN
                          │
                    manual onboarding
                          │
             ┌────────────┴────────────┐
             │                         │
       Organization exists       Organization absent
             │                         │
             │                    Create Organization
             │                         │
             └────────────┬────────────┘
                          │
                          ▼
                     Organization
                          │
                          ▼
                 OrganizationMembership
                          │
                          ▼
                    Account / Person
                          │
                          ▼
                  owner / administrator
                          │
                          ▼
                Organization administration
                          │
             ┌────────────┼─────────────┐
             ▼            ▼             ▼
          Branches     Licenses      API Keys
```

## Архитектурный принцип

На текущем этапе **System Admin является точкой доверия**.

Пользователь не доказывает системе:

> «Я владею этой организацией».

Это делает оператор платформы во время персонального onboarding.

Поэтому нам сейчас не нужен сложный verification workflow. Мы только должны построить модель так, чтобы позже System Admin можно было заменить автоматизированными механизмами verification без изменения `OrganizationMembership`, `Organization`, API authorization и document ingestion.

---

# Recommended API surface for Phase 4a

```text
POST   /api/v1/admin/organizations
GET    /api/v1/admin/organizations
GET    /api/v1/admin/organizations/{organization_id}

POST   /api/v1/admin/organizations/{organization_id}/members
GET    /api/v1/admin/organizations/{organization_id}/members
```

При этом обычный organization management API будет отдельным:

```text
GET    /api/v1/organizations
GET    /api/v1/organizations/{organization_id}
GET    /api/v1/organizations/{organization_id}/members
```

и будет защищён через OrganizationMembership.

API integration:

```text
POST   /api/v1/integration/documents
POST   /api/v1/integration/batches
```

будет защищён API key и появится на следующих фазах.
