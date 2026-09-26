Я бы выстроил эти четыре компонента не как четыре независимые фичи, а как **последовательные стадии ingestion pipeline**. Ключевой принцип: каждая следующая стадия должна получать стабильный контракт от предыдущей.

Рекомендованный порядок:

```text
                    PDF / JPEG
                        │
                        ▼
                     Marker
                        │
                        ▼
              marker.md / raw text
                        │
                        ▼
              ┌───────────────────┐
              │ Classification 2.0│
              └─────────┬─────────┘
                        │
             document_type + confidence
                        │
                        ▼
                  ┌───────────┐
                  │ PII Gate  │
                  └─────┬─────┘
                        │
                  sanitized /
                  approved document
                        │
                        ▼
             ┌─────────────────────┐
             │ GenericCanonical 2.0│
             └──────────┬──────────┘
                        │
                        │ fallback / generic
                        │
                        ▼
              Canonical representation
                        │
             ┌──────────┴──────────┐
             │                     │
             ▼                     ▼
   AppointmentCanonical       LaboratoryCanonical
             │
             ▼
       Structured MD
             │
             ▼
       Medical History
```

Но **внутри разработки** порядок я бы немного изменил.

# Рекомендуемый порядок разработки

## 0. Сначала — Canonical Core / общие контракты

Перед реализацией четырёх компонентов стоит сделать небольшой foundation layer.

Не полноценный отдельный этап продукта, а технический prerequisite:

```text
canonical/
├── core/
│   ├── document.py
│   ├── identifier.py
│   ├── person.py
│   ├── organization.py
│   ├── observation.py
│   ├── provenance.py
│   └── metadata.py
│
├── extraction/
├── validation/
└── registry/
```

Определить:

* `DocumentID`
* `ProcessingID`
* `Schema`
* `SchemaVersion`
* `Confidence`
* `Provenance`
* `SourceReference`
* `ExtractionMetadata`
* общие ошибки pipeline
* versioning

Это позволит не переделывать четыре компонента после первой интеграции.

---

# 1. Classification 2.0

**Первым полноценным компонентом я бы делал именно Classification 2.0.**

Причина простая: дальше pipeline должен понимать, **что перед ним за документ**.

Например:

```json
{
  "document_type": "appointment",
  "confidence": 0.96,
  "subtype": "specialist_consultation"
}
```

или:

```json
{
  "document_type": "laboratory",
  "confidence": 0.99
}
```

или:

```json
{
  "document_type": "generic",
  "confidence": 0.54
}
```

### Classification 2.0 должен определить

Минимально:

```text
laboratory
appointment
discharge
diagnosis
imaging
prescription
referral
other
unknown
```

При этом я бы разделил:

```text
document_type
document_subtype
confidence
```

Например:

```json
{
  "document_type": "appointment",
  "document_subtype": "cardiology_consultation",
  "confidence": 0.94
}
```

### Почему первым

Потому что Classification станет router'ом:

```text
Classification
      │
      ├── laboratory → LaboratoryCanonical
      │
      ├── appointment → AppointmentCanonical
      │
      ├── discharge → GenericCanonical
      │
      └── unknown → GenericCanonical
```

### Definition of Done

До перехода дальше:

* versioned classification schema;
* prompt version;
* model metadata;
* confidence;
* deterministic validation;
* fallback;
* regression dataset;
* tests на реальные документы;
* audit/provenance.

---

# 2. PII Gate

После Classification — **PII Gate**.

Здесь есть важный нюанс.

PII Gate не должен зависеть от конкретного Canonical schema.

Он работает над:

```text
raw / normalized document
```

а не над:

```text
AppointmentCanonical
LaboratoryCanonical
```

То есть:

```text
Marker
   ↓
Classification
   ↓
PII Gate
   ↓
Canonical extraction
```

### Задача PII Gate

Определить:

```text
можно ли использовать документ
для дальнейшей AI обработки
```

и какие PII в нём присутствуют.

Например:

```json
{
  "status": "allowed",
  "findings": [
    {
      "type": "patient_name",
      "location": "...",
      "action": "retain"
    }
  ]
}
```

Но я бы не делал PII Gate просто как:

```text
PII detected → reject
```

Для вашего продукта это слишком грубо.

Медицинский документ **по определению содержит персональные данные**.

Поэтому задача Gate скорее:

```text
detect
→ classify
→ apply policy
→ decide
```

Например:

```text
patient PII
    → allowed

organization PII
    → allowed

third-party PII
    → redact / review

financial information
    → redact

credentials / secrets
    → reject
```

### Почему PII Gate до GenericCanonical

Потому что GenericCanonical — это уже структурированное представление, которое может попасть:

* в PostgreSQL;
* vector DB;
* analytics;
* search;
* LLM context.

Намного лучше контролировать данные **до структурирования и индексации**.

---

# 3. GenericCanonical 2.0

После Classification + PII Gate я бы делал **GenericCanonical 2.0**.

Это фундамент для специализированных schemas.

Его роль:

> структурировать документ настолько, насколько это возможно без предположений о конкретном типе документа.

Например:

```text
GenericCanonical
├── document
├── patient
├── organization
├── practitioner
├── dates
├── identifiers
├── observations
├── diagnoses
├── procedures
├── medications
├── recommendations
└── sections
```

Но главное преимущество GenericCanonical:

### fallback

Если Classification говорит:

```json
{
  "document_type": "appointment",
  "confidence": 0.91
}
```

можно использовать:

```text
AppointmentCanonical
```

Но если:

```json
{
  "document_type": "unknown",
  "confidence": 0.42
}
```

документ **не должен ломать pipeline**.

Он идёт:

```text
GenericCanonical
```

---

# 4. GenericCanonical должен быть реализован раньше AppointmentCanonical

Это важный архитектурный момент.

Я бы не начинал сразу:

```text
AppointmentCanonical
```

потому что в процессе его разработки почти наверняка появятся reusable concepts:

```text
Person
Organization
Observation
Diagnosis
Medication
Procedure
Identifier
Provenance
Date
Quantity
```

Если Appointment сделать первым, есть риск получить:

```text
AppointmentObservation
AppointmentDiagnosis
AppointmentMedication
```

а потом дублировать их в LaboratoryCanonical.

Вместо этого:

```text
GenericCanonical
        │
        ├── Observation
        ├── Diagnosis
        ├── Medication
        ├── Procedure
        ├── Person
        └── Organization
                 │
                 ▼
        AppointmentCanonical
```

---

# 5. AppointmentCanonical

И только после стабильного GenericCanonical — специализированный AppointmentCanonical.

Тогда его задача становится намного проще.

Он добавляет **контекст приёма** поверх общих primitives:

```text
AppointmentCanonical
│
├── encounter
├── complaints
├── history
├── examination
├── observations
├── diagnoses
├── procedures
├── medications
├── recommendations
└── follow_up
```

При этом:

```text
observations
diagnoses
procedures
medications
person
organization
provenance
```

переиспользуются из Core/Generic модели.

---

# 6. Получается такая последовательность

Я бы зафиксировал roadmap следующим образом:

```text
PHASE 0
Canonical Core
    │
    ▼
PHASE 1
Classification 2.0
    │
    ▼
PHASE 2
PII Gate
    │
    ▼
PHASE 3
GenericCanonical 2.0
    │
    ▼
PHASE 4
AppointmentCanonical
```

А после этого:

```text
PHASE 5
LaboratoryCanonical 2.0

PHASE 6
ImagingCanonical

PHASE 7
DischargeCanonical

PHASE 8
Medical Timeline
```

---

# 7. Но есть ещё более важная зависимость

Я бы разделил **разработку** и **production pipeline**.

Разработка:

```text
Core
 ↓
Classification
 ↓
PII
 ↓
Generic
 ↓
Appointment
```

Production pipeline после завершения:

```text
                 Marker
                   │
                   ▼
             Normalization
                   │
                   ▼
             Classification
                   │
                   ▼
                PII Gate
                   │
                   ▼
            Schema Resolver
                   │
          ┌────────┼─────────┐
          ▼        ▼         ▼
       Generic Appointment Laboratory
          │        │         │
          └────────┼─────────┘
                   ▼
              Validation
                   │
                   ▼
              Provenance
                   │
                   ▼
           Canonical Storage
                   │
          ┌────────┼─────────┐
          ▼        ▼         ▼
        JSON       MD       Vector
```

---

# 8. Я бы не делал PII Gate "после Classification" зависимым от Classification

То есть технически:

```text
Classification → PII Gate
```

это порядок pipeline.

Но интерфейс должен быть:

```python
class PIIGate:
    async def inspect(
        self,
        document: NormalizedDocument,
        context: ProcessingContext,
    ) -> PIIResult:
        ...
```

а не:

```python
class AppointmentPIIGate:
```

PII должен быть **document-level capability**, а не schema-level.

---

# 9. Как организовать этапы внутри каждого компонента

Для каждого из четырёх компонентов я бы использовал одинаковую последовательность:

### Step 1 — Specification

```text
SPEC.md
```

Определить contract.

### Step 2 — Schema

```text
JSON Schema
```

### Step 3 — Pydantic models

```text
models/
```

### Step 4 — Service interface

```text
service/
```

### Step 5 — LLM prompt

```text
prompts/
```

### Step 6 — Validation

```text
validators/
```

### Step 7 — Regression dataset

```text
fixtures/
```

### Step 8 — Integration

```text
pipeline/
```

### Step 9 — Metrics

```text
evaluation/
```

Это позволит не получить ситуацию:

> "LLM вроде генерирует правильный JSON, но непонятно, насколько он действительно стабилен."

---

# 10. Особое внимание Classification 2.0 → GenericCanonical

Я бы сделал **Schema Resolver**, а не жёсткое условие в worker:

```python
if classification.type == "appointment":
    ...
elif classification.type == "laboratory":
    ...
```

Вместо этого:

```python
resolution = schema_registry.resolve(
    classification
)
```

Например:

```text
appointment
    → appointment:v2

laboratory
    → laboratory:v2

discharge
    → generic:v2

unknown
    → generic:v2
```

Это даст вам возможность позже добавить:

```text
imaging:v1
prescription:v1
discharge:v2
```

без переписывания pipeline.

---

# 11. Какой компонент даст максимальный эффект первым

С точки зрения зависимости:

| Этап                     | Что создаёт                      |
| ------------------------ | -------------------------------- |
| Canonical Core           | общий фундамент                  |
| **Classification 2.0**   | маршрутизацию                    |
| **PII Gate**             | policy/security boundary         |
| **GenericCanonical 2.0** | универсальный fallback           |
| **AppointmentCanonical** | первый полноценный domain schema |

Поэтому я бы **не начинал с AppointmentCanonical**.

И особенно не начинал бы с большого количества medical fields.

Сначала нужно стабилизировать:

```text
Document
    ↓
Classification
    ↓
PII policy
    ↓
Canonical contract
```

После этого AppointmentCanonical становится относительно изолированной domain-задачей.

---

# 12. Практический порядок commits / milestones

Я бы даже организовал работу агента примерно так:

```text
M0 — Canonical foundation
    ↓
M1 — Classification 2.0 contract
    ↓
M2 — Classification 2.0 implementation
    ↓
M3 — Classification evaluation
    ↓
M4 — PII Gate specification
    ↓
M5 — PII Gate implementation   ← открытая проблема: утечка в fields.note, см. §13
    ↓
M6 — PII Gate evaluation
    ↓
M7 — GenericCanonical 2.0 specification
    ↓
M8 — GenericCanonical implementation
    ↓
M9 — GenericCanonical regression/evaluation
    ↓
M10 — Schema Registry / Resolver
    ↓
M11 — AppointmentCanonical specification
    ↓
M12 — AppointmentCanonical implementation
    ↓
M13 — Appointment regression/evaluation
    ↓
M14 — End-to-end pipeline
```

---

# 13. M5 — открытая проблема: утечка в `fields.note`

Зафиксировано, потому что M5 нельзя начинать как «доделать обвязку по плану»:
в текущем виде план закрыл бы утечку только частично, и это выглядело бы как
починка.

Архитектурный референс: [PII GATE/IMPL_ARCH.md](./PII%20GATE/IMPL_ARCH.md).
Состояние кода: [PII GATE/IMPL_RPRT.md](./PII%20GATE/IMPL_RPRT.md).

## 13.1. Что произошло

M4 — контракт, в pipeline не вызывается ничего. Утечка при этом **живая**:
каждый обработанный документ проходит её прямо сейчас.

```text
2b8fdd0d…/canonical.json → fields.note, 322 символа
fbbcb675…/canonical.json → fields.note, 759 символов
```

`fields` в обоих случаях содержит **только** `note`. То есть не «имя мелькнуло
в тексте», а весь клинический документ лёг в одну строку свободного текста.

```text
2b8fdd0d   ФИО пациента · ФИО врача · адрес · номер талона
fbbcb675   ФИО пациента · возраст и пол · лабораторный номер ·
           ФИО врача · диагноз · дата забора
```

Цепочка до PostgreSQL:

```text
build_canonical            pipeline.py:164
    │
    ├──▶ canonical.json     pipeline.py:199   → S3
    ├──▶ structured.md     pipeline.py:203   → S3   (ФИО подтверждено в обоих)
    └──▶ event.data        pipeline.py:236   → DocumentAnalysisCompleted
                                                   │
                                                   ▼
                                    extraction.data = event.data
                                    account-api/app/services/documents.py:536
                                                   │
                                                   ▼
                                    document_extractions.data
```

## 13.2. Почему правило промпта не сработало

`app/prompts/canonical.yaml:100` содержит прямой запрет:

```text
- Never include patient identity (name, date of birth, SNILS, insurance policy number).
```

Модель его нарушила. Правило в промпте — это **просьба, а не контроль**: оно
не проверяется и не может быть проверено. Доказательство обратного получено
на реальных прогонах, поэтому опираться на промпт в этой точке нельзя.

## 13.3. Почему «просто добавить контур 2» утечку не закроет

Контур 2 ловит находку и **логирует** её, но по текущей таблице политики
не останавливает:

```text
stage=canonical, destination=persistence  →  базовая таблица (policy.py:44-45)

  person_name     action=allow   risk=medium
  ticket_number   action=allow   risk=high

  →  decision = ALLOW
  →  DECISION_REMEDIATION[allow] = warn
  →  документ сохраняется С ИМЕНЕМ ПАЦИЕНТА
```

Эскалация `redaction_available` здесь не срабатывает: она срабатывает только на
действии `REDACT`, а базовая таблица не выдаёт его никогда — 22 `allow` и
один `block` (`SECRET`).

Отдельно: `SANITIZE` нечем выполнять. `PIIRedactor.redact()` принимает строку
markdown, а `fields.note` — вложенный путь в dict. Санитайзера payload в
контракте не существует.

Итог без изменений: guard пишет `pii.scan.completed` и сохраняет ФИО. Это
хуже молчания — появляется запись, которая выглядит как контроль.

## 13.4. Что M5 обязан решить

```text
1. Эскалировать identity/contact/government/medical_id на
   stage=canonical, destination=persistence

2. Дать механизм выполнить remediation для вложенного пути
   (mask по field_path), а не только для markdown-строки
```

Два варианта:

| | Механизм | Поведение | Цена |
| --- | --- | --- | --- |
| **A** | `REDACT` + санитайзер payload | утечка закрыта, документ сохраняется с маской | новый контракт, ~20 строк |
| **B** | `BLOCK` → `RETRY_THEN_FAIL` | утечка закрыта, повтор extraction с более строгим промптом | легитимные заметки с ФИО будут падать |

Рекомендован **A**: он сохраняет документ и не создаёт операционной нагрузки
на легитимных данных.

Оба варианта — **major-бамп** `PII_POLICY_VERSION` 1.0.0 → 2.0.0: по правилу
SemVer в `app/pii/persistence.py` любое изменение, меняющее решение, является
major.

## 13.5. Ловушка двух точек дампа

Объект `canonical` сериализуется **дважды**, и это главный риск реализации:

```text
pipeline.py:199   canonical_json = json.dumps(canonical.model_dump(...))   → S3
pipeline.py:236   data={**canonical.model_dump(...), ...}                 → событие → БД
```

Санитизировать нужно **сам объект `canonical` до обеих точек**. Починка только
:199 оставит ФИО в PostgreSQL через :236 — при этом контур будет выглядеть
работающим, а утечка сохранится. Нужен тест, ассертящий чистоту обоих дампов
на payload с утечкой.

## 13.6. Блокеры обвязки, найденные при подготовке

```text
organization_id обязателен в PIIPolicyContext, но отсутствует
  в ProcessingContext, и в контрактах событий (DocumentEvent,
  DocumentConverted) нет ни organization, ни tenant.
  Единственный источник — settings.s3_tenant_id. Использовать его
  как заглушку, не трогая cross-package контракт событий.

PIIDetector.detect принимает NormalizedDocument, а guard обходит
  строковые листья. Нужен detect_text(text) в протоколе,
  detect() становится обёрткой. Minor-бамп контракта.

Агрегация только ВНУТРИ листа, никогда между листьями: два пути
  с одинаковым значением схлопнутся в один, remediation починит
  один путь, и утечка останется во втором.

OCR отправляет документ во внешний LLM на pipeline.py:92 — раньше
  обоих контуров. Полностью реализованный M5 этот вызов не
  прикроет. Либо gate ставится перед OCR, либо вызов документируется
  как доверенный. Это открытый вопрос, а не решённый факт.
```

## 13.7. Границы текущего контроля

Санитизация закроет **идентификаторы**, но не сделает `fields.note` безопасным.
В `fbbcb675` там лежит диагноз, лабораторный номер и дата забора, а
`PIICategory` клинических фактов не содержит намеренно (IMPL_ARCH §4) —
это работа gate над структурой, а не над таксономией PII.

Отсюда вывод: для произвольного клинического прозрачного текста правильное
средство — структурное (не класть запись в `note`), а не PII-контроль. Guard
снижает утечку идентификаторов; он не является способом сделать свободный
текст пригодным к хранению.

## 13.8. Решение по объёму M5

```text
В объёме:   контур 2 (canonical guard)
Вне объёма: контур 1 (source gate перед extraction)
            markdown-редакция PIIRedactor
            destination EXTERNAL_LLM
            комбинационный порог для REVIEW
            OCR-вызов на pipeline.py:92
            account-api (PII metadata внутренняя, API не добавляем)
```

---

## Итоговая рекомендация


**Я бы сейчас двигался именно так:**

```text
                    ┌─────────────────┐
                    │ Canonical Core  │
                    └────────┬────────┘
                             │
                             ▼
                  ┌─────────────────────┐
                  │ Classification 2.0  │
                  └──────────┬──────────┘
                             │
                             ▼
                       ┌───────────┐
                       │ PII Gate  │
                       └─────┬─────┘
                             │
                             ▼
                  ┌─────────────────────┐
                  │ GenericCanonical 2.0│
                  └──────────┬──────────┘
                             │
                       Schema Registry
                             │
                             ▼
                  ┌─────────────────────┐
                  │ AppointmentCanonical│
                  └─────────────────────┘
```

**Главная идея:** `Classification` отвечает **что это**, `PII Gate` — **что с этими данными разрешено делать**, `GenericCanonical` — **как безопасно представить документ в универсальной структуре**, а `AppointmentCanonical` — **как глубже структурировать конкретный класс медицинского документа**.

И я бы обязательно поставил **evaluation/regression dataset после каждого из трёх LLM-компонентов**. Для вашего проекта это будет гораздо ценнее, чем просто набор unit-тестов: со временем именно эти датасеты позволят безопасно менять модели, prompts и schema versions, не деградируя качество extraction.
