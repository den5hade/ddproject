С учётом того, как у тебя сейчас устроен `ai-worker`, я бы **не ставил Laya на основной VPS приложения**. Но и делать отдельный VPS только под Laya прямо сейчас я бы тоже не стал.

### Моя рекомендация

На текущем этапе:

```text
                         ┌─────────────────────┐
                         │   Main App VPS      │
                         │                     │
                         │ FastAPI             │
                         │ PostgreSQL          │
                         │ RabbitMQ            │
                         │ frontend            │
                         └──────────┬──────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │   AI Worker VPS     │
                         │                     │
                         │ ai-worker            │
                         │ ├─ PII Gate         │
                         │ ├─ Classification    │
                         │ │   ├─ Rule          │
                         │ │   └─ Laya          │
                         │ ├─ GenericCanonical │
                         │ ├─ Appointment       │
                         │ └─ LLM client        │
                         │                     │
                         │ Laya model           │
                         └─────────────────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │ Marker GPU VPS      │
                         │                     │
                         │ Marker worker       │
                         │ включается batch-wise│
                         └─────────────────────┘
```

То есть **Laya я бы первоначально запускал там же, где `ai-worker`**, а не вместе с Marker.

Но при этом архитектуру самого `ai-worker` надо сделать так, чтобы Laya можно было безболезненно вынести в отдельный inference service.

---

# Почему не основной VPS

Твой основной VPS должен оставаться максимально предсказуемым:

```text
Web/API
Auth
Organization
Documents
PostgreSQL
RabbitMQ
S3 coordination
```

Laya — ML runtime. Даже если он относительно лёгкий, он добавляет:

* PyTorch;
* transformers;
* model weights;
* CPU/RAM consumption;
* потенциально GPU;
* model loading;
* cache;
* inference latency;
* дополнительные зависимости.

Сам Laya позиционируется как локальный inference engine, поддерживает CPU/GPU и имеет несколько checkpoint'ов; `Router(preload=True)` может загружать их в память заранее. ([GitHub][1])

Поэтому смешивать его с production API VPS я бы не стал.

---

# Почему не Marker VPS

Это ещё важнее.

У тебя Marker имеет совершенно другой lifecycle:

```text
queue grows
      ↓
20+ documents
      ↓
start GPU VPS
      ↓
Marker processes batch
      ↓
queue empty
      ↓
shutdown GPU VPS
```

Laya потенциально будет использоваться **постоянно**, потому что classification происходит практически для каждого документа.

Получится:

```text
Marker:

  ON → process batch → OFF


Laya:

  ON → classification → classification → classification → ...
```

Это два разных workload-а.

Поэтому объединять их только ради того, чтобы сэкономить один VPS, на мой взгляд, преждевременно.

---

# Но есть важный нюанс

Я бы **не делал Laya отдельным microservice прямо сейчас**.

То есть не:

```text
ai-worker
    │
    HTTP
    ▼
laya-service
```

а:

```text
ai-worker
    │
    ▼
classification/
    │
    ├── rule classifier
    │
    └── laya classifier
```

Laya должен быть **одним из implementation backends классификации**, а не частью pipeline напрямую.

---

# Как это должно выглядеть

У тебя уже есть:

```text
app/classification/
├── classifier.py
├── resolver.py
├── service.py
├── scoring.py
├── signals/
│   ├── appointment.py
│   ├── laboratory.py
│   ├── prescription.py
│   └── generic.py
```

Я бы развил это примерно так:

```text
app/
└── classification/
    ├── __init__.py
    │
    ├── models.py
    ├── schemas.py
    ├── exceptions.py
    │
    ├── normalize.py
    │
    ├── classifier.py
    │
    ├── service.py
    ├── resolver.py
    │
    ├── scoring.py
    ├── signals/
    │
    ├── backends/
    │   ├── __init__.py
    │   ├── base.py
    │   ├── rule_based.py
    │   └── laya.py
    │
    ├── policies/
    │   ├── __init__.py
    │   └── production.py
    │
    ├── evaluation/
    │   ├── evaluate.py
    │   ├── metrics.py
    │   └── datasets.py
    │
    └── config.py
```

Главная идея:

```python
class DocumentClassifier(Protocol):

    def classify(
        self,
        document: ClassificationInput,
    ) -> ClassificationResult:
        ...
```

И реализации:

```text
RuleBasedClassifier
        │
        └── ClassificationResult

LayaClassifier
        │
        └── ClassificationResult
```

А pipeline ничего не знает о Laya.

---

# Ещё лучше — сделать Laya optional

Это я бы обязательно сделал.

Например:

```text
CLASSIFIER_BACKEND=rule
```

локально:

```text
CLASSIFIER_BACKEND=laya
```

для экспериментов:

```text
CLASSIFIER_BACKEND=hybrid
```

Это позволит тебе сравнивать:

```text
              same document
                    │
          ┌─────────┴─────────┐
          ▼                   ▼
      Rule 2.1             Laya
          │                   │
          ▼                   ▼
       result              result
          │                   │
          └─────────┬─────────┘
                    ▼
                evaluator
```

И это особенно хорошо соответствует твоему текущему M3/evaluation подходу.

---

# Laya не должен сразу становиться production classifier

Это, пожалуй, самое важное.

Laya сам по себе не является специализированным медицинским классификатором. Документация проекта прямо рекомендует рассматривать поставляемые checkpoints как базу для специализации, а fine-tuning на собственных данных может существенно менять качество. ([GitHub][1])

Поэтому я бы сделал следующий путь:

```text
                    Laya
                      │
                      ▼
              Local experiment
                      │
                      ▼
              Classification eval
                      │
             ┌────────┴────────┐
             │                 │
          Rule 2.1            Laya
             │                 │
             └────────┬────────┘
                      ▼
                  compare
                      │
                      ▼
              real documents
                      │
                      ▼
             collect ground truth
                      │
                      ▼
              fine-tune Laya
                      │
                      ▼
             Laya medical model
```

---

# Почему Laya особенно интересен именно тебе

У тебя classification сейчас имеет примерно такой смысл:

```text
document
   ↓
laboratory?
appointment?
prescription?
generic?
other?
```

Это хороший кандидат для Laya, потому что Laya работает не как генеративная LLM, а как decision engine: `choice`, `score`, `noul`. Результат получается непосредственно как структурированное решение, без генерации текста. ([GitHub][2])

Например, концептуально:

```python
questions = {
    "document_type": {
        "type": "choice",
        "instructions": "What type of medical document is this?",
        "criteria": {
            "laboratory": "...",
            "appointment": "...",
            "prescription": "...",
            "discharge": "...",
            "diagnosis": "...",
            "other": "..."
        }
    }
}
```

И получать:

```json
{
  "document_type": {
    "choice": "laboratory"
  }
}
```

При этом я бы **не переносил текущие thresholds/confidence из твоего rule classifier напрямую в Laya**. В документации Laya отдельно отмечено, что его `confidence` имеет другую семантику и не следует переносить calibration threshold от другой системы. ([GitHub][1])

---

# CPU или GPU?

Вот здесь я бы пока не принимал решение окончательно.

Laya поддерживает CPU и NVIDIA GPU, а multilingual checkpoint рассчитан на 100+ языков. При этом для длинных документов документация предупреждает, что качество заметно зависит от длины входа; заявлен максимум до 8192 токенов, но результаты на более длинном контексте требуют собственной проверки. ([GitHub][1])

Для твоего use case я бы сначала сделал benchmark:

```text
                         100 docs
                            │
                ┌───────────┴───────────┐
                ▼                       ▼
              CPU                     GPU
                │                       │
          latency/doc             latency/doc
          RAM                     VRAM
          throughput              throughput
                │                       │
                └───────────┬───────────┘
                            ▼
                         cost/doc
```

И только после этого выбирать VPS.

Вполне возможно, что для твоего количества документов **CPU будет достаточен**.

---

# Очень важный момент — не отправляй в Laya необработанный PII

У тебя уже есть:

```text
app/pii/
├── detectors.py
├── gate.py
├── models.py
└── policy.py
```

Поэтому я бы поставил flow:

```text
Marker
   │
   ▼
normalized markdown
   │
   ▼
PII Gate
   │
   ▼
classification input
   │
   ├───────────────┐
   ▼               ▼
Rule classifier   Laya
   │               │
   └───────┬───────┘
           ▼
   ClassificationResult
```

А не:

```text
Marker
   │
   ▼
Laya
   │
   ▼
PII
```

Для медицинских документов это особенно важно.

---

# Где я бы физически разместил компоненты

На твоём текущем этапе:

### VPS #1 — Application

```text
Next.js
FastAPI
PostgreSQL
RabbitMQ
```

### VPS #2 — AI Worker

```text
ai-worker

PII
Classification
Laya
GenericCanonical
AppointmentCanonical
LLM client
```

### VPS #3 — Marker

```text
Marker
GPU

ON only when queue > threshold
```

И S3 отдельно:

```text
                 S3
              /      \
             /        \
        Marker       AI Worker
```

---

# А когда Laya вынести отдельно?

Когда появится хотя бы одно из следующих условий:

### 1. Laya начинает конкурировать за RAM/CPU

Например:

```text
ai-worker
   ├── Laya
   ├── embeddings
   ├── canonical
   └── LLM processing
```

и один процесс начинает влиять на latency другого.

### 2. Нужен GPU

Если окажется, что Laya на GPU значительно дешевле/быстрее CPU, тогда:

```text
AI Worker VPS
       │
       │ HTTP/gRPC
       ▼
Laya Inference VPS
       │
       └── GPU
```

### 3. Нужно масштабировать classification отдельно

Например:

```text
100 documents/min
        │
        ▼
   load balancer
    /    |    \
 Laya  Laya  Laya
```

### 4. Появится несколько ML classifiers

Например:

```text
ML Inference VPS

├── Laya
├── embeddings
├── reranker
├── medical NER
└── future models
```

Тогда отдельный inference node уже имеет смысл.

---

# Я бы даже заложил это сейчас

Физически:

```text
ai-worker
     │
     ▼
ClassificationBackend
     │
     ├── RuleBackend
     │
     └── LayaBackend
```

Но интерфейс:

```python
class ClassificationBackend(Protocol):
    ...
```

позволит позже заменить:

```text
LayaBackend
```

на:

```text
RemoteLayaBackend
```

без изменения pipeline.

Сегодня:

```text
ai-worker
    │
    └── LayaBackend
          │
          └── local Laya
```

Позже:

```text
ai-worker
    │
    └── RemoteLayaBackend
             │
             │ HTTP
             ▼
        Laya inference
        separate VPS
```

Это практически идеальный migration path.

---

# И ещё один момент: не загружай все checkpoints без необходимости

У Laya есть несколько checkpoints и `Router`, причём `Router(preload=True)` загружает все три сразу, тогда как lazy loading позволяет не держать всё в памяти. ([GitHub][1])

Для твоего production use case я бы сначала исследовал именно:

```text
laya-multilingual
```

поскольку твои документы могут содержать русский язык.

И отдельно протестировал:

```text
max_len
```

на твоих реальных Markdown-документах.

Не стоит автоматически передавать весь Marker Markdown целиком только потому, что Laya умеет принимать длинный контекст.

---

## Поэтому мой итоговый выбор

**Сейчас:**

```text
                Main VPS
                   │
                   │ RabbitMQ
                   ▼
             AI Worker VPS
                   │
          ┌────────┼────────┐
          │        │        │
         PII    Rule      Laya
          │        │        │
          └────────┼────────┘
                   │
             Canonical
                   │
                   ▼
              PostgreSQL/S3
```

**Marker оставляем отдельно:**

```text
Marker GPU VPS
      │
      │ temporary
      ▼
  process batch
      │
      ▼
    shutdown
```

**Laya пока не выделяем в отдельный VPS.**

Но архитектурно делаем его **сменным backend'ом**, чтобы через несколько месяцев можно было сделать:

```text
AI Worker VPS
      │
      │ RemoteLayaBackend
      ▼
Laya GPU VPS
```

без переделки всего AI pipeline.

И я бы именно так продолжал твой текущий roadmap: **сначала M3 → затем Laya как experimental classifier → evaluation на тех же fixtures → shadow comparison с Classification 2.1 → реальные документы → только после измерений решать, нужен ли отдельный Laya VPS.** Это позволит не оплачивать ещё один сервер до того, как появится доказанная нагрузка или потребность в GPU.

[1]: https://github.com/NandhaKishorM/laya?utm_source=chatgpt.com "GitHub - NandhaKishorM/laya: Non-autoregressive System 1 decision engine. Typed choice, score and yes/no decisions over any text in a single forward pass, in 100+ languages, with a router that picks the right checkpoint per request. · GitHub"
[2]: https://github.com/NandhaKishorM/laya/blob/main/docs/index.md?utm_source=chatgpt.com "laya/docs/index.md at main · NandhaKishorM/laya · GitHub"
