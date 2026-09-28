Да. Если под **Jev** вы имеете в виду TypeSafe Jev — модель для typed decisions/classification, которая возвращает выбор из заранее заданного набора классов и вероятности, — то я бы добавлял её в ваш `ai-worker` **не как замену текущего Classification 2.1.0, а как второй `ClassifierProvider`**. Это хорошо соответствует назначению Jev: classification с фиксированным набором labels и confidence/probabilities. ([Jev by TypeSafe AI][1])

Для вашего проекта это особенно удобно, потому что после M3 у вас уже есть evaluation framework и baseline classifier.

---

# 1. Главная архитектурная идея

Не делать:

```text
ClassificationService
       │
       ├── RuleScoringEngine
       │
       └── Jev
```

и не делать:

```python
if classifier == "jev":
    ...
```

внутри pipeline.

Лучше:

```text
                  ClassificationService
                           │
                    ClassifierProvider
                           │
             ┌─────────────┴──────────────┐
             │                            │
             ▼                            ▼
      RuleBasedClassifier            JevClassifier
          2.1.0                         1.x
             │                            │
             └─────────────┬──────────────┘
                           ▼
                 ClassificationResult
```

Pipeline вообще не должен знать, кто сделал classification.

---

# 2. Новый слой `providers`

Я бы изменил структуру:

```text
apps/ai-worker/app/classification/
│
├── __init__.py
│
├── service.py
├── models.py
├── schemas.py
├── resolver.py
├── exceptions.py
│
├── providers/
│   ├── __init__.py
│   ├── base.py
│   ├── rule_based.py
│   └── jev.py
│
├── signals/
│   ├── ...
│
├── scoring.py
│
├── prompts/
│   └── ...
│
└── evaluation/
    ├── evaluate.py
    ├── compare.py
    └── metrics.py
```

---

# 3. `ClassifierProvider` — основной контракт

Например:

```python
class ClassifierProvider(Protocol):

    @property
    def provider_name(self) -> str:
        ...

    @property
    def model_version(self) -> str:
        ...

    async def classify(
        self,
        document: NormalizedDocument,
        context: ClassificationContext,
    ) -> ClassificationResult:
        ...
```

Но я бы немного изменил `ClassificationResult`, чтобы он был **provider-neutral**.

---

# 4. Unified ClassificationResult

Например:

```json
{
  "type": "laboratory",
  "subtype": "biochemistry",
  "confidence": 0.94,
  "probabilities": {
    "laboratory": 0.94,
    "appointment": 0.03,
    "discharge": 0.01,
    "imaging": 0.01,
    "other": 0.01
  },
  "provider": "jev",
  "model": "typesafe/jev-1.x",
  "classifier_version": "jev-1.0.0"
}
```

Для вашего текущего rule-based classifier:

```json
{
  "type": "laboratory",
  "subtype": "biochemistry",
  "confidence": 0.91,
  "probabilities": {
    "laboratory": 0.91,
    "appointment": 0.04,
    "discharge": 0.02,
    "imaging": 0.01,
    "other": 0.02
  },
  "provider": "rule_based",
  "model": null,
  "classifier_version": "2.1.0"
}
```

Таким образом downstream pipeline вообще не интересует источник результата.

---

# 5. Важный момент: не пытаться заставить Jev повторять вашу текущую scoring logic

Сейчас у вас:

```text
MarkdownNormalizer
      ↓
signals
      ↓
RuleScoringEngine
      ↓
classification
```

Для Jev будет:

```text
MarkdownNormalizer
      ↓
JevClassifier
      ↓
Jev Decision
      ↓
ClassificationResult
```

То есть:

```text
ClassificationService
```

отвечает за **контракт**, а конкретный provider отвечает за **механизм принятия решения**.

---

# 6. Как я бы использовал Jev

Jev поддерживает classification через фиксированный набор вариантов и возвращает выбранный label вместе с probability distribution. ([Jev by TypeSafe AI][1])

Поэтому запрос должен концептуально выглядеть:

```text
Document:

<normalized document>

Classify this medical document into exactly one category.

Categories:

laboratory
appointment
discharge
diagnosis
imaging
prescription
referral
other
```

Но я бы **не отправлял весь marker.md без preprocessing**.

У вас уже есть:

```text
MarkdownNormalizer
```

и его стоит использовать.

Например:

```text
marker.md
   ↓
normalize
   ↓
extract useful text
   ↓
truncate / bound context
   ↓
Jev
```

Это позволит контролировать:

* latency;
* cost;
* input size;
* воспроизводимость.

---

# 7. Но subtype я бы сначала не отдавал Jev

Я бы на первом этапе сделал:

```text
Jev
  ↓
document_type
```

а subtype оставил отдельным этапом.

Например:

```text
Jev
 ↓
laboratory
 ↓
LaboratorySubtypeResolver
 ↓
biochemistry
```

Причина — вы сейчас хотите сравнить **сам classification layer**.

Если сразу сделать:

```text
Jev → type + subtype + confidence + ...
```

вы усложните эксперимент.

Сначала:

```text
document_type
```

Затем можно экспериментировать:

```text
document_type
+
document_subtype
```

---

# 8. Не смешивал бы confidence Jev с вашим confidence

Это очень важно.

У Jev есть собственная probability/confidence semantics. Документация описывает probability distribution и confidence как концентрацию распределения, причём confidence не является гарантией правильности. ([Jev by TypeSafe AI][1])

Поэтому не надо делать:

```python
confidence = normalize_jev_confidence(...)
```

на первом этапе.

Лучше сохранить:

```json
{
  "confidence": 0.94,
  "confidence_source": "jev"
}
```

А для baseline:

```json
{
  "confidence": 0.91,
  "confidence_source": "rule_based"
}
```

И затем M3/M3.5 сравнить их **эмпирически**.

---

# 9. Очень полезно сохранять всю probability distribution

Не только:

```json
{
  "type": "laboratory",
  "confidence": 0.94
}
```

а:

```json
{
  "type": "laboratory",
  "confidence": 0.94,
  "probabilities": {
    "laboratory": 0.94,
    "appointment": 0.03,
    "discharge": 0.01,
    "imaging": 0.01,
    "other": 0.01
  }
}
```

Это даст вам возможность потом исследовать:

```text
confidence
vs
actual correctness
```

и сравнить calibration:

```text
RuleBased
vs
Jev
```

---

# 10. Где хранить API client

Я бы **не помещал TypeSafe API client непосредственно в `classification/jev.py`**.

Лучше:

```text
app/
├── providers/
│   └── typesafe/
│       ├── client.py
│       ├── models.py
│       └── exceptions.py
│
└── classification/
    └── providers/
        └── jev.py
```

Получается:

```text
classification/providers/jev.py
          │
          ▼
providers/typesafe/client.py
          │
          ▼
       TypeSafe
          │
          ▼
         Jev
```

Это позволит позже поменять способ доступа к Jev, например:

```text
direct API
     ↓
AI Gateway
```

без изменения classification provider.

---

# 11. Предлагаемая структура

В итоге я бы сделал так:

```text
apps/ai-worker/app/
│
├── classification/
│   │
│   ├── service.py
│   ├── models.py
│   ├── schemas.py
│   ├── resolver.py
│   ├── exceptions.py
│   │
│   ├── providers/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── rule_based.py
│   │   └── jev.py
│   │
│   ├── evaluation/
│   │   ├── evaluate.py
│   │   ├── compare.py
│   │   └── metrics.py
│   │
│   ├── signals/
│   │   ├── laboratory.py
│   │   ├── appointment.py
│   │   └── ...
│   │
│   └── scoring.py
│
├── providers/
│   │
│   └── typesafe/
│       ├── __init__.py
│       ├── client.py
│       ├── models.py
│       └── exceptions.py
│
└── pipeline/
    └── ...
```

---

# 12. Configuration

Я бы сделал provider configurable:

```env
CLASSIFIER_PROVIDER=rule_based
```

Для локального эксперимента:

```env
CLASSIFIER_PROVIDER=jev
```

Но ещё лучше:

```env
CLASSIFIER_PROVIDER=rule_based
CLASSIFIER_SHADOW_PROVIDER=jev
```

Тогда:

```text
                 marker.md
                     │
             ┌───────┴────────┐
             ▼                ▼
       rule_based             Jev
             │                │
             ▼                ▼
          Result A          Result B
             │                │
             └───────┬────────┘
                     ▼
                  Compare
```

При этом **только `rule_based` управляет production pipeline**.

---

# 13. Shadow mode — я считаю самым полезным вариантом

Для вашей текущей стадии я бы сделал именно:

```text
CLASSIFIER_PROVIDER=rule_based
CLASSIFIER_SHADOW_PROVIDER=jev
```

Результат:

```text
classification/result.json
```

может содержать:

```json
{
  "primary": {
    "provider": "rule_based",
    "version": "2.1.0",
    "type": "laboratory",
    "confidence": 0.91
  },
  "shadow": {
    "provider": "jev",
    "model": "typesafe/jev-...",
    "type": "laboratory",
    "confidence": 0.94
  }
}
```

Но я бы **не смешивал shadow result с canonical classification result**.

Лучше:

```text
classification/
├── result.json
└── experiments/
    └── jev.json
```

или отдельный artifact kind:

```text
classification_experiment
```

---

# 14. Это даст очень хороший эксперимент

После M3:

```text
11 fixtures
    │
    ├────────── RuleBased 2.1.0
    │
    └────────── Jev
```

Получаем:

```text
                     RuleBased       Jev
------------------------------------------------
Accuracy                 X%           Y%
Laboratory F1            X            Y
Appointment F1           X            Y
Other recall             X            Y
False laboratory         X            Y
Ambiguous                X            Y
Avg latency              X            Y
P95 latency              X            Y
Cost/document            X            Y
Confidence calibration   X            Y
```

И вот это будет намного полезнее, чем просто "Jev вроде хорошо классифицирует".

Jev как раз интересен для вашего случая не только качеством, но и тем, что он предназначен для быстрых bounded decisions; текущая документация указывает на фиксированные классы и вероятностный результат. ([Jev by TypeSafe AI][1])

---

# 15. Ещё одна важная архитектурная возможность

Я бы заложил:

```text
ClassifierResolver
```

```python
classifier = resolver.resolve(
    provider="jev"
)
```

Например:

```text
ClassifierResolver
       │
       ├── rule_based
       ├── jev
       ├── legacy
       └── future_llm
```

Но **не делать routing по confidence внутри Resolver на первом этапе**.

Не нужно пока:

```text
if Jev confidence < 0.8:
    call GPT
```

Это следующий эксперимент.

Сначала:

```text
Jev
vs
RuleBased
```

затем:

```text
Jev high confidence
      ↓
continue

Jev low confidence
      ↓
LLM fallback
```

---

# 16. Как это вписывается в ваш общий pipeline

После M3:

```text
                         Marker
                           │
                           ▼
                     Normalization
                           │
                           ▼
                  ClassificationService
                           │
                 ┌─────────┴─────────┐
                 │                   │
                 ▼                   ▼
           RuleBased 2.1.0         Jev
                 │                   │
                 └─────────┬─────────┘
                           │
                    ClassificationResult
                           │
                           ▼
                        PII Gate
                           │
                           ▼
                     Schema Resolver
                           │
             ┌─────────────┼─────────────┐
             ▼             ▼             ▼
          Generic      Appointment   Laboratory
```

И **Jev остаётся заменяемой реализацией classification**, а не превращается в фундамент всего AI-worker.

---

## Я бы добавил отдельный M3.5

С учётом Jev я бы немного скорректировал roadmap:

```text
M0 — Canonical Foundation
 ↓
M1 — Classification Contract
 ↓
M2 — Classification 2.0
 ↓
M3 — Evaluation + Calibration
 ↓
M3.5 — Classifier Provider Abstraction
 ↓
M3.6 — Jev Adapter + Shadow Evaluation
 ↓
M4 — PII Gate
```

Причём **M3.6 не должен менять production classifier**.

Его задача исключительно:

```text
Jev
 ↓
same fixtures
 ↓
same ground truth
 ↓
same metrics
 ↓
comparison with 2.1.0
```

После этого у вас появится объективная база для решения, **какую роль Jev должен играть дальше**: основной classifier, shadow classifier или быстрый first-stage router. Я бы не принимал это решение заранее — его стоит определить по результатам M3.6.

[1]: https://www.jevtypesafeai.com/jev/classifier?utm_source=chatgpt.com "Jev classifier — typed classification without an LLM"
