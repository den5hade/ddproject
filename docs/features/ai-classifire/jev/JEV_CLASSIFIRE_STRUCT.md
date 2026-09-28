С учётом реальной структуры вашего `ai-worker`, я бы **не создавал новую параллельную архитектуру `classification/providers/...` так, как предлагал выше**. У вас уже есть достаточно хорошо сформированный `classification` domain, и добавление Jev лучше сделать минимально инвазивно.

Ваш текущий код уже показывает правильные точки расширения:

```text
classification/
├── classifier.py
├── resolver.py
├── service.py
├── models.py
├── schemas.py
├── scoring.py
├── evaluate.py
└── signals/
```

Поэтому я бы строил Jev **внутри существующего Classification domain**, а не создавал второй abstraction layer без необходимости.

## Предлагаемая структура

Я бы пришёл примерно к такой структуре:

```text
apps/ai-worker/app/
│
├── classification/
│   ├── __init__.py
│   │
│   ├── service.py
│   ├── classifier.py
│   ├── resolver.py
│   ├── models.py
│   ├── schemas.py
│   ├── exceptions.py
│   │
│   ├── normalize.py
│   ├── scoring.py
│   ├── signals/
│   │
│   ├── providers/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── rule_based.py
│   │   └── jev.py
│   │
│   ├── evaluation/
│   │   ├── ...
│   │
│   └── artifact.py
│
├── llm/
│   ├── client.py
│   ├── provider.py
│   ├── structured_output.py
│   └── ...
│
└── ...
```

Но здесь есть важный вопрос: **нужно ли вообще создавать `providers/`?**

Я бы сказал — **да, если вы действительно планируете несколько классификаторов**.

У вас уже есть минимум:

```text
Rule-based classifier
        +
Jev classifier
```

а потенциально появятся:

```text
Jev
LLM classifier
legacy classifier
organization-specific classifier
hybrid classifier
```

Поэтому abstraction сейчас оправдан.

---

# 1. `classifier.py` должен стать контрактом

Сейчас у вас, судя по структуре, `classifier.py` является основной реализацией.

Я бы постепенно разделил:

```text
classifier.py
```

как facade/compatibility layer и перенёс конкретную реализацию в:

```text
providers/rule_based.py
```

Получится:

```text
classification/
│
├── classifier.py          # public classification interface
│
└── providers/
    ├── base.py
    ├── rule_based.py
    └── jev.py
```

Например:

```python
class Classifier(Protocol):
    async def classify(
        self,
        document: NormalizedDocument,
    ) -> ClassificationResult:
        ...
```

---

# 2. `RuleBasedClassifier`

Ваш существующий код:

```text
normalize
signals
scoring
resolver
```

я бы практически не трогал.

Получится:

```text
RuleBasedClassifier
        │
        ├── normalize
        ├── signals
        ├── scoring
        └── resolver
```

То есть существующая логика становится одним provider.

Это важно для безопасности изменений.

Не надо в рамках Jev переписывать текущий classifier.

---

# 3. `JevClassifier`

Новый файл:

```text
classification/providers/jev.py
```

его задача очень простая:

```text
NormalizedDocument
       ↓
Jev
       ↓
Jev result
       ↓
ClassificationResult
```

Он **не должен знать про RabbitMQ, S3, pipeline, canonical или PII**.

---

# 4. Jev client лучше оставить за пределами Classification

У вас уже есть:

```text
app/llm/
```

Это хороший фундамент.

Я бы не делал:

```text
classification/providers/jev.py
    ↓
HTTP
    ↓
Jev
```

Лучше:

```text
classification/providers/jev.py
          ↓
      app/llm/
          ↓
       provider
          ↓
         Jev
```

Если Jev является внешним LLM/API provider.

То есть примерно:

```text
app/
├── llm/
│   ├── client.py
│   ├── provider.py
│   ├── structured_output.py
│   └── ...
│
└── classification/
    └── providers/
        └── jev.py
```

`llm` отвечает:

> как вызвать модель.

`classification` отвечает:

> что попросить модель определить и как интерпретировать результат.

Это хорошее разделение ответственности.

---

# 5. Не делал бы отдельный Jev schema внутри pipeline

Лучше иметь общий:

```text
ClassificationResult
```

Например концептуально:

```python
class ClassificationResult(BaseModel):
    type: DocumentType
    subtype: DocumentSubtype | None

    confidence: float

    provider: str
    classifier_version: str

    probabilities: dict[str, float] | None
```

Тогда:

```text
RuleBasedClassifier
        ↓
ClassificationResult

JevClassifier
        ↓
ClassificationResult
```

И downstream ничего не знает о Jev.

---

# 6. Но Jev-specific данные не надо терять

Я бы предусмотрел:

```python
metadata: dict[str, Any]
```

или более строгий `provider_metadata`.

Например:

```json
{
  "provider": "jev",
  "classifier_version": "1.0.0",
  "confidence": 0.94,
  "provider_metadata": {
    "probabilities": {
      "laboratory": 0.94,
      "appointment": 0.03,
      "prescription": 0.02,
      "other": 0.01
    }
  }
}
```

Это позволит потом анализировать Jev, не меняя общий контракт каждый раз, когда появляются provider-specific поля.

---

# 7. Resolver у вас уже существует

И это очень хорошо.

Вместо создания нового `ClassifierResolver` я бы **расширил существующий**:

```text
classification/resolver.py
```

Например:

```text
ClassifierResolver
      │
      ├── rule_based
      │
      └── jev
```

Конфигурация:

```env
CLASSIFICATION_PROVIDER=rule_based
```

или:

```env
CLASSIFICATION_PROVIDER=jev
```

---

# 8. Ещё лучше — primary + shadow

Для вашей задачи я бы сразу заложил два режима.

### Normal

```env
CLASSIFICATION_PROVIDER=rule_based
```

Получаем:

```text
marker.md
   ↓
RuleBased
   ↓
ClassificationResult
   ↓
PII Gate
```

### Shadow

```env
CLASSIFICATION_PROVIDER=rule_based
CLASSIFICATION_SHADOW_PROVIDER=jev
```

Получаем:

```text
                    marker.md
                       │
             ┌─────────┴─────────┐
             ▼                   ▼
        RuleBased               Jev
             │                   │
             ▼                   ▼
          Result A             Result B
             │                   │
             └─────────┬─────────┘
                       ▼
                  comparison
```

Но:

**Jev не должен влиять на pipeline.**

То есть:

```text
RuleBased → authoritative
Jev       → experimental
```

---

# 9. Artifact тоже нужно разделить

Ваш:

```text
classification/artifact.py
```

уже существует.

Я бы его не ломал.

Основной:

```text
classification/result.json
```

содержит:

```json
{
  "classifier_version": "2.1.0",
  "provider": "rule_based",
  "type": "laboratory",
  "confidence": 0.91
}
```

А экспериментальный результат Jev:

```text
classification/
    result.json

classification/
    experiments/
        jev/
            result.json
```

или, что мне нравится больше:

```text
classification/
├── result.json
└── candidates/
    └── jev.json
```

Таким образом downstream никогда случайно не начнёт использовать experimental result.

---

# 10. Evaluation у вас уже есть — это огромный плюс

Ваш текущий:

```text
classification/evaluate.py
```

не нужно переписывать.

Его нужно сделать provider-aware.

Например:

```bash
python -m app.classification.evaluate \
    --provider rule_based
```

и:

```bash
python -m app.classification.evaluate \
    --provider jev
```

Оба запускают:

```text
same fixtures
same manifest
same ground truth
same metrics
```

И это именно то, что вам нужно.

---

# 11. А потом comparison

Я бы добавил:

```text
classification/compare.py
```

или:

```text
classification/evaluation/compare.py
```

и:

```bash
python -m app.classification.compare \
    --baseline rule_based \
    --candidate jev
```

Получаете:

```text
Classification comparison

Dataset: 11 fixtures

                    RuleBased 2.1.0    Jev 1.x
------------------------------------------------
Accuracy                  ...             ...
Laboratory F1             ...             ...
Appointment F1            ...             ...
Prescription F1           ...             ...
Other recall              ...             ...
False laboratory          ...             ...
Ambiguous                 ...             ...
```

---

# 12. Я бы не создавал сейчас отдельный `jev/` domain

То есть **не надо**:

```text
app/jev/
```

если Jev используется только для Classification.

Иначе получится:

```text
app/
├── jev/
├── classification/
├── canonical/
├── pii/
```

и постепенно `jev` начнёт восприниматься как самостоятельный domain.

На самом деле в вашем проекте:

```text
Jev = implementation detail of classification
```

Поэтому:

```text
classification/providers/jev.py
```

логичнее.

---

# 13. Как это вписывается в вашу существующую архитектуру

Сейчас:

```text
pipeline
   │
   ▼
classification.service
   │
   ▼
classifier
   │
   ▼
scoring/signals
```

После изменения:

```text
pipeline
   │
   ▼
classification.service
   │
   ▼
classifier resolver
   │
   ├───────────────┐
   ▼               ▼
RuleBased          Jev
   │               │
   ▼               ▼
ClassificationResult
        │
        ▼
     artifact
        │
        ▼
      PII Gate
        │
        ▼
     Canonical
```

Это **минимальное изменение вашей существующей архитектуры**, а не её перестройка.

---

# 14. Что я бы сделал конкретно

С учётом вашей текущей структуры я бы разбил реализацию Jev на следующие шаги.

### J0 — Provider contract

Добавить:

```text
classification/providers/base.py
```

и унифицировать:

```text
ClassificationResult
```

для текущего classifier.

---

### J1 — Extract RuleBased provider

Создать:

```text
classification/providers/rule_based.py
```

Перенести туда текущую реализацию практически без изменений.

Проверить:

```text
existing tests
```

и убедиться, что:

```text
RuleBased 2.1.0
```

даёт те же результаты.

Это **самый важный regression checkpoint**.

---

### J2 — Jev provider

Добавить:

```text
classification/providers/jev.py
```

Используя существующий:

```text
app/llm/
```

---

### J3 — Resolver

Изменить:

```text
classification/resolver.py
```

чтобы:

```text
rule_based
jev
```

были взаимозаменяемыми providers.

---

### J4 — CLI evaluation

Ваш существующий:

```text
classification/evaluate.py
```

должен поддерживать:

```bash
--provider rule_based
--provider jev
```

---

### J5 — Jev evaluation

Запустить:

```text
11 fixtures
        ↓
Jev
        ↓
existing ground truth
        ↓
existing metrics
```

---

### J6 — Shadow mode

Только после того, как standalone evaluation работает:

```text
RuleBased
    +
Jev shadow
```

на одном pipeline execution.

---

### J7 — Comparison report

Получить:

```text
RuleBased 2.1.0
vs
Jev
```

по:

* accuracy;
* precision;
* recall;
* F1;
* false laboratory;
* generic;
* ambiguous;
* confidence;
* latency;
* token usage / cost, если применимо.

---

## И ещё один момент по вашей структуре

Я вижу в дереве:

```text
app/
├── __pycache__
├── classification/__pycache__
├── ...
tests/**/__pycache__
```

и `reports/`.

`__pycache__` не должен находиться в git. Я бы обязательно проверил `.gitignore`/`.dockerignore` и удалил их из репозитория, если они tracked.

Это не связано с Jev, но сейчас хороший момент привести repository hygiene в порядок.

---

### Моя итоговая рекомендация

Вашу существующую структуру **не нужно перестраивать**.

Добавьте только:

```text
classification/
└── providers/
    ├── __init__.py
    ├── base.py
    ├── rule_based.py
    └── jev.py
```

и используйте уже существующие:

```text
classification/resolver.py
classification/service.py
classification/models.py
classification/schemas.py
classification/evaluate.py
classification/artifact.py
llm/*
```

Это даст вам очень чистую модель:

```text
             Classification Contract
                      │
                ClassifierResolver
                      │
          ┌───────────┴───────────┐
          │                       │
          ▼                       ▼
   RuleBased 2.1.0              Jev
          │                       │
          └───────────┬───────────┘
                      ▼
            ClassificationResult
                      │
              ┌───────┴────────┐
              ▼                ▼
         Production          Shadow
            flow             evaluation
```

И главное — **не привязывайте Jev к `canonical`, `pii`, `pipeline` или `artifact storage` напрямую**. Jev должен знать только о входном документе и классификационном контракте. Это позволит вам безболезненно заменить его позже или добавить третий классификатор.
