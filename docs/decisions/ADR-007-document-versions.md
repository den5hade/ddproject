# ADR-007: Documents are versioned

- **Status**: Accepted
- **Date**: Proposed at project inception

## Context

A specialist may correct a report/encounter; overwriting would lose the
original.

## Decision

`Document` is the stable metadata entity; content lives in immutable
`document_versions` rows (`UNIQUE(document_id, version)`), each with its own
S3 key. Processing jobs and extractions are anchored to a specific version.

## Consequences

- Full audit trail of content changes (v1, v2, ...).
- Extraction/processing is version-specific → idempotency keys align to
  `document_version_id`.
- Slight storage growth; mitigated by version retention policy (TODO).