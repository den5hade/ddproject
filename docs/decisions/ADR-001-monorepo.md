# ADR-001: Monorepo

- **Status**: Accepted
- **Date**: Proposed at project inception

## Context

Multiple services (account-api, marker-worker, marker-orchestrator, ai-worker,
web) plus shared packages. Option: one repo vs. per-service repos.

## Decision

One git repository for the whole monorepo. Services share code; commits are
atomic (a contract change can land together with its consumers); CI triggers
are path-scoped.

## Consequences

- Shared `uv.lock` pins one version set everywhere.
- Path-scoped CI/workflows keep builds focused.
- Monorepo ≠ one deployment unit (see [OVERVIEW](../architecture/OVERVIEW.md)).

## Status note

Details to finalize: branch protection, release tagging, versioning of shared
packages.