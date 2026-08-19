# Events

Event contracts shared by all services. Defined in `packages/contracts`
(`pdf-contracts`). **All services must use the same contracts.**

## Event catalog

```text
auth.otp.requested
document.upload.requested      account-api → objectstorage-worker (temp_path, no binary)
document.stored                objectstorage-worker → account-api (key, checksum)
document.uploaded              account-api → marker orchestrator
document.conversion.requested  marker orchestrator → marker-worker
document.converted             marker-worker → account-api / ai-worker
document.analysis.requested    ai orchestrator → ai-worker
document.analysis.completed    ai-worker → account-api
document.processing.failed     any worker → account-api (permanent failure)
```

Consumers: account-api owns every DB state transition; workers stay stateless
and only publish.

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
  "schema_version": 1,
  "document_id": "uuid",
  "document_version_id": "uuid | null",
  "patient_id": "uuid",
  "occurred_at": "datetime"
  "..."   // event-specific fields (storage_key, checksum, error_code, ...)
}
```

## Typed contracts (Python)

```python
class DocumentEvent(BaseModel):
    event_id: UUID
    schema_version: int = 1
    document_id: UUID
    document_version_id: UUID | None = None
    patient_id: UUID
    occurred_at: datetime = Field(default_factory=...)


class DocumentStored(DocumentEvent):
    storage_key: str
    mime_type: str
    size_bytes: int
    checksum: str
```

## Correlation

Every workflow carries a `correlation_id` (= `document_id`) so a single
document can be traced across S3 → RabbitMQ → Marker → AI → DB.

## Notes

- RabbitMQ carries **commands/events only** — never file payloads.
- Binary artifacts travel via S3; events carry IDs + storage keys.