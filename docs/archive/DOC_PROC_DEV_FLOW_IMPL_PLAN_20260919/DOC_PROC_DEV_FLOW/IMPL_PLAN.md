# Document Processing Development Flow Implementation Plan

Implementation plan for the development-mode document processing pipeline: PDF →
images → unstructured markdown → LLM extraction → **canonical.json** (source of
truth) → Pydantic validation → Python-rendered `structured.md` (+ YAML
frontmatter). The dev flow simulates the production marker service using the
cloud.ru AI model, following `docs/development/OAI_YAML_JSON_AI.md` (#29).

**Revision 6** — adds Phase G (`GET /documents/{id}/canonical` route) and the
Phase 6 plan (ai-worker Dockerfile + compose profile), moving both out of
"Out of scope". Consolidates the A–F canonical pipeline (all done).

**Revision 5** — full restructure into the concise, step/status-oriented format
of `docs/development/AUTH_FIX_IMPL_PLAN.md`. Consolidates Phases 1–4 (done),
adds the canonical / structured rendering plan (Phases A–F, pending), and drops
the earlier code-heavy sections in favor of tables and per-phase
Status/Changes/Verification/Next-Step blocks.

Status legend: `[ ]` pending · `[x]` done.

---

## 0. Pipeline overview

**Current (implemented) flow:**

```
account-api upload → document.upload.requested → objectstorage-worker
  → document.stored → account-api on_document_stored (PROCESSING, publish document.uploaded)
  → ai-worker handle_converting (marker.md, publish document.converted)
  → ai-worker handle_structuring (structured.md, publish document.analysis.completed)
  → account-api on_document_analysis_completed (COMPLETED/FAILED)
```

**Target (canonical) flow after Phases A–F:**

```
handle_structuring → LLM extract canonical.json (source of truth)
  → validate via Pydantic → render structured.md + YAML frontmatter (Python)
  → upload canonical.json + structured.md → publish enriched document.analysis.completed
  → account-api persists canonical into document_extractions.data
```

### Dev-mode mechanism (NOT a flag)

"Using ai-worker" means the ai-worker process is **running and subscribed** to
queue `document.convert` (routing keys `document.uploaded,document.converted`).
By default it is **not** in `infrastructure/development/docker-compose.yml`; it is
started manually (`cd apps/ai-worker && uv run python -m app.main`). Phase 6
provides an opt-in compose **profile** (`ai-worker`) as a containerized
alternative (see Phase 6 plan below).

### Status management invariant

Document status is mutated **only** in `apps/account-api/app/services/documents.py`,
never in workers/consumers:

| Site | Effect |
|------|--------|
| `create_document` / `add_version` | `PENDING` |
| `on_document_stored` | `PROCESSING` + publish `document.uploaded` |
| `on_document_analysis_completed` | `COMPLETED` / `FAILED` |
| `on_document_processing_failed` | `FAILED` |
| `on_document_converted` | only sets `ProcessingJobStatus.SUCCEEDED` on the job, **not** document status |

Consumer dispatch: `apps/account-api/app/consumers/document_events.py:52-59`;
routing keys at `apps/account-api/app/core/config.py:116`.

---

## 1. Execution summary

| Phase | Scope | Status |
|-------|-------|--------|
| 1 | ai-worker core (convert + structure, publish events) | [x] done |
| 2 | Orchestrator event contracts (`DocumentConversionRequested`, `DocumentAnalysisRequested`) | [x] done |
| 3 | Storage markdown helpers (`markdown_key`, `MARKDOWN_ARTIFACTS`, `upload/download_markdown`) + processor refactor | [x] done |
| 4 | `GET /documents/{id}/markdown` endpoint (presigned URLs) | [x] done |
| 7 | ai-worker unit tests (19 passing) | [x] done |
| A | New `packages/canonical` (schema registry, validation, render) | [x] done |
| B | ai-worker `handle_structuring` rework → canonical.json + structured.md | [x] done |
| C | Source metadata on `DocumentUploaded`/`DocumentStored` (`original_filename`, `mime_type`, `sha256`), `document_type` threading | [x] done |
| D | Storage canonical kind + JSON helpers; account-api `download_json` | [x] done |
| E | Inline canonical JSON on `GET /documents/{id}/markdown` (`CanonicalResponse`) | [x] done |
| F | Canonical persisted into `document_extractions.data` (+ round-trip tests) | [x] done |
| G | New `GET /documents/{id}/canonical` route serving persisted canonical JSON | [x] done |
| 6 | ai-worker Dockerfile + compose profile (containerized alternative to manual run) | [x] done |

---

## 2. Completed phases

### Phase 1 — ai-worker core [x]

**Changes.** Created `apps/ai-worker/` (`main.py`, `config.py`, `processor.py`,
`pdf_converter.py`, `ai_client.py`, `prompts/`{`__init__.py`, `ocr.yaml`,
`structuring.yaml`}, `pyproject.toml`). Added `CloudS3.download_bytes()` to
`packages/storage/storage/s3.py`.

**Verification.** Smoke test passed: converting + structuring publish
`document.converted` / `document.analysis.completed` and upload `marker.md` /
`structured.md`; errors publish `document.processing.failed`.

### Phase 2 — Event contracts [x]

**Changes.** Created + exported `DocumentConversionRequested`
(`storage_key`, `mime_type`) and `DocumentAnalysisRequested`
(`output_storage_key`, `mime_type`).

**Verification.** Round-trip tests added; 6 contracts tests passing.

### Phase 3 — Storage helpers + processor refactor [x]

**Changes.** `packages/storage/storage/keys.py`: `MARKDOWN_ARTIFACTS`,
`markdown_artifact_filename`, `markdown_key`. `storage/__init__.py`:
`MARKDOWN_KIND_*`, `upload_markdown`, `download_markdown`. Processor refactored to
use them.

**Verification.** Storage tests 11 passing; ai-worker 19 passing; contracts 6
passing; ruff/format clean (only pre-existing `s3.py:84` E501).

### Phase 4 — `GET /documents/{id}/markdown` endpoint [x]

**Changes.**
- `app/schemas/document.py`: added `MarkdownResponse`, `DocumentExtractionResponse`,
  `JobResponse`, `DownloadUrlResponse`.
- `app/services/storage.py`: added `markdown_object_key(*,patient_id,document_id,version_id,kind)`,
  `object_exists(key)` (wraps `CloudS3.head()`, `False` when `_s3 is None`),
  `download_url`; imports `MARKDOWN_KIND_*`, `markdown_key`.
- `app/services/documents.py`: added `get_markdown(document_id, version_id=None)`
  (resolves doc + version → `DocumentNotFoundError` if no stored version; resolves
  owner patient; returns URLs only for existing artifacts).
- `app/api/v1/documents.py`: route guarded by `require_document_access(action=VIEW_DOCUMENT)`,
  uses `DocumentServiceDep` alias, `version_id` default after non-default Annotated.

**Verification.** 178 account-api tests passing: `tests/unit/test_markdown_service.py`
(5 unit tests with `FakeStorage`), `tests/test_documents_api.py` (3 API tests —
404 no version, empty when no artifacts, presigned URLs via `FakeMarkdownStorage`).

### Phase 7 — ai-worker tests [x]

**Changes.** Created `tests/conftest.py` (fixtures `sample_pdf` ←
`apps/web/tests/e2e/fixtures/sample.pdf`, `prompts_dir`) and `test_prompt_manager.py`,
`test_pdf_converter.py`, `test_ai_client.py`, `test_processor.py`.

**Verification.** 19 passing (after fix: use
`patch.object(..., "create", new=AsyncMock(return_value=response))` with
`MagicMock` message/choice/response objects because `AsyncMock(content=None)` is
truthy). Ruff fix + format applied.

---

## 3. Canonical pipeline plan (Phases A–F)

### Locked design decisions

1. LLM → `canonical.json` only; **Python renders markdown** (deterministic) + YAML
   frontmatter. `canonical.json` is the single source of truth.
2. `GET /documents/{id}/markdown` returns **inline parsed canonical JSON** (not a
   presigned URL).
3. New shared uv workspace package `packages/canonical` (`name="pdf-canonical"`,
   pydantic + pyyaml) used by both ai-worker and account-api.
4. Persist canonical JSON in the existing `document_extractions.data` JSON column
   on analysis completion.
5. Chunking, embeddings, and vector DB are **out of scope**.

### Frontmatter / metadata contract

YAML frontmatter field set (locked). All metadata is built by Python, **never the
LLM**. Only `document_date`, `language`, `type`, `subtype` plus the doc-specific
payload come from the LLM (validated by Pydantic).

| Section | Fields (built by Python) |
|---------|--------------------------|
| top | `doc_id` (= `document_id` UUID), `type`, `subtype` |
| `document` | `language = "ru"`, `document_date`, `uploaded_at`, `page_count` |
| `source` | `type = "user_upload"`, `mime_type`, `filename`, `sha256`, `object_key` |
| `processing` | `pipeline_version = "1.0.0"`, `extraction`{`model`, `prompt_version`, `schema`, `schema_version`, `tokens`{`input`,`output`,`total`,`cost_usd`}} |
| `validation` | `status = "valid\|warning\|invalid"`, `schema_valid`, `warnings[]`, `validated_at` |

### `canonical.yaml` prompt config

At `apps/ai-worker/app/prompts/canonical.yaml`, keys:
`name, description, pipeline_version, prompts.<doc_type>.{system_prompt,model,temperature}`.
Per-doc-type entries:
- `default` — generic `fields` dict;
- `laboratory` — results: `name/value/unit/reference_min/reference_max/flagged`;
- `prescription` — medications: `name/dosage/frequency/duration`, `doctor`, `issued_at`.

Model `Qwen/Qwen3.5-397B-A17B`, temperature `0.0`.

### Canonical schema registry

In `packages/canonical/canonical/schemas/`:
- `BaseCanonical` envelope (`document_date`, `language`, `type`, `subtype`);
- `LaboratoryCanonical`, `PrescriptionCanonical`, `GenericCanonical`;
- registry dict `CANONICAL_MODELS` keyed by doc type with
  `DEFAULT_CANONICAL_MODEL = GenericCanonical`;
- `build_canonical(doc_type, raw)` uses Pydantic `model_validate`;
- `render.py`: `render_markdown`, `render_frontmatter` (yaml.safe_dump),
  `render_document`;
- Pydantic metadata model `FrontmatterMeta` in `metadata.py`.

---

### Phase A — `packages/canonical` package [x]

**Status:** done. Package created, workspace-wired, tested, ruff-clean. See
"Phase A Implementation Status" below.

**Changes.**
- New uv workspace package `packages/canonical` (`name="pdf-canonical"`,
  deps `pydantic`, `pyyaml`): `metadata.py` (`FrontmatterMeta`), `schemas/`
  (registry + `build_canonical`), `render.py` (`render_markdown`,
  `render_frontmatter`, `render_document`).
- Root `pyproject.toml`: add `packages/canonical` to `members` and
  `pdf-canonical` to `[tool.uv.sources]`.
- Add dependency `pdf-canonical` to ai-worker and account-api `pyproject.toml`.

**Verification.** Package test suite passes (8 tests); both apps resolve
`pdf-canonical` cleanly via `uv tree`; ruff check + format clean; ai-worker (19)
and account-api (178) tests unaffected.

#### Phase A Implementation Status

- Files created: `packages/canonical/pyproject.toml`,
  `packages/canonical/canonical/{__init__.py, metadata.py, render.py}`,
  `packages/canonical/canonical/schemas/__init__.py`,
  `packages/canonical/tests/test_canonical.py`.
- What was added: `FrontmatterMeta` metadata envelope (Python-built only);
  `BaseCanonical` + `LaboratoryCanonical` / `PrescriptionCanonical` /
  `GenericCanonical` schema registry with `build_canonical` (extra="forbid");
  deterministic `render_markdown` / `render_frontmatter` / `render_document`.
- Workspace wiring: root `pyproject.toml` members + `pdf-canonical` source;
  `pdf-canonical` dependency added to ai-worker + account-api; `uv lock`
  regenerated (156 packages; `pdf-canonical v0.1.0` added).
- Deviation: `ExtractionMeta.schema` renamed to `schema_name` with
  serialization/validation alias `schema` to avoid shadowing the Pydantic
  `BaseModel.schema` classmethod (frontmatter output unchanged: still `schema`).
- Verification: 8 tests pass; ruff/format clean; `uv tree` shows `pdf-canonical`
  resolved by ai-worker + account-api.
- Next step: confirm before Phase B (ai-worker canonical extraction + render).

### Phase B — ai-worker `handle_structuring` rework [x]

**Status:** done. Canonical extraction + deterministic render implemented and
tested. See "Phase B Implementation Status" below.

**Changes.**
- Add `AIClient.extract_canonical(...) -> ExtractionResult` — JSON-only output,
  `response_format={"type":"json_object"}` with JSON-block (code-fence) fallback,
  captures token `usage` (input/output/total). `structure_markdown` is removed;
  kept `extract_text_from_image`.
- Add `canonical.yaml` (per-doc-type prompts: `default`, `laboratory`,
  `prescription`); `PromptManager` treats `canonical` like `structuring`
  (reads `prompts.<doc_type>`).
- `handle_structuring`: download marker.md → `extract_canonical` → `json.loads` →
  `build_canonical` validate → build `FrontmatterMeta` from event + prompt + usage
  → upload `canonical.json` (source of truth) + rendered `structured.md` →
  publish enriched `DocumentAnalysisCompleted` (`schema_name`,
  `schema_version="1.0.0"`, `data` = canonical + `canonical_key`/`structured_key`).

**Verification.** 25 ai-worker tests passing; ruff check + format clean;
account-api unaffected.

#### Phase B Implementation Status

- Files changed: `apps/ai-worker/app/{ai_client.py, processor.py}`,
  `apps/ai-worker/app/prompts/{__init__.py, canonical.yaml}`,
  `apps/ai-worker/tests/{test_ai_client.py, test_processor.py, test_prompt_manager.py}`.
- What was added: `AIClient.extract_canonical` (returns `ExtractionResult` with
  `content` + `usage`, `response_format=json_object`, code-fence fallback);
  `canonical.yaml`; `handle_structuring` produces + uploads `canonical.json` and
  `structured.md`; `_build_frontmatter` composes the Python-built YAML envelope;
  `_build_canonical_key` (via `build_key` + `"canonical.json"`).
- Deviation: `handle_structuring` currently defaults `doc_type` to `"default"`
  (generic schema) and builds the `source` block from event attributes
  (`original_filename`/`mime_type`/`sha256`) only when present. The events do not
  yet carry those fields nor a doc type — wired forward-compatibly via
  `getattr(event, ...)`. Full routing + source enrichment lands in Phase C.
  Storage canonical-key helper is deferred to Phase D (processor uses `build_key`
  directly for now).
- Verification: 25 ai-worker tests pass; ruff check + format clean; unchanged
  account-api (178) + canonical (8) suites green.
- Next step: confirmed Phase C, then Phase D (storage canonical kind).

### Phase C — source metadata on events [x]

**Status:** done. Source metadata + `document_type` threaded through the whole
pipeline. See "Phase C Implementation Status" below.

**Changes.**
- Extend `DocumentUploaded` / `DocumentStored` (+ `DocumentUploadRequested`,
  `DocumentConverted`) with `original_filename`, `mime_type`, `sha256`, and
  `document_type` (all defaulted for backward compatibility).
- account-api `on_document_stored` populates these on the `document.uploaded`
  publish (`sha256` from `DocumentStored.checksum`, `document_type` from the
  stored version/source).
- account-api `create_document` / `add_version` set `document_type` on
  `DocumentUploadRequested`; objectstorage-worker threads `original_filename` +
  `document_type` into `DocumentStored`; ai-worker threads the source block +
  `document_type` into `DocumentConverted`.
- ai-worker `handle_structuring` maps domain `document_type` → canonical schema
  (`lab_result→laboratory`, `prescription→prescription`, else `default`) for
  prompt selection and `build_canonical`; the rendered frontmatter `source`
  block now carries real filename/mime/sha256.

**Verification.** Contracts round-trip tests updated (9 passing); account-api
(178), ai-worker (25), objectstorage-worker (6), canonical (8) all green; ruff
check clean.

#### Phase C Implementation Status

- Contracts changed: `DocumentUploadRequested`, `DocumentStored`,
  `DocumentUploaded`, `DocumentConverted` gained `original_filename`,
  `mime_type`, `sha256`, `document_type` (defaults keep old callers working).
- account-api: `create_document` / `add_version` set `document_type` on the
  upload request; `on_document_stored` populates the full source block on
  `DocumentUploaded` (`sha256=event.checksum`).
- objectstorage-worker: `_stored` threads `original_filename` + `document_type`
  from the upload request into `DocumentStored`.
- ai-worker: `handle_converting` threads source + `document_type` into
  `DocumentConverted`; `handle_structuring` maps domain doc type → canonical
  schema (`_canonical_doc_type`); frontmatter `source` now populated.
- Verification: 9 contracts / 178 account-api / 25 ai-worker / 6
  objectstorage-worker / 8 canonical tests pass; ruff check clean.
- Next step: confirm before Phase D (storage canonical kind + JSON helpers).

### Phase D — storage canonical kind + JSON helpers [x]

**Status:** done. Canonical storage kind, JSON helpers, and account-api download
method implemented and tested. See "Phase D Implementation Status" below.

**Changes.**
- `packages/storage/storage/keys.py`: add `"canonical": "canonical.json"` to
  `MARKDOWN_ARTIFACTS`; update `markdown_artifact_filename` docstring.
- `storage/__init__.py`: add `MARKDOWN_KIND_CANONICAL = "canonical"`, `upload_json`
  (uploads string as `application/json`), `download_json` (returns raw JSON
  string; callers parse with `json.loads`).
- account-api `StorageService`: add `canonical_object_key(*,patient_id,
  document_id,version_id)` (reuses `markdown_object_key(kind=CANONICAL)`) and
  `download_json(key) -> dict | None` (wraps `self._s3.download_bytes` in
  `asyncio.to_thread` + `json.loads`; returns `None` on missing/unconfigured S3).
- ai-worker `processor.py`: replace `_build_canonical_key` (raw `build_key` +
  literal `canonical.json`) with `markdown_key(... kind=MARKDOWN_KIND_CANONICAL)`.
  Remove `_CANONICAL_FILENAME` constant.

**Verification.** Storage tests 14 passing (was 11, +3); ai-worker 25; account-api
183 (was 178, +5); ruff clean.

#### Phase D Implementation Status

- Files changed: `packages/storage/storage/{keys.py, __init__.py}`,
  `apps/account-api/app/services/storage.py`,
  `apps/ai-worker/app/processor.py` (import + `_build_canonical_key`),
  `packages/storage/tests/{test_keys.py, test_markdown_helpers.py}`,
  `apps/account-api/tests/unit/test_markdown_service.py`.
- What was added: `MARKDOWN_KIND_CANONICAL` + `canonical` in `MARKDOWN_ARTIFACTS`;
  `upload_json`/`download_json` storage helpers; `canonical_object_key` /
  `download_json` on `StorageService` (JSON parsed, `None` on missing S3);
  ai-worker canonical key now uses `markdown_key` via storage constant.
- Verification: 14 storage / 25 ai-worker / 183 account-api tests pass; ruff
  check clean on all touched source files.
- Next step: confirmed Phase E (inline canonical JSON on GET).

### Phase E — inline canonical JSON on GET [x]

**Status:** done. `GET /documents/{id}/markdown` now returns inline parsed
canonical JSON + rendered markdown instead of presigned URLs. See "Phase E
Implementation Status" below.

**Changes.**
- `app/services/documents.py`: `get_markdown` now returns `CanonicalResponse` —
  downloads `canonical.json` via `download_json` (None when absent) plus the
  rendered `structured.md` via new `download_text`; drops the presigned-URL /
  unstructured-key path.
- `app/api/v1/documents.py`: `GET /documents/{id}/markdown` response model is now
  `CanonicalResponse` (inline `{canonical, canonical_key, structured_markdown,
  has_canonical}` instead of `MarkdownResponse` presigned URLs).
- `app/schemas/document.py`: `CanonicalResponse` added; `MarkdownResponse` kept.
- `app/services/storage.py`: generic `download_text(key) -> str | None` added;
  `download_json` refactored to use it.

#### Phase E Implementation Status

- Files changed: `app/services/documents.py`, `app/api/v1/documents.py`,
  `app/schemas/document.py`, `app/services/storage.py`,
  `tests/unit/test_markdown_service.py`, `tests/test_documents_api.py`.
- Deviation from initial plan: also returns inline `structured_markdown` (the
  deterministic rendered view) alongside canonical JSON; presigned-URL artifacts
  are dropped from this route (no remaining consumer).
- Behavioral note: canonical key built as `.../canonical.json`; fakes updated so
  canonical kinds emit `.json` while other kinds emit `.md`.
- Verification: 28 tests pass in the two touched files; full account-api suite
  183 pass; ruff check + format clean on all touched files.
- Next step: confirmed Phase F (persist canonical into
  `document_extractions.data`).

### Phase F — persist canonical into `document_extractions.data` [x]

**Status:** done. Enriched `DocumentAnalysisCompleted.data` (canonical + keys)
already persisted into the `document_extractions.data` JSON column via
`on_document_analysis_completed`; added tests asserting the canonical round-trip.
See "Phase F Implementation Status" below.

**Changes.** Confirmed `on_document_analysis_completed` (`app/services/documents.py`)
already writes `extraction.data = event.data` for the enriched shape from the
ai-worker (`data={**canonical, canonical_key, structured_key}`). Added dedicated
tests mirroring that enriched event and asserting the full round-trip.

**Verification.** Account-api suite 185 pass (2 new tests); ruff check clean on
the touched test file (format diff on this file is pre-existing).

#### Phase F Implementation Status

- Files changed: `tests/unit/test_document_events.py`.
- Confirmed no service/model change required: `DocumentExtraction.data`
  (`models/extraction.py:32`) is a SQLAlchemy `JSON` column and
  `on_document_analysis_completed` already assigns `event.data` to it.
- New tests: `test_analysis_completed_persists_enriched_canonical_and_keys`
  (full canonical + keys + schema metadata round-trip) and
  `test_analysis_completed_creates_extraction_when_id_is_new`.
- Verification: 185 account-api tests pass; ruff check clean.
- Note: `test_document_events.py` had a pre-existing `ruff format --check`
  failure (line ~441 + missing EOF newline) unrelated to this phase; left
  untouched per convention.
- Pipeline canonical flow is now complete (Phases A–F).

---

### Phase G — `GET /documents/{id}/canonical` route [x]

**Status:** done. New backend route serving the persisted canonical JSON for a
document (latest succeeded extraction) from `document_extractions.data`. See
"Phase G Implementation Status" below.

**Context / decision.**
- The canonical JSON for a doc is already persisted in `document_extractions.data`
  (Phase F) and already exposed two ways:
  - `GET /documents/{id}/extractions` → `DocumentExtractionResponse[]` (list;
    includes `data`).
  - `GET /documents/{id}/markdown` → `CanonicalResponse.canonical` (reads S3).
- Phase G adds a **dedicated, fast** route that reads from the DB (no S3
  round-trip per request) so a user opening one of their docs can view the JSON
  data of that doc directly.

**Changes.**
- `app/services/documents.py`: add `get_canonical(document_id) -> dict | None` —
  resolves the document (raises `DocumentNotFoundError`), then returns the
  `data` of the latest **SUCCEEDED** `DocumentExtraction` (via
  `_extractions.list_by_document`, already newest-first); raise `CanonicalDataNotFoundError`
  when no succeeded extraction exists.
- `app/schemas/document.py`: add `CanonicalDataResponse` wrapping the canonical
  payload + extraction metadata (`schema_name`, `schema_version`, `confidence`,
  `data`).
- `app/api/v1/documents.py`: add `GET /documents/{id}/canonical` guarded by
  `require_document_access(action=AuditAction.VIEW_DOCUMENT)` using the
  `DocumentServiceDep` alias; router maps both domain 404s via `raise_for`
  (`DocumentNotFoundError`, `CanonicalDataNotFoundError`).
- `app/domain/medical.py`: add `CanonicalDataNotFoundError`; mapped to 404 in
  `app/api/v1/http_errors.py`.

**Response shape.**
```json
{ "schema_name": "...", "schema_version": "1.0.0", "confidence": 1.0,
  "data": { "...canonical fields...", "canonical_key": "...", "structured_key": "..." } }
```
Note: `data` is returned as-is (includes `canonical_key` / `structured_key`
alongside the canonical object, matching `document_extractions.data`).

**Verification.** Unit test (latest succeeded extraction's data returned; no
succeeded extraction → 404; unknown doc → 404) + API test
(`GET /documents/{id}/canonical` returns persisted data; 404 when not
processed). ruff check + format clean on touched files.

#### Phase G Implementation Status

- Files changed: `app/services/documents.py`, `app/schemas/document.py`,
  `app/api/v1/documents.py`, `app/domain/medical.py`,
  `app/api/v1/http_errors.py`, `tests/unit/test_markdown_service.py`,
  `tests/test_documents_api.py`.
- What was added: `CanonicalDataResponse` schema; `DocumentService.get_canonical`
  (returns latest SUCCEEDED extraction's `data` as `CanonicalDataResponse`);
  `CanonicalDataNotFoundError` domain error mapped to 404; `GET
  /documents/{id}/canonical` route gated by `VIEW_DOCUMENT`. Reads from DB only
  (no S3 round-trip).
- Verification: 5 new tests (3 unit + 2 API); full account-api suite 190 pass
  (was 185); ruff check + format clean on all touched files (the remaining
  `medical.py` format diff is a pre-existing missing EOF newline, left
  untouched).
- Next step: confirmed Phase 6 (ai-worker Dockerfile + compose profile).

---

### Phase 6 — ai-worker Dockerfile + compose profile [x]

**Status:** done. ai-worker containerized as an opt-in dev compose service under
the `ai-worker` profile; Docker build verified end-to-end. See "Phase 6
Implementation Status" below.

**Context / decision.**
- `apps/ai-worker/Dockerfile` built from the repo root via uv (python 3.12).
  **Bug found & fixed:** the original `CMD` used script mode
  (`python app/main.py`), which prepends `app/` to `sys.path` and so resolved
  `import storage` to an empty shadow package instead of `pdf-storage`, failing
  with `ImportError: cannot import name 'CloudS3'`. Fixed to module mode
  (`python -m app.main`) and removed the empty `apps/ai-worker/app/storage/`
  shadow package (a bootstrap scaffold).
- The ai-worker needs only `RABBITMQ_URL` + S3 + `AI_API_KEY`, which it gets from
  `env_file: .env` (S3 vars) plus inline `RABBITMQ_URL` / `AI_*` overrides; it
  reads/writes S3 directly, so it needs **no** uploads volume.
- Its `pyproject.toml` deps do **not** include `torch`, so the Docker build is
  unaffected by the pre-existing mac-x86 `uv sync --all-packages` torch issue.
- To avoid conflicting with the default manual dev mode, the service is added
  under a compose **profile** (`ai-worker`) so it only starts when requested.

**Changes.**
- `apps/ai-worker/Dockerfile`: `CMD` → `uv run --no-project python -m app.main`
  (module mode fixes the `storage` import shadowing).
- Removed empty shadow package `apps/ai-worker/app/storage/__init__.py`.
- `infrastructure/development/docker-compose.yml`: add `ai-worker` service —
  build `context: ../..`, `dockerfile: apps/ai-worker/Dockerfile`,
  `env_file: .env`, env `RABBITMQ_URL` + `AI_BASE_URL` / `AI_API_KEY` /
  `AI_MODEL`, `restart: unless-stopped`, `depends_on: rabbitmq`,
  `profiles: ["ai-worker"]`.
- `Makefile`: add `compose-ai-worker` (+ `compose-ai-worker-logs`) targets and
  register them in `.PHONY`.
- Update Section 0 dev-mode note (done) to document both ways to run the worker.

**Verification.** `docker compose -f infrastructure/development/docker-compose.yml
--profile ai-worker config --services` lists `ai-worker` only with the profile
(0 without). `docker build -f apps/ai-worker/Dockerfile` succeeds. The image
boots past imports in module mode (reaches the rabbitmq connect stage; fails only
without a broker). ai-worker unit tests 25 pass after shadow-package removal.

#### Phase 6 Implementation Status

- Files changed: `apps/ai-worker/Dockerfile`,
  `infrastructure/development/docker-compose.yml`, `Makefile`;
  deleted `apps/ai-worker/app/storage/__init__.py`.
- Key fix: Dockerfile `CMD` script-mode → module-mode (`python -m app.main`)
  to stop `app/storage` (0-byte shadow package) from hiding `pdf-storage`.
  Removed the empty shadow package so the bug cannot recur via `python
  app/main.py`.
- Used existing `.env` (already has `S3_*`, `AI_BASE_URL`, `AI_API_KEY`,
  `AI_MODEL`); compose only overrides `RABBITMQ_URL` (container hostname) and
  the `AI_*` defaults.
- Verification: image builds and boots correctly; `ai-worker` appears in the
  compose service list only when the profile is enabled; 25 ai-worker tests pass.
- Next step: (optional) run the full stack with the profile and smoke-test an
  uploaded document end-to-end.

---

## 4. Tests

- **Contracts** — round-trip for extended events (Phase C).
- **storage** — `canonical.json` key + JSON helpers (Phase D).
- **`packages/canonical`** — schema validation, `build_canonical`, render
  (Phase A).
- **ai-worker** — `extract_canonical`, `handle_structuring` canonical flow
  (Phase B).
- **account-api** — inline canonical JSON on GET (Phase E), persistence into
  `document_extractions.data` (Phase F), `/documents/{id}/canonical` route
  (Phase G).

---

## 5. Implementation order (after the rewrite, pending user approval)

1. Phase A — `packages/canonical` package + workspace wiring. [x]
2. Phase C — event source metadata (unblocks YAML `source`). [x]
3. Phase B — ai-worker canonical extraction + render. [x]
4. Phase D — storage canonical kind + JSON helpers. [x]
5. Phase E — inline canonical JSON on GET. [x]
6. Phase F — persistence tests. [x]
7. Phase G — `GET /documents/{id}/canonical` route. [x]
8. Phase 6 — ai-worker Dockerfile + compose profile. [x]

Phases A–F execute in sequence; each ends with tests + status update + a pause to
confirm with the user.

---

## 6. Notes

- `canonical.json` is the single source of truth; `structured.md` is a
  deterministic Python render for human/app consumption.
- Frontmatter metadata is always built by Python — never trusted from the LLM.
- `Qwen/Qwen3.5-397B-A17B` supports vision (multimodal) for OCR; extraction uses
  JSON-object response format with JSON-block fallback.
- All S3 operations are async via `asyncio.to_thread`.
- Follow `docs/development/CONTRIBUTING.md`: route signatures use the `Annotated`
  alias `DocumentServiceDep` (no `Depends(...)` in signature); non-default Annotated
  params precede defaults; service raises domain exceptions; router maps via
  `raise_for`; service commits once.
