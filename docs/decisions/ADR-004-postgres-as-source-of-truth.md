# ADR-004: PostgreSQL as source of truth

- **Status**: Accepted
- **Date**: Proposed at project inception

## Context

Where does structured medical data live — PostgreSQL, Qdrant, or S3?

## Decision

PostgreSQL is the source of truth for all structured (medical) data. Qdrant is
only a search/index layer (embeddings/chunks) and can be rebuilt from
PostgreSQL + artifacts. S3 holds binaries. AI output must pass Pydantic and
domain validation before it reaches PostgreSQL.

## Consequences

- Qdrant can be dropped/rebuilt without data loss.
- AI extraction results are reviewable/correctable in PostgreSQL.
- Enforces a strict persistence boundary across services.