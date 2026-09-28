Да. С учетом текущей структуры `ai-worker` я бы добавлял **Laya не как замену `Classification 2.0`, а как отдельный classifier backend**, подключенный через существующий classification contract. Это особенно важно, потому что Laya по своей природе отличается от вашего rule-based классификатора: он делает typed `choice/score/noul` decisions, а не генерирует текст. ([GitHub][1])

При этом я бы **не встраивал Laya непосредственно в `scoring.py`**. Лучше сохранить `Classification 2.0` как reference/deterministic classifier и добавить Laya как альтернативный engine.

## 1. Что именно мы добавляем

Целевая схема:

```text
                         ┌──────────────────────┐
                         │ Classification input │
                         │ normalized document  │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │ ClassificationService│
                         └──────────┬───────────┘
                                    │
                         classifier strategy
                                    │
                  ┌─────────────────┼─────────────────┐
                  │                 │                 │
                  ▼                 ▼                 ▼
          ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
          │ Rule-based   │  │    Laya      │  │ future model │
          │ Classifier   │  │ Classifier   │  │              │
          │ 2.1          │  │              │  │              │
          └──────────────┘  └──────────────┘  └──────────────┘
                  │                 │
                  └─────────────────┘
                            │
                            ▼
                    ClassificationResult
                            │
                            ▼
                    existing pipeline
```

Ключевая идея:

> **Laya должен реализовывать ваш `Classifier` interface, а не знать о pipeline, S3, RabbitMQ, canonical или repositories.**

Это позволит позже добавить, например:

```text
rule
laya
llm
fine-tuned-laya
organization-specific
ensemble
```

без изменения pipeline.

---

# 2. Почему Laya хорошо подходит именно как экспериментальный classifier

Laya поддерживает `choice`, `score` и `noul` решения. Для вашей задачи `choice` естественно отображается на:

```text
laboratory
appointment
prescription
generic
other
```

Например:

```python
questions = {
    "document_type": {
        "type": "choice",
        "instructions": "Classify the medical document.",
        "criteria": {
            "laboratory": "...",
            "appointment": "...",
            "prescription": "...",
            "generic": "...",
            "other": "..."
        }
    }
}
```

Laya возвращает typed answer, а не сгенерированный текст. Это снижает необходимость парсить LLM output. ([GitHub][1])

Но важный момент: **не следует сразу считать zero-shot Laya production classifier'ом**. Сам проект прямо позиционирует базовые checkpoints как zero-shot и рекомендует specialization/fine-tuning на собственных данных; в опубликованном примере fine-tuning существенно меняет accuracy. ([GitHub][2])

Поэтому первая задача — **локальный benchmark на ваших 11 fixtures**, а не замена текущего классификатора.

---

# 3. Предлагаемая архитектура

Я бы немного расширил существующую:

```text
app/
└── classification/
    ├── __init__.py
    │
    ├── models.py
    ├── schemas.py
    ├── exceptions.py
    │
    ├── classifier.py
    ├── service.py
    ├── resolver.py
    │
    ├── normalize.py
    │
    ├── scoring.py
    │
    ├── artifact.py
    ├── evaluate.py
    │
    ├── engines/
    │   ├── __init__.py
    │   ├── base.py
    │   ├── rule_based.py
    │   └── laya.py
    │
    ├── laya/
    │   ├── __init__.py
    │   ├── client.py
    │   ├── config.py
    │   ├── questions.py
    │   ├── mapper.py
    │   └── models.py
    │
    └── signals/
        ├── ...
```

Но есть важное архитектурное различие:

### `engines/`

Это abstraction уровня classification:

```text
engines/
    base.py
    rule_based.py
    laya.py
```

### `laya/`

Это adapter к конкретной внешней библиотеке:

```text
laya/
    client.py
    questions.py
    mapper.py
    models.py
```

Таким образом:

```text
Classification
      │
      ▼
LayaClassifier
      │
      ▼
LayaClient
      │
      ▼
laya.Router
```

---

# 4. Classification engine contract

Я бы сначала формализовал интерфейс.

Например:

```python
class ClassificationEngine(Protocol):
    name: str
    version: str

    def classify(
        self,
        document: ClassificationDocument,
    ) -> ClassificationResult:
        ...
```

Или abstract class:

```python
class ClassificationEngine(ABC):

    @abstractmethod
    def classify(
        self,
        document: ClassificationDocument,
    ) -> ClassificationResult:
        ...
```

Тогда существующий classifier становится:

```text
RuleBasedClassifier
        implements
ClassificationEngine
```

и новый:

```text
LayaClassifier
        implements
ClassificationEngine
```

---

# 5. Не смешивать Laya result с вашим ClassificationResult

Это принципиально.

Laya может вернуть что-то вроде:

```json
{
  "answers": {
    "document_type": {
      "choice": "laboratory"
    }
  },
  "routing": {
    "model": "multilingual"
  }
}
```

Но внутри вашего приложения результат должен быть вашим:

```json
{
  "type": "laboratory",
  "subtype": null,
  "confidence": 0.91,
  "decision": "accepted",
  "classifier": "laya",
  "classifier_version": "0.x",
  "model": "laya-multilingual"
}
```

То есть:

```text
Laya output
    ↓
LayaMapper
    ↓
ClassificationResult
```

Так pipeline остается независимым от Laya.

---

# 6. Laya adapter

Предлагаю:

```text
app/classification/laya/client.py
```

Отвечает только за запуск модели.

Например концептуально:

```python
class LayaClient:

    def __init__(
        self,
        model: str,
        device: str,
    ):
        self.router = Router(...)
    
    def predict(
        self,
        text: str,
        questions: dict,
    ) -> LayaRawResult:
        ...
```

Важно не вызывать `Router()` на каждый документ.

Нужно:

```text
worker startup
      │
      ▼
LayaClassifier
      │
      ▼
LayaClient
      │
      ▼
Router loaded once
```

а не:

```text
document
 ↓
create Router
 ↓
load model
 ↓
predict
 ↓
destroy
```

Это особенно важно для GPU/CPU memory.

---

# 7. Model lifecycle

У Laya есть `Router`, который может загружать checkpoints при первом использовании, а `Router(preload=True)` загружает несколько checkpoints сразу. ([GitHub][2])

Для вашего worker я бы сделал:

```text
AI Worker startup
       │
       ├── rule classifier
       │
       └── optional Laya
              │
              ├── lazy
              │
              └── preload
```

Через config:

```env
CLASSIFICATION_ENGINE=rule
LAYA_ENABLED=false
LAYA_MODEL=multilingual
LAYA_DEVICE=cpu
LAYA_PRELOAD=false
```

Для локального эксперимента:

```env
CLASSIFICATION_ENGINE=laya
LAYA_ENABLED=true
LAYA_MODEL=multilingual
LAYA_DEVICE=mps
```

или CUDA:

```env
LAYA_DEVICE=cuda
```

---

# 8. Очень важный момент — русский медицинский текст

У вас документы преимущественно русскоязычные.

Поэтому **не стоит использовать English checkpoint только потому, что он быстрее**.

У Laya есть `laya-multilingual`, рассчитанный на 100+ языков; Router умеет выбирать multilingual checkpoint. Для длинных документов документация также указывает возможность `max_len=8192`, хотя авторы рекомендуют самостоятельно проверять качество на собственных данных. ([GitHub][1])

Для вашего benchmark я бы сравнил:

```text
Laya English
       vs
Laya multilingual
```

но production candidate сразу строил бы вокруг:

```text
laya-multilingual
```

---

# 9. Не отправлять весь marker.md без ограничений

Это одна из наиболее важных частей интеграции.

Ваш текущий flow:

```text
Marker
 ↓
marker.md
 ↓
normalize
 ↓
classification
```

Для Laya желательно определить:

```text
ClassificationInput
```

Например:

```python
class ClassificationInput:
    text: str
    title: str | None
    source_type: str | None
    language: str | None
```

И создать отдельный:

```text
LayaInputBuilder
```

который формирует оптимизированный текст.

Например:

```text
document title

first N characters

headings

high-value medical sections

laboratory markers

appointment metadata
```

Но на первом этапе я бы **не делал сложную оптимизацию**.

MVP:

```text
normalized markdown
        ↓
Laya
```

И только после benchmark смотреть, действительно ли требуется preprocessing.

---

# 10. Questions должны быть versioned

Я бы не хранил questions непосредственно в `laya.py`.

Например:

```text
app/classification/laya/questions.py
```

```python
LAYA_CLASSIFICATION_PROMPT_VERSION = "1.0.0"
```

и:

```python
DOCUMENT_TYPE_QUESTION = {
    "type": "choice",
    "instructions": "...",
    "criteria": {
        ...
    }
}
```

Или лучше:

```text
app/prompts/classification/
    laya_document_type_v1.yaml
```

Например:

```yaml
version: "1.0.0"

question:
  type: choice

  instructions: >
    Classify the medical document into exactly one category.

  criteria:
    laboratory: >
      Laboratory test results...

    appointment: >
      Medical consultation...

    prescription: >
      Prescription...

    generic: >
      General medical document...

    other: >
      Documents that do not fit...
```

Это хорошо вписывается в уже существующую у вас систему:

```text
app/prompts/
```

---

# 11. Confidence — отдельный вопрос

Я бы **не приравнивал автоматически Laya probability к вашему `confidence`**.

Это разные семантики.

Нужно:

```text
Laya probability
       ↓
LayaClassificationEvidence
       ↓
confidence calibration
       ↓
ClassificationResult.confidence
```

Например:

```python
class LayaEvidence:
    selected_class: str
    probability: float
    alternatives: dict[str, float]
```

А затем:

```python
ClassificationResult(
    type=...,
    confidence=...,
    evidence=...
)
```

На первом этапе можно сохранить probability как есть, но назвать ее:

```text
model_probability
```

а не делать вид, что она уже calibrated confidence.

---

# 12. Margin тоже нужно сохранить

Для вашего текущего classifier уже есть идея:

```text
confidence
margin
ambiguity
```

Laya хорошо позволяет сохранить:

```text
top probability
second probability
margin
```

Например:

```json
{
  "selected": "laboratory",
  "probability": 0.91,
  "second": {
    "type": "appointment",
    "probability": 0.06
  },
  "margin": 0.85
}
```

Это очень полезно для сравнения:

```text
Rule classifier
vs
Laya
```

---

# 13. Нужно сохранить два classifier results

На этапе исследования я бы **не делал Laya replacement**.

Pipeline может временно работать так:

```text
                    document
                       │
              ┌────────┴────────┐
              ▼                 ▼
       Rule classifier       Laya
              │                 │
              ▼                 ▼
          result A           result B
              │                 │
              └────────┬────────┘
                       ▼
                    evaluator
```

То есть Laya работает в **shadow mode**.

Например:

```env
CLASSIFICATION_ENGINE=rule
CLASSIFICATION_SHADOW_ENGINE=laya
```

Основной pipeline использует:

```text
rule
```

но одновременно собирает:

```text
laya result
```

Это намного безопаснее.

---

# 14. Artifact

Я бы добавил отдельный artifact только после того, как определится контракт.

Например:

```text
classification/
    result.json
```

но:

```json
{
  "classifier": {
    "name": "laya",
    "version": "0.3.5",
    "model": "laya-multilingual"
  },
  "decision": {
    "type": "laboratory",
    "confidence": 0.91
  },
  "evidence": {
    "probabilities": {
      "laboratory": 0.91,
      "appointment": 0.04,
      "prescription": 0.02,
      "generic": 0.02,
      "other": 0.01
    }
  }
}
```

Но здесь я бы **не менял ваш существующий artifact contract ради Laya**.

Добавить:

```json
engine: "laya"
```

и оставить общий schema.

---

# 15. Версионирование

Нужно различать минимум четыре версии:

```text
classifier_version
model_version
question_version
artifact_schema_version
```

Например:

```json
{
  "classifier": {
    "engine": "laya",
    "version": "0.1.0"
  },

  "model": {
    "name": "laya-multilingual",
    "version": "0.3.5"
  },

  "question": {
    "version": "1.0.0"
  },

  "schema": {
    "version": "1.0.0"
  }
}
```

Это особенно важно для ваших будущих evaluation runs.

---

# 16. Dataset

Самое ценное для этого этапа — ваши существующие fixtures.

Сейчас у вас:

```text
tests/fixtures/classification/
```

и 11 документов.

Не нужно создавать новый dataset.

Сделать:

```text
existing 11 fixtures
       │
       ├── Rule 2.1
       │
       └── Laya
```

и получить:

```text
document                  expected    rule       laya
---------------------------------------------------------
datalab-...               laboratory  laboratory laboratory
appointment_002           appointment appointment appointment
prescription_001          prescription ...
generic_001               generic     generic    ...
...
```

---

# 17. Laya Evaluation

Я бы расширил существующий:

```text
app/classification/evaluate.py
```

а не создавал:

```text
evaluate_laya.py
```

CLI:

```bash
python -m app.classification.evaluate --engine rule
```

```bash
python -m app.classification.evaluate --engine laya
```

и:

```bash
python -m app.classification.evaluate --compare rule laya
```

Последняя команда особенно полезна:

```text
Classification Evaluation
=========================

Dataset: 11 documents

                 Rule 2.1     Laya
Accuracy         10/11        9/11
Laboratory       ...          ...
Appointment       ...          ...
Prescription      ...          ...
Generic           ...          ...

Disagreements: 3
```

---

# 18. Disagreement report

Я бы сделал это обязательной частью.

Например:

```text
reports/
    classification/
        rule-2.1/
        laya-0.1/
        comparisons/
```

и:

```text
reports/classification/comparisons/
    rule-vs-laya-2026-09-25.md
```

Для каждого disagreement:

```text
Document: b8f07559

Expected:
laboratory

Rule:
laboratory
confidence: 0.87

Laya:
generic
probability: 0.61

Top alternatives:
laboratory: 0.31
appointment: 0.08

Analysis:
...
```

Это позволит принимать решение **на основании документов**, а не субъективно.

---

# 19. Не добавлять Laya в `signals/`

Это я бы отдельно зафиксировал агенту.

Сейчас:

```text
classification/
└── signals/
    ├── laboratory.py
    ├── appointment.py
    ├── prescription.py
```

Это часть:

```text
RuleScoringEngine
```

Laya не является signal.

Поэтому **не делать**:

```text
signals/laya.py
```

и не пытаться представить neural model как еще один signal.

Правильно:

```text
classification/
├── engines/
│   ├── base.py
│   ├── rule_based.py
│   └── laya.py
│
└── laya/
    ├── client.py
    ├── mapper.py
    ├── questions.py
    └── models.py
```

---

# 20. Интеграция с Pipeline

Текущий pipeline не должен знать:

```python
from laya import Router
```

Он должен знать только:

```python
classifier.classify(...)
```

То есть:

```text
pipeline
   │
   ▼
ClassificationService
   │
   ▼
ClassificationEngine
   │
   ├── RuleBasedClassifier
   │
   └── LayaClassifier
```

Это даст вам возможность позже сделать:

```text
ClassificationEngine
       │
       ├── rule
       ├── laya
       ├── llm
       ├── fine-tuned-laya
       └── ensemble
```

---

# 21. API/CLI для локального тестирования

Я бы добавил простой developer command:

```bash
make classify-laya FILE=tests/fixtures/classification/laboratory/b8f07559.md
```

или:

```bash
uv run --project apps/ai-worker \
    python -m app.classification.laya \
    tests/fixtures/classification/laboratory/b8f07559.md
```

Output:

```text
Laya Classification
-------------------

model: laya-multilingual
document_type: laboratory

probabilities:
  laboratory: 0.91
  appointment: 0.04
  prescription: 0.02
  generic: 0.02
  other: 0.01

latency: 37ms
```

Это сильно ускорит исследование.

---

# 22. Зависимости

Laya сейчас требует Python >=3.10 и runtime dependencies включают PyTorch, Transformers, Safetensors, Hugging Face Hub и NumPy. ([GitHub][3])

У вас Python 3.12, поэтому базовая совместимость по версии Python есть.

Но я бы **не добавлял Laya в production dependency group без отдельного dependency review**.

Например:

```toml
[project.optional-dependencies]

classification-laya = [
    "laya==0.3.5",
]
```

или отдельная dependency group.

Причина — `torch` существенно увеличит environment.

Для development:

```bash
uv sync --extra classification-laya
```

Для production image:

```text
AI worker base
        │
        ├── standard
        │
        └── laya
```

если это потребуется.

---

# 23. GPU vs CPU

Я бы начал **с CPU для функционального benchmark**, если скорость приемлема.

Затем:

```text
CPU benchmark
       ↓
accuracy evaluation
       ↓
GPU benchmark
       ↓
latency comparison
```

У Laya заявлена очень низкая latency на T4, но это не означает, что она автоматически будет оптимальной для вашего конкретного worker и медицинских документов. ([GitHub][1])

В evaluation добавить:

```text
latency_ms
model
device
input_tokens
```

---

# 24. Длинные документы — отдельный эксперимент

Это потенциально критично именно для вас.

Laya документация указывает ограничение контекста и возможность `max_len=8192` для multilingual checkpoint, но качество на длинных документах необходимо проверять на собственной выборке. ([GitHub][2])

Поэтому benchmark должен включать:

```text
short document
medium document
long document
```

и:

```text
tokens
prediction
latency
```

Например:

```text
Document        Tokens    Accuracy    Latency
------------------------------------------------
lab_001          430       ✓           32ms
lab_002          980       ✓           38ms
appointment      2100      ?           74ms
discharge        5100      ?           ...
```

---

# 25. Proposed implementation phases

Я бы сделал это в 7 небольших milestones.

### L0 — Classifier abstraction

Сначала:

```text
ClassificationEngine
ClassificationResult
engine selection
```

Перевести текущий rule classifier на этот interface.

**Никакого Laya пока.**

---

### L1 — Laya adapter

Добавить:

```text
classification/laya/
classification/engines/laya.py
```

Сделать:

```text
Laya Router
     ↓
LayaClient
     ↓
LayaClassifier
     ↓
ClassificationResult
```

---

### L2 — Laya classification contract

Зафиксировать:

```text
document_type
probabilities
model
model_version
question_version
latency
```

и mapping:

```text
Laya choice
     ↓
DocumentType enum
```

---

### L3 — Local CLI

Добавить:

```bash
make classify-laya
```

для одного документа.

Затем:

```bash
make eval-classification-laya
```

для fixtures.

---

### L4 — Evaluation

Расширить evaluator:

```text
rule
laya
comparison
```

Получить:

```text
accuracy
precision
recall
F1
confusion matrix
confidence/probability distribution
latency
token length
```

---

### L5 — Shadow mode

Добавить:

```env
CLASSIFICATION_ENGINE=rule
CLASSIFICATION_SHADOW_ENGINE=laya
```

Pipeline:

```text
document
    │
    ├── rule → production result
    │
    └── laya → experimental result
```

Laya **не влияет на canonical generation**.

---

### L6 — Decision

Только после результатов:

```text
Rule 2.1
vs
Laya
```

решать, нужен ли:

```text
Laya as primary
```

или:

```text
Laya as secondary
```

или:

```text
Rule + Laya ensemble
```

или:

```text
fine-tuned Laya
```

---

# 26. Следующий этап — fine-tuning

И вот здесь Laya становится особенно интересным для вашего проекта.

Не стоит сразу пытаться fine-tune.

Сначала:

```text
11 documents
     ↓
zero-shot Laya
     ↓
evaluation
```

Затем, когда накопится:

```text
100+
500+
1000+
```

реальных документов:

```text
real documents
       ↓
verified labels
       ↓
training dataset
       ↓
fine-tuned Laya
       ↓
evaluation
       ↓
calibration
```

Сам Laya проект показывает, что fine-tuning на decision-specific данных может существенно изменить результат относительно базового checkpoint. ([GitHub][2])

---

# 27. Итоговая структура

С учетом **именно вашего текущего `ai-worker`** я бы стремился к такой структуре:

```text
app/
└── classification/
    │
    ├── __init__.py
    ├── models.py
    ├── schemas.py
    ├── exceptions.py
    │
    ├── classifier.py
    ├── service.py
    ├── resolver.py
    ├── normalize.py
    │
    ├── scoring.py
    │
    ├── engines/
    │   ├── __init__.py
    │   ├── base.py
    │   ├── rule_based.py
    │   └── laya.py
    │
    ├── laya/
    │   ├── __init__.py
    │   ├── client.py
    │   ├── config.py
    │   ├── mapper.py
    │   ├── models.py
    │   └── questions.py
    │
    ├── signals/
    │   ├── base.py
    │   ├── laboratory.py
    │   ├── appointment.py
    │   ├── prescription.py
    │   └── generic.py
    │
    ├── artifact.py
    └── evaluate.py
```

А tests:

```text
tests/
└── unit/
    └── classification/
        ├── engines/
        │   ├── test_rule_based.py
        │   └── test_laya.py
        │
        ├── laya/
        │   ├── test_client.py
        │   ├── test_mapper.py
        │   └── test_questions.py
        │
        ├── test_evaluate.py
        └── test_classifier.py
```

И reports:

```text
reports/
└── classification/
    ├── rule/
    ├── laya/
    └── comparisons/
```

## Главное архитектурное решение

Я бы зафиксировал для агента следующее:

> **Laya is an experimental implementation of the existing ClassificationEngine contract. It must not replace, modify, or be embedded into the existing RuleScoringEngine. The first integration must support standalone local inference, evaluation against the existing 11 fixtures, and shadow execution. Laya results must be mapped into the existing classification domain model, while preserving Laya-specific model/version/question/probability metadata for evaluation and provenance. No change to canonical generation or downstream pipeline behavior is allowed until evaluation demonstrates its value.**

Это позволит вам спокойно экспериментировать с Laya, не разрушая уже сделанные **M0 → M3** и не превращая `classification/` в код, жестко завязанный на одну ML-модель.

[1]: https://github.com/NandhaKishorM/laya?utm_source=chatgpt.com "GitHub - NandhaKishorM/laya: Non-autoregressive System 1 decision engine. Typed choice, score and yes/no decisions over any text in a single forward pass, in 100+ languages, with a router that picks the right checkpoint per request. · GitHub"
[2]: https://github.com/NandhaKishorM/laya "GitHub - NandhaKishorM/laya: Non-autoregressive System 1 decision engine. Typed choice, score and yes/no decisions over any text in a single forward pass, in 100+ languages, with a router that picks the right checkpoint per request. · GitHub"
[3]: https://github.com/NandhaKishorM/laya/blob/main/pyproject.toml?utm_source=chatgpt.com "laya/pyproject.toml at main · NandhaKishorM/laya · GitHub"
