# Data Lifecycle

Where data lives, who can access it, how long it lives, how it is deleted —
for every major object. Useful for developers and for future compliance
reviews.

## End-to-end lifecycle

```text
User registration
       ↓
Personal data (Account → Person)
       ↓
Document upload (metadata in PG, binary in S3)
       ↓
Processing (Marker → AI)
       ↓
Extracted medical data (PostgreSQL)
       ↓
Analytics (derived from extraction)
       ↓
Archive / retention
       ↓
Deletion
```

## Per-object matrix

| Object | Where stored | Who can access | Retention | Deletable? | Audited? |
|--------|--------------|----------------|-----------|------------|----------|
| Account | PostgreSQL (`accounts`) | owner, system admin | as long as account lives | account deletion (soft, `status=deleted`) | ✅ (login/logout) |
| Person | PostgreSQL (`persons`) | owner (person/patient), specialists w/ grant | lifetime | with account | ✅ |
| Patient / MedicalRecord | PostgreSQL | owner; specialists via `patient_access_grants` | lifetime | yes (owner) | ✅ |
| Document metadata | PostgreSQL (`documents`, `document_versions`) | owner; grant holders (`can_view_documents`) | until deleted/archived | yes (owner) | ✅ view/download/upload |
| Document binary | S3 (`original/`, `converted/`) | via presigned URLs only | retention window (TODO) | yes (owner) | ✅ via URL generation |
| ProcessingJobs | PostgreSQL | owner via job endpoints | cleanup policy (TODO) | no (history) | ✅ |
| Extraction | PostgreSQL (`document_extractions`) | owner; grant `can_view_extractions` | lifetime of record | yes (owner) | ✅ |
| Qdrant vectors | Qdrant | search feature only, never direct | rebuildable from artifacts | yes (rebuild) | ❌ (derived) |
| AccessGrant | PostgreSQL (`patient_access_grants`) | patient (grantor), auditor | grant lifetime (`expires_at`) | yes (revoke) | ✅ grant/revoke |
| AuditLog | PostgreSQL (`audit_logs`) | system admin, compliance | **retained** (append-only) | **no** | n/a |

## Principles

- Binary and metadata share a lifecycle: deleting a document deletes metadata,
  versions and (after retention) S3 objects.
- Access grants are time-boxed (`expires_at`) and revocable
  (`status = revoked`) — access is not permanent.
- Audit logs are append-only and subject to retention, not ad-hoc deletion.
- Qdrant is derived data; it can always be rebuilt from PostgreSQL + S3.

## TODOs (compliance review)

- Define concrete retention windows (S3 objects, audit logs, sessions).
- Define account/patient deletion semantics (soft vs. hard delete cascades).
- Define consent model (`patient_consents`) — separate from Access.
- Document backup/restore and PITR policy.