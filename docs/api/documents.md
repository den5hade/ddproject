# Documents API

Upload workflow, versions, extractions.

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/v1/patients/{patient_id}/documents` | Create doc + presigned upload URL |
| `POST` | `/api/v1/documents/{id}/upload-confirm` | Finalize upload, create version + job |
| `GET` | `/api/v1/documents/{id}` | Doc metadata |
| `GET` | `/api/v1/documents/{id}/versions` | Version list |
| `POST` | `/api/v1/documents/{id}/versions` | New version |
| `GET` | `/api/v1/documents/{id}/extractions` | Extraction results |
| `GET` | `/api/v1/documents/{id}/jobs` | Processing jobs for the document |

## Authorization

- Patient: own patient only.
- Specialist: requires `can_upload_documents` / `can_view_documents` grant flag.

## Upload workflow

1. Create document → returns presigned upload URL (`UploadUrlResponse`).
2. Client uploads the binary **directly to S3** (never through the API).
3. `upload-confirm` → creates `DocumentVersion` v1 (`status=uploaded`),
   creates `DocumentProcessingJob(PDF_CONVERSION)`, publishes
   `document.uploaded`, sets `document.status=processing`.
4. Processing updates the job/status via events (`document.converted`,
   `document.analysis.completed`).

## Quota

Free (unsubscribed) accounts are limited to **10 documents**; enforced at
upload time.

## S3 rule

Never expose S3 keys to the client — use presigned URLs only
(see [data/STORAGE.md](../data/STORAGE.md)). A presigned upload without
`upload-confirm` does not create a viewable document.
