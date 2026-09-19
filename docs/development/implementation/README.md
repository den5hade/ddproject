# Implementation Plans

This directory contains the reference model and index of implementation plans.

## Reference Model

[ORGS](../ORGS/) — canonical example of the four-document lifecycle (`IMPL_SPEC.md`, `IMPL_ARCH.md`, `IMPL_PLAN.md`, `IMPL_RPRT.md`) for substantial implementation work.

## Active Plans

*None currently — all feature contours complete.*

## Archived Plans (Completed)

| Plan | Scope | Completed | Archive |
|------|-------|-----------|---------|
| AUTH_FIX | Auth & security fixes (account status, OTP, refresh rotation, consumer resilience) | 2026-09-19 | [archive/AUTH_FIX_IMPL_PLAN_20260919/](../../archive/AUTH_FIX_IMPL_PLAN_20260919/) |
| DOC_PROC_DEV_FLOW | Dev-mode document processing pipeline (PDF → canonical.json → structured.md) | 2026-09-19 | [archive/DOC_PROC_DEV_FLOW_IMPL_PLAN_20260919/](../../archive/DOC_PROC_DEV_FLOW_IMPL_PLAN_20260919/) |
| TOPOLOGY | RabbitMQ topology bootstrap (queue declaration via rabbit-setup) | 2026-09-19 | [archive/TOPOLOGY_IMPL_PLAN_20260919/](../../archive/TOPOLOGY_IMPL_PLAN_20260919/) |

## Conventions

- One plan per feature contour (multi-phase, multi-service)
- Status markers `[x]` / `[ ]` mirrored in heading, summary table, and implementation order
- Each phase ends with tests + status update + pause for confirmation
- Depth lives in SPEC/ARCH (ORGS only); active plans stay executable roadmaps
- See `docs/development/operational/IMPL_PLAN_SCHEMA.md` for full schema