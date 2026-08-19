# Documents API

Upload workflow, versions, extractions, processing jobs.

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/v1/patients/{patient_id}/documents` | Upload a document (multipart) |
| `GET` | `/api/v1/documents/{id}` | Doc metadata |
| `GET` | `/api/v1/documents/{id}/versions` | Version list |
| `POST` | `/api/v1/documents/{id}/versions` | Upload a new version (multipart) |
| `GET` | `/api/v1/documents/{id}/extractions` | Extraction results |
| `GET` | `/api/v1/documents/{id}/jobs` | Processing jobs for the document |
| `GET` | `/api/v1/documents/{id}/download` | Presigned download URL (`?version_id=`) |
| `GET` | `/api/v1/jobs/{job_id}` | Single processing job |

Multipart uploads send the binary in the `upload` part plus form fields
`title`, `document_type`, `encounter_id` (all optional).

## Authorization

- Patient: own patient only.
- Specialist: requires `can_upload_documents` / `can_view_documents` grant flag.
- Uploads require `can_upload_documents`; reads/downloads require
  `can_view_documents`.

## Upload workflow

1. `POST /patients/{patient_id}/documents` → account-api stages the file,
   creates `Document` + `DocumentVersion` v1 (`status=pending`) and a
   `PDF_CONVERSION` job, then publishes `document.upload.requested`.
2. **objectstorage-worker** normalizes and uploads the staged file to S3 under
   the immutable key (see [data/STORAGE.md](../data/STORAGE.md)), then
   publishes `document.stored`.
3. account-api persists the storage key/checksum, sets
   `document.status = processing`, and publishes `document.uploaded`.
4. Processing updates the job/status via events (`document.converted`,
   `document.analysis.completed`, `document.processing.failed`).

## Quota

Free (unsubscribed) accounts are limited to **10 documents**; enforced at
upload time. Subscribed accounts are exempt.

## S3 rule

Never expose S3 keys to the client — downloads use presigned GET URLs only
(see [data/STORAGE.md](../data/STORAGE.md)). If object storage is not
configured, downloads return `503`.
