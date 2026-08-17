# Data Flow

Where data lives and how it moves between components.

## Storage roles

| Store | Holds | Role |
|-------|-------|------|
| PostgreSQL | accounts, persons, patients, specialists, organizations, medical records, encounters, documents metadata, versions, processing jobs, extractions, access grants, audit logs | **Source of truth** |
| S3 | original PDFs/images, converted Markdown/JSON artifacts | Source of binary artifacts |
| Qdrant | chunks + embeddings + metadata | Search/index layer (never source of truth) |
| RabbitMQ | commands/events in transit | Transport, not a database |
| Redis | OTP codes, rate limiting | Ephemeral cache |

## Pipeline flow

```text
Upload
  │
  ▼
S3  (presigned upload, binary never proxied through account-api)
  │
  ▼
document.uploaded
  │
  ▼
Marker (GPU VPS, ephemeral)
  │
  ▼
document.converted
  │
  ▼
AI extraction (ai-worker)
  │
  ▼
document.analysis.completed
  │
  ├──────────────┐
  ▼              ▼
PostgreSQL    Embeddings → Qdrant
```

## API flow

```text
Client ── HTTPS ── nginx ── /api/* ── account-api ── PostgreSQL
                          │
                          └─ presigned URL ── S3 (direct client upload)
```

## Key invariants

- Medical/structured data → PostgreSQL only.
- Binary artifacts → S3 only, referenced by key, never by local path.
- S3 keys are never exposed to clients; downloads/uploads use **presigned URLs**.
- AI output → Pydantic validation → domain service → repository → PostgreSQL.
- Qdrant is derived from PostgreSQL artifacts and can be rebuilt.

## Correlation

Every document workflow carries a `correlation_id` (document_id) end to end so
a single document can be traced across S3 → RabbitMQ → Marker → AI → DB.
