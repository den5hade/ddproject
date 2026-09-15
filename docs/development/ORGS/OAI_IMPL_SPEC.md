You are a senior Python backend engineer and software architect working on an existing medical-record platform.

I will provide you with an architecture/design document in Markdown describing the planned evolution of the **Organization domain and Organization API integration**.

Your task is to study that document together with the existing codebase and produce a **concrete, implementation-ready development plan** for the changes.

The goal is NOT to implement the changes yet.

The goal is to produce a detailed technical implementation specification that another AI coding agent or developer can follow step by step.

---

# 1. Primary sources of truth

Use the following sources in this order:

1. The provided architecture Markdown document — this is the primary specification for the requested Organization-domain changes.
2. The existing codebase — this is the source of truth for what is already implemented.
3. Existing tests, migrations, models, services, repositories, API routers, event contracts, and configuration — use these to understand existing conventions and avoid proposing duplicate or conflicting abstractions.

Do not assume that something is implemented simply because it is described in the architecture document.

Clearly distinguish:

* already implemented;
* partially implemented;
* planned;
* missing;
* requiring modification.

Do not redesign unrelated parts of the system.

Do not introduce technologies or architectural patterns that conflict with the existing project unless there is a strong technical reason. If you believe a deviation is necessary, explain why.

---

# 2. Main objective

Create a detailed implementation plan for evolving the existing `Organization` domain to support:

* INN;
* OGRN;
* legal address;
* **admin organization onboarding** — a `system_admin` creates an organization
  and connects a representative by email; the representative is authorized by an
  **organization-scoped role** (`OrganizationMembership.role`, never a global
  `AccountRole`); **no public self-registration** — a regular account cannot
  `POST /organizations`; multi-membership allowed;
* multiple organization licenses;
* multiple organization branches with separate addresses;
* organization API keys;
* secure API-key authentication;
* organization-to-platform integration API;
* single document upload through the integration API;
* bulk document upload;
* patient resolution by email;
* automatic creation of a pending client when the email does not exist;
* notification to the client;
* organization-provided document types;
* future organization-specific document schemas;
* API-key usage monitoring;
* audit/security requirements;
* future integration with the Federal Registry of Medical Organizations;
* proper organization-level data isolation;
* idempotency and external identifiers;
* integration with the existing document-processing pipeline.

The implementation plan must fit the current project rather than describing a greenfield system.

---

# 3. First: inspect the existing codebase

Before designing the implementation, inspect the repository thoroughly.

At minimum, identify:

## Database

* existing Organization model;
* OrganizationMembership;
* Account;
* Person;
* Patient;
* MedicalRecord;
* Document;
* DocumentVersion;
* DocumentProcessingJob;
* DocumentExtraction;
* Encounter;
* AuditLog;
* existing enums;
* existing foreign keys;
* indexes;
* unique constraints;
* Alembic migration structure.

## Authentication and authorization

Find:

* JWT authentication;
* current-user dependencies;
* RBAC implementation;
* roles;
* permissions;
* organization membership checks;
* patient access grants;
* existing authorization dependencies.

Understand how the project currently performs:

```text
authentication
authorization
resource ownership
organization isolation
```

Do not invent a second authorization system if an existing abstraction can be extended.

## Document processing

Inspect:

* document upload flow;
* S3/object storage integration;
* DocumentService;
* DocumentVersion creation;
* ProcessingJob creation;
* RabbitMQ events;
* ai-worker;
* canonical extraction;
* document type handling;
* notification-worker;
* existing document status transitions.

The Organization API must reuse the existing processing pipeline wherever possible.

## API

Inspect:

* router organization;
* router document;
* API versioning;
* Pydantic request/response models;
* dependency injection conventions;
* error handling;
* pagination;
* authentication patterns;
* response conventions.

## Tests

Inspect:

* model tests;
* repository tests;
* service tests;
* API tests;
* authentication tests;
* integration tests;
* worker tests.

Follow the existing testing style.

---

# 4. Produce an implementation gap analysis

Start the document with a table similar to:

| Area                  | Current state | Required state | Action |
| --------------------- | ------------- | -------------- | ------ |
| Organization          | ...           | ...            | modify |
| Organization onboarding | ...         | admin: `POST /admin/organizations`, `POST /admin/organizations/{id}/members`, membership role `owner|admin`, `created_by`, account reuse by email, no public self-registration | modify + create |
| Branches              | ...           | ...            | create |
| Licenses              | ...           | ...            | create |
| API Keys              | ...           | ...            | create |
| Document source       | ...           | ...            | modify |
| Patient resolution    | ...           | ...            | create |
| Bulk upload           | ...           | ...            | create |
| Notifications         | ...           | ...            | modify |
| Monitoring            | ...           | ...            | create |
| Schemas               | ...           | ...            | create |
| Registry verification | ...           | future         | defer  |

Base every "current state" statement on the actual repository.

---

# 5. Database implementation specification

Provide exact proposed SQLAlchemy 2.x models.

For every new or modified model specify:

* table name;
* Python class name;
* fields;
* Python types;
* SQL types;
* nullable/non-nullable;
* defaults;
* server defaults;
* foreign keys;
* relationships;
* indexes;
* unique constraints;
* check constraints;
* enum usage;
* cascade behavior;
* soft-delete/deactivation strategy if applicable.

At minimum evaluate these entities:

```text
Organization
OrganizationMembership (add organization-scoped `role` owner|admin|member)
OrganizationBranch
OrganizationLicense
OrganizationApiKey
OrganizationApiRequest
OrganizationUploadBatch
OrganizationUploadBatchItem
OrganizationDocumentSchema
```

Also identify required modifications to:

```text
Document
DocumentVersion
DocumentExtraction
DocumentProcessingJob
Account
Patient
MedicalRecord
AuditLog
Notification
```

Only recommend modifications where they are actually required.

---

# 6. SQLAlchemy models

For each model provide implementation-level detail.

Example format:

```python
class OrganizationBranch(Base):
    __tablename__ = "organization_branches"

    id: Mapped[UUID] = mapped_column(...)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey(...),
        nullable=False,
    )

    code: Mapped[str] = mapped_column(...)
    name: Mapped[str] = mapped_column(...)
    address: Mapped[str] = mapped_column(...)
```

Do not necessarily provide complete code for every model, but provide enough detail that implementation is unambiguous.

If the existing project has a model convention, follow it exactly.

---

# 7. Alembic migration plan

Provide a migration-by-migration plan.

Do not recommend one giant migration if the changes can be safely separated.

For every migration specify:

* migration purpose;
* tables/columns added;
* indexes;
* constraints;
* foreign keys;
* data migration requirements;
* backward compatibility concerns;
* upgrade sequence;
* downgrade considerations.

Pay particular attention to existing organizations.

For example:

```text
Existing Organization rows
        ↓
add nullable INN/OGRN
        ↓
data migration if necessary
        ↓
constraints/indexes
```

Do not require NOT NULL constraints that existing production data cannot satisfy.

---

# 8. Organization API-key architecture

Design the complete API-key implementation.

Specify:

* API-key format;
* generation;
* entropy;
* prefix;
* hashing;
* storage;
* display behavior;
* rotation;
* revocation;
* expiration;
* status;
* permissions/scopes;
* last-used timestamp;
* authentication dependency;
* failure behavior.

The raw API key must never be stored in plaintext.

Explain exactly how authentication should work:

```text
HTTP request
    ↓
extract API key
    ↓
hash
    ↓
lookup
    ↓
validate status
    ↓
validate expiration
    ↓
resolve organization
    ↓
resolve API-key permissions
    ↓
OrganizationAPIContext
    ↓
endpoint
```

Provide the proposed FastAPI dependency structure.

---

# 9. Separate human and machine authentication

Clearly distinguish:

## Organization management API

Human users:

```text
JWT
+
organization membership
+
organization_admin permission
```

## Organization integration API

Machine-to-machine:

```text
API Key
+
organization context
+
API-key permissions
```

Do not use an API key to manage API keys.

Explain which endpoints belong to each security model.

---

# 10. FastAPI endpoints

Provide a complete endpoint inventory.

For every endpoint specify:

* HTTP method;
* path;
* authentication mechanism;
* required role/permission;
* request model;
* response model;
* status codes;
* error cases;
* idempotency requirements;
* organization isolation requirements.

At minimum cover:

## Organization onboarding (admin)

```text
POST /api/v1/admin/organizations                       (new org + representative)
GET  /api/v1/admin/organizations                       (all organizations)
GET  /api/v1/admin/organizations/{id}                  (organization)
POST /api/v1/admin/organizations/{id}/members          (attach representative)
GET  /api/v1/admin/organizations/{id}/members          (list representatives)
```
(no public `POST /organizations`; gate: `system_admin`; representative access
is `OrganizationMembership.role`, no global role granted)

## Organization management

```text
GET    /organizations/me
PATCH  /organizations/me
```

## Branches

```text
GET
POST
PATCH
DELETE/deactivate
```

## Licenses

```text
GET
POST
PATCH
DELETE/deactivate
```

## API Keys

```text
GET
POST
REVOKE/DELETE
ROTATE
```

## Integration

```text
POST /api/v1/integration/documents
POST /api/v1/integration/documents/bulk
GET  /api/v1/integration/documents/{id}
GET  /api/v1/integration/batches/{id}
GET  /api/v1/integration/batches/{id}/items
GET  /api/v1/integration/jobs/{id}
```

Adjust the exact paths to match the existing project's API conventions.

---

# 11. Pydantic schemas

Specify every required request/response schema.

At minimum:

```text
OrganizationCreate
OrganizationUpdate
OrganizationResponse

OrganizationBranchCreate
OrganizationBranchUpdate
OrganizationBranchResponse

OrganizationLicenseCreate
OrganizationLicenseUpdate
OrganizationLicenseResponse

OrganizationApiKeyCreate
OrganizationApiKeyResponse
OrganizationApiKeyListItem

OrganizationDocumentUploadRequest
OrganizationDocumentUploadResponse

OrganizationBulkUploadRequest
OrganizationBulkUploadResponse

OrganizationBatchResponse
OrganizationBatchItemResponse
```

For every schema specify:

* fields;
* types;
* optionality;
* validation;
* normalization;
* maximum lengths;
* enums;
* nested structures.

---

# 12. INN and OGRN validation

Define the validation strategy.

Determine:

* acceptable formats;
* normalization — strip **all** whitespace so only canonical digits persist;
* whether checksum validation should be implemented;
* whether uniqueness is database-enforced (yes — unique indexes are the
  idempotency source of truth; service pre-check is UX-only);
* whether values are optional for existing organizations;
* when they become required (required at admin onboarding
  `POST /admin/organizations`);
* shared validators reused by `OrganizationCreate`, `OrganizationUpdate` and
  future registry verification.

Do not blindly implement validation based only on frontend assumptions.

If there are domain-specific uncertainties, explicitly mark them as decisions requiring confirmation.

---

# 13. Branch architecture

Specify:

```text
Organization 1:N OrganizationBranch
```

Explain:

* branch code;
* uniqueness;
* active/inactive state;
* address;
* branch references in documents;
* behavior when a branch is deactivated;
* whether historical documents retain the branch reference.

Do not allow deleting a branch in a way that breaks historical medical records.

---

# 14. License architecture

Specify:

```text
Organization 1:N OrganizationLicense
```

Define:

* license number;
* license type;
* status;
* issued date;
* expiration date;
* scope;
* issuer;
* uniqueness;
* historical behavior;
* future verification support.

Design the model so that future government-registry verification can be added without coupling the domain directly to an external provider.

---

# 15. Patient resolution

Design a dedicated service for:

```text
Organization + email
        ↓
Account
        ↓
Person
        ↓
Patient
        ↓
MedicalRecord
```

Cover all cases:

1. Account exists and Patient exists.
2. Account exists but Patient does not.
3. Account does not exist.
4. Account exists but email is not verified.
5. Concurrent requests try to create the same account.

Use existing unique constraints and transaction behavior.

Explain how race conditions are handled.

Do not create duplicate users.

---

# 16. Automatic client creation

The expected flow is:

```text
Organization sends email
        ↓
No existing account
        ↓
Create pending Account
        ↓
Create Person
        ↓
Create Patient
        ↓
Create MedicalRecord
        ↓
Create Document
        ↓
Process document
        ↓
Notify client
```

Do not mark the account as email-verified automatically.

Reuse the existing account lifecycle if possible.

---

# 17. Document ingestion

Design the Organization document ingestion flow using existing document infrastructure.

The intended architecture is:

```text
Organization API
      ↓
API-key authentication
      ↓
Patient resolution
      ↓
Document creation
      ↓
DocumentVersion
      ↓
S3/object storage
      ↓
ProcessingJob
      ↓
RabbitMQ
      ↓
existing AI/document pipeline
      ↓
canonical.json
      ↓
structured representation
      ↓
notification
```

Explicitly identify which existing services should be reused and which new services should be introduced.

Do not create a second document-processing pipeline.

---

# 18. Document source

Determine the exact database representation for:

```text
organization_id
organization_branch_id
uploaded_by_account_id
```

Explain why each field is required or not required.

Preserve historical source information even if a branch is later deactivated.

---

# 19. Document type

Existing platform document types must be preserved.

Organizations should be able to provide a document type when submitting a document.

Design:

```text
organization-provided type
        +
platform document type
        +
AI detection if necessary
```

Specify how conflicts should be handled.

Do not silently discard the organization's provided type.

---

# 20. External IDs and idempotency

Design support for:

```text
external_id
Idempotency-Key
```

Explain:

* uniqueness scope;
* database constraints;
* duplicate request behavior;
* retry behavior;
* timeout behavior;
* how organizations can safely retry requests.

A repeated request must not create duplicate medical documents.

---

# 21. Bulk upload architecture

Do not design bulk upload as one large synchronous transaction.

Use:

```text
Batch
    ↓
Batch Items
    ↓
individual Documents
    ↓
individual ProcessingJobs
```

Specify:

* maximum batch size;
* request format;
* asynchronous behavior;
* batch status;
* item status;
* partial failures;
* retry;
* idempotency;
* progress;
* result retrieval.

Provide the exact proposed API contract.

---

# 22. Notification flow

Integrate with the existing notification architecture.

The organization workflow should result in a client notification.

Design at least:

```text
document received
document processing completed
document processing failed
```

Determine which notifications should actually be implemented in the first version.

Do not include sensitive medical information in email.

The notification should provide:

* organization name;
* document availability;
* appropriate generic information;
* secure link to the platform.

Use the existing notification worker if possible.

---

# 23. Organization-specific document schemas

Design the future-ready architecture for:

```text
OrganizationDocumentSchema
```

Support:

* schema name/code;
* version;
* description;
* platform document type;
* schema definition;
* status;
* creator;
* immutable published versions.

Explain how organization schemas interact with:

```text
Document
DocumentExtraction
canonical.json
Pydantic validation
LLM extraction
```

Do not allow organization-defined schemas to compromise the platform's canonical data model.

Clearly separate:

```text
platform canonical schema
```

from:

```text
organization-specific extraction schema
```

---

# 24. API monitoring

Design API-key usage monitoring.

At minimum capture:

```text
organization_id
api_key_id
request_id
HTTP method
path/endpoint
status code
duration
timestamp
```

Potentially:

```text
request size
response size
IP
user agent
error code
```

Do NOT store:

* raw request body;
* medical document content;
* canonical JSON;
* patient PII unless explicitly necessary.

Explain the difference between:

```text
API usage logs
security audit logs
medical audit logs
```

Reuse the existing `AuditLog` appropriately instead of turning it into a generic HTTP access log.

---

# 25. Rate limiting

Specify a rate-limiting strategy.

It should be:

* per API key;
* configurable;
* suitable for bulk upload;
* independent from business logic;
* compatible with future scaling.

Do not hardcode arbitrary limits into endpoint implementations without configuration.

---

# 26. Organization isolation

This is a critical security requirement.

Every organization integration resource must be scoped to the authenticated organization.

For example:

```text
organization A API key
    ↓
document belonging to organization B
    ↓
DENY
```

Specify the exact authorization checks for:

* documents;
* batches;
* batch items;
* jobs;
* branches;
* licenses;
* API keys;
* schemas.

Pay particular attention to IDOR vulnerabilities.

---

# 27. Service/repository architecture

Provide the exact proposed structure.

For example:

```text
repositories/
    organization.py
    organization_branch.py
    organization_license.py
    organization_api_key.py
    organization_upload_batch.py
    organization_document_schema.py

services/
    organization.py
    organization_branch.py
    organization_license.py
    organization_api_key.py
    organization_patient_resolver.py
    organization_document.py
    organization_bulk_upload.py
    organization_schema.py
```

But first inspect the actual repository structure and adapt this to existing conventions.

Do not blindly create new architectural layers if equivalent abstractions already exist.

---

# 28. Event architecture

Specify all new events required by the Organization integration workflow.

For example:

```text
organization.document.submitted
organization.batch.created
organization.batch.completed
organization.patient.created
```

Determine whether existing event infrastructure can be reused.

Specify:

* event payload;
* event version;
* identifiers;
* idempotency;
* retry behavior;
* failure handling.

Do not put sensitive medical information unnecessarily into event payloads.

---

# 29. Registry verification architecture

Do NOT implement the actual Federal Registry integration unless the repository already contains it.

Instead, design the extension point.

Use an abstraction such as:

```python
class OrganizationRegistryProvider(Protocol):
    async def verify(
        self,
        inn: str,
        ogrn: str,
    ) -> OrganizationVerificationResult:
        ...
```

Specify:

* domain interface;
* verification status;
* provider abstraction;
* persistence model if required;
* future integration boundary.

The Organization domain must not depend directly on a specific government API.

---

# 30. Observability

Inspect the existing observability implementation.

Specify:

* logs;
* metrics;
* tracing;
* request IDs;
* API-key authentication failures;
* organization API latency;
* document ingestion failures;
* batch failures.

Do not introduce an entirely new observability stack without checking what already exists.

---

# 31. Testing strategy

Create a detailed test plan.

## Unit tests

Cover:

* INN validation;
* OGRN validation;
* API key generation;
* hashing;
* expiration;
* revocation;
* patient resolver;
* batch state transitions;
* schema validation.

## Integration tests

Cover:

```text
Organization
→ API Key
→ Patient
→ Document
→ ProcessingJob
→ RabbitMQ
→ notification
```

## Security tests

Explicitly test:

* organization A cannot access organization B;
* revoked key rejected;
* expired key rejected;
* inactive organization rejected;
* insufficient API-key permission rejected;
* document IDOR rejected;
* batch IDOR rejected;
* job IDOR rejected;
* duplicate requests do not create duplicate documents.

## Concurrency tests

Test simultaneous creation of:

* Account;
* Patient;
* Document.

---

# 32. Implementation order

Produce a phased implementation plan.

Prefer vertical slices rather than creating all database tables first.

A likely structure is:

```text
Phase 1  — Organization core
Phase 2  — Branches
Phase 3  — Licenses
Phase 4  — API Keys
Phase 4a — Organization onboarding (admin)
Phase 4b — Organization context & membership-role authorization
Phase 4c — API-key authentication & verification policy
Phase 4d — Integration API + patient resolver
Phase 4e — Bulk upload
Phase 4f — Notifications
Phase 4g — Organization schemas
Phase 4h — Monitoring
Phase 4i — Registry verification + ownership/invite
```

Adjust this order after inspecting the codebase. Key constraints:

- Onboarding (`POST /admin/organizations` / `POST /admin/organizations/{id}/members`)
  is **system-admin-only**; no public self-registration (`POST /organizations`).
  No pre-existing role is needed to be connected — the representative becomes
  `owner`/`admin` **as a result** of the admin provisioning.
- Account resolution reuses an existing account by normalized email (only creates
  a new PENDING account when there is no match; never duplicates an email).
- One account may hold memberships in several organizations; a second membership
  for the same `(organization_id, account_id)` is rejected (409).
- Organization authorization uses `OrganizationMembership.role`; onboarding grants
  **no** global `organization_admin` `AccountRole` (the legacy global check on
  `/organizations/me/*` migrates to the membership role in 4b).
- `Organization.status = ACTIVE` is necessary-not-sufficient for integration
  access: verification status (`≠ REJECTED`) gates API-key/integration policy.
- DB unique indexes are the idempotency source of truth for INN/OGRN
  (`IntegrityError` → rollback → 409).

For every phase specify:

* objective;
* files to modify;
* files to create;
* database changes;
* APIs;
* services;
* tests;
* dependencies on previous phases;
* acceptance criteria.

---

# 33. File-level implementation plan

This is especially important.

For every proposed change, identify the actual repository path.

For example:

```text
src/account_api/models/organization.py
src/account_api/models/organization_api_key.py
src/account_api/services/organization_api_key.py
src/account_api/api/routes/organization.py
src/account_api/api/routes/integration.py
src/account_api/schemas/organization.py
alembic/versions/xxxx_add_organization_legal_data.py
tests/api/test_organization_api_keys.py
```

Do not invent paths.

Inspect the repository and use its actual structure.

If an existing file should be modified, say exactly why.

---

# 34. Commit strategy

Produce a recommended sequence of small, logically isolated commits.

For example:

```text
1. Add organization legal information
2. Add organization branches
3. Add organization licenses
4. Add organization API key model
5. Add admin organization onboarding: POST /admin/organizations,
   POST /admin/organizations/{id}/members, OrganizationMembership.role,
   created_by_account_id, account reuse by email, no global role,
   IntegrityError → 409 (no public POST /organizations)
6. Add organization context & membership-role authorization (migrate
   /organizations/me/* off the legacy global organization_admin role)
7. Add API key authentication + verification policy
8. Add patient resolver
9. Add organization document source + single integration upload
10. Add notification flow
11. Add bulk upload
12. Add API monitoring
13. Add organization document schemas
```

Adapt the actual commit structure based on the repository.

Each commit should ideally:

* compile;
* pass relevant tests;
* be independently reviewable;
* avoid mixing unrelated concerns.

---

# 35. Do not implement yet

The output must be a **plan/specification only**.

Do not:

* modify files;
* create migrations;
* create models;
* run destructive commands;
* change production configuration;
* install dependencies unless necessary for inspection.

Your final output should tell a developer exactly what needs to be implemented, where, and in what order.

---

# 36. Identify unresolved architectural decisions

At the end, provide a section:

```text
Open Decisions
```

Include only decisions that genuinely cannot be determined from the architecture document or repository.

Examples:

* exact INN/OGRN validation rules;
* exact API rate limits;
* maximum bulk size;
* whether organization API may read document status;
* notification timing;
* organization-specific schema format;
* API key scope granularity;
* retention period for API request logs.

For each decision provide:

```text
Decision
Why it matters
Recommended default
Alternative
```

Do not block the entire implementation on minor decisions.

---

# 37. Final deliverable structure

Produce the final implementation specification using this structure:

```text
# Organization Domain — Implementation Specification

## 1. Executive Summary

## 2. Current State Analysis

## 3. Gap Analysis

## 4. Target Architecture

## 5. Domain Model Changes

## 6. Database Schema

## 7. Alembic Migration Plan

## 8. API-Key Architecture

## 9. Authentication & Authorization

## 10. Organization Management API

## 11. Organization Integration API

## 12. Patient Resolution

## 13. Document Ingestion

## 14. Bulk Upload

## 15. Notification Flow

## 16. Organization Document Schemas

## 17. API Monitoring

## 18. Security Model

## 19. Event Model

## 20. Service & Repository Structure

## 21. Pydantic Schemas

## 22. Testing Strategy

## 23. Implementation Phases

## 24. File-by-File Change Plan

## 25. Commit Plan

## 26. Definition of Done

## 27. Open Decisions

## 28. Risks
```

The final document should be detailed enough that implementation can begin immediately after review.

The most important principle is:

> Extend the existing architecture instead of creating a parallel architecture.

Reuse existing:

* authentication;
* RBAC;
* OrganizationMembership;
* Document;
* DocumentVersion;
* DocumentProcessingJob;
* DocumentExtraction;
* S3;
* RabbitMQ;
* canonical processing;
* notification infrastructure;
* AuditLog.

Only introduce new abstractions where the current system genuinely lacks the required capability.

Before finalizing the plan, verify every proposed change against the actual repository and explicitly identify any assumptions.
