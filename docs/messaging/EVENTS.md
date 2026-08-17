# Events

Event contracts shared by all services. Defined in `packages/contracts`
(`pdf-contracts`). **All services must use the same contracts.**

## Event catalog

```text
auth.otp.requested
document.uploaded
document.conversion.requested
document.converted
document.analysis.requested
document.analysis.completed
document.processing.failed
```

## Versioning

Every event carries a `schema_version`. Example:

```text
document.converted v1  ──▶  (AI worker may still consume v1)
document.converted v2  (marker worker starts publishing v2)
```

Versioned contracts prevent the microservice architecture from breaking on
every schema change. Consumers should tolerate `schema_version <= N`.

## Canonical payload shape

```json
{
  "event_id": "uuid",
  "event_type": "document.converted",
  "schema_version": 1,
  "document_id": "uuid",
  "document_version_id": "uuid",
  "patient_id": "uuid",
  "storage_key": "...",
  "occurred_at": "..."
}
```

## Typed contracts (Python)

```python
class DocumentConverted(BaseModel):
    event_id: UUID
    document_id: UUID
    document_version_id: UUID
    patient_id: UUID
    output_storage_key: str
    occurred_at: datetime
```

## Correlation

Every workflow carries a `correlation_id` (= `document_id`) so a single
document can be traced across S3 → RabbitMQ → Marker → AI → DB.

## Notes

- RabbitMQ carries **commands/events only** — never file payloads.
- Binary artifacts travel via S3; events carry IDs + storage keys.