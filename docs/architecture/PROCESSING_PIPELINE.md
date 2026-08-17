# Processing Pipeline

Canonical end-to-end pipeline. Each step has an input, output, owner, queue,
retry policy, failure state and idempotency key. This is the single source of
truth for the document lifecycle — services must not invent their own.

## Canonical flow

```text
Upload
  │
  ▼
S3
  │
  ▼
document.uploaded
  │
  ▼
Marker (conversion)
  │
  ▼
document.converted
  │
  ▼
AI extraction
  │
  ▼
document.analysis.completed
  │
  ├───────────────┐
  ▼               ▼
PostgreSQL      Embeddings
                  │
                  ▼
                Qdrant
```

## Steps

### 1. Upload → S3

| | |
|---|---|
| Input | Original file (PDF/JPEG/PNG) |
| Output | Object in S3; `DocumentVersion` v1 row |
| Owner | account-api (`DocumentService.finalize_upload`) |
| Queue | — (synchronous; RabbitMQ event published after) |
| Retry | n/a |
| Failure state | `document.status = pending` (never visible as processed) |
| Idempotency key | `document_version_id` |

Workflow: `POST /patients/{patient_id}/documents` (presigned URL) → client
uploads directly to S3 → `POST /documents/{id}/upload-confirm` → create
`DocumentProcessingJob(PDF_CONVERSION)` → publish `document.uploaded`.

### 2. Marker conversion

| | |
|---|---|
| Input | `document_id`, `document_version_id`, `storage_key` |
| Output | Markdown/JSON artifact in S3; `document.converted` |
| Owner | marker-worker (GPU VPS) |
| Queue | `document.convert` (DLQ: `document.convert.dlq`) |
| Retry | 3 attempts → DLQ |
| Failure state | `document_processing_jobs.status = failed` |
| Idempotency key | `document_version_id` (skip if already converted) |

### 3. AI extraction

| | |
|---|---|
| Input | `document.converted` (markdown/JSON artifact) |
| Output | `DocumentExtraction` row + embeddings in Qdrant; `document.analysis.completed` |
| Owner | ai-worker |
| Queue | `document.extract` (DLQ: `document.extract.dlq`) |
| Retry | 3 attempts → DLQ |
| Failure state | `document_extractions.status = failed`, low confidence → `REVIEW_REQUIRED` |
| Idempotency key | `document_version_id` |

AI pipeline inside ai-worker:

```text
load artifact → normalize → detect document type → split/chunk
→ LLM structured extraction → Pydantic validation → PostgreSQL → embeddings → Qdrant
```

### 4. Persistence

Structured data → PostgreSQL (source of truth). Embeddings → Qdrant
(search index only).

## Document state machine

```text
UPLOADING → UPLOADED → QUEUED → CONVERTING → CONVERTED
          → EXTRACTING → EXTRACTED → INDEXING → COMPLETED
                │
                └── PROCESS ──┬── FAILED
                              └── RETRY
```

Never use a single `status = "processing"`; the state machine lets clients show
`Uploaded ✓ / Converted ✓ / Analyzed ✓ / Added to medical record`.

## Failure handling summary

- Marker/LLM failure: retry 1-3 → DLQ.
- Invalid extraction (low confidence): `EXTRACTION_REVIEW_REQUIRED`, not `COMPLETED`.
- All retries are idempotent: a worker must not reprocess a version already
  marked completed.
