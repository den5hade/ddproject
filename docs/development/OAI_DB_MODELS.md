Да. Здесь я бы уже **не строил модель вокруг `User → Documents`**, потому что с появлением врача, электронной медкарты, приёмов и прав доступа это быстро станет ограничением.

Лучше разделить:

1. **Account / Identity** — кто входит в систему.
2. **Person** — физическое лицо, которому принадлежит медицинская информация.
3. **Patient** — роль человека как пациента.
4. **Healthcare organization / specialist** — врач и организация.
5. **Medical record** — электронная медицинская карта пациента.
6. **Encounter** — конкретный приём/контакт с врачом.
7. **Document** — PDF/image и его версии.
8. **Medical data** — структурированные данные, извлечённые из документов.
9. **Access / Consent** — кто и почему имеет доступ к медицинской карте.
10. **Audit log** — кто, когда и что смотрел/изменил.

Это даст намного более устойчивую модель.

---

# 1. Главный принцип модели

Я бы разделил **аккаунт** и **пациента**.

Не стоит делать:

```text
User
 ├── email
 ├── password
 ├── role
 └── documents
```

Лучше:

```text
Account
   │
   └── Person
         │
         ├── Patient
         │
         └── Specialist
```

Потому что один человек потенциально может быть одновременно:

```text
Person
 ├── Patient
 └── Specialist
```

Например врач сам может пользоваться вашим сервисом как пациент.

---

# 2. Общая модель

Я бы начал примерно с такой структуры:

```text
                         ┌──────────────┐
                         │   Account    │
                         │              │
                         │ email        │
                         │ phone        │
                         │ password     │
                         └──────┬───────┘
                                │
                                │ 1:1
                                ▼
                         ┌──────────────┐
                         │    Person    │
                         │              │
                         │ name         │
                         │ birth_date   │
                         │ ...          │
                         └──────┬───────┘
                                │
                ┌───────────────┼────────────────┐
                │                                │
                ▼                                ▼
          ┌───────────┐                    ┌────────────┐
          │  Patient  │                    │ Specialist │
          └─────┬─────┘                    └─────┬──────┘
                │                                │
                │                                │
                ▼                                ▼
        ┌─────────────────┐              ┌──────────────┐
        │ Medical Record  │              │ Organization │
        └────────┬────────┘              └──────────────┘
                 │
       ┌─────────┼──────────────┐
       │         │              │
       ▼         ▼              ▼
   Documents  Encounters    Medical Data
       │         │              │
       │         │              │
       └─────────┴──────┬───────┘
                        ▼
                     S3 / DB
```

---

# 3. Account

`accounts` — это именно техническая учётная запись.

Я бы не делал `phone` и `email` обязательными одновременно.

```text
accounts
--------
id UUID PK

email
email_verified_at

phone
phone_verified_at

password_hash

status
created_at
updated_at
last_login_at
```

Например:

```text
status:
    pending
    active
    blocked
    deleted
```

### Email/phone лучше нормализовать

Например:

```text
email_normalized
phone_e164
```

И сделать unique indexes.

```text
UNIQUE(email_normalized)
UNIQUE(phone_e164)
```

Но поскольку оба могут быть `NULL`, PostgreSQL нормально позволит:

```text
email = NULL
phone = "+..."

email = "..."
phone = NULL
```

---

# 4. Не хранить пароль в Account как обычный password

Хранить:

```text
password_hash
```

Например Argon2id.

Если хотите сделать архитектуру более гибкой, можно вынести authentication identities:

```text
accounts
    │
    ├── account_identities
    │
    └── sessions
```

Например:

```text
account_identities
------------------
id
account_id

type
value
verified_at

created_at
```

где:

```text
type:
    email
    phone
```

Это позволит в будущем добавить:

```text
Google
Apple
OIDC
etc.
```

без переделки `accounts`.

Для вашего проекта я бы **сразу сделал `account_identities`**, хотя это немного сложнее.

---

# 5. Person

`person` — человек как субъект медицинских данных.

```text
persons
-------
id UUID PK

first_name
last_name
middle_name

date_of_birth
sex

created_at
updated_at
```

При этом я бы осторожно относился к медицински значимым полям вроде пола/гендерной идентичности: если они нужны для анализа, модель лучше сделать явно, а не добавлять всё подряд.

---

# 6. Account → Person

```text
accounts
    │
    │ 1:1
    ▼
persons
```

Например:

```text
accounts
id = A1

persons
id = P1
```

`accounts.person_id`:

```text
UNIQUE
```

---

# 7. Роли

Я бы **не делал одну колонку**:

```text
users.role = "client"
```

Потому что довольно быстро появится:

```text
client
specialist
admin
organization_admin
laboratory
support
```

А человек может иметь несколько ролей.

Лучше:

```text
roles
-----
id
code
name
```

Например:

```text
client
specialist
organization_admin
system_admin
support
```

И:

```text
account_roles
-------------
account_id
role_id
```

Получаем:

```text
Account
 ├── client
 └── specialist
```

если понадобится.

---

# 8. Но RBAC недостаточно

Вот это особенно важно для медицинского приложения.

Недостаточно:

```text
role = specialist
```

Потому что любой специалист не должен видеть всех пациентов.

Нужна модель:

```text
Role
 +
Relationship / Grant
 +
Permission
```

Например:

```text
Dr. Ivanov
     │
     │ assigned
     ▼
Patient #123
```

---

# 9. Организации

Я бы сразу ввёл:

```text
organizations
-------------
id
name
type
status
created_at
```

Например:

```text
Clinic ABC
Hospital XYZ
Private practice
Laboratory
```

---

# 10. Specialist profile

```text
specialists
-----------
id
person_id
license_number
specialty
status
created_at
updated_at
```

Но лучше specialty вынести в справочник:

```text
specialties
-----------
id
code
name
```

И связь:

```text
specialist_specialties
----------------------
specialist_id
specialty_id
```

Потому что врач может иметь несколько специализаций.

---

# 11. Specialist ↔ Organization

```text
organization_members
--------------------
id

organization_id
account_id

position
status

joined_at
left_at
```

Например:

```text
Clinic A
   │
   ├── Dr. Ivanov
   ├── Dr. Petrov
   └── Nurse Smith
```

---

# 12. Patient

Пациент — отдельная сущность.

```text
patients
--------
id UUID PK

person_id UUID UNIQUE

medical_record_number
status

created_at
updated_at
```

Причём я бы **не использовал email/phone как идентификатор пациента**.

У пациента должен быть внутренний immutable UUID.

---

# 13. Medical Record

Это центральная сущность.

```text
medical_records
---------------
id UUID PK

patient_id UUID UNIQUE

created_at
updated_at
```

Получаем:

```text
Patient
   │
   └── MedicalRecord
           │
           ├── Documents
           ├── Encounters
           ├── Observations
           ├── Diagnoses
           └── ...
```

И очень важно:

> **Medical Record не равен Account.**

У пациента может быть account, но медицинская карта — отдельная сущность.

---

# 14. Документы

Я бы сделал:

```text
documents
---------
id UUID

medical_record_id

document_type

title
original_filename
mime_type
size_bytes

storage_key

status

uploaded_by_account_id
created_at
updated_at
```

Типы:

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

Но `document_type` лучше сделать enum/reference table в зависимости от того, насколько часто вы будете его менять.

---

# 15. Очень важно: uploaded_by ≠ patient

Например:

```text
Patient uploads blood test
```

тогда:

```text
uploaded_by_account_id = patient
```

А врач после приёма:

```text
Doctor uploads consultation report
```

тогда:

```text
uploaded_by_account_id = doctor
```

При этом оба документа принадлежат:

```text
medical_record_id = patient medical record
```

---

# 16. Encounter — обязательно

Поскольку вы хотите:

> врач может просматривать документы и добавлять новые документы после приёма

нужна сущность:

```text
encounters
---------
id UUID

medical_record_id
specialist_id
organization_id

type
status

started_at
ended_at

reason
summary

created_at
updated_at
```

Например:

```text
Patient #123

Encounter #456
2026-08-15
Dr. Ivanov
Cardiology

Documents:
    consultation.pdf
    ECG.pdf

Extracted data:
    blood_pressure
    heart_rate
    diagnosis
    recommendations
```

---

# 17. Документ может быть связан с Encounter

Добавляем:

```text
documents.encounter_id
```

Но nullable:

```text
encounter_id NULL
```

Потому что документ может быть загружен пациентом самостоятельно:

```text
blood_test.pdf
```

без конкретного приёма.

Получается:

```text
MedicalRecord
    │
    ├── Document
    │
    ├── Document
    │
    └── Encounter
          │
          ├── Document
          ├── Document
          └── Document
```

---

# 18. Document versions

Это я бы заложил с самого начала.

```text
documents
---------
id
medical_record_id
type
title
created_at


document_versions
-----------------
id
document_id

version

s3_key
mime_type
size_bytes
checksum

created_at
created_by_account_id
```

Почему?

Например врач исправил заключение.

Не стоит:

```text
UPDATE document
```

и терять старую версию.

Лучше:

```text
document
    │
    ├── v1
    ├── v2
    └── v3
```

---

# 19. Обработка документа

Отдельная таблица:

```text
document_processing_jobs
------------------------
id UUID

document_id
document_version_id

job_type
status

attempts

started_at
finished_at

error_code
error_message

created_at
updated_at
```

Например:

```text
PDF_CONVERSION
AI_EXTRACTION
EMBEDDING
```

---

# 20. AI extraction

Я бы **не складывал результаты AI только в Qdrant**.

Qdrant — поисковый индекс.

Структурированные медицинские данные должны находиться в PostgreSQL.

Например:

```text
document_extractions
--------------------
id

document_id
document_version_id

schema_name
schema_version

status

data JSONB

confidence

created_at
updated_at
```

Например:

```json
{
  "test_type": "CBC",
  "results": [
    {
      "name": "hemoglobin",
      "value": 135,
      "unit": "g/L",
      "reference_min": 120,
      "reference_max": 160
    }
  ]
}
```

---

# 21. Я бы сделал отдельную модель для observations

Если вы хотите действительно хорошую медицинскую аналитику, одного JSONB со временем станет мало.

Можно начать:

```text
document_extractions.data JSONB
```

а затем выделить:

```text
observations
------------
id

patient_id
medical_record_id

code
name

value_numeric
value_text
unit

reference_low
reference_high

observed_at

source_document_id
source_encounter_id

created_at
```

Например:

```text
Patient
  │
  ├── Hemoglobin = 135 g/L
  ├── Glucose = 5.2 mmol/L
  ├── Weight = 78 kg
  └── Blood pressure = 125/80
```

И тогда аналитика становится намного проще.

---

# 22. Diagnoses

Аналогично:

```text
diagnoses
---------
id

patient_id
medical_record_id
encounter_id

code_system
code
name

status

onset_date
resolved_date

source_document_id

created_at
```

В будущем можно использовать ICD-10/ICD-11 или другую медицинскую терминологию.

---

# 23. Medications

Если планируется медицинская карта, я бы заложил:

```text
medications
-----------
id

patient_id
medical_record_id
encounter_id

name
active_ingredient
dosage
unit
frequency

started_at
ended_at

status

source_document_id
```

Но это можно сделать на втором этапе.

---

# 24. Самая важная часть — доступ врача к карте

Вот здесь я бы **не делал**:

```text
patient.specialists = [...]
```

Лучше отдельная таблица:

```text
patient_access_grants
---------------------
id UUID

patient_id
specialist_account_id

organization_id

access_type

status

granted_at
expires_at

granted_by_account_id

created_at
updated_at
```

Например:

```text
access_type:

view
upload
edit
full
```

Но я бы ещё лучше разделил permission:

```text
patient_access_grants
---------------------
patient_id
account_id

can_view_documents
can_upload_documents
can_view_extractions
can_view_analytics
can_create_encounters
can_edit_medical_data

expires_at
```

---

# 25. Почему access grant лучше роли

Представим:

```text
Dr. Ivanov
role = specialist
```

Это говорит только:

> Иванов — врач.

Но не говорит:

> Иванов имеет право видеть медицинскую карту пациента №123.

Для этого нужна отдельная связь:

```text
Dr. Ivanov
      │
      │ access grant
      ▼
Patient #123
```

---

# 26. В идеале добавить Consent

Для медицинской системы я бы не смешивал:

```text
Access
```

и:

```text
Consent
```

Это разные вещи.

Например:

```text
patient_consents
----------------
id

patient_id

purpose

status

granted_at
revoked_at
expires_at

granted_by

created_at
```

Например:

```text
CONSULTATION
DOCUMENT_ACCESS
AI_ANALYSIS
DATA_SHARING
```

Точная модель зависит от юридической юрисдикции и требований продукта, но архитектурно такое разделение полезно.

---

# 27. Пример сценария: пациент приходит к врачу

Допустим:

```text
Patient: Иван Иванов
Doctor: Петров
```

Пациент заранее предоставил доступ.

В БД:

```text
patient_access_grants

patient_id = P123
account_id = DR456

can_view_documents = true
can_upload_documents = true
can_view_analytics = true
can_create_encounters = true
```

Врач открывает:

```text
GET /patients/P123/medical-record
```

Backend проверяет:

```text
1. authenticated?
2. account active?
3. role specialist?
4. access grant exists?
5. grant not expired?
6. required permission?
```

Только после этого возвращает данные.

---

# 28. После приёма врач создаёт Encounter

```text
POST /patients/P123/encounters
```

Создаётся:

```text
encounter
-----------
patient = P123
specialist = DR456
organization = CLINIC1
started_at = ...
```

После этого врач загружает:

```text
consultation.pdf
```

Document:

```text
medical_record_id = MR123
encounter_id = ENC789
uploaded_by_account_id = DR456
```

Дальше обычный pipeline:

```text
S3
 ↓
RabbitMQ
 ↓
Marker
 ↓
Markdown/JSON
 ↓
AI extraction
 ↓
PostgreSQL
 ↓
Qdrant
```

---

# 29. Audit Log — для такой системы я считаю обязательным

Нужно знать не только:

> у кого есть доступ

но и:

> кто реально смотрел данные.

Например:

```text
audit_logs
----------
id UUID

actor_account_id

action

resource_type
resource_id

patient_id

ip_address
user_agent

metadata JSONB

created_at
```

Actions:

```text
LOGIN
VIEW_PATIENT
VIEW_DOCUMENT
DOWNLOAD_DOCUMENT
UPLOAD_DOCUMENT
CREATE_ENCOUNTER
UPDATE_ENCOUNTER
GRANT_ACCESS
REVOKE_ACCESS
VIEW_ANALYTICS
```

Например:

```text
2026-08-15 14:32

actor = Dr. Petrov
action = VIEW_DOCUMENT
document = D123
patient = P456
```

Для медицинской системы это очень полезная и часто необходимая часть security/compliance architecture.

---

# 30. Я бы добавил access reason

Особенно для специалистов:

```text
access_reason
```

Например:

```text
treatment
consultation
diagnosis
follow_up
```

Не обязательно в MVP, но модель доступа лучше спроектировать так, чтобы это можно было добавить.

---

# 31. Admin

`admin` я бы **не делал обычным пациентским доступом**.

Есть:

```text
system_admin
```

который управляет:

* пользователями;
* организациями;
* специалистами;
* настройками.

Но это **не должно автоматически означать доступ ко всем медицинским документам**.

Это принцип least privilege.

Например:

```text
system_admin
    │
    ├── manage users
    ├── manage organizations
    └── manage configuration

НЕ автоматически:

    read every medical document
```

Если нужен такой доступ — отдельное privileged permission:

```text
medical_data_admin
```

и всё равно через audit log.

---

# 32. Я бы разделил роли так

На первом этапе:

```text
CLIENT
SPECIALIST
ORGANIZATION_ADMIN
SYSTEM_ADMIN
SUPPORT
```

Но permission system сделать отдельно:

```text
permissions
-----------
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

И:

```text
role_permissions
----------------
role_id
permission_id
```

Получается нормальный RBAC.

---

# 33. Но RBAC + ABAC будет ещё лучше

Для медицинской карты фактически нужна комбинация:

```text
RBAC
+
resource ownership
+
access grant
+
organization
+
consent
```

То есть решение:

```text
Can Dr. Petrov read Document X?
```

не просто:

```text
role == specialist
```

а:

```text
authenticated
AND account.active
AND role == specialist
AND specialist belongs to organization
AND patient_access_grant exists
AND grant.active
AND grant.can_view_documents
AND document belongs to patient's medical_record
```

Это уже правильная модель.

---

# 34. Итоговая ER-модель

Я бы примерно пришёл к такой структуре:

```text
Account
│
├── AccountIdentity
│
├── AccountRole ───── Role ───── RolePermission ───── Permission
│
└── Person
      │
      ├── Patient
      │     │
      │     └── MedicalRecord
      │            │
      │            ├── Documents
      │            │      │
      │            │      ├── DocumentVersions
      │            │      ├── ProcessingJobs
      │            │      └── Extractions
      │            │
      │            ├── Encounters
      │            │      │
      │            │      └── Documents
      │            │
      │            ├── Observations
      │            └── Diagnoses
      │
      └── Specialist
             │
             ├── SpecialistSpecialty
             │
             └── OrganizationMembership
                        │
                        ▼
                   Organization


Patient
   │
   ├── AccessGrants ───────── Specialist
   │
   └── Consents

Account
   │
   └── AuditLogs
```

---

# 35. В виде основных таблиц

Я бы начал примерно с этого набора:

```text
accounts
account_identities
persons

roles
permissions
account_roles
role_permissions

patients
specialists

organizations
organization_memberships
specialties
specialist_specialties

medical_records

encounters

documents
document_versions
document_processing_jobs

document_extractions

observations
diagnoses
medications

patient_access_grants
patient_consents

audit_logs
```

При этом **не нужно реализовывать все таблицы в MVP**.

---

# 36. Что реально сделать в MVP

Я бы ограничил первый релиз:

```text
accounts
account_identities
persons

roles
permissions
account_roles
role_permissions

patients
specialists
organizations
organization_memberships

medical_records

documents
document_versions

encounters

document_processing_jobs
document_extractions

patient_access_grants

audit_logs
```

А затем:

```text
observations
diagnoses
medications
consents
```

добавлять по мере развития медицинской аналитики.

---

# 37. Самое важное изменение по сравнению с первоначальной моделью

Изначально у нас было:

```text
User
  ↓
Documents
```

Для вашей новой задачи я бы окончательно перешёл на:

```text
                    Account
                       │
                     Person
                       │
                 ┌─────┴─────┐
                 │           │
              Patient    Specialist
                 │           │
                 │      Organization
                 │           │
                 └─────┬─────┘
                       │
                Access Grant
                       │
                       ▼
                Medical Record
                       │
          ┌────────────┼────────────┐
          │            │            │
      Documents    Encounters   Medical Data
          │            │            │
          └────────────┴────────────┘
                       │
                    AI Pipeline
                       │
              ┌────────┴────────┐
              ▼                 ▼
          PostgreSQL          Qdrant
```

И это, на мой взгляд, **гораздо правильнее для продукта, который из "анализатора загруженных PDF" постепенно превращается в персональную электронную медицинскую карту**.

Особенно важно, что **медицинские данные не должны быть просто "файлами пользователя"**. Файл — это artifact/source, а `MedicalRecord`, `Encounter`, `Observation`, `Diagnosis` и `DocumentExtraction` — уже структурированная медицинская информация. Это разделение даст вам возможность позже строить аналитику по динамике показателей, истории приёмов и результатам анализов, не заставляя AI каждый раз перечитывать PDF.
