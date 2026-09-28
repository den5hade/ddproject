Да — и здесь ты правильно заметил несогласованность. **Если мы фиксируем тот flow, который мы обсуждали раньше, то я не должен был помещать `PII Gate` перед Classification без дополнительного архитектурного решения.**

Нужно разделить две вещи: **PII Gate как security/privacy boundary** и **classification как определение типа документа**.

### Я бы сейчас зафиксировал flow так

```text
UPLOAD
  │
  ▼
STORAGE
  │
  ▼
SOURCE VALIDATION
  │
  ▼
OCR / MARKER
  │
  ▼
OCR QUALITY CHECK
  │
  ▼
DOCUMENT CLASSIFICATION
  │
  ├── Rule Classifier
  │
  └── Laya Classifier
  │
  ▼
ClassificationResult
  │
  ▼
Classification Resolver
  │
  ├── laboratory
  ├── appointment
  ├── prescription
  ├── discharge
  ├── diagnosis
  ├── generic
  └── review
  │
  ▼
SELECTED CANONICAL SCHEMA
  │
  ▼
LLM EXTRACTION
  │
  ▼
PYDANTIC VALIDATION
  │
  ├── invalid → retry / failed
  │
  ▼
PII / SAFETY GATE
  │
  ▼
SEMANTIC VALIDATION
  │
  ▼
canonical.json
  │
  ├── S3
  ├── DB
  └── structured.md
```

То есть **PII Gate в этом flow находится после extraction**, как ты первоначально описывал.

---

## Тогда где находится Laya?

Именно здесь:

```text
                    DOCUMENT CLASSIFICATION
                              │
                              ▼
                    ClassificationService
                              │
                    ┌─────────┴─────────┐
                    │                   │
                    ▼                   ▼
              RuleClassifier      LayaClassifier
                    │                   │
                    └─────────┬─────────┘
                              ▼
                    ClassificationResult
```

Но есть принципиальный вопрос:

> **Должны ли Rule и Laya одновременно классифицировать каждый документ?**

Мой ответ: **нет, не обязательно.**

Это было слишком упрощённо в предыдущей схеме.

---

# Я бы разделил production и evaluation

### Production

На первом этапе:

```text
Document
   │
   ▼
ClassificationService
   │
   ▼
RuleClassifier 2.1
   │
   ▼
ClassificationResult
```

Laya не влияет на результат.

### Evaluation / Shadow

Параллельно:

```text
                 Document
                    │
          ┌─────────┴─────────┐
          │                   │
          ▼                   ▼
   RuleClassifier           Laya
          │                   │
          ▼                   ▼
       Result A             Result B
          │                   │
          └─────────┬─────────┘
                    ▼
                Evaluator
                    │
                    ▼
              comparison
```

Именно это я бы использовал для твоего текущего этапа.

---

# Почему это лучше

У тебя уже есть:

```text
M0 — Canonical foundation
M1 — Classification contract
M2 — Classification implementation
M3 — Classification evaluation
```

После M3 у тебя появляется **baseline classifier 2.1**.

Поэтому Laya не должен ломать этот baseline.

Правильная последовательность:

```text
                  Classification 2.1
                         │
                         │ production
                         ▼
                      Result
```

и одновременно:

```text
                  Classification 2.1
                         │
                         ├─────────────┐
                         │             │
                         ▼             ▼
                       Rule           Laya
                         │             │
                         └──────┬──────┘
                                ▼
                            Evaluation
```

---

# А если Laya окажется лучше?

Тогда уже можно поменять policy:

```text
CLASSIFIER_BACKEND=rule
```

на:

```text
CLASSIFIER_BACKEND=laya
```

или, например:

```text
CLASSIFIER_BACKEND=hybrid
```

Но это **policy decision**, а не изменение pipeline.

---

# И я бы ещё уточнил роль PII Gate

Здесь есть потенциально важный архитектурный момент.

Если `PII Gate` предназначен для того, чтобы **не выпускать PII за пределы твоего контролируемого окружения**, то его место действительно зависит от того, где работают классификаторы.

Например:

### Если Rule + Laya работают локально

```text
Marker
  ↓
Classification
  ↓
LLM
  ↓
PII Gate
```

может быть вполне нормальным вариантом.

### Если Laya работает на внешнем API

Тогда уже другое:

```text
Marker
  ↓
PII Gate
  ↓
Laya API
```

Потому что privacy boundary проходит **перед отправкой данных наружу**.

Поэтому нельзя сказать, что `PII Gate` всегда должен находиться до или после classification. Это определяется **trust boundary конкретного deployment**.

---

# Для твоей текущей архитектуры

Если:

* Marker — твой VPS;
* `ai-worker` — твой VPS;
* Laya — локальная библиотека внутри `ai-worker`;
* Rule classifier — локальный;
* LLM — отдельно рассматриваемый компонент;

я бы зафиксировал:

```text
Marker
   │
   ▼
Normalized Markdown
   │
   ▼
OCR Quality
   │
   ▼
Classification
   │
   ├── Rule 2.1
   └── Laya (shadow/evaluation)
   │
   ▼
ClassificationResult
   │
   ▼
Schema Resolver
   │
   ▼
LLM Extraction
   │
   ▼
Pydantic Validation
   │
   ▼
PII / Safety Gate
   │
   ▼
Semantic Validation
   │
   ▼
Canonical
```

И **это я бы считал основной версией flow на текущем этапе**.

---

## Главное

Моя предыдущая схема:

```text
Marker
 ↓
PII Gate
 ↓
Rule + Laya
 ↓
ClassificationResult
```

была слишком категоричной.

**Для твоего текущего deployment я бы её не фиксировал.**

Я бы зафиксировал:

```text
                DOCUMENT
                    │
                    ▼
              CLASSIFICATION
                    │
          ┌─────────┴─────────┐
          ▼                   ▼
       Rule 2.1             Laya
      production           shadow
          │                   │
          ▼                   ▼
       result             evaluation
          │
          ▼
       resolver
          │
          ▼
    canonical schema
          │
          ▼
      LLM extraction
          │
          ▼
      PII / Safety
          │
          ▼
       canonical
```

Это также означает, что **Laya сейчас вообще не требует изменения основного data flow**. Мы добавляем его как альтернативный classifier backend и evaluation path. Это намного безопаснее для уже реализованных M0–M3.
