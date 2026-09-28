Да. Но здесь есть важное уточнение: репозиторий `jaredpalmer/kev` сейчас позиционируется не как готовый production-медицинский классификатор, а как **research prototype/family of Jev-like decision models**. Он принимает один `state`/документ и набор типизированных вопросов (`choice`, `noul`, `score`) и возвращает распределение вероятностей, без генерации текста. В текущей документации есть, в частности, Kev-0.8B, 4B и 9B; авторы прямо рекомендуют измерять качество на собственных данных, а модельные карточки предупреждают, что модели не предназначены для production-решений, влияющих на людей, включая medical routing. Поэтому в вашем проекте я бы вводил Kev сначала как **экспериментальный/shadow classifier**, а не сразу как production replacement вашего Classification 2.1.0. ([GitHub][1])

Ниже — архитектура именно для вашего существующего `ai-worker`.

---

# 1. Цель интеграции

Сейчас у вас:

````text
marker.md
    ↓
Classification 2.1.0
    ↓
classification/result.json
    ↓
PII Gate
    ↓
Canonical
````

Добавление Kev должно дать возможность запускать:

```text
marker.md
    ↓
Classification Resolver
    ├── rule_based
    └── kev
```

при этом **остальная pipeline не должна знать, какой classifier был использован**.

Главный контракт:

```text
Document
    ↓
Classifier
    ↓
ClassificationResult
```

а не:

```text
Document
    ↓
Kev
    ↓
какая-то специальная Kev-модель
    ↓
pipeline
```

Это принципиально важно.

---

# 2. Как использовать Kev для вашей задачи

Архитектура Kev хорошо подходит для вашей задачи концептуально.

Вместо того чтобы просить LLM:

> "Определи тип этого документа"

мы формируем decision question:

```text
STATE:
<текст документа>

QUESTION:
What type of medical document is this?

OPTIONS:
laboratory
appointment
prescription
discharge
diagnosis
imaging
other
```

Kev возвращает распределение:

```json
{
  "laboratory": 0.91,
  "appointment": 0.05,
  "prescription": 0.01,
  "discharge": 0.01,
  "diagnosis": 0.01,
  "imaging": 0.00,
  "other": 0.01
}
```

Это принципиально интереснее для вашего Classification domain, чем обычный `label + confidence`, потому что вы получаете **полное распределение вероятностей**.

Сам Kev именно так и устроен: один документ/state + несколько вопросов, каждый вопрос имеет собственную probability distribution. Вопросы не должны видеть ответы других вопросов. ([GitHub][2])

---

# 3. Я бы не использовал один вопрос

Для вашего Classification 2.0 я бы заложил несколько независимых questions.

Например:

```text
Q1 — document_type
Q2 — medical_domain
Q3 — document_subtype
Q4 — has_structured_laboratory_results
Q5 — is_clinical_encounter
```

Но **не нужно сразу реализовывать все пять**.

Первый production-like experiment:

```text
Q1:
What is the primary document type?

OPTIONS:
laboratory
appointment
prescription
discharge
diagnosis
imaging
other
```

Затем:

```text
Q2:
What is the subtype?

OPTIONS:
...
```

И только после оценки качества добавлять дополнительные questions.

---

# 4. Главный архитектурный принцип

Я бы сделал:

```text
                    ClassificationService
                            │
                            ▼
                    ClassifierResolver
                            │
                ┌───────────┴───────────┐
                │                       │
                ▼                       ▼
         RuleBasedClassifier      KevClassifier
                │                       │
                │                       ▼
                │                  Kev Client
                │                       │
                │                       ▼
                │                  Kev Server
                │
                └───────────┬───────────┘
                            ▼
                  ClassificationResult
```

`KevClassifier` не должен непосредственно загружать модель внутри `ai-worker`.

Я бы **не начинал с embedded Kev**.

---

# 5. Kev как отдельный inference service

У вас уже есть отдельный `ai-worker`.

Я бы не смешивал:

```text
ai-worker
+
PyTorch
+
Kev weights
+
LLM
+
pipeline
```

в одном процессе.

Вместо этого:

```text
                         AI Worker VPS
                              │
                 ┌────────────┴────────────┐
                 │                         │
                 ▼                         ▼
             ai-worker                 Kev server
             FastAPI/worker            GPU inference
                 │                         │
                 │ HTTP                    │
                 └─────────────────────────┘
```

Например:

```text
ai-worker
    ↓
http://kev:8008/v1/systemone
```

Сам проект Kev предоставляет `kev.serve` и TypeSafe-compatible `/v1/systemone` API. ([GitHub][3])

Это также соответствует вашему первоначальному подходу с тяжёлыми AI-компонентами на отдельных ресурсах.

---

# 6. Почему отдельный Kev server лучше

Плюсы:

### Независимый lifecycle

Можно:

```text
ai-worker = always on
kev = start/stop as needed
```

### Независимая модель

Можно менять:

```text
Kev-0.8B
↓
Kev-4B
↓
Kev-9B
```

не меняя `ai-worker`.

### Независимые ресурсы

Например:

```text
CPU VPS
    ai-worker

GPU VPS
    Kev
```

### Возможность A/B

Можно одновременно:

```text
RuleBased
Kev-0.8B
Kev-4B
```

и сравнивать результаты.

---

# 7. Архитектура внутри вашего repository

Я бы расширил существующий:

```text
apps/ai-worker/app/classification/
```

так:

```text
classification/
├── __init__.py
│
├── classifier.py
├── resolver.py
├── service.py
│
├── models.py
├── schemas.py
├── exceptions.py
│
├── normalize.py
├── scoring.py
│
├── providers/
│   ├── __init__.py
│   ├── base.py
│   ├── rule_based.py
│   └── kev.py
│
├── kev/
│   ├── __init__.py
│   ├── client.py
│   ├── models.py
│   ├── questions.py
│   └── mapper.py
│
├── evaluation/
│   ├── ...
│
├── evaluate.py
└── artifact.py
```

Я бы именно так разделил:

```text
providers/kev.py
```

и:

```text
kev/
```

Потому что это две разные ответственности.

---

# 8. `classification/kev/client.py`

Здесь находится HTTP client.

Например концептуально:

```python
class KevClient:
    async def classify(
        self,
        state: str,
        questions: list[KevQuestion],
    ) -> KevResponse:
        ...
```

Он знает:

* URL;
* timeout;
* API key;
* model;
* HTTP;
* retries;
* response parsing.

Он **не знает**, что такое `laboratory` или `appointment`.

---

# 9. `classification/kev/questions.py`

Здесь описываем наши decision questions.

Например:

```python
DOCUMENT_TYPE_QUESTION = KevQuestion(
    id="document_type",
    type="choice",
    instruction="What is the primary type of this medical document?",
    options=[
        "laboratory",
        "appointment",
        "prescription",
        "discharge",
        "diagnosis",
        "imaging",
        "other",
    ],
)
```

Это очень важный слой.

Потому что **question schema становится частью вашего classifier contract**.

Я бы версионировал её:

```text
document_type:v1
document_type:v2
```

---

# 10. `classification/kev/mapper.py`

Kev говорит:

```text
"laboratory"
```

а ваше приложение должно говорить:

```python
DocumentType.LABORATORY
```

Поэтому нужен mapper:

```text
Kev output
    ↓
KevMapper
    ↓
ClassificationResult
```

Например:

```json
{
  "provider": "kev",
  "classifier_version": "kev-0.8b-v1",
  "question_version": "document_type-v1",
  "type": "laboratory",
  "confidence": 0.91,
  "probabilities": {
    "laboratory": 0.91,
    "appointment": 0.05,
    "prescription": 0.01,
    "other": 0.03
  }
}
```

---

# 11. Общий `ClassificationResult`

Я бы немного расширил ваш существующий контракт.

Например:

```python
class ClassificationResult(BaseModel):
    type: DocumentType
    subtype: DocumentSubtype | None

    confidence: float

    provider: str
    classifier_version: str
    question_version: str

    probabilities: dict[str, float]

    decision: ClassificationDecision

    metadata: dict[str, Any]
```

Таким образом:

### Rule Based

```json
{
  "provider": "rule_based",
  "classifier_version": "2.1.0"
}
```

### Kev

```json
{
  "provider": "kev",
  "classifier_version": "kev-0.8b",
  "question_version": "document_type-v1"
}
```

---

# 12. Не называйте confidence Kev confidence

Это важный момент.

Kev возвращает probability distribution, а не обязательно вашу бизнес-интерпретацию confidence.

Например:

```text
laboratory 0.52
appointment 0.45
other       0.03
```

Top-1:

```text
laboratory
```

но это совершенно другая ситуация, чем:

```text
laboratory 0.98
appointment 0.01
other 0.01
```

Поэтому я бы хранил:

```text
probabilities
top_probability
margin
decision_confidence
```

отдельно.

Например:

```json
{
  "top_probability": 0.52,
  "second_probability": 0.45,
  "margin": 0.07
}
```

А `decision_confidence` рассчитывать уже вашим application-level policy.

---

# 13. Особенно важно для вашего M3

Ваш текущий Classification M3 уже занимается calibration.

Kev прекрасно вписывается туда, но **не надо смешивать calibration RuleBased и calibration Kev**.

Например:

```text
RuleBased
    classifier_version 2.1.0

Kev
    model_version kev-0.8b
    question_version document_type-v1
    calibration_version 1.0
```

Отдельные метрики:

```text
accuracy
precision
recall
F1
ECE
Brier
confidence distribution
```

Kev сам делает большой акцент на calibration и в model cards публикует ECE/Brier, поэтому эти метрики особенно естественны для сравнения. ([GitHub][2])

---

# 14. Shadow mode

Для вашего проекта это, на мой взгляд, **главный режим первой интеграции**.

Pipeline:

```text
                    marker.md
                       │
                       ▼
              ClassificationService
                       │
             ┌─────────┴─────────┐
             ▼                   ▼
        RuleBased              Kev
             │                   │
             │                   │
             ▼                   ▼
       authoritative         experimental
             │                   │
             │              classification
             │              candidate artifact
             │                   │
             └─────────┬─────────┘
                       ▼
                    PII Gate
```

Kev **не влияет** на дальнейшую обработку.

---

# 15. Shadow result

Я бы не записывал Kev поверх:

```text
classification/result.json
```

Вместо этого:

```text
classification/
├── result.json
└── candidates/
    └── kev/
        └── result.json
```

Например:

```text
documents/{document_id}/versions/{version}/
    marker.md

    classification/
        result.json

        candidates/
            kev/
                result.json
```

Это позволяет потом делать retrospective evaluation.

---

# 16. Что хранить в Kev artifact

Я бы сделал примерно:

```json
{
  "artifact_type": "classification_candidate",
  "provider": "kev",
  "model": "jaredpalmer/kev-0.8b",
  "model_revision": "...",
  "question_version": "document_type-v1",

  "input": {
    "source_artifact": "marker.md",
    "content_hash": "..."
  },

  "decision": {
    "type": "laboratory",
    "top_probability": 0.94,
    "second_probability": 0.03,
    "margin": 0.91
  },

  "probabilities": {
    "laboratory": 0.94,
    "appointment": 0.03,
    "prescription": 0.01,
    "discharge": 0.01,
    "diagnosis": 0.00,
    "imaging": 0.00,
    "other": 0.01
  },

  "runtime": {
    "latency_ms": 120,
    "input_tokens": 100
  }
}
```

---

# 17. Не передавайте в Kev PII без необходимости

У вас уже есть:

```text
app/pii/
```

и PII Gate.

Здесь есть архитектурный вопрос.

Если Kev используется **до PII Gate**, модель увидит потенциальные:

* ФИО;
* дату рождения;
* телефон;
* адрес;
* номер документа.

Для медицинского проекта я бы не принимал это как default.

Нужно явно решить:

```text
PII Gate
```

где именно стоит относительно classifier.

Для первой интеграции я бы предусмотрел:

```text
marker.md
    ↓
PII-safe classification input
    ↓
Kev
```

То есть classifier получает минимально необходимый текст.

Но это отдельная policy и не должно случайно появиться внутри `KevClient`.

---

# 18. Ограничение контекста — отдельный риск

Это особенно важно.

Kev-0.5B тренировался на state context ≤384 tokens, хотя serving допускает значительно больше; в текущем проекте также есть отдельные исследования проблем long-context. В model card прямо отмечено, что long documents требуют отдельного внимания. ([GitHub][2])

А ваши:

```text
marker.md
```

могут быть:

```text
5k
10k
30k tokens
```

Поэтому нельзя просто:

```python
kev(document_markdown)
```

для любого документа.

Нужен:

```text
Document
    ↓
ClassificationInputBuilder
    ↓
bounded classification state
    ↓
Kev
```

---

# 19. ClassificationInputBuilder

Я бы добавил:

```text
classification/input/
├── __init__.py
├── builder.py
├── policy.py
└── truncation.py
```

И:

```python
class ClassificationInputBuilder:
    def build(
        self,
        document: NormalizedDocument,
    ) -> ClassificationInput:
        ...
```

Policy должна определить:

* максимальное количество tokens;
* начало документа;
* конец документа;
* наличие таблиц;
* заголовки;
* metadata;
* OCR quality.

Для лабораторных документов особенно полезно сохранить:

```text
название исследования
+
названия показателей
+
референсные значения
+
результаты
```

а не просто первые 384 tokens.

---

# 20. Я бы сделал несколько input strategies

Например:

```text
FULL
HEAD
HEAD_TAIL
SIGNAL_EXCERPT
```

Для экспериментов:

```text
KevInputPolicy
```

может быть:

```text
laboratory:
    HEAD + TABLES + SIGNALS

appointment:
    HEAD + BODY

generic:
    HEAD + TAIL
```

Но **не надо делать это до базового benchmark**.

Сначала:

```text
одинаковый input
+
одинаковый dataset
+
Kev
```

и только потом оптимизация.

---

# 21. Evaluation architecture

Ваш существующий:

```text
classification/evaluate.py
```

я бы расширил:

```bash
uv run ... python -m app.classification.evaluate \
    --provider rule_based
```

и:

```bash
uv run ... python -m app.classification.evaluate \
    --provider kev
```

А затем:

```bash
uv run ... python -m app.classification.compare \
    --baseline rule_based \
    --candidate kev
```

---

# 22. Comparison должен сравнивать не только accuracy

Для вашего проекта я бы сравнивал:

| Metric             | RuleBased | Kev |
| ------------------ | --------: | --: |
| Accuracy           |         ✓ |   ✓ |
| Macro F1           |         ✓ |   ✓ |
| Laboratory recall  |         ✓ |   ✓ |
| Appointment recall |         ✓ |   ✓ |
| False laboratory   |         ✓ |   ✓ |
| Generic rate       |         ✓ |   ✓ |
| Ambiguous          |         ✓ |   ✓ |
| Top probability    |         — |   ✓ |
| Margin             |         — |   ✓ |
| ECE                |         — |   ✓ |
| Brier              |         — |   ✓ |
| Latency            |         ✓ |   ✓ |
| Memory             |         ✓ |   ✓ |
| Cost               |         ✓ |   ✓ |

Особенно:

```text
false_laboratory
```

для вашей медицинской системы я бы оставил отдельным gate.

---

# 23. Question design

Первый вопрос:

```text
What is the primary type of this document?
```

Но варианты должны быть **строго такими же, как ваш domain enum**:

```text
laboratory
appointment
prescription
discharge
diagnosis
imaging
other
```

Не:

```text
lab report
doctor visit
medical prescription
...
```

Иначе mapper будет постоянно бороться с семантическими различиями.

---

# 24. Я бы добавил второй вопрос позже

После первого benchmark:

```text
Q1:
primary document type
```

потом:

```text
Q2:
Is this document primarily a laboratory report?
```

и сравнить:

```text
Q1 probability
vs
Q2 probability
```

Это может дать интересный сигнал.

Но не надо сразу делать composite classifier.

---

# 25. Multi-question преимущество Kev

Одна из интересных особенностей архитектуры Kev — несколько вопросов могут быть упакованы в один запрос, при этом branches изолированы и не видят ответы друг друга. ([GitHub][3])

Для вашего будущего это позволяет сделать:

```text
STATE = document

Q1 → document_type
Q2 → is_laboratory
Q3 → has_results
Q4 → clinical_encounter
Q5 → document_quality
```

одним inference.

Но я бы **не использовал Q2–Q5 для принятия решений до оценки их качества**.

---

# 26. Configuration

В `app/config/settings.py` добавить примерно:

```text
CLASSIFICATION_PROVIDER=rule_based

CLASSIFICATION_SHADOW_PROVIDER=kev

KEV_BASE_URL=http://kev:8008
KEV_API_KEY=
KEV_MODEL=jaredpalmer/kev-0.8b

KEV_TIMEOUT_SECONDS=10

KEV_QUESTION_VERSION=document_type-v1

KEV_ENABLED=false
KEV_SHADOW_ENABLED=false
```

Это позволит запускать:

### Production

```text
RULE_BASED
```

### Local

```text
KEV
```

### Shadow

```text
RULE_BASED + KEV
```

---

# 27. Local development

Для вас я бы обязательно сделал отдельный compose profile:

```yaml
services:

  ai-worker:
    ...

  kev:
    ...
    profiles:
      - kev
```

Запуск:

```bash
docker compose --profile kev up
```

Получается:

```text
RabbitMQ
Postgres
S3
ai-worker
Kev
```

---

# 28. Но не обязательно сразу контейнеризировать Kev

На первом этапе даже лучше:

```text
Terminal 1:
kev.serve

Terminal 2:
ai-worker
```

Например:

```text
localhost:8008
```

Так вы быстрее сможете проверить classifier contract.

---

# 29. Tests

Добавить:

```text
tests/unit/classification/providers/
├── test_rule_based.py
├── test_kev.py
└── test_resolver.py

tests/unit/classification/kev/
├── test_client.py
├── test_mapper.py
├── test_questions.py
└── test_input_builder.py
```

Особенно важны:

### Contract test

Оба classifier должны возвращать:

```python
ClassificationResult
```

### Mapper test

```text
Kev probabilities
        ↓
ClassificationResult
```

### Timeout test

Kev недоступен:

```text
RuleBased остаётся рабочим
```

если это shadow mode.

---

# 30. Circuit breaker

Я бы не делал сложный circuit breaker в первой версии.

Достаточно:

```text
timeout
retry = 0 или 1
```

и:

```text
Kev failure
    ↓
shadow failure recorded
    ↓
main pipeline continues
```

Если Kev когда-нибудь станет primary:

```text
Kev failure
    ↓
fallback RuleBased
```

но это уже отдельный этап.

---

# 31. Versioning

Для каждого результата должны быть минимум:

```text
provider
model
model_revision
classifier_version
question_version
input_policy_version
```

Например:

```json
{
  "provider": "kev",
  "model": "jaredpalmer/kev-0.8b",
  "model_revision": "q35-08b/02-trial-2",
  "classifier_version": "1.0.0",
  "question_version": "document_type-v1",
  "input_policy_version": "default-v1"
}
```

Это особенно важно, потому что модельные checkpoints в Kev развиваются; текущий repository уже содержит несколько поколений моделей и отдельные evaluation protocols. ([GitHub][4])

---

# 32. План разработки

Я бы не делал это одной большой Phase.

## K0 — Architecture / contract

**Цель:** не менять behaviour.

Сделать:

```text
Classifier Protocol
ClassificationResult
ClassifierResolver
Provider interface
```

Выделить:

```text
RuleBasedClassifier
```

из существующей реализации.

### Acceptance

```text
pytest
```

полностью зелёный.

Результаты RuleBased до/после идентичны.

---

# K1 — Kev infrastructure

Создать:

```text
classification/kev/
classification/providers/kev.py
```

Добавить:

```text
KevClient
KevQuestion
KevResponse
KevMapper
```

Добавить settings.

**Пока pipeline не использовать.**

---

# K2 — Local Kev

Запустить:

```text
Kev server
```

локально.

Проверить:

```text
ai-worker
   ↓
HTTP
   ↓
Kev
   ↓
response
```

на одном markdown.

---

# K3 — Input Builder

Добавить:

```text
ClassificationInputBuilder
```

и:

```text
input_policy_version
```

Первоначально максимально простой:

```text
normalized markdown
↓
bounded text
```

Без сложной эвристики.

---

# K4 — Kev standalone evaluation

Запустить ваш существующий dataset:

```text
11 fixtures
```

через Kev.

Получить:

```text
reports/
    classification-kev-v1.md
```

Здесь **ничего не менять в RuleBased**.

---

# K5 — Comparison

Сделать:

```text
RuleBased 2.1.0
vs
Kev
```

на одном ground truth.

Получить:

```text
classification-comparison.md
```

---

# K6 — Shadow mode

Pipeline:

```text
marker.md
   │
   ├── RuleBased → production
   │
   └── Kev → candidate
```

Persist:

```text
classification/result.json

classification/candidates/kev/result.json
```

---

# K7 — Real-document evaluation

Вот этот этап для вашего проекта будет гораздо важнее первоначальных 11 fixtures.

Собрать реальные документы:

```text
laboratory
appointment
prescription
discharge
diagnosis
imaging
other
```

и сделать manual ground truth.

Потому что текущий Kev сам по себе показывает хорошие/интересные результаты на своих evaluation datasets, но его model cards прямо подчёркивают необходимость измерять поведение на собственных данных и ограничения out-of-domain performance. ([GitHub][5])

---

# K8 — Calibration

После появления достаточного количества ваших документов:

```text
Kev raw probabilities
        ↓
calibration
        ↓
application confidence
```

Измерять:

```text
ECE
Brier
reliability
confidence bins
```

---

# K9 — Decision

Только после K7/K8 принимать решение:

```text
RuleBased primary
Kev shadow
```

или:

```text
Kev primary
RuleBased fallback
```

или:

```text
Hybrid
```

Это должно быть **результатом evaluation**, а не архитектурным предположением.

---

# 33. Что я бы НЕ делал

На первом этапе не стоит:

### ❌ Заменять RuleBased

```text
RuleBased → removed
Kev → primary
```

слишком рано.

### ❌ Fine-tune Kev на ваших медицинских данных

Сначала нужен baseline.

### ❌ Добавлять 10 questions

Начать с одного.

### ❌ Передавать весь marker.md

Сначала определить input policy.

### ❌ Встраивать PyTorch в ai-worker

Лучше отдельный inference service.

### ❌ Использовать Kev для медицинских выводов

Kev здесь должен решать:

```text
"What type of document is this?"
```

а не:

```text
"What disease does the patient have?"
```

Это особенно важно, учитывая ограничения, указанные авторами самого проекта. ([GitHub][6])

---

# 34. Итоговая архитектура

В итоге я бы строил так:

```text
                         ┌──────────────────────┐
                         │       marker.md      │
                         └──────────┬───────────┘
                                    │
                                    ▼
                       ┌────────────────────────┐
                       │ ClassificationService  │
                       └───────────┬────────────┘
                                   │
                                   ▼
                       ┌────────────────────────┐
                       │  ClassifierResolver    │
                       └───────────┬────────────┘
                                   │
                    ┌──────────────┴──────────────┐
                    │                             │
                    ▼                             ▼
          ┌──────────────────┐          ┌──────────────────┐
          │ RuleBased 2.1.0  │          │   KevClassifier  │
          └────────┬─────────┘          └────────┬─────────┘
                   │                             │
                   │                             ▼
                   │                    ┌─────────────────┐
                   │                    │    KevClient    │
                   │                    └────────┬────────┘
                   │                             │ HTTP
                   │                             ▼
                   │                    ┌─────────────────┐
                   │                    │    Kev Server   │
                   │                    │ GPU / inference │
                   │                    └─────────────────┘
                   │
                   └──────────────┬──────────────┘
                                  │
                                  ▼
                     ┌────────────────────────┐
                     │ ClassificationResult   │
                     └────────────┬───────────┘
                                  │
                         ┌────────┴────────┐
                         │                 │
                         ▼                 ▼
                   authoritative       candidate
                      result             result
                         │                 │
                         ▼                 ▼
                classification/     classification/
                  result.json        candidates/
                                     kev/result.json
```

И структура вашего `ai-worker` после K1/K2 будет примерно:

```text
app/
├── classification/
│   ├── classifier.py
│   ├── resolver.py
│   ├── service.py
│   ├── models.py
│   ├── schemas.py
│   │
│   ├── providers/
│   │   ├── base.py
│   │   ├── rule_based.py
│   │   └── kev.py
│   │
│   ├── kev/
│   │   ├── client.py
│   │   ├── models.py
│   │   ├── questions.py
│   │   ├── mapper.py
│   │   └── input.py
│   │
│   ├── evaluation/
│   ├── evaluate.py
│   └── artifact.py
│
├── llm/
├── pii/
├── canonical/
├── pipeline/
└── ...
```

**Ключевое решение:** я бы сейчас проектировал Kev как **взаимозаменяемый `ClassifierProvider` + отдельный inference service + shadow/evaluation mode**. Это идеально соответствует тому состоянию, в котором находится ваш проект после M3: существующий RuleBased classifier остаётся стабильным baseline, а Kev становится новым кандидатом, которого можно локально прогнать на тех же fixtures, затем подключить к реальному flow без риска изменить основной результат.

Для ориентира по самому проекту Kev: [репозиторий jaredpalmer/kev](https://github.com/jaredpalmer/kev?utm_source=chatgpt.com) ([GitHub][7])

[1]: https://github.com/jaredpalmer/kev/blob/main/README.md?utm_source=chatgpt.com "kev/README.md at main · jaredpalmer/kev · GitHub"
[2]: https://github.com/jaredpalmer/kev/blob/main/MODEL_CARD.md?utm_source=chatgpt.com "kev/MODEL_CARD.md at main · jaredpalmer/kev · GitHub"
[3]: https://github.com/jaredpalmer/kev/blob/main/docs/model-cards/kev-0.6b.md?utm_source=chatgpt.com "kev/docs/model-cards/kev-0.6b.md at main · jaredpalmer/kev · GitHub"
[4]: https://github.com/jaredpalmer/kev/blob/main/PLAN.md?utm_source=chatgpt.com "kev/PLAN.md at main · jaredpalmer/kev · GitHub"
[5]: https://github.com/jaredpalmer/kev/blob/main/docs/model-cards/kev-0.8b.md?utm_source=chatgpt.com "kev/docs/model-cards/kev-0.8b.md at main · jaredpalmer/kev · GitHub"
[6]: https://github.com/jaredpalmer/kev/blob/main/docs/model-cards/kev-0.5b.md?utm_source=chatgpt.com "kev/docs/model-cards/kev-0.5b.md at main · jaredpalmer/kev · GitHub"
[7]: https://github.com/jaredpalmer/kev?utm_source=chatgpt.com "GitHub - jaredpalmer/kev: tiny Jev-like family of decision models built on top of Qwen3.5 you can train and run on your own · GitHub"
