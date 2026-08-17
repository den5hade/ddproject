# Jobs API

Document processing job state.

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/jobs/{id}` | One processing job |
| `GET` | `/api/v1/documents/{id}/jobs` | All jobs of a document |

## Job model

`document_processing_jobs` (`ProcessingJobType`):
`pdf_conversion / ai_extraction / embedding`.

Status: `queued / running / succeeded / retrying / failed` + `attempts`,
`started_at`, `finished_at`, `error_code`, `error_message`.

## Behavior

- Jobs are created by account-api and updated by event handlers
  (`document_converted`, `document_analysis_requested`).
- Clients poll this endpoint to render progress:
  `Uploaded ✓ → Converted ✓ → Analyzed ✓`.
- Job history is retained for diagnostics (not user-deletable).

## Related

See [architecture/PROCESSING_PIPELINE.md](../architecture/PROCESSING_PIPELINE.md)
for the state machine and retry/DLQ policy.