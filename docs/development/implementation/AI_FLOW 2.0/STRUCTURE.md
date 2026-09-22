Да. С учётом того, что мы уже разделили `Classification 2.0`, `PII Gate`, `GenericCanonical 2.0` и специализированные canonical-схемы, я бы **не делал `ai-worker` набором отдельных FastAPI-приложений**. Это должен быть worker/service, который оркестрирует AI processing pipeline, а domain-specific логика находится внутри отдельных модулей.

Я бы предложил такую структуру:

```text
services/
└── ai-worker/
    │
    ├── app/
    │   ├── __init__.py
    │   ├── main.py
    │   │
    │   ├── config/
    │   │   ├── __init__.py
    │   │   ├── settings.py
    │   │   └── logging.py
    │   │
    │   ├── worker/
    │   │   ├── __init__.py
    │   │   ├── runner.py
    │   │   ├── consumer.py
    │   │   ├── publisher.py
    │   │   └── lifecycle.py
    │   │
    │   ├── pipeline/
    │   │   ├── __init__.py
    │   │   ├── pipeline.py
    │   │   ├── context.py
    │   │   ├── stages.py
    │   │   ├── result.py
    │   │   └── errors.py
    │   │
    │   ├── classification/
    │   │   ├── __init__.py
    │   │   ├── service.py
    │   │   ├── models.py
    │   │   ├── schemas.py
    │   │   ├── prompts/
    │   │   │   ├── v1/
    │   │   │   └── v2/
    │   │   ├── validators.py
    │   │   └── exceptions.py
    │   │
    │   ├── pii/
    │   │   ├── __init__.py
    │   │   ├── gate.py
    │   │   ├── detector.py
    │   │   ├── policy.py
    │   │   ├── models.py
    │   │   ├── validators.py
    │   │   └── exceptions.py
    │   │
    │   ├── canonical/
    │   │   ├── __init__.py
    │   │   │
    │   │   ├── core/
    │   │   │   ├── models/
    │   │   │   │   ├── document.py
    │   │   │   │   ├── person.py
    │   │   │   │   ├── organization.py
    │   │   │   │   ├── identifier.py
    │   │   │   │   ├── observation.py
    │   │   │   │   ├── value.py
    │   │   │   │   ├── quantity.py
    │   │   │   │   └── provenance.py
    │   │   │   │
    │   │   │   └── validation.py
    │   │   │
    │   │   ├── generic/
    │   │   │   ├── __init__.py
    │   │   │   ├── canonical.py
    │   │   │   ├── extractor.py
    │   │   │   ├── validator.py
    │   │   │   ├── renderer.py
    │   │   │   └── prompts/
    │   │   │       └── v2/
    │   │   │
    │   │   ├── appointment/
    │   │   │   ├── __init__.py
    │   │   │   ├── canonical.py
    │   │   │   ├── encounter.py
    │   │   │   ├── complaint.py
    │   │   │   ├── history.py
    │   │   │   ├── examination.py
    │   │   │   ├── diagnosis.py
    │   │   │   ├── procedure.py
    │   │   │   ├── medication.py
    │   │   │   ├── recommendation.py
    │   │   │   ├── follow_up.py
    │   │   │   ├── extractor.py
    │   │   │   ├── validator.py
    │   │   │   ├── renderer.py
    │   │   │   └── prompts/
    │   │   │       └── v2/
    │   │   │
    │   │   ├── laboratory/
    │   │   │   ├── __init__.py
    │   │   │   ├── canonical.py
    │   │   │   ├── result.py
    │   │   │   ├── reference_range.py
    │   │   │   ├── extractor.py
    │   │   │   ├── validator.py
    │   │   │   ├── renderer.py
    │   │   │   └── prompts/
    │   │   │       └── v2/
    │   │   │
    │   │   └── registry/
    │   │       ├── registry.py
    │   │       ├── resolver.py
    │   │       └── definitions.py
    │   │
    │   ├── llm/
    │   │   ├── __init__.py
    │   │   ├── client.py
    │   │   ├── provider.py
    │   │   ├── models.py
    │   │   ├── structured_output.py
    │   │   ├── token_usage.py
    │   │   └── exceptions.py
    │   │
    │   ├── artifacts/
    │   │   ├── __init__.py
    │   │   ├── reader.py
    │   │   ├── writer.py
    │   │   ├── models.py
    │   │   └── storage.py
    │   │
    │   ├── messaging/
    │   │   ├── __init__.py
    │   │   ├── consumer.py
    │   │   ├── publisher.py
    │   │   ├── messages.py
    │   │   └── routing.py
    │   │
    │   ├── repositories/
    │   │   ├── __init__.py
    │   │   ├── processing.py
    │   │   ├── documents.py
    │   │   └── canonical.py
    │   │
    │   ├── provenance/
    │   │   ├── __init__.py
    │   │   ├── service.py
    │   │   └── models.py
    │   │
    │   └── health/
    │       ├── __init__.py
    │       └── checks.py
    │
    ├── tests/
    │   ├── unit/
    │   │   ├── classification/
    │   │   ├── pii/
    │   │   ├── canonical/
    │   │   │   ├── generic/
    │   │   │   ├── appointment/
    │   │   │   └── laboratory/
    │   │   ├── llm/
    │   │   └── pipeline/
    │   │
    │   ├── integration/
    │   │   ├── test_pipeline.py
    │   │   ├── test_messaging.py
    │   │   └── test_artifacts.py
    │   │
    │   └── fixtures/
    │       ├── classification/
    │       ├── pii/
    │       ├── generic/
    │       ├── appointment/
    │       └── laboratory/
    │
    ├── prompts/
    │   └── README.md
    │
    ├── Dockerfile
    ├── pyproject.toml
    ├── README.md
    └── .env.example
```

## Главное разделение

Я бы концептуально разделил `ai-worker` на **5 уровней**:

```text
                         ai-worker
                             │
       ┌─────────────────────┼──────────────────────┐
       │                     │                      │
 Infrastructure           Pipeline               Domain
       │                     │                      │
       ▼                     ▼                      ▼
 messaging              orchestration          canonical
 artifacts              processing             classification
 LLM client             context                PII
 repositories                                  schemas
```

Это важно, потому что иначе через несколько месяцев `ai-worker` превратится в один большой `tasks.py`.

---

# 1. `worker/` — только запуск worker

```text
worker/
├── runner.py
├── consumer.py
├── publisher.py
└── lifecycle.py
```

Этот слой **не должен знать**, как извлекается диагноз или как работает AppointmentCanonical.

Его задача:

```text
RabbitMQ
   ↓
message
   ↓
pipeline.process()
   ↓
success/failure
   ↓
RabbitMQ
```

Например:

```python
async def handle(message):
    result = await pipeline.process(message)

    if result.success:
        await publisher.publish(result.events)
    else:
        await publisher.publish_failure(result)
```

---

# 2. `pipeline/` — сердце ai-worker

Это, на мой взгляд, самый важный каталог.

```text
pipeline/
├── pipeline.py
├── context.py
├── stages.py
├── result.py
└── errors.py
```

Pipeline должен быть примерно таким:

```text
Input Artifact
      │
      ▼
Load
      │
      ▼
Normalize
      │
      ▼
Classification
      │
      ▼
PII Gate
      │
      ▼
Schema Resolution
      │
      ▼
Canonical Extraction
      │
      ▼
Validation
      │
      ▼
Provenance
      │
      ▼
Render
      │
      ▼
Persist
      │
      ▼
Publish Event
```

Например:

```python
class DocumentPipeline:

    async def process(
        self,
        context: ProcessingContext,
    ) -> PipelineResult:

        document = await self.load(context)

        normalized = await self.normalize(
            document,
            context,
        )

        classification = await self.classify(
            normalized,
            context,
        )

        pii_result = await self.pii_gate.inspect(
            normalized,
            context,
        )

        schema = self.schema_registry.resolve(
            classification
        )

        canonical = await schema.extract(
            normalized,
            context,
        )

        validation = schema.validate(
            canonical
        )

        ...
```

---

# 3. `pipeline/context.py`

Я бы обязательно сделал единый `ProcessingContext`.

Например:

```python
@dataclass
class ProcessingContext:
    processing_id: UUID
    document_id: UUID
    user_id: UUID | None

    organization_id: UUID | None

    source_artifact_id: str

    classification: ClassificationResult | None = None

    pii_result: PIIResult | None = None

    schema_name: str | None = None
    schema_version: str | None = None
```

В него постепенно добавляются:

```text
model
prompt_version
token_usage
processing timestamps
trace_id
```

Это лучше, чем передавать 15 аргументов между сервисами.

---

# 4. `classification/`

Classification — самостоятельный bounded context.

```text
classification/
├── service.py
├── models.py
├── schemas.py
├── validators.py
├── exceptions.py
└── prompts/
```

`service.py`:

```python
class ClassificationService:
    async def classify(
        self,
        document: NormalizedDocument,
        context: ProcessingContext,
    ) -> ClassificationResult:
        ...
```

LLM client при этом находится **не здесь**.

Classification знает:

```text
какой prompt использовать
какой schema ожидать
как валидировать результат
```

Но не знает:

```text
как отправляется HTTP request конкретному LLM provider.
```

---

# 5. `pii/`

Аналогично:

```text
pii/
├── gate.py
├── detector.py
├── policy.py
├── models.py
├── validators.py
└── exceptions.py
```

Здесь важно разделить:

### Detection

```text
Что найдено?
```

### Policy

```text
Что с этим делать?
```

### Gate

```text
Можно ли продолжать pipeline?
```

Например:

```python
findings = detector.detect(document)

decision = policy.evaluate(findings)

return gate.build_result(decision)
```

Это позволит в будущем менять PII policy без переписывания detector.

---

# 6. `canonical/`

Я бы сделал его **domain layer**, а не просто набором Pydantic моделей.

```text
canonical/
├── core/
├── generic/
├── appointment/
├── laboratory/
└── registry/
```

Особенно важен:

```text
registry/
```

Например:

```python
registry.resolve(
    document_type="appointment"
)
```

возвращает:

```text
AppointmentCanonicalHandler
```

а:

```python
registry.resolve(
    document_type="unknown"
)
```

возвращает:

```text
GenericCanonicalHandler
```

Таким образом pipeline не содержит:

```python
if type == ...
elif type == ...
```

---

# 7. `canonical/core/`

Это **не GenericCanonical**.

Это общие primitives:

```text
core/
└── models/
    ├── person.py
    ├── organization.py
    ├── observation.py
    ├── quantity.py
    ├── identifier.py
    └── provenance.py
```

Например `Observation` используется:

```text
LaboratoryCanonical
AppointmentCanonical
GenericCanonical
```

---

# 8. `canonical/generic/`

Здесь находится полноценный:

```text
GenericCanonical 2.0
```

```text
generic/
├── canonical.py
├── extractor.py
├── validator.py
├── renderer.py
└── prompts/
```

Это fallback schema.

---

# 9. `canonical/appointment/`

Здесь:

```text
AppointmentCanonical 2.0
```

и только appointment-specific domain logic:

```text
encounter
complaint
history
examination
diagnosis
procedure
medication
recommendation
follow_up
```

Общие сущности оттуда не копируем.

---

# 10. `llm/`

Очень важно не смешивать LLM infrastructure с domain logic.

```text
llm/
├── client.py
├── provider.py
├── models.py
├── structured_output.py
├── token_usage.py
└── exceptions.py
```

Например:

```python
result = await llm.generate_structured(
    prompt=prompt,
    schema=ClassificationSchema,
)
```

Classification не должен знать:

```text
OpenAI
Anthropic
Ollama
vLLM
```

Это ответственность `llm/provider.py`.

---

# 11. `artifacts/`

Это слой работы с объектным storage:

```text
artifacts/
├── reader.py
├── writer.py
├── storage.py
└── models.py
```

Например:

```python
document = await artifact_reader.read(
    artifact_id=...
)
```

Pipeline не должен напрямую вызывать:

```python
boto3.get_object(...)
```

---

# 12. `messaging/`

RabbitMQ abstraction:

```text
messaging/
├── consumer.py
├── publisher.py
├── messages.py
└── routing.py
```

Например:

```text
document.ready
document.classified
document.pii_checked
document.canonicalized
document.processed
document.failed
```

---

# 13. `repositories/`

Я бы здесь был осторожен.

AI-worker **не должен становиться вторым backend application service**, который напрямую управляет всей бизнес-моделью пользователя.

Repository должен хранить только то, что необходимо processing pipeline:

```text
processing
documents
canonical
```

Например:

```text
processing_id
status
current_stage
error
model
prompt_version
timestamps
```

А не всю user/account/organization domain.

---

# 14. `provenance/`

Это я бы вынес отдельно, потому что со временем provenance станет очень важной частью продукта.

Например:

```json
{
  "field": "diagnoses[0].label",
  "source": {
    "artifact_id": "...",
    "offset": [1234, 1260]
  },
  "model": "...",
  "prompt_version": "...",
  "confidence": 0.97
}
```

Это даст возможность в UI показать:

> Диагноз извлечён из документа.

И потенциально:

> показать исходный фрагмент.

---

# 15. Где хранить prompts

Я бы **не хранил все prompts только в Python-файлах**.

Например:

```text
classification/prompts/v2/
    system.md
    extraction.md
```

и:

```text
canonical/appointment/prompts/v2/
    system.md
    extraction.md
```

Тогда prompt становится versioned artifact:

```text
appointment:v2
prompt:v2.3
model:x
```

И processing metadata может точно восстановить:

```text
какая модель
какой prompt
какая schema
```

использовались для получения результата.

---

# 16. Очень важное правило для AI-worker

Я бы зафиксировал:

> **LLM никогда не пишет непосредственно в PostgreSQL, S3 или RabbitMQ.**

Например:

```text
LLM
 ↓
raw response
 ↓
Pydantic
 ↓
schema validation
 ↓
semantic validation
 ↓
canonical object
 ↓
storage
```

То есть:

```text
                 LLM
                  │
                  ▼
           Structured output
                  │
                  ▼
             Pydantic
                  │
                  ▼
           JSON Schema
                  │
                  ▼
        Semantic validation
                  │
                  ▼
             Canonical
                  │
          ┌───────┼───────┐
          ▼       ▼       ▼
         S3      DB     Event
```

Это будет особенно важно для медицинских документов.

---

# 17. Что я бы НЕ помещал в ai-worker

Не стоит добавлять сюда:

```text
auth/
users/
organizations/
appointments/
permissions/
billing/
```

AI-worker должен знать:

```text
user_id
organization_id
document_id
```

но не должен быть владельцем соответствующих бизнес-доменов.

То есть:

```text
Account Service
    owns Users

Organization Service
    owns Organizations

Document Service
    owns Documents

AI Worker
    owns Processing
```

---

# 18. Финальная схема ответственности

Получается достаточно чистая система:

```text
┌──────────────────────────────────────────────┐
│                 AI WORKER                   │
│                                              │
│  ┌─────────────┐     ┌──────────────────┐  │
│  │   Worker    │────▶│    Pipeline      │  │
│  └─────────────┘     └────────┬─────────┘  │
│                               │             │
│              ┌────────────────┼────────────┐│
│              │                │            ││
│              ▼                ▼            ▼│
│       Classification       PII Gate    Schema Registry
│                                           │
│                         ┌─────────────────┼────────────┐
│                         ▼                 ▼            ▼
│                     Generic         Appointment    Laboratory
│                         │                 │            │
│                         └─────────────────┼────────────┘
│                                           │
│                                      Validation
│                                           │
│                                      Provenance
│                                           │
│                                      Rendering
│                                              │
└──────────────────────────────────────────────┘
             │              │
             ▼              ▼
           S3            RabbitMQ
```

### Я бы зафиксировал для текущего этапа следующие основные bounded contexts внутри `ai-worker`:

```text
1. worker          — execution
2. pipeline        — orchestration
3. classification  — document classification
4. pii             — privacy/security gate
5. canonical       — document schemas
6. llm             — LLM infrastructure
7. artifacts       — S3/object storage
8. messaging       — RabbitMQ
9. provenance      — extraction traceability
10. repositories   — processing persistence
```

И **не добавлял бы пока отдельные `analytics/`, `rag/`, `embeddings/`, `medical_history/`**. Это следующий слой после стабильного Canonical pipeline. Иначе `ai-worker` слишком рано превратится из document-processing worker в монолитный AI backend.
