# ai-worker: Upload → Extract Flow

This document captures the end-to-end document processing flow implemented by
the ai-worker, together with the **decisions** we made along the way to make it
actually work in development and in the containerized setup.

Scope: see also the account-api/objectstorage-worker half of the flow. This
document focuses on the ai-worker and the loading `packages/canonical`
(`pdf-canonical`) package it drives.

---

## 1. Big picture

```
user upload ─▶ account-api ─▶ MQ ─▶ objectstorage-worker ─▶ S3 (original.<ext>)
                                                             │
        account-api (PROCESSING, document.uploaded)   ◀────── event (document.stored)
                                                             │
        ai-worker handle_converting ─▶ marker.md (S3)  ◀────── event (document.uploaded)
                                                             │
        account-api ◀────── event (document.converted) ◀───── ai-worker
                                                             │
        ai-worker handle_structuring ─▶ canonical.json + structured.md (S3)
                                                             │
        account-api (COMPLETED + persist extraction) ◀────── event (document.analysis.completed)
```

Artifacts stored on S3 (per document version):

| kind | filename | producer |
| --- | --- | --- |
| `unstructured` | `marker.md` | ai-worker `handle_converting` |
| `canonical` | `canonical.json` | ai-worker `handle_structuring` |
| `structured` | `structured.md` | ai-worker `handle_structuring` |

---

## 2. Event wiring

- ai-worker subscribes on queue `document.convert` with routing keys
  `document.uploaded, document.converted` (`Settings.ai_worker_queue`,
  `Settings.ai_worker_routing_keys`, `app/main.py`).
- Two handlers in `app/processor.py`:
  - `handle_converting(DocumentUploaded)` → publish `document.converted`.
  - `handle_structuring(DocumentConverted)` → publish `document.analysis.completed`.
- Document **status is only mutated in account-api** (`services/documents.py`);
  the worker never changes document state directly.

---

## 3. `handle_converting` — OCR to `marker.md`

1. `_load_images(storage_key)` downloads the original from S3:
   - extension `.pdf` → render each page to an image with PyMuPDF
     (`app/pdf_converter.py`, `pdf_dpi=300`, `pdf_format=png`).
   - extension `.jpg/.jpeg/.png/.tiff/.tif` → the raw blob is the single
     "page" (no rendering). `original_filename_for()` maps
     `image/jpeg → original.jpg` so a JPEG upload always exposes `.jpg`.
   - anything else → `ValueError("unsupported document extension: ...")`.
2. For every image: **one vision call** to the cloud.ru OCR model
   (`Qwen/Qwen3.5-397B-A17B`, prompt `ocr.yaml`) → markdown text.
   Temperatures: `0.1`.
3. Pages are joined as `## Page N\n\n…`, uploaded as `marker.md`, then
   `document.converted` is published.

Ocr prompt (`app/prompts/ocr.yaml`): a medical-document OCR specialist that
preserves headers/tables/lists and outputs markdown only. Thinking stays
enabled here (see Decision 4).

---

## 4. `handle_structuring` — the interesting part

1. Download `marker.md`.
2. **Choose the canonical schema/prompt** (see §5) →
   `canonical_doc_type` ∈ {`laboratory`, `prescription`, `default`}.
3. Load the matching prompt from `app/prompts/canonical.yaml` and call
   `AIClient.extract_canonical(markdown, system_prompt)`.
4. Validate the model JSON against the Pydantic canonical schema
   (`packages/canonical/canonical/schemas`, `build_canonical`).
5. Render:
   - `canonical.json` — `canonical.model_dump(mode="json", by_alias=True)`.
   - `structured.md` — deterministic Python renderer
     (`packages/canonical/canonical/render.py`) with Python-built YAML
     frontmatter (`canonical/metadata.py`), **never** LLM-generated markdown.
6. Upload both, publish `document.analysis.completed` with the canonical data
   (persisted into `document_extractions.data` in account-api).

---

## 5. Decision 1 — how the lab/non-lab schema is chosen

**Problem.** The canonical schema used to be selected purely from the
client-declared `document_type` sent at upload (default `other`). A lab PDF
uploaded without a tag fell through to `generic`, and the whole report was
collapsed into one prose `note` in `canonical.json` — the measurements were
thrown away even though `marker.md` contained a full results table.

**Decision.** Route by **content**, purely offline, using a heuristic
classifier — no extra LLM round-trip, no new model in `.env`.

`classify_document_type(markdown, client_type)` (`app/doc_classifier.py`):

1. Explicit, recognized client type wins:
   - `lab_result` → `laboratory`
   - `prescription` → `prescription`
2. Otherwise scan `marker.md` text for keyword sets:
   - lab: «результаты лабораторных исследов», «лабораторное исследование»,
     «общий анализ крови», «скорость оседания эритроцитов»,
     «референтный диапазон», …
   - prescription: «рецепт», «назначение», «дозировка», «принимат», «таблет», …
3. Else → `default` (generic).

`default` is both a valid prompt key (`canonical.yaml`) and maps through
`build_canonical` to `GenericCanonical` (`DEFAULT_CANONICAL_MODEL`).

**Why heuristic and not LLM-based:** deterministic, zero cost, zero latency,
no new config. It was validated against the real failing sample: the uploaded
lab protocol now classifies as `laboratory` even when the client says `other`.

---

## 6. Decision 2 — canonical schemas and prompts

Shared (`packages/canonical/canonical/schemas/__init__.py`), all non-PII:

- `BaseCanonical` envelope: `document_date`, `language`, `type`, `subtype`,
  `institution {name,address,ogrn}`, `material`, `conclusion`, `fields`.
- `laboratory`: `equipment`, `performed_by`, `fields.results[]` where each
  `ResultItem` has `name`, `value`, `unit`, `reference_min/max`, `flagged`,
  `interpretation`, `comment`.
- `prescription`: `fields.medications[]` + `doctor`, `issued_at`.
- `generic`: loose `fields: dict`.

Prompts (`app/prompts/canonical.yaml`) describe the envelope, an example, and
cardinal rules:
- capture every measurement and reference range;
- `flagged` when outside reference range;
- `interpretation`/`comment` come from the corresponding source columns;
- **never include patient identity** (name, DOB, SNILS, policy number);
- keep original values; don't invent data.

The renderer (`render.py`) turns this into a real measurement list
(material/equipment/conclusion/performed_by + per-result interpretation,
warning `⚠` for flagged), not a single `note`.

---

## 7. Decision 3 — provenance metadata

Python-built YAML frontmatter (`processor._build_frontmatter`):

- `document`: `language`, `document_date`, `page_count` (from `## Page N`).
- `source`: `object_key`, `filename`, `mime_type`, `sha256`,
  `declared_type` (the client-sent type, for debuggability).
- `processing`: `pipeline_version`, model, prompt_version, schema(+version),
  token usage, cost.
- `validation`: status/schema_valid/warnings/validated_at.

Everything in frontmatter is computed by Python; the LLM never produces it.

---

## 8. Decision 4 — the JSON extraction saga (why it failed & the fix)

The single most painful part of this flow. `Qwen/Qwen3.5-397B-A17B` is a
**reasoning model** served through cloud.ru's OpenAI-compatible gateway, and
its behavior kept breaking `json.loads(result.content)` with:

```
JSONDecodeError: Expecting value: line 1 column 1 (char 0)
```

History of root causes and fix layers (`AIClient.extract_canonical`):

1. **Empty `content` from reasoning model.** With thinking enabled, the answer
   lands in `message.reasoning_content` and `content` comes back empty. Handle
   via `_message_text()`: prefer `content`, fall back to
   `reasoning_content`, then legacy `reasoning`.
2. **Prose-only replies accepted as success.** `_extract_json` used to return
   arbitrary text when no JSON braces were found; that "truthy" string went
   straight into `json.loads` → `char 0`. Now `_extract_json` returns `""`
   unless a `{...}` block is found, and `_candidate_json()` hard-requires the
   recovered string to `json.loads` into a `dict` before it is accepted.
3. **Strict call refusing.** If attempt #1 (with
   `response_format={"type":"json_object"}`) yields nothing parseable, retry
   once **without** `response_format` and recover the block from free text.
   If both fail → `ValueError("model returned no parseable canonical JSON on
   either attempt")` → job fails with a readable message via
   `document.processing.failed`.
4. **Thinking starves the answer (the actual production blocker).** For the
   longer lab prompt, the model burned its entire 4096-token budget on
   chain-of-thought (~60 s/call) and never emitted the JSON. **Fix: disable
   thinking for canonical extraction** via
   `extra_body={"chat_template_kwargs": {"enable_thinking": False}}` on every
   `extract_canonical` call (OpenAI SDK `extra_body`, cloud.ru forwards
   chat-template kwargs). The reasoning fallback in step 1 stays as a safety
   net; the OCR path keeps thinking enabled.

Net effect: canonical extraction is deterministic, fast, and returns exactly
one parseable JSON dict, or a clear error.

---

## 9. Decision 5 — containerized dev mode

`ai-worker` used to run only manually (`uv run python -m app.main`). We added:

- **Dockerfile** (`apps/ai-worker/Dockerfile`): builds from repo root,
  `uv sync --project apps/ai-worker --no-dev --no-install-project`. Entrypoint
  is **module mode**:
  `CMD ["uv","run","--no-project","python","-m","app.main"]`.
- **Opt-in compose profile** (`infrastructure/development/docker-compose.yml`):
  service `ai-worker` under `profiles: ["ai-worker"]`, `env_file: .env`,
  explicit `RABBITMQ_URL`/`AI_BASE_URL`/`AI_API_KEY`/`AI_MODEL`, and
  `depends_on: rabbitmq (healthy)`. Start with `make compose-ai-worker`.
- `make compose-stop` / `make compose-down` now pass `--profile ai-worker`
  so teardown really stops the worker too (profile-filtered `down` otherwise
  ignored it).

**Why module mode matters (a real bug we hit).** A 0-byte scaffold file
`apps/ai-worker/app/storage/__init__.py` shadowed the `pdf-storage` package
when the script ran as
`python app/main.py` → `import storage` resolved to the empty shadow package
→ `ImportError: cannot import name 'CloudS3'`. Running with `-m app.main`
keeps `app/` out of `sys.path` (it is a namespace package, and the real
`storage` comes from the `pdf-storage` dependency), and the empty shadow
package was deleted.

---

## 10. Configuration

Read from real environment variables first, then a CWD-relative `.env`
(`Settings`, pydantic-settings, case-insensitive).

| Setting | Default | Purpose |
| --- | --- | --- |
| `RABBITMQ_URL` | — | full DSN (compose sets it) |
| `AI_BASE_URL` | `https://foundation-models.api.cloud.ru/v1` | OpenAI-compatible endpoint |
| `AI_API_KEY` | — | cloud.ru token |
| `AI_MODEL` | `Qwen/Qwen3.5-397B-A17B` | default model (prompts may override) |
| `AI_MAX_TOKENS` | `4096` | cap per completion |
| `S3_*` | — | S3-compatible storage (bucket, endpoint, keys, region) |
| `PDF_DPI` / `PDF_FORMAT` | `300` / `png` | PDF page rendering |

No separate model is needed for schema selection — the classifier is offline
(Decision 1).

---

## 11. Errors & failure model

- Any exception in `handle_converting` / `handle_structuring` is caught,
  logged via `logger.exception`, and published as
  `document.processing.failed` with a `job_type` (`pdf_conversion` /
  `markdown_structuring`) and the message text. account-api marks the document
  FAILED.
- `extract_canonical` raises a `ValueError` with a clear message (Decision 4)
  instead of leaking a raw `JSONDecodeError` traceback into the job failure.
- `_load_images` rejects unknown extensions with a descriptive error.

---

## 12. Testing

- `apps/ai-worker/tests/` — processor handlers, ai-client extraction
  (reasoning fallback, `_candidate_json`, `enable_thinking`, retry), the
  heuristic classifier, PDF conversion, prompt loading.
- `packages/canonical/tests/` — schema validation and rendering for all three
  canonical types.
- Run: `cd apps/ai-worker && uv run --no-sync pytest tests/ -q` and
  `cd packages/canonical && uv run --no-sync pytest tests/ -q`.
- Lint: `uv run --no-sync ruff check app tests` + `ruff format --check` from
  `apps/ai-worker`.

---

## 13. Manual end-to-end check

1. `make compose-start` (base infra: S3, RabbitMQ, …).
2. `make compose-ai-worker` (build + start the worker under the profile) **or**
   `cd apps/ai-worker && uv run python -m app.main`.
3. `make setup-web && make dev-web` (frontend on :5173, proxies `/api` →
   `localhost:8000`).
4. Upload a lab PDF (Vite dev mode also proxies uploads). Wait for:
   - `marker.md` → `converting_completed`;
   - `canonical.json` + `structured.md` → `structuring_completed`.
5. Inspect via `GET /documents/{id}/markdown` and
   `GET /documents/{id}/canonical`.

Diagnostics: `docker logs development-ai-worker-1 -f` (container) or
`make compose-ai-worker-logs`. Typical failure signatures:
`canonical_no_json retry ...` then `model returned no parseable canonical
JSON` → the model returned no JSON; with thinking disabled this should be rare
and is a model/prompt issue, not an infrastructure one.