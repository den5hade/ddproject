# PII Gate — архитектура и целевая реализация

**Документ:** архитектурный референс PII Gate.
**Статус:** M4 (контракт) завершён · M5 (обвязка) не начат.
**Смежные документы:** [IMPL_PLAN.md](./IMPL_PLAN.md) (план M4, семь фаз, все `[x]`) · [IMPL_RPRT.md](./IMPL_RPRT.md) (отчёт о реализации) · [ORDER.md](../ORDER.md).

## Статус документа

Документ заменяет прежний `SUM.md`. Нумерация разделов §1–§38 и фаз Phase 1–10
**сохранена намеренно**: на конкретные секции ссылаются докстринги в
`app/pii/*.py` и `tests/support/pii_imports.py`. Смена номеров сделала бы
существующие ссылки ложными, поэтому новые архитектурные разделы добавлены
после §38, а не вклинены внутрь.

Прошлая версия `SUM.md` писалась как проектное предложение и к моменту
завершения M4 разошлась с кодом. Что исправлено в этом документе:

| Расхождение | Было в `SUM.md` | Стало |
| --- | --- | --- |
| Число категорий | 21 перечисление, 22 в тексте | 23 значения, 6 групп (§3) |
| `TICKET_NUMBER`, `SECRET` | отсутствуют | добавлены, первое — из реального evidence (§3) |
| `PIIFinding.value` | `str \| None` | `str`, `Field(exclude=True)` (§5) |
| `PIIFinding` | переносимая модель | in-process only, не wire-контракт (§5) |
| Оценка риска | внутри detection | policy-конфигурация (§12) |
| `PIICategory` | 5 групп | 5 групп + `secret` (§3) |
| `PIIContext` | свободный набор полей | `PIIPolicyContext`, destination + redaction (§18) |
| Хранилище | новые колонки в `document_processing` | только artifact + frontmatter-блок, без БД (§20, §21) |
| API | `POST /internal/.../pii-scan` | доменный компонент в процессе, HTTP не нужен (§27) |
| Audit | `PII_SCAN_COMPLETED` и др. | словарь `pii.*` (§22) |
| Фазы | 10 фаз, ни одна не начата | 10 фаз → 7 фаз плана, все `[x]` как контракт (§28) |
| Статус | предложение | M4 = контракт без обвязки (§2.1) |

Существенные утверждения этого документа помечены статусом:

```text
[M4]  реализовано в контракте, код есть, поведения нет
[M5]  целевое состояние, кода нет
[LOCKED] решение зафиксировано, менять только новым решением
```

## Карта документа

```text
§1      Цель этапа
§2      Главное архитектурное решение          §2.1 текущее состояние · §2.2 detect ≠ policy
§3–§4   Таксономия: что считать PII            23 значения, 6 групп
§5–§6   PII Finding и граница, которую он не пересекает
§7–§11  Источники обнаружения                  pattern · structured · ner · llm · canonical
§12–§13 Риск и решение                         policy-данные, не вывод детектора
§14–§16 Неприкосновенность оригинала, redacted artifact, destination
§17–§18 policy-driven                          evaluate(findings, context)
§19–§22 Result, хранение, БД, audit            что пересекает границу и куда
§23–§24 Встраивание в pipeline                 общий контур решения
§25–§27 Organization, user access, API         что сознательно не делаем
§28–§33 План и фазы                            10 фаз → 7 фаз плана, статус
§34–§35 False positives / false negatives
§36–§37 Security requirements · ≠ compliance
§38     Итоговый pipeline проекта
§39     Что не следует делать в этом этапе
§40     Приоритеты
§41     Vertical slice
§42     Тестовая стратегия
§43     Definition of Done
§44     Главный архитектурный результат
§45     Итоговая последовательность реализации
```

---

# 1. Цель этапа

**PII Gate** — контролирующий слой между получением текста документа и его
дальнейшей передачей в AI/extraction pipeline.

Его задача не в том, чтобы удалить персональные данные из медицинской карты.
Медицинский документ без идентификаторов пациента часто вообще теряет смысл.

Главная задача:

> определить, какие персональные и чувствительные данные присутствуют в
> документе, насколько уверенно они обнаружены, и **разрешено ли** передавать
> этот artifact на следующий этап обработки.

Целевой контур:

```text
PDF / JPEG
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
    ├── Classification 2.0
    │
    └── PII Gate
            │
            ▼
      Policy decision
            │
   ┌────────┼────────┐
   ▼        ▼        ▼
 ALLOW    REVIEW    BLOCK
   │        │        │
   ▼        ▼        ▼
Extraction  Queue   halt
   │
   ▼
canonical.json
```

Три наблюдения, которые определяют весь дизайн:

* PII в медицинском документе — это **ожидаемая** находка, а не инцидент.
* Решение о продолжении обработки принимает **policy**, а не детектор.
* Ни одно сырое PII-значение не пересекает границу сериализации (§6).

---

# 2. Главное архитектурное решение

## 2.1. Текущее состояние, от которого начинаем

**M4 реализовал контракт целиком и не реализовал ни одного вызова.**

```text
apps/ai-worker/app/pii/     13 модулей, 2328 строк
├── models.py                таксономия и boundary-модели
├── schemas.py               JSON-схемы для внешних потребителей
├── detectors.py             PIIDetector + 4 реализации-заглушки
├── aggregation.py           PIIAggregator
├── masking.py               HMAC-SHA256 fingerprint + маскирование
├── redaction.py             PIIRedactor + PlaceholderRedactor
├── policy.py                23 правила, PIIDestination, PolicyEngine
├── gate.py                  PIIGate, DECISION_OUTCOMES
├── canonical_guard.py       пост-extraction сторож + walk_string_leaves
├── persistence.py           контракт artifact / frontmatter / audit
├── fixtures.py              загрузчик regression dataset
├── exceptions.py            PIIDecisionError
└── README.md                документация модуля, 726 строк
```

Что работает:

```text
таксономия из 23 категорий          [M4]
таблица риска и действий             [M4]
модели с запретом сырых значений     [M4]
маскирование и HMAC-fingerprint      [M4]
контракт persistence / audit         [M4]
regression dataset (3 synthetic)     [M4]
262 теста PII, 436 тестов приложения [M4]
```

Чего нет:

```text
PIIDetectorBase.detect            → NotImplementedError
PIIAggregatorBase.aggregate       → NotImplementedError
PolicyEngineBase.evaluate         → NotImplementedError
RedactorBase.redact               → NotImplementedError
CanonicalPIIInspectorBase.inspect → NotImplementedError
PIIGateBase.inspect               → NotImplementedError

app/pipeline не импортирует app.pii вообще
```

Шесть заглушек поднимают исключение **из метода работы, а не из
`__init__`**. Это deliberate: pipeline M5 должен иметь возможность собрать
цепочку целиком и убедиться, что незавершённый gate падает громко. Заглушка,
возвращающая пустой `ALLOW`, была бы самой опасной в репозитории — pipeline
выглядел бы здоровым, и каждый документ проходил бы.

`DETECTOR_VERSION = "1.0.0"` и `PII_POLICY_VERSION = "1.0.0"` при полном
отсутствии детекторов — это версии **контракта**, а не алгоритмов. Они
предопределены, чтобы M5 не менял версию при первом же запуске.

## 2.2. Detection и policy — разные контракты

Два вопроса, которые нельзя смешивать:

### PII detection

> Какие персональные данные есть в документе?

```json
{
  "category": "person_name",
  "masked_value": "И***** И***** И*********",
  "confidence": 0.97,
  "source": "pattern",
  "detector": "email_phone_passport"
}
```

### PII policy

> Можно ли с этим документом продолжать обработку?

```text
ALLOW
REVIEW
BLOCK
```

Это **разные задачи с разными владельцами**. Детектор отвечает за
извлечение и ничего не решает. Policy отвечает за решение и ничего не
извлекает.

Недопустимо:

```python
if pii_found:
    block()
```

Потому что в вашем случае наличие PII **ожидаемо**. Медицинская карта без
ФИО, даты рождения и номера карты теряет смысл. Gate, который блокирует по
факту наличия PII, заблокирует весь domain.

Отсюда следствие, которое определяет таблицу в §12: `PIICategory` не несёт ни
риска, ни действия. Это taxonomy detection, а не policy. Связь между ними
живёт в одном месте — `DEFAULT_POLICY` в `policy.py`.

[LOCKED] Ни один модуль детекции не импортирует `app.pii.policy`, и ни один
модуль policy не импортирует детектор. Связь строится в `gate.py`.

---

# 3. Что считать PII

Таксономия разделена на группы с самого начала, потому что группа определяет
политику по умолчанию.

```text
identity      PERSON_NAME DATE_OF_BIRTH AGE GENDER NATIONALITY
contact       EMAIL PHONE ADDRESS
government    PASSPORT NATIONAL_ID INSURANCE_NUMBER SNILS INN
medical_id    PATIENT_ID MEDICAL_RECORD_NUMBER LAB_ORDER_ID ENCOUNTER_ID TICKET_NUMBER
practitioner  DOCTOR_NAME DOCTOR_LICENSE ORGANIZATION_NAME ORGANIZATION_ID
secret        SECRET
```

Итого **23 значения в 6 группах** [M4]. Порядок объявления — это порядок
декларации, и именно его выдаёт `PIICategory.model_json_schema()`.

Два решения, которых не было в исходной редакции:

`TICKET_NUMBER` добавлен из **реального evidence**, а не из симметрии:

```text
2b8fdd0d…/marker.md → «Номер талона: 2026030709303211960141»
```

Категория, которую никто не предусмотрел, встретилась в реальном прогоне
pipeline. Это лучшее доказательство, что таксономия должна расширяться
наблюдением, а не спекуляцией.

`SECRET` — единственная категория с действием `BLOCK` в таблице по
умолчанию, и единственная с риском `critical`:

```text
API key
password
private key
```

Обнаружение credentials — это уже не медицинский PII, а инцидент
безопасности (§13).

Новое значение категории — это **minor** событие контракта и обязано
сопровождаться двумя вещами: строкой в `DEFAULT_POLICY` и правилом в таблице
маскирования. Иначе категория унаследует ни действия, ни маски.

## 3.1. Почему practitioner и organization — не PII пациента

Отдельная группа, и это не косметика:

```text
medical organization
```

и

```text
patient PII
```

— разные вещи. Название клиники само по себе обычно не является
идентификатором пациента.

Будущий `AppointmentCanonical` нуждается в данных врача и организации, то
есть в `DOCTOR_NAME` и `ORGANIZATION_NAME`. Если бы они лежали в одной
группе с `PERSON_NAME`, то политика внешнего LLM, которая должна маскировать
пациента, замаскировала бы ещё и выдавшего клинику. Это типичная ошибка
избыточной редакции, которая ломает полезность документа.

Практическое следствие: `REDACT_ON_EXTERNAL` (18 категорий, §16) состоит из
групп `identity`, `contact`, `government` и `medical_id` и **не содержит**
ни одной категории `practitioner`.

---

# 4. Medical data — отдельная категория

Называть всё это просто `PII` неточно. `PERSON` и `MEDICAL` — не одно и то
же:

```text
«Иванов Иван»
```

и

```text
«диагноз: сахарный диабет»
```

имеют совершенно разную семантику. Для будущего audit- и policy-слоя это
существенно: медицинский факт о пациенте чувствительнее, чем его имя, но он
не является идентификатором, и его нельзя ни обнаружить, ни отредактировать
по правилам идентификаторов.

Правильная рамка:

```text
Sensitive Data
├── PERSONAL
├── MEDICAL
├── IDENTIFIER
├── CONTACT
└── ORGANIZATION
```

Таксономия `PIICategory` (§3) намеренно покрывает только те сущности,
которые **можно детектировать в тексте**. Диагноз, лабораторный результат и
анамнез в неё не входят: они появляются в `canonical.json` после
extraction, и их чувствительность обеспечивается контролями доступа к
canonical, а не детектором PII.

Это не упущение, а разделение ответственности: PII Gate отвечает за
идентификаторы, extraction-контур — за клиническое содержимое.

---

# 5. PII Finding

Основной объект — `PIIFinding` в `models.py`.

```text
category (PIICategory)
value (str)                 ← Field(exclude=True): не сериализуется, не логируется
masked_value (str)          ← обязателен; строится mask_pii_value()
value_fingerprint (str)     ← обязателен; salted HMAC через hash_pii_value(); не логируется
confidence (float 0–1)      ← диапазон задокументирован, валидатора нет
source (PIISource) · detector (str) · detector_version (str)
start (int|None) · end (int|None) · metadata (dict)
```

Модель `frozen=True`, `extra="forbid"` [M4].

Три решения, которые отличают её от исходного эскиза:

**`value` обязателен, а не `str | None`.** Finding не может существовать без
текста, который его обосновал: redaction нужен реальный подстрока в процессе.
Альтернатива превращала бы «нет сырого значения» в дисциплину вызова, а не в
контроль.

**Finding — только in-process, это не wire-контракт.** Через границу
переходит исключительно `PIIFindingSummary` (§6). `value` и
`value_fingerprint` объявлены `Field(exclude=True)`, поэтому
`model_dump()` физически не может их выдать — не по забывчивости, а по
определению поля.

Две ловушки для поздних фаз, зафиксированные в докстринге:

```text
model_json_schema() по-прежнему перечисляет value и value_fingerprint
```

`exclude` — это забота сериализации, а не схемы. Поэтому `PIIFinding` нельзя
использовать как источник JSON-схемы или artifact. Phase 2 экспортирует
`PIIFindingSummary` именно поэтому.

```text
metadata — dict, поэтому frozen-модель фактически не хешируема
```

Поэтому агрегатор (Phase 3 плана) дедуплицирует по кортежу
`(category, value_fingerprint)`, а не по самой модели. Это не оптимизация,
а единственный корректный вариант.

---

# 6. PII не пересекает границу

Это самый важный security requirement этапа, и в M4 он обеспечен
структурно, а не соглашением.

Плохо:

```text
PII detected:
name=Иванов Иван Иванович
phone=+79991234567
```

Хорошо:

```text
PII detected:
category=person_name
confidence=0.97
document_id=...
```

Если значение необходимо для отладки — только замаскированное:

```text
И***** И***** И*********
+7******4567
```

## 6.1. Три инварианта, выраженные в типах

```text
1. Сырое значение не пересекает границу
   PIIFinding.value            Field(exclude=True)
   PIIFinding.value_fingerprint Field(exclude=True)
   PIIFindingSummary           полей value нет вообще
   PIIScanResult                полей value нет вообще
   PIIAuditRecord              полей value нет вообще
   CanonicalPIIViolation        полей value нет вообще

2. Fingerprint — солёный HMAC-SHA256
   генерируется masking.hash_pii_value(secret, value)
   никогда не логируется, не попадает в frontmatter и в event
   существует только внутри процесса

3. Gate — документная capability
   models.py не импортирует app.classification и packages.canonical
   тип документа передаётся в policy обычной строкой
```

Третий инвариант существует не ради чистоты. `PIIMeta` (M5) будет жить в
`packages/canonical`, а gate — в `app/pii`. Если бы `models.py` импортировал
тип canonical, зависимость стала бы циклической и доменный контракт перестал
бы быть переносимым.

`PIIFindingSummary` — единственная форма, которой finding может пересечь
границу:

```text
category · masked_value · confidence · source · detector · start · end
```

`start`/`end` опциональны, потому что находка от structured-field или от
canonical-guard может не иметь текстовых смещений.

---

# 7. Источники обнаружения

Gate строится не на одном детекторе, а на абстракции с несколькими
реализациями.

```python
class PIIDetector(Protocol):
    def detect(
        self,
        document: NormalizedDocument,
    ) -> list[PIIFinding]:
        ...
```

Реализации [M4]:

```text
PatternPIIDetector          §8
StructuredFieldPIIDetector  §9
SecretPIIDetector           §11, credentials
CompositePIIDetector        агрегирует несколько источников
```

Реализации NER и LLM (§10, §11) объявлены как целевые, кода нет.

Источники (`PIISource`) — пять значений [M4]:

```text
pattern           regex по тексту
structured_field  документная разметка: «Пациент:»
ner               модель именованных сущностей
llm               LLM-fallback
canonical         пост-extraction сторож (§14, план Phase 6)
```

`canonical` существует по конкретной причине: он позволяет в сохранённом
результате отличить находку сторожа от находки сканирования исходного
документа. Без него post-extraction leak был бы неотличим от обычного
события.

## 7.1. Один NormalizedDocument на оба контура

Критично, и это отдельное решение: **не делать второй parser `marker.md`**.

```text
Marker
  ↓
NormalizedDocument
  ├── Classification
  └── PII Gate
```

Тип импортируется **type-only**. `app.pii` не владеет разбором документа и не
зависит от Marker. Если завтра источником станет не PDF, а API или FHIR, gate
получит тот же `NormalizedDocument` без изменений в своём коде.

---

# 8. Detector №1 — regex/pattern

Для хорошо определённых сущностей:

```text
EMAIL
PHONE
SNILS
INN
passport patterns
medical record IDs
```

Это:

* быстро;
* дёшево;
* детерминированно;
* легко тестируется.

Детерминированность здесь не оптимизация, а требование §36: один и тот же
документ при одной версии детектора обязан давать один и тот же результат.
Воспроизводимость audit-решения целиком опирается на этот пункт.

Порядок реализации: pattern первым, потому что он даёт самый дешёвый
работающий baseline и самый предсказуемый набор находок для настройки
порогов уверенности.

---

# 9. Detector №2 — structured fields

Если Marker или extraction уже выделил:

```text
Patient:
Date of birth:
Phone:
Email:
```

то это гораздо более сильный сигнал, чем сырой текст.

```text
Patient: Иванов Иван Иванович
```

Здесь не нужно пытаться распознать имя исключительно NLP-моделью. Разметка
 документа — это уже ground truth.

Практическое следствие: `structured_field` должен давать находку без
`start`/`end`, если смещения недоступны. Именно поэтому эти поля опциональны
в `PIIFindingSummary` (§6).

---

# 10. Detector №3 — NER

Для:

```text
PERSON
LOCATION
ORGANIZATION
```

можно использовать NER.

Но NER не должен быть первым implementation requirement. Для первой версии:

```text
regex
+
document structure
+
known labels
```

проще контролировать. NER добавляется вторым уровнем, когда измерение
recall покажет конкретный класс пропусков, а не в общем случае.

Обоснование против «просто добавить NER сразу»: NER — вероятностный
компонент, а детектор PII обязан быть воспроизводимым (§36). Добавление
вероятностного слоя до того, как детерминированные слои закрыли известные
классы, увеличивает число настраиваемых порогов раньше, чем появляется
baseline для сравнения.

---

# 11. Detector №4 — LLM

LLM тоже не должен быть primary detector:

```text
regex
   ↓
structured extraction
   ↓
NER
   ↓
LLM fallback
```

LLM полезен для сложных случаев:

```text
«пациент ранее наблюдался у доктора Петрова...»
```

но не должен быть единственным механизмом защиты.

LLM-fallback несёт отдельный риск: модель, вызванная для классификации
чувствительного текста, не должна получать этот текст раньше, чем сработала
политика. Отсюда порядок §24: LLM-детектор включается только на
`PIIDestination.EXTERNAL_LLM` и только если policy разрешил.

`SecretPIIDetector` (реализация есть [M4]) не использует LLM: credentials
обнаруживаются детерминированными паттернами. Это осознанно — security
решение не должно зависеть от вероятностной модели.

---

# 12. PII Risk Level

Лестница риска — четыре уровня [M4]:

```text
LOW
MEDIUM
HIGH
CRITICAL
```

Распределение по 23 категориям в текущей таблице [M4]:

| Риск | Количество | Примеры |
| --- | --- | --- |
| `critical` | 1 | `SECRET` |
| `high` | 10 | `PASSPORT`, `MEDICAL_RECORD_NUMBER`, `TICKET_NUMBER` |
| `medium` | 6 | `PHONE`, `PERSON_NAME`, `DATE_OF_BIRTH` |
| `low` | 6 | `EMAIL`, `NATIONALITY`, `ORGANIZATION_ID` |

Но это **policy configuration**, а не абсолютная классификация. Риск
присваивается политикой таблице `DEFAULT_POLICY`, а не детектором.

Это разделение принципиально. Если бы детектор присваивал риск, то смена
политики потребовала бы перевыпуска всех находок и версии детектора, а
исторические решения перестали бы объясниться текущей таблицей. Сейчас при
изменении `DEFAULT_POLICY` меняется `PII_POLICY_VERSION`, и все решения,
принятые по старой версии, остаются интерпретируемыми.

`PIIRiskLevel` не пишется в finding. Он появляется в `PIIScanResult` и
`PIIAuditRecord` как результат policy.

---

# 13. PII Gate Decision

Самое важное — результат Gate.

```python
class PIIDecision(str, Enum):
    ALLOW = "allow"
    ALLOW_WITH_WARNING = "allow_with_warning"
    REVIEW = "review"
    BLOCK = "block"
```

[LOCKED] `PIIDecision` следует словарю IMPL_ARCH §13, а не эскизу
`{"status": "allowed"}` из `ORDER.md` §2. Расхождение зафиксировано в плане
(§7): словарь IMPL_ARCH побеждает, потому что `ALLOW_WITH_WARNING` и `REVIEW`
невыразимы в форме `status`.

### Обычная медицинская карта

```json
{
  "decision": "allow_with_warning",
  "risk_level": "high",
  "findings_count": 7
}
```

Наличие `person_name`, `date_of_birth`, `medical_record_number` — это
норма. На `internal_llm` (§16) это `ALLOW_WITH_WARNING`: документ
обрабатывается, факт обнаружения фиксируется.

### Подозрительный документ

Обнаружен паспорт плюс несколько неожиданных идентификаторов, и
destination — внешний LLM:

```json
{
  "decision": "review",
  "reasons": ["high_risk_patient_categories_at_external_destination"]
}
```

### Security violation

Документ содержит credentials:

```json
{
  "decision": "block",
  "risk_level": "critical",
  "reasons": ["secret_detected"]
}
```

Это уже не обычный medical PII, а инцидент безопасности.

## 13.1. Известное ограничение: REVIEW на дефолтном destination

Следует прямо зафиксировать, потому что это выглядит как баг, но является
следствием запертой таблицы.

При `destination = INTERNAL_LLM` (дефолт, §16) таблица даёт только:

```text
22 категории → allow
1 категория  → block   (SECRET)
```

Ни одна комбинация не даёт `REVIEW`. Следовательно:

```text
REVIEW достижим на internal_llm
    ← только через unknown destination
    ← или через redaction_unavailable при REDACT-категории

REVIEW на internal_llm по комбинации категорий
    ← требует явного правила, решение за M5/M6
```

Комбинационный порог («паспорт + несколько неожиданных идентификаторов»)
не реализован и не должен быть введён молча: он меняет судьбу
обрабатываемых документов. Это предмет отдельного решения, а не деталь
реализации.

## 13.2. Fail closed

`PIIDecisionError` поднимается, когда решение получить **невозможно**.
Дефолта в `ALLOW` не существует.

```text
неизвестная категория в находке      → PIIDecisionError
отсутствует секрет для HMAC         → PIIDecisionError
destination вне допустимого набора  → PIIDecisionError
```

Обоснование: `ALLOW` по умолчанию при неопределённости — это режим отказа,
при котором уязвимость обнаруживается на стороне пользователя, а не в логах.
Цена ложного срабатывания (один документ ушёл на ручную проверку) несопоставима
с ценой отказа (PII ушёл во внешний сервис молча).

---

# 14. PII Gate не должен модифицировать оригинальный документ

Оригинал неизменяем:

```text
original.pdf     immutable
marker.md         immutable
```

Gate создаёт отдельный metadata-artifact:

```text
pii_result.json
```

но не перезаписывает оригинал. `marker.md` и upload остаются нетронутыми.

## 14.1. Post-extraction canonical guard

Второй контур проверки — после того как extraction собрал
`canonical.json`. Обнаруженные там находки получают
`source = canonical` и `stage = canonical`.

Реальные утечки этого контура [M4, зафиксировано как evidence]:

```text
2b8fdd0d…/canonical.json → fields.note: «…для пациента Шадеркина Дениса…»
fbbcb675…/canonical.json → fields.note: «…для пациента Шадеркина Дениса…»
```

Оба — одна и та же утечка фамилии в свободном текстовом поле. Она
проходит через source gate незамеченной, потому что `fields.note` не является
извлекаемым полем схемы.

Механика обхода [M4] — `walk_string_leaves`, рекурсивный обход всех строковых
листьев структуры. Он не привязан к схеме, поэтому покрывает и `fields.note`,
и любое другое текстовое поле, добавленное позже.

Соответствие решений в `DECISION_REMEDIATION` [M4]:

```text
BLOCK / REVIEW   → halt, документ не принимается
ALLOW_WITH_WARNING → продолжать, canonical принимается, факт фиксируется
ALLOW            → продолжать
```

---

# 15. Отдельный redacted artifact

Обезличенная версия — отдельный artifact:

```text
marker.md
   │
   ▼
PII Gate
   │
   ├── pii_result.json
   │
   └── redacted.md
```

Например:

```text
Иванов Иван Иванович
```

↓

```text
[PATIENT_NAME]
```

Это **должно быть отдельным artifact**. Оригинал не заменяется никогда (§14).

`PIIRedactor` и `PlaceholderRedactor` объявлены [M4], `redact` поднимает
`NotImplementedError` [M5].

Ограничение, которое нельзя пропустить: `redacted.md` **не является
основанием для пропуска source gate**. Redaction и детекция — разные
операции. Если redactor не покрыл категорию, gate всё равно должен был её
найти. Порядок в §24: detect → aggregate → policy → act.

---

# 16. Trusted и External LLM — это destination

Два режима работы:

### Trusted LLM

Модель в контролируемом окружении:

```text
marker.md
   ↓
LLM
```

PII обнаруживается, но не обязательно редактируется.

### External LLM

Внешний API:

```text
marker.md
   ↓
PII Gate
   ↓
redaction
   ↓
external LLM
```

Это позволяет менять LLM-провайдера без переписывания document pipeline:
изменение — это смена значения `PIIDestination`, а не кода.

[LOCKED] Текущий провайдер внешний, но доверенный по имени
(`ai_base_url = https://foundation-models.api.cloud.ru/v1`), поэтому
`INTERNAL_LLM` — запертый дефолт. Сегодня pre-extraction redaction не
выполняется.

`PIIDestination` — четыре значения [M4]:

```text
INTERNAL_LLM   internal_llm
EXTERNAL_LLM   external_llm
PERSISTENCE    persistence
UNKNOWN        unknown
```

`UNKNOWN` — **не синоним `INTERNAL_LLM`**. Неизвестный destination fail
closed (§13.2). Это различие важно: молчаливый дефолт в trusted-режим при
неизвестном направлении — это ровно тот класс дефекта, который приводит к
утечке.

Policy — это данные. Переключение на `EXTERNAL_LLM` меняет таблицу
поведения, а не код.

`REDACT_ON_EXTERNAL` — 18 категорий [M4]:

```text
identity + contact + government + medical_id
```

Группы `practitioner` и `secret` в него не входят, и это deliberate (§3.1).

---

# 17. PII Gate должен быть policy-driven

Не делать:

```python
if pii_found:
    block()
```

Вместо этого:

```python
policy.evaluate(
    findings=findings,
    context=context,
)
```

Контекст может включать:

```text
source
organization
document_type
processing_environment
llm_provider
user_consent
```

Пример поведения:

```text
organization A + internal processing        → allow
external LLM                                 → redact
unknown destination                           → review
```

[LOCKED] Решение выводится из данных. `DEFAULT_POLICY` — это `PIIPolicy`
с 23 правилами, а не код с ветвлениями [M4]. Добавление категории, изменение
риска или смена действия не требуют изменения кода — только новой строки в
таблице и новой `PII_POLICY_VERSION`.

Практическое следствие: policy не должен зависеть от detection. Обратная
зависимость допустима только в `gate.py`, который и строит цепочку.

---

# 18. Context для Policy

Заложен `PIIPolicyContext` [M4] — не свободный набор полей, а конкретная
модель.

```text
destination          PIIDestination   ← обязателен
redaction_available  bool             ← обязателен
document_type        str | None       ← обычная строка, не canonical-тип
```

`destination` и `redaction_available` — **валидируемые входные данные
конструктора**, а не значения в `ProcessingContext.attributes`. Причина:
ошибка в destination не должна быть обнаружима только в момент, когда PII
уже уйдёт. Валидация на границе делает неверную конфигурацию
невозможной до начала обработки.

`redaction_available` существует по той же причине, что и `destination`:
категория с действием `REDACT` на destination, где redaction невозможна, не
должна молча превращаться в `ALLOW`. Это путь в `REVIEW` (§13.1).

Не обязательно заполнять все поля сразу, но API расширяем: добавление
`organization` и `user_consent` не должно быть breaking change.

---

# 19. PII Result

Форма результата:

```json
{
  "decision": "allow_with_warning",
  "risk_level": "high",
  "stage": "document",
  "destination": "internal_llm",
  "findings": [
    {
      "category": "person_name",
      "masked_value": "И***** И***** И*********",
      "confidence": 0.97,
      "source": "pattern",
      "detector": "email_phone_passport",
      "start": 12,
      "end": 31
    }
  ],
  "findings_count": 7,
  "category_counts": {
    "person_name": 1,
    "date_of_birth": 1,
    "medical_record_number": 1
  },
  "detector_version": "1.0.0",
  "policy_version": "1.0.0",
  "processed_at": "2026-09-21T10:00:00Z"
}
```

Ключевое: **`value` не сохраняется в aggregate result**. Полный
`PIIFinding` существует только в процессе, а пересечь границу может лишь
`PIIFindingSummary` (§6).

`PIIScanResult` [M4] — это и есть persisted-проекция. Отдельна от
`PIIDecisionResult`, внутреннего выхода policy: `PIIDecisionResult` несёт
per-category карту действий, которую `PIIScanResult` отбрасывает. M5 может
действовать по `REDACT`, не выводя его заново из decision.

`decision` — действие с наивысшим приоритетом:

```text
BLOCK > REVIEW > ALLOW_WITH_WARNING > ALLOW
```

`findings_count` обязан равняться `len(findings)`, `processed_at` —
timezone-aware. Оба — документированные инварианты, по соглашению того же
типа, что у `confidence`.

---

# 20. Где хранить PII Result

```text
documents/
    {document_id}/
        original/
            source.pdf

        marker/
            document.md

        pii/
            pii_result.json          ← PII_ARTIFACT_FILENAME

        classification/
            result.json

        canonical/
            canonical.json

        structured/
            document.md
```

`PII_ARTIFACT_FILENAME = "pii_result.json"` [M4]. Имя зафиксировано
константой, а не строкой в коде загрузки, потому что его читает
`fixtures.py` и M5-обвязка.

Плюс metadata-блок `"pii"` в frontmatter и в `data` события (§22), плюс
audit. Три представления одного решения, ни одно из которых не содержит
сырых значений.

[LOCKED] Ни один из этих путей не является новой таблицей БД и не требует
миграции.

---

# 21. Database

В M4 и M5 **новая таблица и новые колонки не создаются**.

Это изменение относительно ранней редакции документа, где предлагались
`pii_status`, `pii_risk_level`, `pii_detector_version`, `pii_policy_version`
в `document_processing`. Решение заменено:

```text
pii_result.json         ← object storage
frontmatter блок "pii"   ← существующий frontmatter
data события            ← существующее событие
```

Обоснование: метаданные PII — это производная величина от конкретного
прогона, а не независимая сущность. Колонки в `document_processing` означали
бы, что источник истины раздвоен: строчка в БД и файл в S3 могут
разойтись, и аудит перестанет отвечать на вопрос «какое решение было принято
для этого документа».

Если понадобится поиск:

> показать все документы, где был обнаружен `passport`

— тогда добавляется отдельная таблица. Это отдельное проектное решение с
отдельной миграцией, а не следствие текущего этапа. Индексирование по
наличию категории — это уже query layer, а не gate.

---

# 22. Audit

Gate пишет audit record на каждое решение. Словарь [M4]:

```text
pii.scan.completed      ALLOW, ALLOW_WITH_WARNING
pii.review.required     REVIEW
pii.blocked             BLOCK
pii.redacted            аддитивно, при фактической редакции
```

`pii.redacted` — аддитивное событие: оно не меняет словарь решений, а
фиксирует факт, что редакция выполнена и в исходном виде произошло
`ALLOW_WITH_WARNING` (§13).

```text
DECISION_AUDIT_EVENTS = {
  "allow":             "pii.scan.completed",
  "allow_with_warning":"pii.scan.completed",
  "review":            "pii.review.required",
  "block":             "pii.blocked",
}
```

`PIIAuditRecord` [M4] несёт:

```text
event · document_id · stage · decision · risk_level
findings_count · detector_version · policy_version · occurred_at
```

Ни значений, ни fingerprint, ни внутренностей детектора. Запись доказывает
**что решение было принято**, но никогда — **что было найдено**.

`stage` в записи позволяет отличить решение source-gate от решения
canonical-guard, не сохраняя находок.

---

# 23. Интеграция с Classification 2.0

Порядок контуров:

```text
Marker
   │
   ▼
NormalizedDocument
   │
   ├── Classification 2.0
   │        │
   └── PII Gate
            │
            ▼
      общий decision
```

Почему PII не обязательно раньше Classification: classification тоже
работает с потенциально чувствительным содержимым, но подача классификатора
на вход — отдельный вопрос, не закрытый этим gate.

Целевой вариант — параллельный:

```text
Marker
   │
   ├───────────────┐
   ▼               ▼
Classification   PII Gate
   │               │
   └───────┬───────┘
           ▼
     Policy Engine
           │
           ▼
      Extraction
```

Для масштабируемой системы предпочтителен второй вариант: классификация и
детекция независимы, и решение принимается после обоих.

[M5] Точная точка вызова в pipeline — `pipeline.py:147`, после
классификации. Это решение зафиксировано в плане §4.9, а не выбирается
заново при реализации.

---

# 24. Более правильная архитектура

```text
                       marker.md
                           │
              ┌────────────┴────────────┐
              │                         │
              ▼                         ▼
        Classification               PII Gate
              │                    detect
              │                    aggregate
              │                    policy
              │                         │
              └────────────┬────────────┘
                           ▼
                     PIIDecision
                           │
               ┌───────────┼───────────┐
               ▼           ▼           ▼
             ALLOW    ALLOW_WITH_     REVIEW / BLOCK
               │        WARNING         │
               ▼           ▼           ▼
          Extraction   Extraction    halt
               │
               ▼
         canonical.json
               │
               ▼
      canonical guard (§14.1)
```

Внутри gate порядок [LOCKED]:

```text
detect → aggregate → policy → decide
```

`detect` не знает о policy, `aggregate` не знает о destination, `policy` не
знает о детекторах. Решение собирается только в `gate.py`, и именно там
`PIIDecisionResult` проецируется в `PIIScanResult` — единственное место, где
внутренний выход policy становится безопасным для сериализации.

---

# 25. PII Gate и Organization

Модель `Organization` может нести собственную политику:

```text
Organization
      │
      └── ProcessingPolicy
```

В будущем организация сможет иметь:

```text
external_llm_allowed = false
redaction_required   = true
```

или:

```text
external_llm_allowed = true
```

На текущем этапе это future extension. `PIIPolicyContext` (§18) расширяем
именно так, чтобы появление organization-specific policy не потребовало
изменения сигнатуры.

Важно: policy конкретной организации должна **сужать** таблицу по умолчанию,
а не расширять её. Организация, запрещающая внешний LLM, обязана иметь
возможность получить более строгий результат, но не менее строгий.

---

# 26. PII Gate и user access

Очень важно: **результат PII-детекции не должен автоматически становиться
доступным specialist или client через обычный API**.

Пользователь должен видеть:

```text
document
classification
analysis
```

но не:

```text
raw PII findings
detector internals
policy decisions
```

PII metadata — это security/internal artifact.

Практическое следствие, зафиксированное как решение: в M5 **не добавляется
ни один API-поверхностный слой и ни одно событие** для этого. Наличие
persisted-артефакта не означает наличия способа его прочитать извне.

---

# 27. API

Внутренний API не нужен.

Ранняя редакция предлагала:

```http
POST /internal/documents/{document_id}/pii-scan
```

Решение: **сначала обычный доменный компонент в процессе.**

```python
result = await pii_gate.inspect(document, context)
```

Обоснование: pipeline работает в одном worker-процессе. HTTP-эндпоинт
 добавил бы сериализацию, сетевой сбой и второй источник истины, не дав
ничего, кроме уже существующей асинхронной точки вызова.

Отдельный сервис имеет смысл только при существенной нагрузке, и это
отдельное проектное решение.

---

# 28. План разработки

M4 реализовал контракт за **7 фаз плана**, которые покрывают **10
проектных фаз** этого документа. Соответствие:

| Фаза этого документа | Фаза плана | Статус |
| --- | --- | --- |
| §28 Phase 1 — Domain contract | Phase 1 — Domain contract | `[x]` |
| §28 Phase 2 — NormalizedDocument | Phase 2 — Schemas | `[x]` |
| §28 Phase 3 — Pattern detectors | Phase 3 — Detector contract | `[x]` |
| §28 Phase 4 — Structured detectors | Phase 3 + Phase 4 | `[x]` |
| §28 Phase 5 — PII aggregation | Phase 3 + Phase 4 | `[x]` |
| §29 Phase 6 — Policy Engine | Phase 5 — Policy + gate contract | `[x]` |
| §30 Phase 7 — Redaction | Phase 4 — Masking & redaction contract | `[x]` |
| §31 Phase 8 — Persistence | Phase 7 — Persistence, provenance & versioning | `[x]` |
| §32 Phase 9 — Audit | Phase 7 | `[x]` |
| §33 Phase 10 — Tests | все фазы | `[x]` |

Расхождение нумерации историческое: план сознательно укрупнил
проектные фазы до семи, Phase 6 плана — canonical-guard, которого в
изначальном списке не было. Ссылки на «Phase N» в `app/pii/*.py` указывают
на фазу **плана**; ссылки на «Phase N» этого документа — на
проектную. Обе системы живы, поэтому таблица выше обязательна для чтения
кода.

## Phase 1 — Domain contract

```text
PIICategory · PIISource · PIIRiskLevel · PIIAction
PIIDecision · PIIDestination · PIIScanStage
PIIFinding · PIIFindingSummary · PIIScanResult
PIIAuditRecord · PIIDecisionResult
```

Создано [M4]. Число категорий исправлено 22 → 23 в Phase 1: список
удерживал 23 элемента, ошибка была в тексте.

## Phase 2 — NormalizedDocument

Используется то же normalized representation, что и для Classification 2.0.
Не делать второй parser `marker.md` (§7.1).

Тип импортируется type-only: `app.pii` не владеет разбором документа.

## Phase 3 — Pattern detectors

```text
EMAIL
PHONE
DATE_OF_BIRTH
SNILS
INN
PASSPORT
```

с учётом целевой юрисдикции.

Контракт `PIIDetector` и четыре реализации-заглушки созданы [M4];
`detect` поднимает `NotImplementedError` [M5].

## Phase 4 — Structured detectors

```text
Patient:
Пациент:
ФИО:
Дата рождения:
№ медицинской карты:
```

и аналогичные document labels.

`StructuredFieldPIIDetector` создан [M4].

## Phase 5 — PII aggregation

```text
findings
  ↓
deduplication
  ↓
confidence
  ↓
risk
```

Один телефон, найденный тремя детекторами:

```text
regex
structured field
NER
```

должен стать одной находкой.

[LOCKED] Ключ дедупликации — `(category, value_fingerprint)`, а не модель:
`metadata` — `dict`, поэтому frozen-модель не хешируема (§5).

`PIIAggregator.aggregate` поднимает `NotImplementedError` [M5].

---

# 29. Фаза 6 — Policy Engine

```python
decision = policy.evaluate(
    findings=findings,
    context=context,
)
```

`DEFAULT_POLICY` [M4] — 23 правила, версия `1.0.0`:

```text
expected medical PII        → allow
high-risk at external dest  → review
secrets/credentials         → block
```

Распределение: 22 категории `allow`, 1 категория `block` (`SECRET`).
Риск: 1 critical, 10 high, 6 medium, 6 low (§12).

Действия (`PIIAction`): `allow` · `warn` · `redact` · `review` · `block`.
Значения `redact` и `review` присутствуют в enum как policy-конфигурация, но
в текущей таблице не назначены ни одной категории — они включаются решением
M5/M6 (§13.1).

`PolicyEngineBase.evaluate` поднимает `NotImplementedError` [M5].

---

# 30. Фаза 7 — Redaction

Реализуется абстракция:

```python
redact(document, findings)
```

и artifact:

```text
redacted.md
```

Redaction не обязана входить в основной pipeline сразу, но
`redaction_available` обязан быть известен policy (§18) — иначе категория с
действием `redact` на недоступном destination превратится в молчаливый
`allow`.

`PIIRedactor` и `PlaceholderRedactor` созданы [M4], `redact` поднимает
`NotImplementedError` [M5].

---

# 31. Фаза 8 — Persistence

Контракт persistence создан [M4] в `persistence.py`. Фиксирует:

```text
PII_META_BLOCK_KEY        = "pii"
PII_ARTIFACT_FILENAME     = "pii_result.json"
PII_META_REQUIRED_KEYS    = 9 ключей
PII_META_OPTIONAL_KEYS    = ("reasons", "warnings")
PII_POLICY_VERSION        = "1.0.0"
DETECTOR_VERSION          = "1.0.0"
```

Обязательные ключи блока:

```text
categories · category_counts · decision · destination
detector_version · findings_count · policy_version · risk_level · stage
```

Опциональные:

```text
reasons · warnings
```

Обратите внимание: `reasons` и `warnings` опциональны, потому что это
диагностика, а не часть решения. Но если `decision != ALLOW`, ожидается
непустой `reasons` — иначе решение невозможно объяснить постфактум. Это
проверяется тестом контракта.

[M5] Обвязка хранилища: в `packages/storage` добавляется
`MARKDOWN_KIND_PII` и пара `"pii": "pii_result.json"`, в
`app/pii/artifact.py` — `build_pii_artifact(...)` по образцу
`app/classification/artifact.py`. Artifact загружается **до** публикации
события — инвариант порядка из M2 Phase 4.

---

# 32. Фаза 9 — Audit

События:

```text
pii.scan.completed
pii.review.required
pii.blocked
pii.redacted          (аддитивно)
```

Никаких сырых PII-значений в audit (§22). Словарь и соответствие
решений зафиксированы в контракте [M4].

[M5] Фактическая запись — в обвязке pipeline, а не в `app.pii`: пакет
остаётся независимым от инфраструктуры и не импортирует event bus.

---

# 33. Фаза 10 — Tests

Минимальный dataset:

```text
tests/fixtures/pii/
├── manifest.json
├── clean/
├── patient/
└── malicious/
```

Создано в M4 [M4]: три **синтетических** fixture, покрывающих три исхода —
`allow`, `review`, `block`. Это максимальный разброс решений, достижимый без
настоящего marker-а.

```text
clean/generic-notice-01.md          нет находок          → allow, low
patient/synthetic-consultation-01.md 7 категорий         → review, high
malicious/synthetic-injection-01.md  secret + injection  → block, critical
```

Реальные копии документов намеренно **не** скопированы: это создало бы
вторую копию того самой утечки, для предотвращения которой milestone и
существует. Настоящий marker добавляется в M5.

`expected_*` в M4 — декларация ground truth, которую некому проверить при
отсутствии детекторов; это спецификация для подтверждения в M5.

`expected_decision` зависит от контекста: категория пациента даёт
`ALLOW_WITH_WARNING` на внутреннем destination и `REVIEW` на внешнем (§16).
Записи manifest фиксируют предполагаемый контекст в поле `notes`.

Тесты:

```text
test_email_detection
test_phone_detection
test_patient_name_detection
test_birth_date_detection
test_medical_record_id_detection

test_duplicate_findings
test_confidence
test_risk_level

test_allow_policy
test_review_policy
test_block_policy

test_no_pii_in_logs
test_no_pii_in_audit
```

---

# 34. False positives — отдельная задача

Для медицинских документов это критично.

Например:

```text
«Москва»
```

может быть:

* адресом пациента;
* адресом клиники;
* местом рождения;
* просто словом в тексте.

Поэтому детектор должен возвращать:

```text
category
confidence
source
```

а не только:

```text
Москва → location
```

`source` здесь — не метаданные, а способ отличить находку из текста от
находки из document label: у них разная надёжность и разные пороги.

Практическое замечание: `PIICategory` не содержит дату как отдельную
категорию. `DATE_OF_BIRTH` — да, а «дата обслуживания» — нет, и это
осознанно: сервисная дата не является PII пациента. Наивное
извлечение всех дат даёт основную массу ложных срабатываний на
медицинских документах.

---

# 35. False negatives

Ещё важнее.

Например:

```text
Пациент: И.И. Иванов
```

NER может не распознать это как имя.

Поэтому комбинация:

```text
structured labels
+
patterns
+
NER
```

лучше единственной модели.

Подтверждено реальным evidence этого проекта: утечка в `fields.note`
(§14.1) — это false negative, который прошёл через source gate, потому что
`fields.note` не является извлекаемым полем. Реакция на такие находки —
не улучшение regex, а отдельный контур проверки post-extraction.

Это и есть причина, по которой gate имеет два контура, а не один.

---

# 36. Security requirements

## PII Gate MUST

* не менять original artifact (§14);
* не писать PII в application logs (§6);
* не писать PII в audit logs (§22);
* не передавать PII в telemetry (§6);
* version detectors (`DETECTOR_VERSION`);
* version policies (`PII_POLICY_VERSION`);
* сохранять decision (§22);
* иметь deterministic detectors (§8);
* поддерживать redaction (§15);
* иметь regression dataset (§33).

## PII Gate SHOULD

* поддерживать несколько detector types (§7);
* поддерживать organization-specific policies (§25);
* иметь evaluation metrics (§42);
* поддерживать повторный scan после изменения detector version.

Четыре MUST, обеспеченные типами, а не соглашением: неизменяемость
оригинала, запрет PII в логах и audit, детерминированность и версионирование
проверяются тестами контракта, а не ревью. Остальные обеспечиваются
структурой моделей (§6.1).

---

# 37. PII Gate ≠ compliance

Это стоит зафиксировать отдельно, потому что наличие gate часто ошибочно
читают как «данные теперь защищены по закону».

PII Gate — технический механизм:

```text
detect
aggregate
policy
redact
audit
```

Он сам по себе не означает:

```text
GDPR compliant
HIPAA compliant
152-ФЗ compliant
```

Compliance зависит ещё от:

* хранения;
* доступа;
* retention;
* consent;
* encryption;
* data residency;
* processor agreements;
* deletion;
* backups;
* audit;
* incident response.

Поэтому PII Gate следует рассматривать как **один из
security/privacy controls**, а не как compliance layer целиком.

Конкретные пробелы, которые gate не закрывает и которые не должен создавать
впечатления закрытых: сроки хранения, право на удаление, согласие
пациента, размещение данных, шифрование на уровне S3 и БД, работа с
резервными копиями. Ни один из них не входит в периметр этого этапа.

---

# 38. Итоговый pipeline проекта

```text
                     Upload
                        │
                        ▼
                  Object Storage
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
           ┌────────────┴────────────┐
           │                         │
           ▼                         ▼
      Classification              PII Gate
           │                    detect
           │                    aggregate
           │                    policy
           │                         │
           └────────────┬────────────┘
                        ▼
                  PIIDecision
                        │
           ┌────────────┼────────────┐
           ▼            ▼            ▼
         ALLOW   ALLOW_WITH_     REVIEW / BLOCK
           │        WARNING          │
           ▼            ▼            ▼
    Schema Resolver  Extraction     halt
           │            │
           └──────┬─────┘
                  ▼
         canonical.json
                  │
                  ▼
        canonical guard (§14.1)
                  │
                  ▼
         Structured Markdown
                  │
                  ▼
    Analytics / Search / Vectorization
```

PII Gate реализуется **до LLM Extraction**, но не как отдельный
микросервис (§27).

Структура пакета:

```text
ai-worker/
├── classification/
├── pii/
│   ├── models.py
│   ├── schemas.py
│   ├── detectors.py
│   ├── aggregation.py
│   ├── masking.py
│   ├── redaction.py
│   ├── policy.py
│   ├── gate.py
│   ├── canonical_guard.py
│   ├── persistence.py
│   ├── fixtures.py
│   └── exceptions.py
├── extraction/
├── schemas/
└── processing/
```

Граница ответственности, ради которой структура и выбрана:

```text
Marker          → получение текста
Classification  → тип документа
PII Gate        → privacy/security decision
Extraction      → получение canonical structure
```

---

# 39. Что не следует делать в этом этапе

```text
Не создавать отдельный микросервис PII (§27)

Не создавать таблицу PII findings в БД (§21)

Не добавлять HTTP-эндпоинт сканирования (§27)

Не отдавать PII metadata через API specialist/client (§26)

Не делать NER или LLM первым детектором (§10, §11)

Не добавлять категорию в PIICategory без строки в DEFAULT_POLICY
    и без правила в таблице маскирования (§3)

Не полагаться на PIIGate-заглушку, возвращающую пустой ALLOW (§2.1)

Не переносить значение или fingerprint в summary, artifact, event
    или frontmatter (§6)

Не переписывать marker.md или original.pdf (§14)

Не вводить комбинационный порог для REVIEW молча (§13.1)

Не добавлять PII в order документа раньше, чем gate вынес решение
```

---

# 40. Приоритеты

## P0 — обязательно (M5)

```text
Реализовать пять заглушек:
  PIIDetector.detect
  PIIAggregator.aggregate
  PolicyEngine.evaluate
  PIIRedactor.redact
  CanonicalPIIInspector.inspect

HMAC-секрет в Settings (сегодня его нет)

PIIPolicyContext: destination + redaction_available
    через валидируемый конструктор

PIIMeta + FrontmatterMeta.pii + build_frontmatter_meta(pii=)

app/pii/artifact.py + build_pii_artifact

packages/storage: MARKDOWN_KIND_PII + "pii": "pii_result.json"

Обвязка pipeline:
  PIIGate в __init__
  inspect после классификации
  canonical guard после build_canonical
  frontmatter + event data

Настоящий marker в regression dataset
    и подтверждение expected_*
```

## P1 — следующий слой

```text
Комбинационный порог для REVIEW (§13.1)

Redaction в основном pipeline для EXTERNAL_LLM

Evaluation metrics поверх regression dataset

NER-детектор после baseline

Повторный scan при смене DETECTOR_VERSION

Organization-specific policy (§25)
```

## P2 — после стастабилизации

```text
Таблица PII findings и поиск по категориям (§21)

LLM-fallback детектор (§11)

Redaction через внешний LLM для не-детерминированных находок

Rate/размер fingerprint-пространства: не хранить бесконечный
    набор fingerprint ради дедупликации
```

---

# 41. Рекомендуемый первый vertical slice

Не стоит сначала реализовывать все детекторы, потом policy, потом
persistence. Лучше реализовать вертикально.

### Vertical Slice #1

```text
pattern-детектор для одного класса
    ↓
PIIAggregator
    ↓
PolicyEngine на internal_llm
    ↓
PIIGate.inspect
    ↓
pii_result.json в S3
    ↓
факт в frontmatter
    ↓
паспорт документа: allow_with_warning
```

Один класс, один destination, один исход. Этот срез доказывает всю цепочку
включая persistence, не требуя ни NER, ни redaction, ни внешнего LLM.

### Vertical Slice #2

```text
source gate на internal_llm
    ↓
extraction
    ↓
build_canonical
    ↓
canonical guard
    ↓
fields.note с утечкой → REVIEW
```

Второй срез доказывает второй контур на реальном evidence §14.1.

### Vertical Slice #3

```text
destination = external_llm
    ↓
REDACT-категории
    ↓
PlaceholderRedactor
    ↓
redacted.md
    ↓
pii.redacted
```

Третий срез вводит redaction и аддитивное audit-событие.

---

# 42. Тестовая стратегия

Для этого этапа тестирование должно быть значительно серьёзнее обычного
CRUD: модуль принимает решения о допуске документов.

## Unit

Существует [M4] — 262 теста:

| Файл | Тестов | Что покрывает |
| --- | --- | --- |
| `test_policy_gate.py` | 71 | таблица риска, действия, decision, destination, `DECISION_OUTCOMES` |
| `test_masking_redaction.py` | 37 | HMAC, маскирование, placeholder, `Field(exclude=True)` |
| `test_persistence_contract.py` | 33 | блок `pii`, 9+2 ключа, artifact, audit-словарь, версии |
| `test_canonical_guard.py` | 33 | `walk_string_leaves`, `DECISION_REMEDIATION`, evidence-пути |
| `test_fixture_manifest.py` | 32 | 3 fixture, manifest-схема, `expected_*` |
| `test_models.py` | 23 | 23 категории, границы моделей, инварианты |
| `test_detectors.py` | 20 | контракт детекторов, заглушки, источники |
| `test_schemas.py` | 13 | JSON-схемы, отсутствие `value` в схеме |

## Integration

```text
NormalizedDocument → Detection
Findings → Aggregation → dedup
DecisionResult → ScanResult projection
PolicyContext → PolicyEngine → Decision
Guard violation → Remediation
ScanResult → pii_result.json
ScanResult → frontmatter "pii"
Decision → audit event
```

## Security

Обязательно:

```text
value отсутствует в model_dump() PIIFinding
value отсутствует в PIIFindingSummary
value_fingerprint отсутствует в model_dump() PIIFinding
value отсутствует во всех JSON-схемах
значения нет ни в одном audit-поле
fingerprint не попадает в frontmatter и event
PIIFinding не сериализуется как schema

BLOCK при secret на любом destination
ALLOW_WITH_WARNING на patient-категориях при internal_llm
REVIEW при high-risk на external_llm
unknown destination → не ALLOW
отсутствие секрета → PIIDecisionError, не ALLOW

новая категория без строки в DEFAULT_POLICY
новая категория без правила маскирования
```

## E2E

Минимальный сценарий M5:

```text
Документ с ФИО и номером карты
  ↓
Marker
  ↓
PII gate на internal_llm
  ↓
ALLOW_WITH_WARNING
  ↓
Extraction
  ↓
canonical guard
  ↓
canonical принят
  ↓
pii_result.json загружен
  ↓
факт в frontmatter и в audit
```

Второй сценарий:

```text
Документ с secret
  ↓
PII gate
  ↓
BLOCK
  ↓
canonical не принимается
  ↓
pii.blocked в audit
```

---

# 43. Что считать Definition of Done

Этап нельзя считать завершённым потому, что:

```text
app/pii/ существует
```

Контракт существует, поведения нет (§2.1).

## M4 — контракт (завершён)

* [x] `PIICategory` — 23 значения, 6 групп
* [x] supporting enums
* [x] `PIIFinding` in-process only
* [x] `PIIFindingSummary` — boundary-safe
* [x] `PIIScanResult`, `PIIDecisionResult`
* [x] `PIIAuditRecord` без значений
* [x] `DEFAULT_POLICY` — 23 правила
* [x] `REDACT_ON_EXTERNAL` — 18 категорий
* [x] masking + HMAC
* [x] persistence-контракт: 9+2 ключа, artifact, audit
* [x] regression dataset
* [x] 262 теста PII
* [x] нет импорта `app.pii` в pipeline

## M5 — gate (не начат)

* [ ] `PIIDetector.detect` реализован
* [ ] дедупликация по `(category, value_fingerprint)`
* [ ] `PolicyEngine.evaluate` реализован
* [ ] `PIIRedactor.redact` реализован
* [ ] `CanonicalPIIInspector.inspect` реализован
* [ ] `PIIGate.inspect` реализован
* [ ] HMAC-секрет в `Settings`
* [ ] `PIIPolicyContext` валидируется на границе
* [ ] `PIIMeta` в `packages/canonical`
* [ ] `build_pii_artifact` + `MARKDOWN_KIND_PII`
* [ ] `PIIGate` constructed в `pipeline.__init__`
* [ ] `inspect` вызывается после классификации
* [ ] guard вызывается после `build_canonical`
* [ ] artifact загружен **до** публикации события
* [ ] `pii` в frontmatter и в event `data`
* [ ] настоящий marker в dataset, `expected_*` подтверждены
* [ ] ни одно сырое значение не покидает процесс

---

# 44. Главный архитектурный результат

После M4 платформа перестаёт быть системой, в которой PII-контроля нет, и
становится системой, в которой этот контроль **спроектирован и зафиксирован
контрактом**:

```text
                     ┌── Classification
                     │   (тип документа)
                     │
   marker.md ────────┼── PII Gate
                     │   (privacy/security decision)
                     │
                     ▼
                PIIDecision
                     │
        ┌────────────┼────────────┐
        ▼            ▼            ▼
      ALLOW   ALLOW_WITH_     REVIEW / BLOCK
                            (M5)
```

Конкретный результат состоит в том, что безопасность документа
перестаёт быть свойством конкретного вызова и становится контрактом:

```text
политика — данные, а не код (§17)
решение — версионировано и объяснимо (§22, §36)
сырое значение структурно не может покинуть процесс (§6)
решение воспроизводимо: detector_version + policy_version (§12)
проверка не зависит от наличия детектора: тесты контракта (§42)
```

Это позволяет проектировать M5, не меняя ни одного типа, и менять
детекторы, не меняя ни одного решения, принятого ранее.

---

# 45. Итоговая последовательность реализации

Рекомендуемый порядок M5:

```text
01. HMAC-секрет в Settings
        ↓
02. destination + redaction_available в PIIPolicyContext
        ↓
03. PIIDetector.detect (pattern, один класс)   ← Vertical Slice #1
        ↓
04. PIIAggregator.aggregate (dedup по fingerprint)
        ↓
05. PolicyEngine.evaluate
        ↓
06. PIIGate.inspect
        ↓
07. pii_result.json + MARKDOWN_KIND_PII
        ↓
08. frontmatter "pii" + event data
        ↓
09. PIIMeta в packages/canonical
        ↓
10. PIIGate в pipeline.__init__
        ↓
11. inspect после классификации                  ← контур 1 работает
        ↓
12. PIIRedactor.redact
        ↓
13. настоящий marker + expected_* в dataset
        ↓
14. PIIDetector: structured, secret
        ↓
15. CanonicalPIIInspector.inspect                ← Vertical Slice #2
        ↓
16. guard после build_canonical                  ← контур 2 работает
        ↓
17. redaction для EXTERNAL_LLM                   ← Vertical Slice #3
        ↓
18. NER-детектор                                 ← P1
        ↓
19. комбинационный порог для REVIEW             ← P1
```

Порядок неслучаен. Секрет идёт первым, потому что без него нельзя
вычислить fingerprint, а без fingerprint нельзя дедуплицировать (§5).
`PIIPolicyContext` идёт до policy, потому что решение, зависящее от
направления, должно получать направление до вычисления, а не после (§18).
`PIIMeta` идёт после появления `pii_result.json`, потому что metadata
описывает уже существующий артефакт, а не создаёт его.

Второй контур (§14.1) включается позже первого сознательно: он защищает
уже существующий выход, тогда как первый определяет, появится ли этот
выход вообще. Оба контура обязательны до M6 — в реальном прогоне уже
обнаружена утечка, которую только второй контур и ловит (§35).

Именно такой порядок я считаю оптимальным для текущей стадии проекта: сначала
закрыть **исполняемый gate на одном вертикальном срезе**, затем
подключить второй контур контроля, и только после этого расширять
классификацию находок и редакцию.
