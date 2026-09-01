# ai-worker

Development-mode document processing worker. Consumes uploaded-stored documents
from RabbitMQ, converts them to `markdown`, and extracts structured
`canonical.json` (the single source of truth) which account-api persists and
serves to the frontend.

> Architecture and behavior docs live in the repo-wide [docs/](../../docs/README.md):
> [Document processing dev flow](../../docs/development/DOC_PROC_DEV_FLOW_IMPL_PLAN.md),
> [OAI / YAML / JSON / AI](../../docs/development/OAI_YAML_JSON_AI.md).

The dev flow is **event-driven**, not a flag. The ai-worker does its job simply
by **running and being subscribed** to the `document.convert` queue (routing keys
`document.uploaded,document.converted`). It is an opt-in service: not part of the
default dev stack, starts either manually or via a Docker compose profile.

---

## How it works

The ai-worker implements the "extract & structure" half of the pipeline. It is a
long-running RabbitMQ consumer that reacts to two event types produced upstream
by account-api / objectstorage-worker.

```
account-api: upload → document.upload.requested → objectstorage-worker
  → document.stored

ai-worker (this repo):
  DocumentUploaded   ──► handle_converting   ──► unstructured markdown (marker.md)
                        publish document.converted
  DocumentConverted  ──► handle_structuring  ──► canonical.json + structured.md
                        publish document.analysis.completed

account-api: persists canonical into document_extractions.data, status COMPLETED
```

### 1. `handle_converting` — PDF/image → unstructured markdown

Triggered by `DocumentUploaded`.

1. Loads the source object from S3 (`event.storage_key`).
2. For each page, renders it to an image (`pdf_converter.convert_pdf_to_images`,
   PyMuPDF, 300 DPI PNG) and sends it to the **vision model** to be OCR'd
   (`ai_client.extract_text_from_image`), producing markdown per page.
3. Joins pages into one unstructured markdown and uploads it to S3
   (`.../unstructured.md`).
4. Publishes `document.converted` (`DocumentConverted`) with the output key plus
   source metadata (`original_filename`, `mime_type`, `sha256`, `document_type`).

### 2. `handle_structuring` — markdown → canonical.json

Triggered by `DocumentConverted`.

1. Downloads the unstructured markdown from S3.
2. Maps the domain `document_type` → canonical schema
   (`lab_result → laboratory`, `prescription → prescription`, else `default`).
3. Calls the LLM with the matching prompt from `canonical.yaml` to produce a
   **strict JSON object** (`response_format={"type":"json_object"}`, temperature
   0.0), capturing token usage. A code-fence fallback strips markdown fences if
   the model wraps the JSON.
4. Validates the raw JSON through the Pydantic canonical schema registry
   (`canonical.build_canonical`), the source of truth.
5. Builds the YAML **frontmatter metadata in Python** (never trusted from the
   LLM): `doc_id`, `document`, `source`, `processing`, `validation`.
6. Uploads two artifacts to S3:
   - `canonical.json` — the validated canonical object (`application/json`);
   - `structured.md` — a deterministic Python render (`canonical.render_document`)
     of the canonical object + YAML frontmatter.
7. Publishes `document.analysis.completed` (`DocumentAnalysisCompleted`) with
   `schema_name`, `schema_version="1.0.0"`, `confidence`, and `data` = the
   canonical object + `canonical_key` / `structured_key`.

account-api's `on_document_analysis_completed` persist this `data` into the
`document_extractions.data` JSON column and set the document to `COMPLETED` (or
`FAILED` on error).

### Error handling

Any error in either handler publishes `document.processing.failed`
(`DocumentProcessingFailed`) with the failing step (`pdf_conversion` /
`markdown_structuring`) and message; account-api marks the document `FAILED`.

### Invocation modes

- **Manual (default dev mode):**
  ```bash
  cd apps/ai-worker
  uv run python -m app.main
  ```
  Must be run from the `apps/ai-worker` dir; uses module mode (`-m app.main`) so
  the real `pdf-storage` package is resolved (not the old local `app/storage`
  scaffold).
- **Containerized (opt-in Docker profile):** see the Run section below.

---

## Packages / tech stack

The worker is a **uv workspace member** (`[tool.uv] package = false`); it uses
shared monorepo packages plus its own app modules.

| Layer | Tech | Used for |
| --- | --- | --- |
| Lang/runtime | Python 3.12 (uv) | – |
| Message bus | `pdf-messaging` (aio-pika) + `pdf-contracts` | RabbitMQ consumer + typed event schemas (`DocumentUploaded`, `DocumentConverted`, `DocumentAnalysisCompleted`, `DocumentProcessingFailed`) |
| Object storage | `pdf-storage` (boto3) | Read/write S3 objects (source PDF, markdown, canonical JSON) |
| LLM | `openai` AsyncOpenAI client | Vision OCR + canonical JSON extraction against cloud.ru foundation models |
| PDF → images | `pymupdf` | Render each page at 300 DPI |
| Schemas / validation | `pdf-canonical` (pydantic + pyyaml) | `build_canonical` validation, `render_document` / `render_frontmatter` |
| Config | `pydantic-settings` | `.env`-driven settings |
| Observability | `pdf-observability` | logging + metrics |

### App modules (`apps/ai-worker/app`)

```text
main.py            Consumer loop: subscribe to document.convert → dispatch handlers
config.py          Settings (rabbitmq, ai, s3, prompts_dir) from env/.env
processor.py       DocumentProcessor: handle_converting + handle_structuring + helpers
ai_client.py       AIClient: vision OCR (extract_text_from_image) + canonical JSON
                   (extract_canonical), token usage capture
pdf_converter.py   convert_pdf_to_images / get_pdf_page_count (PyMuPDF)
prompts/           ocr.yaml, canonical.yaml (per-doc-type), legacy structuring.yaml
```

> `worker.py`, `queue.py`, `app/llm/`, and `app/pipeline/` are empty scaffolding
> (0 bytes) carried from the monorepo bootstrap; they are **not** part of the
> current flow. `structuring.yaml` is legacy — active extraction uses
> `canonical.yaml`.

### Prompts (`settings.prompts_dir` = `app/prompts`)

- `ocr.yaml` — `system_prompt` + model for per-page vision OCR (temp 0.1).
- `canonical.yaml` — per-doc-type prompts (`default`, `laboratory`,
  `prescription`) that return a strict JSON envelope; model
  `Qwen/Qwen3.5-397B-A17B`, temperature 0.0; `pipeline_version: "1.0.0"`.
- `structuring.yaml` — legacy; superseded by `canonical.yaml`.

### Key environment variables (`.env`)

| Variable | Default | Purpose |
| --- | --- | --- |
| `RABBITMQ_URL` | `amqp://…` | Broker DSN (queue `document.convert`, keys `document.uploaded,document.converted`) |
| `AI_BASE_URL` | `https://foundation-models.api.cloud.ru/v1` | LLM endpoint |
| `AI_API_KEY` | – | LLM API key |
| `AI_MODEL` | `Qwen/Qwen3.5-397B-A17B` | LLM model |
| `S3_ENDPOINT_URL`, `S3_KEY_ID`, `S3_KEY_SECRET`, `S3_BUCKET_NAME`, `S3_REGION`, `S3_TENANT_ID` | – | cloud.ru S3-compatible object storage |

---

## Run

### 1. Start the dev infra

Bring up Postgres, RabbitMQ, Redis, account-api and the storage/notification
workers (but not ai-worker — it's opt-in):

```bash
make compose-start        # from images already built
# or, first time:
make compose-dev          # build + start
```

### 2. Run the ai-worker

**Option A — manual (simplest, hot code):**

```bash
cd apps/ai-worker
uv run python -m app.main
```

**Option B — containerized (Docker profile):**

```bash
make compose-ai-worker            # build + start the ai-worker container
make compose-ai-worker-logs       # tail its logs
make compose-stop                 # stop the whole stack when done
```

Confirm it subscribed:

```text
ai_worker_started queue=document.convert routing_keys=document.uploaded,document.converted
```

### 3. Set up and run the web frontend

```bash
make setup-web        # npm install (first time only)
make dev-web          # Vite dev server, proxies /api → account-api :8000
```

> The Makefile target is `dev-web` (there is no `web-dev`). This project's
> `dev-web` runs `cd apps/web && npm run dev`.

### 4. Exercise the full flow

1. Open the app at `http://localhost:5173` (Vite) — or directly the API at
   `http://localhost:8000`.
2. Upload a PDF/image for a patient through the UI (or `POST
   /api/v1/patients/{id}/documents`).
3. Watch the worker logs:
   - `converting_completed` → `marker.md` uploaded (`document.converted`);
   - `structuring_completed` → `canonical.json` + `structured.md` uploaded
     (`document.analysis.completed`).
4. Backend serves the result:
   - `GET /api/v1/documents/{id}/canonical` — persisted canonical data (from
     `document_extractions.data`);
   - `GET /api/v1/documents/{id}/markdown` — inline canonical JSON + rendered
     `structured.md`.

---

## Test

```bash
cd apps/ai-worker
uv run pytest          # unit tests (25)
```

## Layout

```text
app/
  main.py           consumer entrypoint (async run)
  config.py         pydantic-settings Settings
  processor.py      DocumentProcessor (two stage handlers)
  ai_client.py      AIClient (OpenAI-compatible vision + JSON extraction)
  pdf_converter.py  PyMuPDF page rendering
  prompts/          ocr.yaml, canonical.yaml (+ legacy structuring.yaml)
tests/              unit tests (conftest, prompt manager, converter, client, processor)
pyproject.toml      uv workspace member ([tool.uv] package = false)
Dockerfile          container image (uv, python 3.12)
```
