Ниже я бы определил **PII Gate** как отдельный security/privacy этап в document-processing pipeline. Для вашего медицинского сервиса он особенно важен, потому что входной документ может содержать не только ФИО и контакты, но и медицинские сведения, номера документов, адреса и идентификаторы пациента.

# PII Gate — описание и план разработки

## 1. Назначение

**PII Gate** — это контролирующий слой между получением/извлечением содержимого документа и его дальнейшей передачей в AI/extraction pipeline.

Его задача не в том, чтобы удалить персональные данные из медицинской карты.

Главная задача:

> определить, какие персональные и чувствительные данные присутствуют в документе, насколько уверенно они обнаружены и разрешено ли передавать данный artifact на следующий этап обработки.

В вашем pipeline:

```text
PDF / JPEG
    │
    ▼
Marker
    │
    ▼
marker.md
    │
    ▼
┌──────────────────┐
│    PII Gate      │
│                  │
│ detect           │
│ classify         │
│ validate         │
│ policy decision  │
└────────┬─────────┘
         │
         ▼
Classification 2.0
         │
         ▼
Schema Resolver
         │
         ▼
LLM Extraction
         │
         ▼
canonical.json
```

---

# 2. Важное принципиальное решение

Я бы разделил два понятия:

### PII detection

Ответ:

> Какие персональные данные есть в документе?

Например:

```json
{
  "type": "person_name",
  "value": "Иванов Иван Иванович"
}
```

### PII policy

Ответ:

> Можно ли с этим документом продолжать обработку?

Это разные задачи.

PII Gate не должен автоматически считать:

```text
PII detected → reject
```

Потому что в вашем случае наличие PII **ожидаемо**.

Медицинский документ без идентификаторов пациента часто вообще теряет смысл.

---

# 3. Что считать PII

Я бы сразу разделил категории.

## Identity

```text
PERSON_NAME
DATE_OF_BIRTH
AGE
GENDER
NATIONALITY
```

## Contact

```text
EMAIL
PHONE
ADDRESS
```

## Government / legal identifiers

```text
PASSPORT
NATIONAL_ID
INSURANCE_NUMBER
SNILS
INN
```

В зависимости от юрисдикции набор можно расширять.

## Medical identifiers

```text
PATIENT_ID
MEDICAL_RECORD_NUMBER
LAB_ORDER_ID
ENCOUNTER_ID
```

## Organization identifiers

```text
DOCTOR_NAME
DOCTOR_LICENSE
ORGANIZATION_NAME
ORGANIZATION_ID
```

Здесь важно не смешивать:

```text
medical organization
```

и:

```text
patient PII
```

Например название клиники само по себе обычно не является PII пациента.

---

# 4. Medical data — отдельная категория

Для вашего проекта я бы не называл всё это просто `PII`.

Нужен более общий термин:

```text
Sensitive Data
```

Например:

```text
PERSONAL
MEDICAL
IDENTIFIER
CONTACT
ORGANIZATION
```

Потому что:

```text
"Иванов Иван"
```

и:

```text
"диагноз: сахарный диабет"
```

имеют совершенно разную семантику.

Для будущего audit/policy layer это важно.

---

# 5. PII Finding

Основной объект:

```python
class PIIFinding(BaseModel):
    category: PIICategory
    value: str | None
    confidence: float

    source: PIISource

    start: int | None
    end: int | None

    detector_version: str

    metadata: dict[str, Any]
```

Например:

```json
{
  "category": "person_name",
  "value": "Иванов Иван Иванович",
  "confidence": 0.97,
  "source": "pattern",
  "detector_version": "1.0.0"
}
```

---

# 6. Не хранить PII в логах

Это один из самых важных security requirements.

Плохо:

```text
PII detected:
name=Иванов Иван Иванович
phone=+79991234567
```

Хорошо:

```text
PII detected:
category=person_name
confidence=0.97
document_id=...
```

Если значение действительно необходимо для debugging — только masked:

```text
И***** И***** И*********
```

или:

```text
+7******4567
```

---

# 7. Источники обнаружения

PII Gate лучше строить не на одном detector.

Я бы сделал abstraction:

```python
class PIIDetector(Protocol):
    def detect(
        self,
        document: NormalizedDocument,
    ) -> list[PIIFinding]:
        ...
```

И несколько detector implementations.

---

# 8. Detector №1 — regex/pattern

Для хорошо определяемых сущностей:

```text
EMAIL
PHONE
SNILS
INN
passport patterns
medical record IDs
```

Это:

* быстро;
* дешево;
* deterministic;
* легко тестируется.

---

# 9. Detector №2 — structured fields

Если Marker/extraction уже выделил:

```text
Patient:
Date of birth:
Phone:
Email:
```

то это гораздо более сильный сигнал.

Например:

```text
Patient: Иванов Иван Иванович
```

не нужно пытаться распознавать имя исключительно NLP-моделью.

---

# 10. Detector №3 — NER

Для:

```text
PERSON
LOCATION
ORGANIZATION
```

можно использовать NER.

Но я бы не делал NER первым implementation requirement.

Для первой версии:

```text
regex
+
document structure
+
known labels
```

будет проще контролировать.

NER можно добавить как второй уровень.

---

# 11. Detector №4 — LLM

LLM я бы также не делал primary detector.

Например:

```text
regex
   ↓
structured extraction
   ↓
NER
   ↓
LLM fallback
```

LLM полезен для сложных случаев:

```text
"пациент ранее наблюдался у доктора Петрова..."
```

но не должен быть единственным механизмом защиты.

---

# 12. PII Risk Level

Для каждого finding:

```text
LOW
MEDIUM
HIGH
CRITICAL
```

Например:

```text
EMAIL              LOW
PHONE              MEDIUM
PERSON_NAME        MEDIUM
DATE_OF_BIRTH      MEDIUM
PASSPORT           HIGH
MEDICAL_RECORD_ID  HIGH
```

Но это **policy configuration**, а не абсолютная классификация.

---

# 13. PII Gate Decision

Самое важное — результат Gate.

```python
class PIIDecision(str, Enum):
    ALLOW = "allow"
    ALLOW_WITH_WARNING = "allow_with_warning"
    REVIEW = "review"
    BLOCK = "block"
```

Например:

### Обычная медицинская карта

```json
{
  "decision": "allow",
  "findings": [
    "person_name",
    "date_of_birth",
    "medical_record_id"
  ]
}
```

Это нормально.

---

### Подозрительный документ

Например обнаружен паспорт + множество неожиданных идентификаторов:

```json
{
  "decision": "review"
}
```

---

### Security violation

Например документ содержит credentials/secrets:

```text
API key
password
private key
```

Тогда:

```json
{
  "decision": "block"
}
```

Это уже не обычный medical PII.

---

# 14. PII Gate не должен модифицировать оригинальный документ

Я бы принципиально сделал:

```text
original.pdf
    ↓
immutable
```

и:

```text
marker.md
    ↓
immutable
```

PII Gate создаёт metadata:

```text
pii/result.json
```

Но не перезаписывает оригинал.

---

# 15. Отдельный redacted artifact

Если в будущем потребуется отправлять обезличенную версию в сторонний LLM:

```text
marker.md
   │
   ▼
PII Gate
   │
   ├── result.json
   │
   └── redacted.md
```

Например:

```text
Иванов Иван Иванович
```

↓

```text
[PATIENT_NAME]
```

Но это **должно быть отдельным artifact**.

Нельзя заменять оригинал.

---

# 16. Это особенно важно для вашей LLM архитектуры

Я бы предусмотрел два режима:

### Trusted LLM

Если модель работает внутри вашего контролируемого окружения:

```text
marker.md
   ↓
LLM
```

PII обнаруживается, но не обязательно редактируется.

### External LLM

Если используется внешний API:

```text
marker.md
   ↓
PII Gate
   ↓
redaction
   ↓
external LLM
```

Это позволит позже менять LLM provider без переписывания document pipeline.

---

# 17. PII Gate должен быть policy-driven

Не делать:

```python
if pii_found:
    block()
```

Вместо этого:

```python
policy.evaluate(findings, context)
```

Контекст может включать:

```text
source
organization
document_type
processing_environment
llm_provider
user_consent
```

Например:

```text
organization A
→ internal processing
→ allow

external LLM
→ redact

unknown destination
→ block
```

---

# 18. Context для Policy

Я бы заложил:

```python
PIIContext(
    document_id,
    organization_id,
    user_id,
    document_type,
    processing_stage,
    destination,
    llm_provider,
)
```

Не обязательно реализовывать все поля сразу.

Но API стоит сделать расширяемым.

---

# 19. PII Result

Например:

```json
{
  "document_id": "doc_123",

  "decision": "allow",

  "risk_level": "medium",

  "findings_count": 7,

  "categories": {
    "person_name": 1,
    "date_of_birth": 1,
    "medical_record_id": 1,
    "doctor_name": 1,
    "organization": 1,
    "address": 2
  },

  "detector_version": "1.0.0",

  "policy_version": "1.0.0",

  "processed_at": "2026-09-21T10:00:00Z"
}
```

Обратите внимание:

**я бы не сохранял `value` в aggregate result.**

Полный `PIIFinding` может существовать отдельно и иметь более строгий access control.

---

# 20. Где хранить PII Result

Например:

```text
documents/
    {document_id}/
        original/
            source.pdf

        marker/
            document.md

        pii/
            result.json

        classification/
            result.json

        canonical/
            canonical.json

        structured/
            document.md
```

---

# 21. Database

В первой версии я бы не создавал сложную normalized database модель для каждого PII finding.

Можно хранить:

```text
document_processing
```

с:

```text
pii_status
pii_risk_level
pii_detector_version
pii_policy_version
```

А детальный результат:

```text
S3 pii/result.json
```

Если понадобится поиск:

> покажи все документы, где был обнаружен passport

тогда добавить отдельную таблицу.

---

# 22. Audit

PII Gate должен писать audit event:

```text
PII_SCAN_COMPLETED
```

Например:

```json
{
  "event": "PII_SCAN_COMPLETED",
  "document_id": "...",
  "decision": "allow",
  "risk_level": "medium",
  "detector_version": "1.0.0",
  "policy_version": "1.0.0"
}
```

И:

```text
PII_BLOCKED
PII_REVIEW_REQUIRED
PII_REDACTION_CREATED
```

При этом audit log также **не должен содержать PII values**.

---

# 23. Интеграция с Classification 2.0

Я бы поставил их следующим образом:

```text
Marker
   │
   ▼
PII Gate
   │
   ▼
Classification 2.0
   │
   ▼
Schema Resolver
   │
   ▼
LLM Extraction
```

Почему PII раньше Classification?

Потому что classification тоже работает с потенциально чувствительным содержимым.

Но если classification полностью локальный и deterministic, порядок можно оптимизировать:

```text
Marker
   │
   ├───────────────┐
   ▼               ▼
PII Gate      Classification
   │               │
   └───────┬───────┘
           ▼
       Policy Gate
           │
           ▼
       Extraction
```

Для масштабируемой системы я предпочёл бы именно второй вариант.

---

# 24. Более правильная архитектура

В результате получается:

```text
                       marker.md
                           │
              ┌────────────┴────────────┐
              │                         │
              ▼                         ▼
        Classification               PII Gate
              │                         │
              │                         │
              └────────────┬────────────┘
                           ▼
                     Policy Engine
                           │
               ┌───────────┼───────────┐
               ▼           ▼           ▼
             ALLOW       REVIEW       BLOCK
               │           │
               ▼           ▼
          Extraction     Queue
               │
               ▼
         canonical.json
```

Это уже гораздо ближе к production-grade pipeline.

---

# 25. PII Gate и Organization

С учётом вашей модели `Organization` я бы сразу предусмотрел:

```text
Organization
      │
      └── ProcessingPolicy
```

В будущем организация сможет иметь policy:

```text
external_llm_allowed = false
redaction_required = true
```

или:

```text
external_llm_allowed = true
```

Но на текущем этапе это можно оставить как future extension.

---

# 26. PII Gate и user access

Очень важно:

**PII detection result не должен автоматически становиться доступным specialist/client через обычный API.**

Пользователь должен видеть:

```text
document
classification
analysis
```

но не:

```text
raw PII findings
detector internals
policy decisions
```

PII metadata — скорее security/internal artifact.

---

# 27. API

Внутренний API можно сделать минимальным:

```http
POST /internal/documents/{document_id}/pii-scan
```

Но если pipeline находится в одном worker process, HTTP endpoint вообще не нужен.

Предпочтительно:

```python
result = pii_gate.scan(document)
```

То есть сначала обычный domain/service component.

Отдельный service имеет смысл только при существенной нагрузке.

---

# 28. План разработки

## Phase 1 — Domain contract

Создать:

```text
pii/
├── domain/
│   ├── enums.py
│   ├── models.py
│   └── result.py
```

Определить:

* `PIICategory`
* `PIISource`
* `PIIRiskLevel`
* `PIIDecision`
* `PIIFinding`
* `PIIScanResult`

---

## Phase 2 — NormalizedDocument

Использовать тот же normalized representation, который создаётся для Classification 2.0.

Это важно:

**не делать второй parser Marker.md.**

```text
Marker
 ↓
NormalizedDocument
 ├── Classification
 └── PII Gate
```

---

## Phase 3 — Pattern detectors

Реализовать сначала:

```text
EMAIL
PHONE
DATE_OF_BIRTH
SNILS
INN
PASSPORT
```

с учётом вашей целевой юрисдикции.

---

## Phase 4 — Structured detectors

Распознавать:

```text
Patient:
Пациент:
ФИО:
Дата рождения:
№ медицинской карты:
```

и аналогичные document labels.

---

## Phase 5 — PII aggregation

Собрать:

```text
findings
 ↓
deduplication
 ↓
confidence
 ↓
risk
```

Например один телефон, найденный тремя detector'ами:

```text
regex
NER
structured field
```

должен стать одним finding.

---

# 29. Phase 6 — Policy Engine

Создать:

```text
pii/policy/
    policy.py
    rules.py
```

Пример:

```python
decision = policy.evaluate(
    findings=findings,
    context=context,
)
```

Первоначальная policy:

```text
expected medical PII
→ ALLOW

high-risk unexpected PII
→ REVIEW

secrets/credentials
→ BLOCK
```

---

# 30. Phase 7 — Redaction

На этом этапе реализовать только abstraction:

```python
redact(document, findings)
```

и artifact:

```text
pii/redacted.md
```

Не обязательно включать redaction в основной pipeline сразу.

---

# 31. Phase 8 — Persistence

Добавить в processing state:

```text
pii_status
pii_risk_level
pii_decision
pii_detector_version
pii_policy_version
```

и:

```text
pii/result.json
```

в object storage.

---

# 32. Phase 9 — Audit

Добавить события:

```text
PII_SCAN_STARTED
PII_SCAN_COMPLETED
PII_REVIEW_REQUIRED
PII_BLOCKED
PII_REDACTED
```

Никаких raw PII values в audit.

---

# 33. Phase 10 — Tests

Минимальный dataset:

```text
tests/fixtures/pii/
├── clean/
├── patient/
├── laboratory/
├── appointment/
├── prescription/
├── mixed/
└── malicious/
```

Тесты:

```text
test_email_detection
test_phone_detection
test_patient_name_detection
test_birth_date_detection
test_medical_record_id_detection

test_duplicate_findings
test_confidence
test_risk_level

test_allow_policy
test_review_policy
test_block_policy

test_no_pii_in_logs
test_no_pii_in_audit
```

---

# 34. False positives — отдельная задача

Для медицинских документов это критично.

Например:

```text
"Москва"
```

может быть:

* адрес пациента;
* адрес клиники;
* место рождения;
* просто название в документе.

Поэтому PII detector должен возвращать:

```text
category
confidence
context
```

а не только:

```text
Москва → LOCATION
```

---

# 35. False negatives

Ещё важнее.

Например:

```text
Пациент: И.И. Иванов
```

NER может не распознать это как имя.

Поэтому комбинация:

```text
structured labels
+
patterns
+
NER
```

лучше единственной модели.

---

# 36. Security requirements

Я бы добавил отдельный раздел в development plan:

### PII Gate MUST

* не менять original artifact;
* не писать PII в application logs;
* не писать PII в audit logs;
* не передавать PII в telemetry;
* version detectors;
* version policies;
* сохранять decision;
* иметь deterministic detectors;
* поддерживать redaction;
* иметь regression dataset.

### PII Gate SHOULD

* поддерживать несколько detector types;
* поддерживать organization-specific policies;
* иметь evaluation metrics;
* поддерживать повторный scan после изменения detector version.

---

# 37. Важный момент: PII Gate ≠ compliance

Я бы специально зафиксировал это в документации проекта.

PII Gate — технический механизм:

```text
detect
classify
policy
redact
audit
```

Он сам по себе не означает:

```text
GDPR compliant
HIPAA compliant
152-ФЗ compliant
```

Compliance зависит ещё от:

* хранения;
* доступа;
* retention;
* consent;
* encryption;
* data residency;
* processor agreements;
* deletion;
* backups;
* audit;
* incident response.

Поэтому PII Gate следует рассматривать как **один из security/privacy controls**, а не как compliance layer целиком.

---

# 38. Итоговый pipeline проекта

С учётом уже спроектированного Classification 2.0 я бы зафиксировал следующий pipeline:

```text
                    Upload
                       │
                       ▼
                    Object
                    Storage
                       │
                       ▼
                     Marker
                       │
                       ▼
                 marker.md
                       │
                       ▼
              NormalizedDocument
                       │
          ┌────────────┴────────────┐
          │                         │
          ▼                         ▼
     Classification              PII Gate
          │                         │
          │                         ▼
          │                  PII Policy
          │                         │
          └────────────┬────────────┘
                       ▼
                 Processing Gate
                       │
             ┌─────────┼─────────┐
             ▼         ▼         ▼
           ALLOW     REVIEW     BLOCK
             │         │
             ▼         ▼
          Schema      Human /
          Resolver    later
             │
             ▼
         LLM Extractor
             │
             ▼
        canonical.json
             │
             ▼
       Structured Markdown
             │
             ▼
      Analytics / Search /
        Vectorization
```

### Я бы реализовал PII Gate **до LLM Extraction**, но не как отдельный микросервис.

На текущем этапе оптимальная структура:

```text
ai-worker/
├── classification/
├── pii/
│   ├── domain/
│   ├── detectors/
│   ├── policy/
│   ├── redaction/
│   └── service.py
├── extraction/
├── schemas/
└── processing/
```

Это даст вам хорошую границу: **Marker отвечает за получение текста, Classification — за тип документа, PII Gate — за privacy/security decision, Extraction — за получение canonical structure.**
