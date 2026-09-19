# Documentation Structure

This document describes the organization of the `docs/` directory.

## Top-Level Overview

```
docs/
├── README.md                 # Entry point — start here
├── DOCS_STRUCTURE.md         # This file
├── ROADMAP.md                # Canonical milestones
├── DDPROJECT.md              # Product concept (Russian)
├── PROJECT_STATUS.md         # Living status (English, concise, updated in place)
├── PROJECT_STATUS_LATEST.md  # Symlink → latest archive snapshot
│
├── architecture/             # System architecture (5 docs)
├── services/                 # Service documentation (4 docs)
├── data/                     # Data layer (4 docs)
├── security/                 # Security (6 docs)
├── messaging/                # Messaging (2 docs)
├── api/                      # API behavior guides (7 docs)
├── deployment/               # Deployment environments (4 docs)
│
├── development/              # Development documentation
│   ├── operational/          # Day-to-day contributor guides
│   ├── implementation/       # Active implementation plans
│   ├── design/               # Technical design documents
│   └── ORGS/                 # Reference model (4-document lifecycle)
│
├── decisions/                # Architecture Decision Records
│   └── proposals/            # Design proposals (pre-ADR)
│
└── archive/                  # Historical/superseded documents
```

## Directory Purposes

### `architecture/`
System-level architecture: overview, components, data flow, processing pipeline, scaling. Stable, rarely changes.

### `services/`
Per-service documentation: responsibilities, boundaries, "does NOT" lists, layering, DI conventions, endpoints. One file per service.

### `data/`
Data layer: database architecture (WHY), concrete schema (WHAT), S3 storage conventions, data lifecycle matrix.

### `security/`
Security contracts: authentication, authorization (RBAC + ABAC), access control algorithm, audit, privacy. Central security reference.

### `messaging/`
RabbitMQ topology, event catalog, versioning, correlation. Transport only — not a database.

### `api/`
Business-behavior guides per resource. Not OpenAPI duplicates — describe authorization, workflows, invariants.

### `deployment/`
Environment-specific: local, staging, production, GPU worker. Infrastructure as code references.

### `development/operational/`
Contributor-facing: setup, contributing conventions, testing, migrations, exception handling, implementation plan schema.

### `development/implementation/`
**Active** implementation plans for in-progress feature contours. Each plan is a status-tracked roadmap (phases, verification, file changes). Named directories match the feature contour.

Reference model: `development/ORGS/` — canonical four-document lifecycle (`IMPL_SPEC`, `IMPL_ARCH`, `IMPL_PLAN`, `IMPL_RPRT`).

### `development/design/`
Technical design documents that inform implementation but are not implementation plans themselves (e.g., AI prompt design, DB model rationale).

### `development/ORGS/`
Reference implementation documentation for the Organization domain. Demonstrates the full SPEC → ARCH → PLAN → RPRT lifecycle. Do not copy literally; use as convention guide.

### `decisions/`
Accepted Architecture Decision Records (ADR-001+). Immutable once accepted.

### `decisions/proposals/`
Design proposals under review. May become ADRs or be archived.

### `archive/`
Historical documents: superseded plans, dated status snapshots, rejected proposals. Preserved for context, not active reference.

## Naming Conventions

| Type | Pattern | Example |
|------|---------|---------|
| General | `DESCRIPTIVE_NAME.md` | `DATABASE.md`, `ACCESS_CONTROL.md` |
| Implementation plan (active) | `implementation/<FEATURE>/IMPL_PLAN.md` | `implementation/DOC_PROC_DEV_FLOW/IMPL_PLAN.md` |
| Implementation lifecycle (ORGS) | `ORGS/IMPL_{SPEC,ARCH,PLAN,RPRT}.md` | `ORGS/IMPL_SPEC.md` |
| ADR | `decisions/ADR-NNN-short-title.md` | `decisions/ADR-001-monorepo.md` |
| Proposal | `decisions/proposals/DESCRIPTIVE_NAME.md` | `decisions/proposals/MARKER_AS_SERVICE.md` |
| Archive | `archive/ORIGINAL_NAME[_DATE].md` | `archive/PROJECT_STATUS_090426.md` |

## Adding New Documentation

1. **General doc** → place in appropriate top-level category (`architecture/`, `security/`, etc.)
2. **Active implementation plan** → create `development/implementation/<FEATURE>/IMPL_PLAN.md` following `IMPL_PLAN_SCHEMA.md`
3. **Technical design** → place in `development/design/`
4. **ADR** → next number in `decisions/ADR-NNN-*.md`
5. **Proposal** → `decisions/proposals/`

Do not create docs for symmetry. Prefer semantic organization.

## Navigation

Start at `README.md` — it links to all major sections.