Да. В вашей текущей цепочке я бы рассматривал **GenericCanonical 2.0** не как «упрощённую версию LaboratoryCanonical», а как **универсальный промежуточный canonical format**, который позволяет сохранить полезную структуру документа даже тогда, когда Classification не смог уверенно определить специализированный тип.

Ключевой принцип:

> **GenericCanonical не должен пытаться придумать медицинскую семантику. Его задача — сохранить наблюдаемую структуру документа, сущности, значения, даты, участников и provenance в стандартизированном формате, не теряя информацию из исходного документа.**

Это особенно важно для вашей системы, потому что документы будут приходить от разных медицинских организаций и заранее неизвестных форматов.

---

# 1. Роль GenericCanonical 2.0

Предлагаю такую модель pipeline:

```text
Original PDF / JPEG
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
        ├───────────────┐
        ▼               ▼
   PII Gate       Classification 2.0
                        │
                        ▼
                 Schema Resolution
                        │
              ┌─────────┴─────────┐
              │                   │
       specialized schema    GenericCanonical
              │                   │
              └─────────┬─────────┘
                        ▼
                 LLM Extraction
                        │
                        ▼
                  canonical.json
```

Но есть важное отличие:

```text
Classification = laboratory
        ↓
LaboratoryCanonical

Classification = appointment
        ↓
AppointmentCanonical

Classification = unknown / ambiguous / unsupported
        ↓
GenericCanonical
```

То есть `GenericCanonical` является **fallback schema**, но одновременно и универсальным форматом для документов, для которых специализированная схема ещё не создана.

---

# 2. Основные требования

GenericCanonical 2.0 должен:

1. сохранять смысловую структуру документа;
2. не требовать заранее известного document type;
3. поддерживать медицинские и немедицинские документы;
4. сохранять неизвестные поля;
5. сохранять provenance;
6. различать extracted value и source text;
7. поддерживать confidence;
8. поддерживать даты;
9. поддерживать людей и организации;
10. поддерживать observations/measurements;
11. поддерживать sections;
12. поддерживать таблицы;
13. позволять позже преобразовать GenericCanonical → SpecializedCanonical;
14. быть пригодным для генерации Markdown;
15. быть пригодным для индексации/vector search;
16. быть пригодным для дальнейшего AI analysis;
17. быть versioned.

---

# 3. Чего GenericCanonical НЕ должен делать

Очень важно определить границы.

GenericCanonical не должен:

* диагностировать пациента;
* интерпретировать лабораторные показатели;
* самостоятельно определять норму/патологию;
* придумывать отсутствующие данные;
* преобразовывать неизвестное значение в известную медицинскую сущность;
* удалять исходный текст;
* заменять specialized canonical schemas.

Например исходный документ содержит:

```text
Гемоглобин 134 г/л
```

GenericCanonical может сохранить:

```json
{
  "label": "Гемоглобин",
  "value": 134,
  "unit": "г/л"
}
```

Но не должен автоматически добавлять:

```json
"interpretation": "normal"
```

если это не было явно указано в исходном документе или не является задачей отдельного medical-analysis pipeline.

---

# 4. Главная идея модели

Я предлагаю сделать GenericCanonical вокруг семи основных блоков:

```text
GenericCanonical
│
├── metadata
├── document
├── subjects
├── encounters
├── sections
├── entities
├── observations
├── relationships
└── provenance
```

При этом `entities`, `observations` и `relationships` позволяют представить документы, которые невозможно заранее описать специализированной schema.

---

# 5. Top-level schema

Пример:

```json
{
  "canonical_version": "2.0",

  "document": {},

  "metadata": {},

  "subjects": [],

  "encounters": [],

  "sections": [],

  "entities": [],

  "observations": [],

  "relationships": [],

  "provenance": {}
}
```

Я бы не делал огромный плоский объект.

Такой подход:

```json
{
  "patient_name": "...",
  "doctor": "...",
  "diagnosis": "...",
  "date": "...",
  "lab_value": "..."
}
```

быстро становится неуправляемым.

---

# 6. Metadata

Metadata описывает **сам canonical artifact**, а не медицинское содержимое.

```json
{
  "metadata": {
    "canonical_version": "2.0",
    "schema": "generic",
    "schema_version": "2.0",
    "document_type": "unknown",
    "document_subtype": null,
    "classification_confidence": 0.61,
    "classification_decision": "fallback",

    "extraction_model": "model-name",
    "extraction_prompt_version": "generic-v2",

    "created_at": "2026-09-21T12:00:00Z"
  }
}
```

---

# 7. Не смешивать Classification и Canonical

Например:

```json
"classification": {
  "type": "laboratory",
  "confidence": 0.92
}
```

и:

```json
"document": {
  "type": "laboratory"
}
```

могут выглядеть одинаково, но иметь разные значения.

Я бы явно разделил:

```json
{
  "classification": {
    "type": "laboratory",
    "confidence": 0.92,
    "method": "rule_score",
    "classifier_version": "2.0.0"
  },

  "document": {
    "type": "laboratory"
  }
}
```

GenericCanonical может сохранять classification result как provenance/context, но не должен самостоятельно классифицировать документ.

---

# 8. Document

```json
{
  "document": {
    "id": "doc_123",

    "title": "Результаты исследования",

    "document_type": "unknown",

    "document_date": "2026-09-20",

    "language": "ru",

    "source": {
      "type": "medical_organization",
      "organization_id": "org_123"
    }
  }
}
```

---

# 9. Document identifiers

Очень важно поддерживать несколько идентификаторов.

Например:

```json
{
  "identifiers": [
    {
      "system": "organization",
      "value": "LAB-2026-12345"
    },
    {
      "system": "medical_record",
      "value": "MR-000123"
    }
  ]
}
```

Не следует предполагать, что у документа только один ID.

---

# 10. Subject

В GenericCanonical нужно иметь универсальный субъект документа.

Обычно:

```text
patient
```

но в будущем документ может относиться к:

* пациенту;
* родственнику;
* нескольким пациентам;
* организации;
* специалисту.

Поэтому:

```json
{
  "subjects": [
    {
      "id": "subject-1",
      "role": "patient",
      "name": "Иванов Иван Иванович",
      "birth_date": "1980-01-01"
    }
  ]
}
```

---

# 11. Почему `subjects`, а не `patient`

Потому что GenericCanonical должен быть generic.

Для medical document:

```text
subject.role = patient
```

Для другого документа:

```text
subject.role = person
```

Для корпоративного документа:

```text
subject.role = organization
```

---

# 12. Sensitive fields

PII Gate и GenericCanonical должны быть разделены.

Canonical может содержать:

```json
{
  "name": "Иванов Иван Иванович"
}
```

если это разрешено processing policy.

Но GenericCanonical не должен отвечать за:

* masking;
* encryption;
* authorization;
* consent.

Это ответственность security/privacy layer.

---

# 13. Encounter

Многие медицинские документы связаны с посещением:

```json
{
  "encounters": [
    {
      "id": "enc-1",
      "type": "outpatient_visit",
      "date": "2026-09-20",
      "status": "completed",
      "specialty": "cardiology"
    }
  ]
}
```

Но поле optional.

---

# 14. Sections

Это одна из самых важных частей GenericCanonical.

```json
{
  "sections": [
    {
      "id": "section-1",
      "title": "Жалобы",
      "type": "complaints",
      "order": 1,
      "content": []
    }
  ]
}
```

Для неизвестного раздела:

```json
{
  "type": "unknown",
  "title": "Дополнительная информация"
}
```

---

# 15. Section types

Не стоит сразу создавать сотни enum values.

Начальный набор:

```text
summary
complaints
history
examination
diagnosis
treatment
medications
laboratory
imaging
recommendations
conclusion
administrative
unknown
```

Но:

```json
"type": "custom",
"label": "Результаты обследования"
```

должен быть допустим.

---

# 16. Entities

Это основной extension point GenericCanonical.

```json
{
  "entities": [
    {
      "id": "entity-1",
      "type": "person",
      "label": "Врач",
      "value": "Петров Петр Петрович"
    }
  ]
}
```

Другой пример:

```json
{
  "id": "entity-2",
  "type": "organization",
  "label": "Медицинская организация",
  "value": "Клиника X"
}
```

---

# 17. Entity types

Первоначально:

```text
person
organization
location
condition
procedure
medication
device
specimen
body_site
document_reference
identifier
unknown
```

Но `type` должен быть extensible.

---

# 18. Observations

Это позволит GenericCanonical сохранять показатели без необходимости знать конкретную schema.

Например:

```json
{
  "observations": [
    {
      "id": "obs-1",

      "name": "Гемоглобин",

      "value": {
        "type": "quantity",
        "value": 134,
        "unit": "г/л"
      },

      "reference_range": {
        "low": 120,
        "high": 160,
        "unit": "г/л"
      }
    }
  ]
}
```

Это уже начинает быть полезно для последующей аналитики.

---

# 19. Но GenericCanonical не должен интерпретировать observation

Не:

```json
"status": "normal"
```

если это не указано в исходном документе.

Можно:

```json
"source_flag": "normal"
```

если лаборатория явно написала:

```text
Норма
```

То есть необходимо различать:

```text
source-derived information
```

и:

```text
AI-derived interpretation
```

---

# 20. Value model

Это критическая часть.

Не следует хранить всё как string:

```json
"value": "134 г/л"
```

Лучше:

```json
{
  "value": {
    "type": "quantity",
    "value": 134,
    "unit": "г/л"
  }
}
```

Поддержать:

```text
string
number
boolean
date
datetime
quantity
range
code
reference
```

---

# 21. Quantity

```json
{
  "type": "quantity",
  "value": 134,
  "unit": "g/L"
}
```

Желательно иметь:

```json
"original_unit": "г/л"
```

и canonical unit:

```json
"unit": "g/L"
```

Но unit conversion я бы пока не делал частью GenericCanonical.

---

# 22. Original value

Очень рекомендую:

```json
{
  "value": {
    "type": "quantity",
    "value": 134,
    "unit": "g/L",
    "original": "134 г/л"
  }
}
```

Это позволит восстановить информацию, которую модель могла нормализовать.

---

# 23. Confidence

У каждого AI-extracted object желательно иметь:

```json
"confidence": 0.94
```

Но не обязательно у каждого поля.

Можно поддерживать:

```json
"confidence": {
  "score": 0.94,
  "level": "high"
}
```

---

# 24. Provenance

Это фундаментальная часть GenericCanonical 2.0.

Для каждого существенного объекта нужно иметь возможность ответить:

> Откуда модель это взяла?

Например:

```json
{
  "provenance": {
    "source_artifact": "marker.md",
    "source_span": {
      "start": 1520,
      "end": 1562
    }
  }
}
```

---

# 25. Лучше сделать reusable Provenance object

```json
{
  "provenance": [
    {
      "source": "marker.md",
      "location": {
        "type": "text_offset",
        "start": 1520,
        "end": 1562
      },
      "extraction_method": "llm",
      "model": "model-name",
      "prompt_version": "generic-v2"
    }
  ]
}
```

Это позволит позже показывать пользователю:

> Этот показатель был извлечён из этого места документа.

---

# 26. Relationships

Это ещё один важный extension point.

Например:

```text
Doctor
   │
   └── performed
          │
       Examination
```

или:

```text
Observation
   │
   └── belongs_to
          │
       Encounter
```

JSON:

```json
{
  "relationships": [
    {
      "source": "obs-1",
      "relation": "belongs_to",
      "target": "enc-1"
    }
  ]
}
```

---

# 27. Почему relationships нужны

Без relationships GenericCanonical быстро превращается в:

```text
список сущностей
```

Вместо:

```text
граф документа
```

А для будущего medical history analysis графическая модель очень полезна.

---

# 28. Unknown fields

Критически важно предусмотреть:

```json
{
  "extensions": {}
}
```

Например:

```json
{
  "extensions": {
    "organization_specific": {
      "department": "LAB",
      "document_number": "123"
    }
  }
}
```

Это позволит не терять данные от организаций, которые используют свои форматы.

---

# 29. Полный пример

Упрощённый GenericCanonical 2.0:

```json
{
  "canonical_version": "2.0",

  "metadata": {
    "schema": "generic",
    "schema_version": "2.0",
    "created_at": "2026-09-21T12:00:00Z",

    "classification": {
      "type": "unknown",
      "confidence": 0.61,
      "decision": "fallback",
      "classifier_version": "2.0.0"
    },

    "extraction": {
      "model": "model-name",
      "prompt_version": "generic-v2"
    }
  },

  "document": {
    "id": "doc_123",
    "title": "Медицинский документ",
    "document_date": "2026-09-20",
    "language": "ru",

    "identifiers": [
      {
        "system": "organization",
        "value": "DOC-12345"
      }
    ]
  },

  "subjects": [
    {
      "id": "subject-1",
      "role": "patient",
      "name": "Иванов Иван Иванович",
      "birth_date": "1980-01-01"
    }
  ],

  "encounters": [
    {
      "id": "enc-1",
      "type": "outpatient_visit",
      "date": "2026-09-20",
      "specialty": "cardiology"
    }
  ],

  "sections": [
    {
      "id": "section-1",
      "title": "Результаты исследования",
      "type": "laboratory",
      "order": 1
    }
  ],

  "entities": [
    {
      "id": "entity-1",
      "type": "person",
      "label": "doctor",
      "value": "Петров Петр Петрович"
    }
  ],

  "observations": [
    {
      "id": "obs-1",

      "name": "Гемоглобин",

      "value": {
        "type": "quantity",
        "value": 134,
        "unit": "g/L",
        "original": "134 г/л"
      },

      "reference_range": {
        "low": 120,
        "high": 160,
        "unit": "g/L"
      },

      "source_flag": "normal",

      "confidence": 0.97
    }
  ],

  "relationships": [
    {
      "source": "obs-1",
      "relation": "belongs_to",
      "target": "enc-1"
    }
  ],

  "provenance": [
    {
      "source": "marker.md",
      "location": {
        "type": "text_offset",
        "start": 1500,
        "end": 1540
      },

      "extraction_method": "llm",

      "model": "model-name",
      "prompt_version": "generic-v2"
    }
  ],

  "extensions": {}
}
```

---

# 30. GenericCanonical и специализированные schemas

Очень важно не делать GenericCanonical тупиком.

Должна существовать трансформация:

```text
GenericCanonical
        │
        ▼
Specialized Canonical
```

Например:

```text
GenericCanonical
       │
       ▼
LaboratoryCanonical
```

если Classification 3.0 или manual review определили документ как laboratory.

Это позволит постепенно улучшать систему.

---

# 31. Generic → Specialized

Например Generic содержит:

```json
{
  "observations": [
    {
      "name": "HGB",
      "value": {
        "type": "quantity",
        "value": 134,
        "unit": "g/L"
      }
    }
  ]
}
```

После определения:

```text
laboratory / hematology
```

можно преобразовать:

```json
{
  "hemoglobin": {
    "value": 134,
    "unit": "g/L"
  }
}
```

Не нужно заново отправлять исходный PDF в LLM.

---

# 32. GenericCanonical и Markdown

Ваш текущий pipeline предполагает:

```text
canonical.json
        ↓
structured markdown
```

GenericCanonical прекрасно подходит для этого.

Например:

```markdown
---
canonical_version: "2.0"
schema: "generic"
document_type: "unknown"
---

# Медицинский документ

## Пациент

**ФИО:** Иванов Иван Иванович

## Результаты

| Показатель | Результат | Ед. |
|---|---:|---|
| Гемоглобин | 134 | г/л |
```

---

# 33. YAML header

Я бы не помещал **весь GenericCanonical JSON** в YAML header.

Лучше:

```yaml
---
canonical_version: "2.0"
schema: "generic"
schema_version: "2.0"

document_id: "doc_123"

document_type: "unknown"
classification_confidence: 0.61

model: "model-name"
prompt_version: "generic-v2"

created_at: "2026-09-21T12:00:00Z"
---
```

А полный canonical JSON хранить отдельно.

---

# 34. Canonical metadata

В YAML стоит добавить:

```text
schema
schema_version
canonical_version
document_id
classification
model
prompt_version
processing_id
created_at
```

И я бы добавил:

```text
source_artifact
marker_version
pii_policy_version
classifier_version
```

Это даст полный lineage.

---

# 35. Processing lineage

В итоге можно получить:

```text
document
   │
   ├── original artifact
   │
   ├── marker_version
   │
   ├── pii_gate_version
   │
   ├── classifier_version
   │
   ├── schema_version
   │
   ├── model
   │
   ├── prompt_version
   │
   └── canonical_version
```

Это очень важно для medical data platform.

---

# 36. Архитектура реализации

Я бы создал отдельный package:

```text
ai-worker/
│
├── canonical/
│   ├── generic/
│   │   ├── domain/
│   │   │   ├── models.py
│   │   │   ├── values.py
│   │   │   ├── sections.py
│   │   │   └── relationships.py
│   │   │
│   │   ├── schema.py
│   │   ├── validator.py
│   │   ├── builder.py
│   │   └── serializer.py
│   │
│   ├── laboratory/
│   ├── appointment/
│   └── registry.py
│
├── extraction/
│   ├── generic/
│   │   ├── extractor.py
│   │   ├── prompt.py
│   │   └── validator.py
│   │
│   └── ...
```

---

# 37. GenericExtractor

Очень важно отделить:

```text
GenericCanonical schema
```

от:

```text
LLM prompt
```

То есть:

```python
GenericExtractor
       │
       ├── prompt
       ├── LLM
       └── validation
               ↓
       GenericCanonical
```

LLM не должен напрямую определять финальный JSON без validation.

---

# 38. Structured Output

Если используем LLM, запрос должен использовать structured output / JSON schema, если это поддерживает выбранный provider.

Pipeline:

```text
marker.md
   ↓
LLM
   ↓
raw structured response
   ↓
Pydantic validation
   ↓
semantic validation
   ↓
GenericCanonical
```

---

# 39. Двухэтапная validation

### Schema validation

Проверяет:

```text
types
required fields
enums
formats
```

### Semantic validation

Проверяет:

```text
date cannot be impossible
quantity.value must be numeric
relationship targets must exist
observation IDs unique
```

Например:

```json
{
  "source": "obs-123",
  "target": "unknown-id"
}
```

должно быть rejected.

---

# 40. Не доверять LLM

GenericCanonical особенно нуждается в validation, потому что fallback schema будет использоваться на самых непредсказуемых документах.

Нельзя:

```text
LLM → save JSON
```

Нужно:

```text
LLM
 ↓
Pydantic
 ↓
Semantic validation
 ↓
Canonical
```

---

# 41. Extraction prompt

Prompt должен явно говорить:

```text
You are extracting structured information from a medical document.

Do not infer information that is not explicitly present.

Preserve source values.

Do not provide medical interpretation.

If a field is unknown, use null.

If document structure is unknown, preserve it as a generic section.

Every extracted entity should be traceable to source text when possible.
```

Это должно стать частью versioned prompt:

```text
generic-v2
```

---

# 42. Unknown information

Главное правило:

```text
unknown ≠ null ≠ empty
```

Например:

```json
"document_date": null
```

означает:

> поле предусмотрено, но значение не обнаружено.

А:

```json
"extensions": {}
```

означает:

> дополнительных полей нет.

---

# 43. Не превращать GenericCanonical в “god schema”

Есть опасность добавить:

```text
100+ fields
```

и получить новый монолит.

Я бы придерживался правила:

> GenericCanonical должен иметь небольшой стабильный core + extensible entities/observations/sections/extensions.

То есть core:

```text
document
subject
section
entity
observation
relationship
provenance
```

а не:

```text
patient_name
doctor_name
diagnosis
lab_result
prescription
imaging_result
...
```

---

# 44. Versioning

Нужны минимум три версии:

```text
canonical_version
schema_version
prompt_version
```

Например:

```yaml
canonical_version: "2.0"
schema: "generic"
schema_version: "2.0"
model: "..."
prompt_version: "generic-v2.3"
```

Также:

```text
classifier_version
pii_detector_version
```

---

# 45. Migration

Нужно сразу определить:

```text
GenericCanonical 1.x
        ↓
migration
        ↓
GenericCanonical 2.0
```

Но **не переписывать старые canonical artifacts автоматически**.

Лучше:

```text
artifact.version = 1.x
```

и migration выполняется при необходимости.

---

# 46. Testing strategy

## Unit

```text
test_value_types
test_quantity
test_sections
test_entities
test_observations
test_relationships
test_provenance
```

## Schema

```text
test_valid_generic_canonical
test_missing_required_field
test_invalid_value_type
test_invalid_relationship
```

## LLM extraction

Использовать фиксированные Marker fixtures.

```text
tests/fixtures/generic/
```

Например:

```text
unknown_medical_report.md
mixed_document.md
foreign_document.md
poor_quality_document.md
```

---

# 47. Golden tests

Для LLM extraction очень полезны golden fixtures:

```text
input:
marker.md

expected:
generic_canonical.json
```

Не обязательно требовать byte-for-byte equality.

Сравнивать semantic structure:

```text
document.type
subject
sections
observations
entities
```

---

# 48. Metrics

Для GenericCanonical я бы отслеживал:

```text
schema_validation_rate
extraction_failure_rate
missing_required_fields
hallucination_rate
unsupported_document_rate
generic_fallback_rate
```

Особенно:

```text
GenericCanonical → specialized conversion rate
```

Например:

```text
1000 generic documents
      ↓
700 eventually classified
      ↓
laboratory: 400
appointment: 200
other: 100
```

Это покажет, какие новые specialized schemas имеет смысл создавать.

---

# 49. Human review

Для документов:

```text
Classification = ambiguous
```

можно использовать GenericCanonical как временный результат.

Например:

```text
Document
   ↓
Classification
   ↓
AMBIGUOUS
   ↓
GenericCanonical
   ↓
available to user
```

Позже специалист/admin может изменить:

```text
document_type = laboratory
```

и запустить:

```text
Generic → Laboratory extraction
```

---

# 50. План разработки

Я бы разбил реализацию на следующие фазы.

## Phase 1 — Domain specification

Определить:

* GenericCanonical 2.0 JSON Schema;
* versioning;
* required/optional fields;
* value model;
* provenance;
* extension model.

Результат:

```text
docs/canonical/GENERIC_CANONICAL_SPEC.md
schemas/canonical/generic-v2.json
```

---

## Phase 2 — Pydantic models

Создать:

```text
canonical/generic/domain/
```

Модели:

```text
GenericCanonical
CanonicalMetadata
Document
Identifier
Subject
Encounter
Section
Entity
Observation
Value
Quantity
Relationship
Provenance
```

---

## Phase 3 — Validator

Реализовать:

```text
GenericCanonicalValidator
```

с:

* schema validation;
* semantic validation;
* relationship validation;
* provenance validation.

---

## Phase 4 — GenericExtractor

Создать:

```text
extraction/generic/
├── extractor.py
├── prompt.py
└── parser.py
```

Pipeline:

```text
Marker
 ↓
Prompt
 ↓
LLM
 ↓
JSON
 ↓
Pydantic
 ↓
GenericCanonical
```

---

## Phase 5 — Schema Registry

Добавить:

```text
generic
laboratory
appointment
...
```

Например:

```python
schema_registry.resolve(
    document_type,
    document_subtype
)
```

Fallback:

```text
unknown
→ generic.v2
```

---

## Phase 6 — Integration with Classification 2.0

```text
ClassificationResult
        ↓
SchemaResolver
        ↓
GenericExtractor
```

для:

```text
unknown
ambiguous
unsupported
```

---

## Phase 7 — Provenance

Добавить source references:

```text
marker artifact
text offsets
section
model
prompt
processing ID
```

---

## Phase 8 — Canonical Markdown generator

```text
GenericCanonical
       ↓
MarkdownRenderer
       ↓
structured.md
```

с YAML header.

---

## Phase 9 — Persistence

Сохранять:

```text
canonical/generic.json
structured/document.md
```

и metadata processing job.

---

## Phase 10 — Regression dataset

Создать:

```text
tests/fixtures/generic/
```

с реальными Marker outputs:

* неизвестный документ;
* плохо структурированный документ;
* смешанный документ;
* документ с таблицами;
* документ с несколькими sections;
* документ без patient information;
* документ с большим количеством PII.

---

## Phase 11 — Evaluation

Добавить CLI:

```bash
python -m app.canonical.evaluate generic
```

Метрики:

```text
valid JSON
schema validation
field extraction
source grounding
hallucination
information loss
```

---

# 51. Критерии готовности GenericCanonical 2.0

Я бы считал Phase завершённой, когда:

* [ ] есть опубликованный JSON Schema;
* [ ] есть Pydantic models;
* [ ] есть semantic validator;
* [ ] GenericExtractor работает через structured output;
* [ ] неизвестные поля не теряются;
* [ ] есть provenance;
* [ ] есть confidence;
* [ ] есть source references;
* [ ] есть versioning;
* [ ] есть Generic → Markdown renderer;
* [ ] Generic интегрирован с Classification 2.0;
* [ ] Generic является fallback schema;
* [ ] есть regression dataset;
* [ ] LLM hallucination проверяется тестами;
* [ ] canonical artifacts сохраняются отдельно от Marker artifacts.

---

# 52. Я бы немного изменил вашу общую модель

Сейчас у вас концептуально получается:

```text
Marker
 ↓
Classification
 ↓
Canonical
 ↓
Markdown
```

Я бы зафиксировал более строгую модель:

```text
                    ORIGINAL
                       │
                       ▼
                    MARKER
                       │
                       ▼
              NormalizedDocument
                       │
             ┌─────────┴─────────┐
             ▼                   ▼
          PII Gate         Classification
             │                   │
             └─────────┬─────────┘
                       ▼
                 Schema Resolver
                       │
             ┌─────────┴──────────┐
             ▼                    ▼
      Specialized Schema     GenericCanonical
             │                    │
             └──────────┬─────────┘
                        ▼
                  Canonical JSON
                        │
                        ▼
                 Markdown Renderer
                        │
                        ▼
              Search / Analytics /
              Vector DB / AI
```

И здесь **GenericCanonical 2.0 становится не временной заглушкой, а устойчивым универсальным слоем данных**.

Это особенно хорошо соответствует вашей будущей модели с организациями: неизвестный формат документа от новой медицинской организации не должен ломать pipeline. Система сначала сохраняет документ в GenericCanonical, а затем вы можете постепенно добавлять специализированные schemas для наиболее распространённых типов документов.

Самое важное архитектурное правило я бы сформулировал так:

> **GenericCanonical preserves what the system knows; SpecializedCanonical expresses what the system understands.**

То есть GenericCanonical должен быть максимально **loss-minimizing**, а специализированные canonical schemas — максимально **domain-specific**. Это позволит развивать медицинскую аналитику постепенно, не ломая уже накопленную электронную медицинскую историю.
