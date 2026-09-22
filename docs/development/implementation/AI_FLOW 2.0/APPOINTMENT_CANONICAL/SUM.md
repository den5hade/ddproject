Да. Для вашего проекта я бы проектировал `AppointmentCanonical` как **специализированный medical-document canonical**, который описывает факт и содержание взаимодействия пациента с медицинским специалистом, но **не пытается выполнять медицинскую интерпретацию**.

Он должен хорошо покрывать:

* первичный и повторный приём;
* консультацию специалиста;
* осмотр;
* anamnesis;
* жалобы;
* объективный статус;
* предварительный/заключительный диагноз, если он указан в документе;
* назначения;
* рекомендации;
* план дальнейшего лечения/обследования;
* врача и медицинскую организацию;
* связь с пациентом;
* provenance каждого существенного извлечённого факта.

При этом я бы сразу заложил возможность дальнейшего расширения в сторону полноценной medical-history модели.

---

# 1. Место AppointmentCanonical в общей системе

Предлагаю закрепить такую структуру pipeline:

```text
                         Original Document
                                │
                                ▼
                             Marker
                                │
                                ▼
                         marker.md / JSON
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
              ┌─────────────────┼──────────────────┐
              │                 │                  │
              ▼                 ▼                  ▼
       Laboratory          Appointment          Generic
       Canonical            Canonical          Canonical
              │                 │                  │
              └─────────────────┼──────────────────┘
                                ▼
                         Canonical JSON
                                │
                                ▼
                       Structured Markdown
                                │
              ┌─────────────────┼─────────────────┐
              ▼                 ▼                 ▼
          PostgreSQL         Vector DB          Analytics
```

`AppointmentCanonical` при этом **не является записью в PostgreSQL о визите**.

Это важно.

Нужно разделять:

```text
AppointmentCanonical
    = extracted representation of a document

Appointment domain entity
    = application/domain representation of a medical encounter
```

Один appointment может быть подтверждён несколькими документами:

```text
Appointment
   │
   ├── visit summary.pdf
   ├── specialist report.pdf
   ├── prescription.pdf
   └── recommendation.pdf
```

Поэтому Canonical должен иметь возможность ссылаться на appointment/encounter, но не быть самим database record.

---

# 2. Главный принцип AppointmentCanonical

Я бы определил его следующим образом:

> **AppointmentCanonical представляет структурированную информацию, явно содержащуюся в документе о медицинском приёме, консультации или осмотре пациента, сохраняя distinction между source-derived facts и AI-derived interpretations.**

То есть если врач написал:

```text
Диагноз: гипертоническая болезнь
```

мы извлекаем:

```json
{
  "diagnoses": [
    {
      "label": "Гипертоническая болезнь"
    }
  ]
}
```

Но модель не должна самостоятельно добавлять:

```json
{
  "diagnoses": [
    {
      "label": "Гипертоническая болезнь",
      "severity": "moderate"
    }
  ]
}
```

если severity отсутствует в документе.

---

# 3. Структура AppointmentCanonical

Предлагаю следующий top-level contract:

```json
{
  "canonical_version": "2.0",
  "schema": "appointment",
  "schema_version": "2.0",

  "metadata": {},

  "document": {},

  "patient": {},

  "encounter": {},

  "practitioner": {},

  "organization": {},

  "complaints": [],

  "history": {},

  "examination": {},

  "observations": [],

  "diagnoses": [],

  "procedures": [],

  "medications": [],

  "recommendations": [],

  "follow_up": {},

  "attachments": [],

  "provenance": [],

  "extensions": {}
}
```

При этом я бы не делал все поля обязательными.

Документ:

```text
"только консультация"
```

может не содержать:

```text
diagnoses
medications
procedures
```

---

# 4. Metadata

Metadata описывает **процесс получения canonical**, а не содержание приёма.

```json
{
  "metadata": {
    "canonical_version": "2.0",
    "schema": "appointment",
    "schema_version": "2.0",

    "document_type": "appointment",

    "classification": {
      "type": "appointment",
      "confidence": 0.96
    },

    "extraction": {
      "model": "model-name",
      "prompt_version": "appointment-v2"
    },

    "created_at": "2026-09-21T12:00:00Z"
  }
}
```

Я бы также предусмотрел:

```text
classifier_version
pii_policy_version
processing_id
source_artifact_id
```

---

# 5. Document

```json
{
  "document": {
    "id": "doc_123",

    "title": "Заключение врача-кардиолога",

    "date": "2026-09-20",

    "language": "ru",

    "identifiers": [
      {
        "system": "organization",
        "value": "CARD-2026-000123"
      }
    ]
  }
}
```

`document.date` и `encounter.date` не обязательно должны совпадать.

Например:

```text
Приём: 20.09.2026
Документ подписан: 21.09.2026
```

---

# 6. Patient

Я бы использовал более строгую структуру, чем просто:

```json
"patient_name": "..."
```

Например:

```json
{
  "patient": {
    "id": null,

    "name": {
      "family": "Иванов",
      "given": ["Иван"],
      "middle": "Иванович",
      "text": "Иванов Иван Иванович"
    },

    "birth_date": "1980-01-01",

    "identifiers": []
  }
}
```

`id` может быть нашим internal patient ID, если он известен.

Но LLM не должна сама генерировать внутренний ID.

---

# 7. Practitioner

```json
{
  "practitioner": {
    "id": null,

    "name": {
      "family": "Петров",
      "given": ["Петр"],
      "middle": "Петрович"
    },

    "specialty": "кардиология",

    "qualification": null
  }
}
```

Важно разделять:

```text
specialty
```

и:

```text
qualification
```

Например:

```text
Кардиолог
Врач высшей категории
```

---

# 8. Organization

```json
{
  "organization": {
    "id": null,

    "name": "Медицинский центр X",

    "identifiers": [
      {
        "system": "INN",
        "value": "..."
      },
      {
        "system": "OGRN",
        "value": "..."
      }
    ],

    "department": "Кардиология",

    "branch": null
  }
}
```

Здесь можно использовать `organization_id`, если документ пришёл через вашу Organization API.

Это особенно важно для вашего будущего B2B pipeline.

---

# 9. Encounter

Это центральный объект AppointmentCanonical.

```json
{
  "encounter": {
    "id": null,

    "type": "outpatient",

    "status": "completed",

    "date": {
      "start": "2026-09-20T14:00:00",
      "end": "2026-09-20T14:40:00"
    },

    "specialty": "cardiology",

    "reason": null,

    "location": null
  }
}
```

---

# 10. Encounter type

Начальный enum:

```text
outpatient
inpatient
telemedicine
home_visit
emergency
preventive
follow_up
consultation
examination
unknown
```

Но лучше позволить:

```json
{
  "type": "custom",
  "label": "Консультация кардиолога"
}
```

---

# 11. Reason for visit

```json
{
  "encounter": {
    "reason": [
      {
        "text": "Повышенное артериальное давление"
      }
    ]
  }
}
```

Не нужно пытаться сразу превращать reason в ICD code.

Если код явно присутствует:

```json
{
  "coding": {
    "system": "ICD-10",
    "code": "I10",
    "display": "..."
  }
}
```

можно сохранить его.

---

# 12. Complaints

Очень важный раздел.

```json
{
  "complaints": [
    {
      "text": "Головная боль",

      "duration": {
        "value": 2,
        "unit": "weeks"
      },

      "frequency": "periodic",

      "severity": null
    }
  ]
}
```

Но я бы не заставлял LLM заполнять duration/frequency, если этого нет.

---

# 13. History

History должна быть extensible.

```json
{
  "history": {
    "present_illness": {
      "text": "..."
    },

    "past_medical_history": {
      "text": "..."
    },

    "family_history": {
      "text": "..."
    },

    "social_history": {
      "text": "..."
    },

    "allergies": [],

    "medications_before_visit": []
  }
}
```

Это особенно важно для будущего анализа medical history.

---

# 14. Почему history лучше разделить

Вместо:

```json
"history": "Пациент рассказал..."
```

лучше:

```text
present_illness
past_medical_history
family_history
social_history
allergies
medications
```

Это позволит в будущем искать:

```text
все аллергии пациента
```

или:

```text
изменения терапии
```

без повторного LLM processing.

---

# 15. Examination

Предлагаю:

```json
{
  "examination": {
    "general": {
      "text": "..."
    },

    "vital_signs": [],

    "physical_findings": [],

    "system_findings": []
  }
}
```

---

# 16. Vital signs

Например:

```json
{
  "vital_signs": [
    {
      "name": "blood_pressure",

      "value": {
        "systolic": 135,
        "diastolic": 85,
        "unit": "mmHg"
      },

      "measured_at": "2026-09-20T14:10:00"
    },

    {
      "name": "heart_rate",

      "value": {
        "value": 72,
        "unit": "bpm"
      }
    }
  ]
}
```

Не надо делать:

```text
blood_pressure_systolic
blood_pressure_diastolic
heart_rate
temperature
oxygen_saturation
...
```

top-level fields.

Используйте единый `Observation/Quantity` pattern.

---

# 17. Physical findings

Например:

```json
{
  "physical_findings": [
    {
      "system": "cardiovascular",
      "finding": "..."
    }
  ]
}
```

Или:

```json
{
  "system": "respiratory",
  "finding": "..."
}
```

---

# 18. Observations

Здесь я рекомендую **переиспользовать модель из GenericCanonical**.

Не создавать второй формат.

Например:

```json
{
  "observations": [
    {
      "id": "obs-1",

      "name": "Артериальное давление",

      "value": {
        "type": "quantity",
        "value": 135,
        "unit": "mmHg"
      },

      "context": "vital_sign",

      "confidence": 0.98
    }
  ]
}
```

То есть:

```text
Canonical Core
       │
       └── Observation
```

используется:

* GenericCanonical;
* AppointmentCanonical;
* LaboratoryCanonical.

Это сильно уменьшит дублирование.

---

# 19. Diagnoses

Предлагаю:

```json
{
  "diagnoses": [
    {
      "id": "dx-1",

      "label": "Гипертоническая болезнь",

      "coding": [
        {
          "system": "ICD-10",
          "code": "I10",
          "display": "..."
        }
      ],

      "status": "confirmed",

      "role": "primary",

      "source_text": "..."
    }
  ]
}
```

---

# 20. Diagnosis status

Минимальный набор:

```text
suspected
preliminary
confirmed
historical
ruled_out
unknown
```

И:

```text
primary
secondary
```

не смешивать со status.

---

# 21. Очень важный момент — diagnosis ≠ interpretation

LLM не должна сама делать:

```text
"diagnosis": "hypertension"
```

если документ говорит только:

```text
"АД 150/95"
```

В первом случае это extraction.

Во втором:

```text
observation
```

и диагноз отсутствует.

Это принципиально для медицинского приложения.

---

# 22. Procedures

Например:

```json
{
  "procedures": [
    {
      "name": "ЭКГ",

      "status": "completed",

      "date": "2026-09-20",

      "result_reference": null
    }
  ]
}
```

Если документ содержит только:

```text
Проведена ЭКГ
```

мы сохраняем procedure.

Не нужно автоматически генерировать результат.

---

# 23. Medications

Я бы сделал:

```json
{
  "medications": [
    {
      "name": "Лозартан",

      "dose": {
        "value": 50,
        "unit": "mg"
      },

      "route": "oral",

      "frequency": "once_daily",

      "duration": null,

      "status": "prescribed"
    }
  ]
}
```

Важно поддерживать:

```text
current
prescribed
stopped
historical
recommended
```

---

# 24. Recommendations

Не надо превращать рекомендации в medical logic.

Просто сохраняем:

```json
{
  "recommendations": [
    {
      "text": "Контроль артериального давления",
      "category": "monitoring"
    },
    {
      "text": "Повторная консультация через 1 месяц",
      "category": "follow_up"
    }
  ]
}
```

---

# 25. Follow-up

Можно сделать структурированным:

```json
{
  "follow_up": {
    "recommended": true,

    "date": "2026-10-20",

    "specialty": "cardiology",

    "reason": "Контроль терапии",

    "instructions": null
  }
}
```

Если дата неизвестна:

```json
{
  "recommended": true,
  "date": null
}
```

---

# 26. Provenance

Я бы сделал его общим для всех Canonical schemas.

Например:

```json
{
  "provenance": [
    {
      "target": "diagnoses[0]",

      "source": {
        "artifact_id": "marker-123",

        "location": {
          "type": "text_offset",
          "start": 1540,
          "end": 1582
        }
      },

      "method": "llm",

      "model": "model-name",

      "prompt_version": "appointment-v2"
    }
  ]
}
```

Это позволит реализовать:

> "Показать, откуда был взят этот диагноз."

---

# 27. Extensions

```json
{
  "extensions": {}
}
```

Например конкретная клиника может передавать:

```json
{
  "extensions": {
    "organization": {
      "department_code": "CARD-01",
      "visit_number": "123456"
    }
  }
}
```

Не надо менять core schema под каждого клиента.

---

# 28. Итоговая AppointmentCanonical schema

Концептуально:

```text
AppointmentCanonical
│
├── metadata
│
├── document
│
├── patient
│
├── encounter
│   ├── type
│   ├── status
│   ├── date
│   ├── specialty
│   ├── reason
│   └── location
│
├── practitioner
│
├── organization
│
├── complaints[]
│
├── history
│   ├── present_illness
│   ├── past_medical_history
│   ├── family_history
│   ├── social_history
│   ├── allergies
│   └── medications_before_visit
│
├── examination
│   ├── general
│   ├── vital_signs
│   ├── physical_findings
│   └── system_findings
│
├── observations[]
│
├── diagnoses[]
│
├── procedures[]
│
├── medications[]
│
├── recommendations[]
│
├── follow_up
│
├── attachments[]
│
├── provenance[]
│
└── extensions
```

---

# 29. Структура Canonical package

Я бы **не** делал:

```text
canonical/
├── generic.py
├── appointment.py
├── laboratory.py
```

Поскольку по мере развития проекта эти файлы быстро превратятся в большие монолиты.

Предлагаю:

```text
app/
└── canonical/
    │
    ├── core/
    │   ├── __init__.py
    │   │
    │   ├── models/
    │   │   ├── metadata.py
    │   │   ├── document.py
    │   │   ├── identifier.py
    │   │   ├── person.py
    │   │   ├── organization.py
    │   │   ├── observation.py
    │   │   ├── value.py
    │   │   ├── quantity.py
    │   │   ├── provenance.py
    │   │   └── relationship.py
    │   │
    │   ├── validation/
    │   │   ├── schema.py
    │   │   └── semantic.py
    │   │
    │   └── types.py
    │
    ├── generic/
    │   ├── __init__.py
    │   ├── models.py
    │   ├── schema.py
    │   ├── validator.py
    │   ├── extractor.py
    │   └── renderer.py
    │
    ├── appointment/
    │   ├── __init__.py
    │   │
    │   ├── models/
    │   │   ├── canonical.py
    │   │   ├── encounter.py
    │   │   ├── patient.py
    │   │   ├── practitioner.py
    │   │   ├── complaint.py
    │   │   ├── history.py
    │   │   ├── examination.py
    │   │   ├── diagnosis.py
    │   │   ├── procedure.py
    │   │   ├── medication.py
    │   │   ├── recommendation.py
    │   │   └── follow_up.py
    │   │
    │   ├── schema.py
    │   ├── validator.py
    │   ├── extractor.py
    │   ├── prompt.py
    │   └── renderer.py
    │
    ├── laboratory/
    │   ├── __init__.py
    │   ├── models/
    │   ├── schema.py
    │   ├── validator.py
    │   ├── extractor.py
    │   ├── prompt.py
    │   └── renderer.py
    │
    ├── imaging/
    │   ├── __init__.py
    │   ├── models/
    │   ├── schema.py
    │   ├── validator.py
    │   ├── extractor.py
    │   ├── prompt.py
    │   └── renderer.py
    │
    ├── registry/
    │   ├── __init__.py
    │   ├── registry.py
    │   └── resolver.py
    │
    ├── extraction/
    │   ├── __init__.py
    │   ├── base.py
    │   ├── result.py
    │   └── errors.py
    │
    ├── rendering/
    │   ├── __init__.py
    │   ├── base.py
    │   ├── markdown.py
    │   └── yaml.py
    │
    └── migrations/
        ├── __init__.py
        └── v1_to_v2.py
```

---

# 30. Но я бы ещё сильнее разделил Core и Schema

Самая важная часть структуры:

```text
canonical/
│
├── core/
│
├── schemas/
│   ├── generic/
│   ├── appointment/
│   ├── laboratory/
│   └── imaging/
│
├── extraction/
├── rendering/
└── registry/
```

То есть:

```text
core
```

содержит reusable primitives.

А:

```text
schemas
```

содержит domain-specific models.

Например:

```text
core.observation
```

используется:

```text
appointment.observations
laboratory.observations
imaging.observations
generic.observations
```

---

# 31. Я бы выбрал именно такую финальную структуру

```text
canonical/
│
├── core/
│   ├── models/
│   │   ├── document.py
│   │   ├── person.py
│   │   ├── organization.py
│   │   ├── observation.py
│   │   ├── value.py
│   │   ├── quantity.py
│   │   ├── identifier.py
│   │   ├── provenance.py
│   │   └── relationship.py
│   │
│   └── validation/
│       ├── base.py
│       └── semantic.py
│
├── schemas/
│   │
│   ├── generic/
│   │   ├── canonical.py
│   │   ├── schema.py
│   │   ├── extractor.py
│   │   ├── prompt.py
│   │   ├── validator.py
│   │   └── renderer.py
│   │
│   ├── appointment/
│   │   ├── canonical.py
│   │   ├── encounter.py
│   │   ├── complaint.py
│   │   ├── history.py
│   │   ├── examination.py
│   │   ├── diagnosis.py
│   │   ├── procedure.py
│   │   ├── medication.py
│   │   ├── recommendation.py
│   │   ├── follow_up.py
│   │   ├── schema.py
│   │   ├── extractor.py
│   │   ├── prompt.py
│   │   ├── validator.py
│   │   └── renderer.py
│   │
│   └── laboratory/
│       └── ...
│
├── extraction/
│   ├── base.py
│   ├── result.py
│   └── errors.py
│
├── rendering/
│   ├── base.py
│   ├── markdown.py
│   └── yaml.py
│
├── registry/
│   ├── registry.py
│   └── resolver.py
│
└── migrations/
    └── ...
```

---

# 32. Registry

Это особенно важно в вашей системе.

Например:

```python
schema_registry.get("appointment")
```

возвращает:

```text
AppointmentSchema
AppointmentExtractor
AppointmentValidator
AppointmentRenderer
```

А:

```python
schema_registry.get("unknown")
```

возвращает:

```text
GenericSchema
GenericExtractor
GenericValidator
GenericRenderer
```

Тогда pipeline не знает о конкретных canonical schemas.

---

# 33. Resolver

Например:

```python
resolution = schema_resolver.resolve(
    classification_result
)
```

Результат:

```python
SchemaResolution(
    schema="appointment",
    version="2.0",
    confidence=0.96,
)
```

или:

```python
SchemaResolution(
    schema="generic",
    version="2.0",
    reason="unsupported_document_type",
)
```

---

# 34. Extractor interface

Я бы сразу ввёл общий interface:

```python
class CanonicalExtractor(Protocol):

    async def extract(
        self,
        document: NormalizedDocument,
        context: ExtractionContext,
    ) -> CanonicalDocument:
        ...
```

Тогда:

```text
GenericExtractor
AppointmentExtractor
LaboratoryExtractor
```

имеют одинаковый контракт.

---

# 35. Validator interface

Аналогично:

```python
class CanonicalValidator(Protocol):

    def validate(
        self,
        canonical: CanonicalDocument,
    ) -> ValidationResult:
        ...
```

---

# 36. Renderer interface

И:

```python
class CanonicalRenderer(Protocol):

    def render_markdown(
        self,
        canonical: CanonicalDocument,
    ) -> str:
        ...
```

Это даст возможность:

```text
AppointmentCanonical
       │
       ├── Markdown
       ├── JSON
       ├── API response
       └── Vector representation
```

без изменения domain model.

---

# 37. План разработки AppointmentCanonical

Я бы разбил его на 8 фаз.

### Phase 1 — Specification

Создать:

```text
docs/canonical/APPOINTMENT_CANONICAL_SPEC.md
```

Определить:

* terminology;
* fields;
* required/optional;
* enums;
* value model;
* provenance;
* validation;
* versioning.

---

### Phase 2 — Core primitives

Если GenericCanonical уже реализован, переиспользовать:

```text
Observation
Quantity
Person
Organization
Identifier
Provenance
Relationship
```

**Не копировать их в AppointmentCanonical.**

---

### Phase 3 — Appointment models

Создать:

```text
schemas/appointment/
```

и:

```text
AppointmentCanonical
Encounter
Complaint
History
Examination
Diagnosis
Procedure
Medication
Recommendation
FollowUp
```

---

### Phase 4 — JSON Schema

Создать:

```text
schemas/canonical/appointment-v2.json
```

и сделать его источником contract validation.

---

### Phase 5 — LLM extractor

Pipeline:

```text
Marker
 ↓
NormalizedDocument
 ↓
AppointmentPrompt
 ↓
LLM Structured Output
 ↓
Pydantic
 ↓
Semantic Validator
 ↓
AppointmentCanonical
```

---

### Phase 6 — Provenance

Добавить:

```text
source artifact
text offsets
model
prompt version
classification
```

для extracted entities.

---

### Phase 7 — Markdown renderer

Например:

```markdown
---
schema: appointment
schema_version: "2.0"
document_id: doc_123
---

# Приём специалиста

## Пациент

Иванов Иван Иванович

## Специалист

Петров Петр Петрович  
Кардиолог

## Жалобы

...

## Анамнез

...

## Осмотр

### Жизненные показатели

| Показатель | Значение |
|---|---:|
| АД | 135/85 mmHg |

## Диагноз

...

## Назначения

...

## Рекомендации

...
```

---

### Phase 8 — Regression dataset

Собрать реальные типы документов:

```text
appointment/
├── cardiologist/
├── therapist/
├── neurologist/
├── endocrinologist/
├── surgeon/
├── telemedicine/
├── follow_up/
├── consultation/
└── mixed/
```

Для каждого:

```text
input marker.md
expected canonical.json
expected markdown
```

---

# 38. Критерии готовности

`AppointmentCanonical 2.0` можно считать готовым для production pipeline, когда:

* [ ] существует versioned specification;
* [ ] существует JSON Schema;
* [ ] есть Pydantic models;
* [ ] переиспользуются Core models;
* [ ] есть structured LLM extraction;
* [ ] есть schema validation;
* [ ] есть semantic validation;
* [ ] есть provenance;
* [ ] есть confidence;
* [ ] есть Markdown renderer;
* [ ] есть prompt versioning;
* [ ] есть regression fixtures;
* [ ] есть fallback в GenericCanonical;
* [ ] extraction не выполняет медицинскую интерпретацию;
* [ ] diagnosis извлекается только если присутствует в source;
* [ ] observation не превращается автоматически в diagnosis;
* [ ] Canonical artifact отделён от application Appointment entity.

---

## 39. Самое важное решение для дальнейшего развития

Я бы сейчас **не строил каждую Canonical schema как полностью независимую модель**.

В вашем случае лучше получить трёхуровневую систему:

```text
                 Canonical
                    │
          ┌─────────┴─────────┐
          │                   │
       Core Model        Domain Schema
          │                   │
    ┌─────┼─────┐       ┌─────┼──────┐
    │     │     │       │     │      │
 Person  Obs  Provenance Generic Appointment Laboratory
```

То есть:

**Core** — универсальные строительные блоки.

**GenericCanonical** — loss-minimizing representation.

**AppointmentCanonical** — domain-specific representation документа о приёме.

А поверх них уже можно постепенно строить:

```text
Canonical
    ↓
Patient Medical Timeline
    ↓
Medical History
    ↓
Analytics
    ↓
Clinical Decision Support
```

Это особенно хорошо соответствует вашему будущему сценарию: один пользователь получает документы из разных организаций, и `AppointmentCanonical`, `LaboratoryCanonical`, `ImagingCanonical` и `GenericCanonical` становятся **единым структурированным слоем электронной медицинской истории**, не привязанным к конкретному поставщику документов.
