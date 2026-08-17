# Marker Worker

Ephemeral GPU worker that converts PDFs to Markdown/JSON with
[Maker](https://github.com/datalab-to/marker). Runs on the GPU VPS only — it is
started and stopped by the orchestrator.

## Purpose

Convert a PDF/image document stored in S3 into Markdown + JSON structure that
the ai-worker can run LLM extraction on.

## Contract

| | |
|---|---|
| Input | `document_id`, `document_version_id`, `storage_key` (from `document.convert`) |
| Output | `converted.md` / `converted.json` artifact in S3; `document.converted` event |
| Dependencies | S3, RabbitMQ, GPU (CUDA), Marker |
| Runtime | short-lived process, fully stateless |
| GPU requirements | NVIDIA GPU with CUDA |

## Flow

```text
RabbitMQ
    │
    │ document.convert
    ▼
Marker Worker
    │
    ├── S3 GET original.pdf
    │
    ├── Marker
    │
    ├── validate result
    │
    ├── S3 PUT result.md
    │
    └── publish document.converted
```

Marker worker knows nothing about users or the medical model — it only sees
IDs (`document_id`, `document_version_id`) and an S3 key.

## Queues

- Consumes: `document.convert`
- Publishes: `document.converted`
- DLQ: `document.convert.dlq`

## Failure handling & idempotency

- Retries: 3 attempts, then DLQ.
- **Idempotency:** if `document_processing_jobs.status = completed` for the
  version it was handed, it must NOT convert again (RabbitMQ may redeliver).

## Shutdown behavior

- On idle (queue drains) the orchestrator stops the VPS; the worker must handle
  `SIGTERM` gracefully (no local state to corrupt — stateless by design).
- Heartbeats are emitted so the orchestrator can detect a hung worker.