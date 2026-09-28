Да — этот `canonical.json` существенно уточняет картину. У вас **reference ranges уже являются частью canonical**, поэтому я бы не стал сейчас создавать отдельный сложный механизм `ReferenceRangeResolver` как обязательную часть следующего этапа.

В вашем текущем формате уже есть главное:

```json
{
  "name": "MCHC Средняя концентрация Hg в эритроците",
  "value": "307,9",
  "unit": "г/л",
  "reference_min": "318",
  "reference_max": "354",
  "flagged": true
}
```

Но я бы разделил две задачи:

1. **извлечение reference range из документа** — это уже делает ваш canonical pipeline;
2. **добавление reference range, когда его нет в документе** — вот для этого нужен отдельный Reference Range Domain.

И здесь есть важный архитектурный момент: **не нужно перезаписывать исходные данные документа**.

---

# 1. Что сейчас уже хорошо

Ваш canonical фактически содержит:

```text
Observation
├── name
├── value
├── unit
├── reference_min
├── reference_max
├── flagged
├── interpretation
└── comment
```

Это достаточно хороший первый слой.

Причём `flagged` уже позволяет UI сделать:

```text
MCHC
307.9 г/л

↓ ниже референсного интервала
318–354 г/л
```

То есть **для документов, где лаборатория сама указала диапазон, вам вообще не нужен внешний справочник**.

Именно так я бы и оставил.

---

# 2. Главная проблема начинается здесь

Допустим документ содержит:

```json
{
  "name": "Глюкоза",
  "value": "5.8",
  "unit": "mmol/L",

  "reference_min": null,
  "reference_max": null,

  "flagged": false
}
```

Вот здесь система не знает:

```text
5.8
↓
normal?
high?
low?
```

И именно **для этого случая** нужен Reference Range Domain.

---

# 3. Я бы не менял существующую модель сразу

На первом этапе оставил бы:

```json
{
  "name": "...",
  "value": "...",
  "unit": "...",
  "reference_min": "...",
  "reference_max": "...",
  "flagged": true,
  "interpretation": null
}
```

Но добавил бы **отдельный metadata-блок**, например:

```json
{
  "reference": {
    "min": "318",
    "max": "354",
    "unit": "g/L",
    "source": "document",
    "source_id": "document-version-id"
  }
}
```

Однако я бы не делал это обязательным breaking change прямо сейчас.

---

# 4. Более правильная эволюция canonical

Я бы постепенно пришёл к:

```json
{
  "name": "MCHC Средняя концентрация Hg в эритроците",

  "value": {
    "value": 307.9,
    "unit": "g/L"
  },

  "reference_range": {
    "low": 318,
    "high": 354,
    "unit": "g/L",

    "source": {
      "type": "document",
      "document_id": "..."
    }
  },

  "interpretation": {
    "status": "low",
    "flagged": true
  },

  "comment": null
}
```

Но это уже **Canonical 2.x**, а не изменение, которое я бы делал прямо сейчас.

---

# 5. Самое важное: source

В вашем случае я бы добавил именно provenance.

Например:

```json
"reference_range": {
  "low": 318,
  "high": 354,
  "unit": "g/L",
  "source": "document"
}
```

Если диапазон пришёл из лабораторного документа:

```text
source = document
```

Если его добавила организация:

```text
source = organization
```

Если из вашего справочника:

```text
source = curated
```

Это позволит системе различать:

```text
318–354
```

и:

```text
318–354
```

по происхождению.

---

# 6. Поэтому я бы изменил предыдущую архитектуру

Вместо:

```text
Canonical
    ↓
Reference Range Resolver
    ↓
Reference Registry
```

я бы сделал:

```text
                    Canonical
                       │
             ┌─────────┴─────────┐
             │                   │
     reference_range       no reference_range
             │                   │
             ▼                   ▼
       use directly       Reference Resolver
                                 │
                    ┌────────────┼────────────┐
                    ▼            ▼            ▼
                 Organization  Curated      NONE
```

То есть **resolver вызывается только при отсутствии применимого диапазона**.

Это существенно проще.

---

# 7. При этом `flagged` надо изменить концептуально

Сейчас:

```json
"flagged": true
```

не говорит, **почему**.

Я бы постепенно перешёл к:

```json
"interpretation": {
  "status": "low",
  "basis": "reference_range",
  "source": "document"
}
```

Например:

```json
{
  "value": "307.9",
  "unit": "g/L",

  "reference_min": "318",
  "reference_max": "354",

  "flagged": true,

  "interpretation": {
    "status": "low",
    "basis": "document_reference_range"
  }
}
```

Это уже намного лучше для будущего AI analysis.

---

# 8. Почему это особенно важно для твоего приложения

У тебя в дальнейшем будет:

```text
Document
   ↓
Canonical
   ↓
Patient history
   ↓
Analytics
```

Если просто хранить:

```text
flagged = true
```

через год будет непонятно:

> Почему этот результат был marked as abnormal?

А если:

```json
"interpretation": {
  "status": "low",
  "basis": "reference_range",
  "reference_source": "document",
  "reference_range_version": "..."
}
```

то результат становится воспроизводимым.

---

# 9. Ещё одна проблема твоего текущего canonical

Обрати внимание:

```json
"value": "307,9",
"reference_min": "318",
"reference_max": "354"
```

Все значения являются **строками**.

Для отображения это нормально.

Для аналитики — плохо.

Тебе потом придётся сравнивать:

```text
"307,9" < "318"
```

что является строковым сравнением, а не числовым.

Я бы разделил:

```json
"value": 307.9,
"display_value": "307,9"
```

и:

```json
"reference_min": 318,
"reference_max": 354
```

То же самое с unit.

---

# 10. Поэтому Canonical Laboratory 2.x я бы строил так

Например:

```json
{
  "name": "MCHC Средняя концентрация Hg в эритроците",

  "value": {
    "numeric": 307.9,
    "display": "307,9",
    "unit": "g/L"
  },

  "reference_range": {
    "low": 318,
    "high": 354,
    "unit": "g/L",

    "source": {
      "type": "document"
    }
  },

  "interpretation": {
    "status": "low",
    "flagged": true,
    "basis": "reference_range"
  }
}
```

Но ещё раз: **я бы не ломал текущий Canonical прямо сейчас**, если у тебя уже есть работающий pipeline.

---

# 11. Для текущего проекта я бы сделал минимальный Reference Domain

С учётом того, что у тебя уже есть:

```text
Classification 2.0
PII Gate
GenericCanonical 2.0
AppointmentCanonical
ai-worker
Canonical Registry
```

я бы добавил:

```text
app/
├── reference_ranges/
│   ├── __init__.py
│   ├── models.py
│   ├── schemas.py
│   ├── resolver.py
│   ├── repository.py
│   ├── service.py
│   └── sources/
│       ├── __init__.py
│       ├── organization.py
│       └── curated.py
```

Но **не добавлял бы пока огромную БД медицинских норм**.

---

# 12. MVP resolver

Алгоритм:

```text
Observation
    │
    ├── reference_min != null
    │       ↓
    │    USE DOCUMENT
    │
    └── reference_min == null
            │
            ▼
      Reference Resolver
            │
            ├── organization range
            │
            ├── curated range
            │
            └── no range
```

То есть:

```python
if observation.reference_min is not None:
    return DocumentReferenceRange(...)
```

И только если:

```python
reference_min is None
reference_max is None
```

мы начинаем искать внешний диапазон.

---

# 13. А потом появляется очень полезный сценарий

Медицинская организация загружает документ:

```text
Глюкоза
5.8 mmol/L
```

без reference range.

Организация уже зарегистрирована в вашей системе и имеет:

```text
Organization Reference Registry
```

для своих исследований.

Тогда:

```text
Document
   ↓
Canonical
   ↓
reference missing
   ↓
Organization Reference Registry
   ↓
5.8 vs organization range
   ↓
interpretation
```

Это намного надёжнее, чем пытаться сразу определить "норму" из глобального интернета.

---

# 14. А global curated registry я бы добавил третьим уровнем

Получится:

```text
Priority 1
────────────────────────
Reference from document

Priority 2
────────────────────────
Organization reference

Priority 3
────────────────────────
Platform curated reference

Priority 4
────────────────────────
No interpretation
```

Причём **приоритет 1 нельзя заменять приоритетом 3**.

Если лаборатория говорит:

```text
MCHC 318–354
```

а твой глобальный справочник говорит:

```text
320–360
```

для этого документа используется:

```text
318–354
```

---

# 15. Для твоего конкретного JSON

Например:

```json
{
  "name": "MCHC Средняя концентрация Hg в эритроците",
  "value": "307,9",
  "unit": "г/л",
  "reference_min": "318",
  "reference_max": "354",
  "flagged": true
}
```

Я бы **не пытался дополнительно интерпретировать это через внешний справочник**.

Canonical pipeline должен считать:

```text
value = 307.9
range = 318–354
↓
status = LOW
```

И сохранить:

```json
"interpretation": {
  "status": "low",
  "basis": "document_reference_range"
}
```

Это уже достаточно.

---

# 16. А вот `PDW 0–100` я бы не пытался автоматически исправлять

В твоём примере:

```json
"PDW Ширина распределения по объему тромбоцитов",
"value": "19,5",
"reference_min": "0",
"reference_max": "100"
```

система видит:

```text
19.5 ∈ 0–100
```

и считает:

```text
not flagged
```

Это соответствует **извлечённому документу**, и на этом уровне pipeline должен сохранить именно документированные данные.

Если в будущем вы захотите определить, что диапазон выглядит подозрительно или требует проверки, это должна быть **отдельная quality/evidence validation**, а не молчаливая замена reference range.

---

# 17. Я бы поэтому разделил три уровня

Это, на мой взгляд, сейчас самое полезное решение для твоего проекта:

```text
                  DOCUMENT FACTS
                        │
                        ▼
                   Canonical
                        │
             ┌──────────┴──────────┐
             │                     │
       extracted range        missing range
             │                     │
             ▼                     ▼
        authoritative       Reference Resolver
        for document               │
                                    ▼
                            external reference
                                    │
                                    ▼
                              interpretation
```

То есть Canonical хранит **что было в документе**, а Reference Domain помогает получить **дополнительную интерпретацию**, когда данных документа недостаточно.

---

## Что бы я рекомендовал сделать сейчас

С учётом текущего состояния твоего `ai-worker`, я бы **не начинал пока с большого справочника**.

Последовательность:

```text
1. Stabilize current LaboratoryCanonical
              ↓
2. Normalize numeric values
              ↓
3. Add explicit interpretation basis
              ↓
4. Preserve document reference range
              ↓
5. Add ReferenceRange domain
              ↓
6. Organization reference ranges
              ↓
7. Curated global ranges
              ↓
8. Reference approval/versioning
              ↓
9. Historical reference snapshots
```

И только после этого имеет смысл наполнять базу референсными значениями.

**Ключевая идея:** твой текущий `reference_min/reference_max` уже является правильным источником истины для конкретного лабораторного документа. Новый справочник должен быть **fallback**, а не заменой этим данным. Это позволит тебе добавить аналитику без риска того, что приложение начнёт "переопределять" результаты лаборатории своими универсальными нормами.
