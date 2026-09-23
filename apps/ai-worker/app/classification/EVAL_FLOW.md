# Classification 2.0 — EVAL_FLOW (оценочный конвейер)

> Как работает оценка классификатора: от фикстур-манифеста до отчёта и
> регрессионных гейтов. Этот документ описывает **процесс** (`evaluate.py`,
> `fixtures.py`, гейты, CLI). Что именно является ground truth и какие находки
> привели к калибровке — в [MANIFEST_AUDIT.md](./MANIFEST_AUDIT.md). Плановая
> часть — в [EVAL_IMPL_PLAN.md](../../../../docs/development/implementation/AI_FLOW%202.0/CLASSIFICATION%202.0/EVAL_IMPL_PLAN.md).

- **Классификатор:** `2.1.0` (детерминированный, rule-based, без LLM).
- **Тестовый набор:** 11 фикстур (7 реальных + 4 синтетических).
- **Результат на датасете:** accuracy 100% (11/11), recall 1.0 по всем типам,
  wrong_schema = 0, false_laboratory = 0, ambiguous = 0.
- **Локальная проверка:** `make eval-classification`; полный набор юнит-тестов
  ai-worker: **174 passed**, ruff чист.

---

## 1. Назначение

EVAL_FLOW — это автономный оффлайн-конвейер оценки детерминированного
классификатора. Он решает три задачи:

1. **Измерять** качество классификации на зафиксированном датасете
   (accuracy / precision / recall / F1, доменные метрики, достоверность).
2. **Фиксировать** поведение классификатора в виде регрессионных гейтов
   (числовых порогов) и не давать регрессиям проходить не замеченными.
3. **Объяснять** каждую калибровку: любое изменение правил обязано ссылаться
   на находку в аудите, а не «я улучшил цифру».

Инварианты (замок):

- **Оффлайн:** `evaluate.py` не трогает S3 / RabbitMQ / БД, не обращается к LLM.
- **Детерминизм:** один `marker.md` + одна версия классификатора → идентичный
  результат (проверяется байт-в-байт повторным прогоном `--json`).
- **Единый источник данных:** и CLI, и тесты читают один и тот же манифест
  через загрузчик из приложения (`fixtures.py`), а не через `tests.*`.

---

## 2. Общая схема потока

```text
tests/fixtures/classification/manifest.json  (ground truth, v1.0.0, 11 записей)
        │  iter_classification_fixtures()  (fixtures.py, app-owned, stdlib-only)
        ▼
Фикстура (markdown + ожидания)
        │
        ▼
MarkdownNormalizer → NormalizedDocument
        │
        ▼
RuleBasedClassificationService (signals → RuleScoringEngine → ClassificationResult)
        │
        ▼
Сравнение: expected vs predicted  (type / subtype / decision)
        │
        ▼
run_evaluation() → list[FixtureEvaluation]
        │
        ├─ compute_metrics()          → per-type TP/FP/FN, P/R/F1, macro/micro, accuracy
        ├─ compute_domain_rates()     → wrong_schema / generic / ambiguous / false_laboratory
        ├─ compute_confidence_stats() → bands, saturation@1.00, reliability
        └─ summarize()                → сводка Phase 9
        │
        ▼
Отображение: render_text (stdout) · render_markdown (--report) · _to_json (--json)
        │
        ▼
Регрессионные гейты (test_regression_dataset.py, test_evaluate.py)
```

Функционально это отдельный слой: классификация ничего не знает об extraction;
оценка ничего не знает о боевом конвейере.

---

## 3. Компоненты

### `fixtures.py` — загрузчик фикстур

- Читает `manifest.json` и разрешает каждый `file` в путь до `.md`.
- Путь по умолчанию: `apps/ai-worker/tests/fixtures/classification/`
  (вычисляется от кода приложения, **не зависит от cwd** — работает и из
  корня репозитория, и в CI).
- Опционально: переменная окружения `CLASSIFICATION_FIXTURES_DIR` — указать
  другой датасет без правок кода.
- Тип: `ClassificationFixture{file, path, source, expected_type,
  expected_subtype, expected_decision}`.
- `tests/support/classification_fixtures.py` — тонкий делегат поверх этого
  загрузчика (единый источник истины).

### `evaluate.py` — ядро оценки и CLI

Ключевые функции (все чистые, где это возможно):

| функция | результат |
|---|---|
| `evaluate_fixture(fixture)` (async) | прогон одной фикстуры через сервис → `FixtureEvaluation` |
| `run_evaluation(fixtures=None)` | оценка всех фикстур: `MarkdownNormalizer → service → сравнение` |
| `summarize(evaluations)` | сводка Phase 9 (документы, accuracy, recall по классам, доменные счётчики) |
| `compute_metrics(evaluations)` | `ClassificationMetrics` (per-type `TypeMetrics` + macro/micro + accuracy) |
| `compute_domain_rates(evaluations)` | `DomainRates`: wrong_schema/generic/ambiguous/false_laboratory (count + rate) |
| `compute_confidence_stats(evaluations)` | bands, `saturated_at_one`, reliability по полосам |
| `render_text(...)` / `render_markdown(...)` | человекочитаемые отчёты |
| `main(argv)` | CLI: `--json`, `--report <path>` |

### Гейты (тесты)

- `tests/unit/classification/test_regression_dataset.py` — пофикстурные
  ассерты + числовые гейты (см. §5).
- `tests/unit/classification/test_evaluate.py` — метрики и CLI: вывод `--json`
  сверяется с эталонными счётчиками ground truth.
- `tests/unit/classification/test_fixture_manifest.py` — валидность манифеста
  (версия, ключи, enum-значения, полнота набора файлов).

### Запуск

```bash
cd apps/ai-worker
uv run python -m app.classification.evaluate            # stdout-сводка
uv run python -m app.classification.evaluate --json     # JSON в stdout
uv run python -m app.classification.evaluate --report reports/eval.md

make eval-classification                                 # из корня репозитория
```

> Примечание: `uv run --project apps/ai-worker python -m ...` из корня
> репозитория **не работает** (`no module named 'app'` — cwd корень не
> попадает в `sys.path`). Поэтому make-цель делает `cd apps/ai-worker`.

---

## 4. Данные: манифест и фикстуры

### Дерево

```text
tests/fixtures/classification/
├── manifest.json
├── laboratory/  (fbbcb675, b8f07559, 27022026, gemotest_1, helix_3, invitro_3)
├── appointment/ (2b8fdd0d, appointment_002)
├── prescription/(prescription_001)
└── other/       (lab_without_keywords_001, generic_001)
```

### Формат записи

```json
{
  "file": "laboratory/fbbcb675.md",
  "source": "real",                    // real | synthetic
  "expected_type": "laboratory",
  "expected_subtype": "hematology",    // null — допустимо
  "expected_decision": "accept"        // accept | fallback | ambiguous
}
```

### Как добавить фикстуру

1. Положить `marker.md` в соответствующую подпапку.
2. Добавить запись в `manifest.json` с человеко-подтверждаемыми ожиданиями.
3. Прогнать `python -m app.classification.evaluate --json` — фикстура появится
   в отчёте.
4. Обновить счётчики ground truth в `test_evaluate.py`
   (`test_cli_json_metrics_match_ground_truth_counts`) и при необходимости —
   числовые гейты.
5. Прогнать юнит-набор (`uv run pytest tests/unit/classification -q`).

> Правило: `expected_*` — это **ground truth**, а не «поведение текущего
> классификатора». Менять ожидание можно только вместе с правилом-изменением
> и задокументированной находкой (см. MANIFEST_AUDIT §Finding → Change).

---

## 5. Метрики и их семантика

### Per-fixture

Для каждой фикстуры сравнивается предсказание с ожиданием по трём осям:
`type`, `subtype` (если `expected_subtype != null`), `decision`. Запись
`FixtureEvaluation` хранит: expected/predicted по осям, флаги совпадения,
`is_correct`, `confidence`, `confidence_level`, `margin`, `top`, `second`,
`per_type` (набранные баллы по типам), сработавшие `signals` (имя, вес,
количество совпадений, score), `classifier_version`.

Вердикт `correct` требует совпадения типа **и** решения; subtype учитывается,
когда манифест объявляет непустой ожидаемый subtype.

### Агрегаты (`compute_metrics`)

- `accuracy` = доля документов, где совпали type **и** decision.
- По каждому типу `TypeMetrics{tp, fp, fn, precision, recall, f1, support}`;
  `tp == support` при идеальном результате.
- `macro` / `micro` — усреднение precision/recall/F1.
- `per_type["laboratory"]["support"]` на текущем датасете = 6 и т.д.

### Доменные метрики (`compute_domain_rates`) — по SUM §29

| метрика | смысл | пример на датасете |
|---|---|---|
| `wrong_schema` | предсказан «чужой» схема-тип (не `other`) | lab → appointment: 0 |
| `generic` | ожидался schema-тип, а предсказан `other` (unexpected generic) | prescription → other: 0 |
| `ambiguous` | предсказанное решение `ambiguous` | 0 |
| `false_laboratory` | ожидался не-laboratory, а предсказан `laboratory` | other → laboratory: 0 |

Каждая — пара `{count, rate}` (счётчик обязателен при N=11). На текущем
датасете все четыре = 0.

### Достоверность (`compute_confidence_stats`)

- Полосы: `0.90-1.00` (HIGH), `0.70-0.90` (MEDIUM), `0.00-0.70` (LOW).
- `saturated_at_one` — число документов с ровно 1.00 (сейчас 6; насыщение
  на однозначных панелях — ожидаемое поведение формулы confidence).
- `reliability` — по каждой непустой полосе: `{correct, total, accuracy}` —
  правильность решений в полосе (сейчас 100% в обеих непустых полосах).

### Сводка Phase 9

```text
Documents: 11

Accuracy:          100.0%
Laboratory recall: 100.0% (6/6)
Appointment recall:100.0% (2/2)

Wrong schema:       0
Generic fallback:   0
Ambiguous:          0
False laboratory:   0
```

---

## 6. Решения и регрессионные гейты

Терминология решений классификатора (не оценки): `FALLBACK` при
`top < SCORE_FLOOR (5.0)` → тип `other`; `AMBIGUOUS` при `margin < 0.25 × top`
(тип сохраняется); иначе `ACCEPT`.

Гейты реализованы **в количестве документов**, а не в процентах, потому что
при N=11 один документ ≈ 9% (процентные цели SUM §30 возобновляются после
~50 реальных маркеров):

| гейт | значение | где проверяется |
|---|---|---|
| recall (type-match) по датасету | ≥ 0.95 (факт 1.0) | `test_regression_dataset.py::test_dataset_not_harder_than_baseline` |
| `wrong_schema` на реальных маркерах | == 0 | `test_count_based_gates_hold_on_dataset` |
| `false_laboratory` по всем фикстурам | == 0 | то же |
| CLI `--json` == эталонные счётчики ground truth | == 0 отклонений | `test_evaluate.py::test_cli_json_metrics_match_ground_truth_counts` |
| `ambiguous` | не гейтится (report-only при N=11) | — |

Реальные лабораторные маркеры, кроме того, обязаны классифицироваться в
`laboratory`/`accept` (`test_real_laboratory_markers_never_misroute`).

Находка F3: `lab_without_keywords_001` — намеренный false-generic зонд
(лабораторная по форме, но без ключевых сигналов) — ожидаемо даёт
`other`/`fallback` и **освобождён** от гейта unexpected-generic.

---

## 7. Детерминизм и воспроизводимость

Оценка полностью детерминирована:

- один и тот же `marker.md` + одна версия `classifier_version` → идентичный
  `ClassificationResult` (method `rule_score`, без LLM и эвристик с
  случайностью);
- повторные прогоны `--json` дают байт-идентичный вывод;
- загрузчик фикстур не зависит от текущей директории.

---

## 8. Версионирование и калибровка (2.1.0)

Классификатор версионируется по M1 §7: `2.0.0` — реализация контракта;
`2.1.0` — калибровка M3, изменившая выход (новое значение subtype); патч —
только документация.

Порядок калибровки («finding → change», зафиксирован в плане):

1. Аудит манифеста (`MANIFEST_AUDIT.md`) → находки F1–F6.
2. Проверка: находка реально проявилась в отчёте? Если нет — изменения нет
   (анти-overfitting: на N=11 главный риск переобучение).
3. Изменение применяется **в связке**: правило + манифест + тесты
   locked-constants + версия → `2.1.0`.
4. Каждая строка изменений = строка «finding → change» в отчёте.

Применено только F2: подтип `microbiology` для Helix-культуры (правило в
`service._laboratory_subtype` со строгим доминированием; манифест
`helix_3`: `null → microbiology`; версия → `2.1.0`). F1/F4/F5 не применялись:
не проявились / ожидаемое поведение.

---

## 9. Ограничения и развитие

- **Маленький датасет (N=11):** гейты в счётчиках; 1 документ ≈ 9%.
  При росте реального набора за ~50 — перекалибровка на большей выборке,
  возврат к процентным гейтам SUM §30, повторный аудит манифеста до любого
  следующего bump-версии.
- **Насыщение confidence 1.00** на однозначных панелях (6/11) — приемлемо;
  пересматривать только если появится свидетельство, что это скрывает
  градацию между «уверенно» и «очень уверенно».
- **Словарь ключевых слов** — базовая линия M2 (по реальным маркерам), дальше
  не переобучался.
- **CI:** набор классификационных тестов (включая гейты) исполняется в
  существующем job `uv run --all-packages pytest apps tests`; отдельный шаг
  не требуется. Локальный `--all-packages` на этой машине упирается в
  отсутствие wheel `torch` для `macosx_x86_64` (CI — linux, не затронут).

## 10. Быстрый старт (чек-лист)

```bash
make eval-classification                                   # отчёт в stdout
cd apps/ai-worker && uv run python -m app.classification.evaluate --json
cd apps/ai-worker && uv run pytest tests/unit/classification -q   # 139 passed
cd apps/ai-worker && uv run pytest tests/unit/pipeline/test_pipeline.py -q  # 9 passed
cd apps/ai-worker && uvx ruff check app/classification
```

Готовый артефакт отчёта: `apps/ai-worker/reports/classification-eval-20260923.md`
(findings → changes → gates → DoD → caveat о масштабировании).