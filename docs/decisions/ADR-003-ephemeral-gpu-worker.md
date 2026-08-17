# ADR-003: Ephemeral GPU worker

- **Status**: Accepted
- **Date**: Proposed at project inception

## Context

Marker conversion needs a GPU (CUDA), which is expensive to keep running 24/7.

## Decision

Marker runs on an **ephemeral GPU VPS** that the orchestrator starts when the
conversion queue grows past a threshold and stops after an idle timeout. The
worker is fully stateless (no local DB, no local files) so the VPS can be
switched on/off and the provider swapped freely.

## Consequences

- GPU cost tracks actual work (see [SCALING](../architecture/SCALING.md)).
- Startup latency on first conversion batch (GPU boot + image pull).
- Orchestrator must handle slow/failed GPU startups
  (`MARKER_START_TIMEOUT_SECONDS`).

## Status note

Threshold/scheduling policy refinements are described but not yet tuned.