# Medical Platform Documentation

This is the project map. Open this file first: it tells you where the API,
the workers, the database and the security documentation live, and how to run
the project locally.

## What is this project?

A workflow-driven medical platform: users register, upload PDF/image documents,
a GPU worker converts them, an AI worker extracts structured medical data into
PostgreSQL, and specialists access patient medical records through explicit
access grants.

- Monorepo layout and deployment model: [STRUCTURE.md](../STRUCTURE.md)
- Live documentation entry point: this file
- Original structure blueprint: [DOCS_STRUCTURE.md](DOCS_STRUCTURE.md)

## Architecture

- [System Architecture](architecture/OVERVIEW.md)
- [Components](architecture/COMPONENTS.md)
- [Data Flow](architecture/DATA_FLOW.md)
- [Processing Pipeline](architecture/PROCESSING_PIPELINE.md)
- [Scaling](architecture/SCALING.md)

## Services

- [Account API](services/ACCOUNT_API.md)
- [Marker Worker](services/MARKER_WORKER.md)
- [Marker Orchestrator](services/MARKER_ORCHESTRATOR.md)
- [AI Worker](services/AI_WORKER.md)

## Data

- [Database](data/DATABASE.md)
- [DB Models](data/DB_MODELS.md)
- [Storage (S3)](data/STORAGE.md)
- [Data Lifecycle](data/DATA_LIFECYCLE.md)

## Security

- [Authentication](security/AUTHENTICATION.md)
- [Authorization](security/AUTHORIZATION.md)
- [RBAC](security/RBAC.md)
- [Access Control](security/ACCESS_CONTROL.md)
- [Audit](security/AUDIT.md)
- [Privacy](security/PRIVACY.md)

## Messaging

- [RabbitMQ](messaging/RABBITMQ.md)
- [Events](messaging/EVENTS.md)

## API

Business-behavior guides per resource (machine-readable schema is served by
FastAPI at `/openapi.json` / `/docs` / `/redoc`):

- [auth](api/auth.md)
- [patients](api/patients.md)
- [documents](api/documents.md)
- [encounters](api/encounters.md)
- [access](api/access.md)
- [jobs](api/jobs.md)
- [analytics](api/analytics.md)

## Deployment

- [Local Setup](deployment/LOCAL.md)
- [Staging](deployment/STAGING.md)
- [Production](deployment/PRODUCTION.md)
- [GPU Worker](deployment/GPU_WORKER.md)

## Development

- [Setup](development/SETUP.md)
- [Contributing](development/CONTRIBUTING.md)
- [Testing](development/TESTING.md)
- [Migrations](development/MIGRATIONS.md)
- Dev & implementation plans: [OC_ACC_IMPLEMTATION.md](development/OC_ACC_IMPLEMTATION.md),
  [OAI_IMPLEMENTATION_PLAN.md](development/OAI_IMPLEMENTATION_PLAN.md),
  [OAI_DB_MODELS.md](development/OAI_DB_MODELS.md)

## Roadmap & Decisions

- [ROADMAP.md](ROADMAP.md)
- [Decisions (ADRs)](decisions/)
