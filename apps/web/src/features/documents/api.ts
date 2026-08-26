import { api, authed } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type DocumentResponse = components["schemas"]["DocumentResponse"];
export type DocumentVersionResponse =
  components["schemas"]["DocumentVersionResponse"];
export type DocumentExtractionResponse =
  components["schemas"]["DocumentExtractionResponse"];
export type DownloadUrlResponse = components["schemas"]["DownloadUrlResponse"];
export type DocumentStatus = components["schemas"]["DocumentStatus"];

/** Statuses that still move — polling continues while in this set (plan §5.2). */
const NON_TERMINAL_STATUSES: ReadonlySet<DocumentStatus> = new Set([
  "pending",
  "processing",
]);

export function isProcessing(status: DocumentStatus): boolean {
  return NON_TERMINAL_STATUSES.has(status);
}

/** GET /patients/{patient_id}/documents — newest-first listing. */
export function listPatientDocuments(patientId: string) {
  return authed(() =>
    api.GET("/api/v1/patients/{patient_id}/documents", {
      params: { path: { patient_id: patientId } },
    }),
  );
}

/** GET /documents/{id} */
export function getDocument(documentId: string) {
  return authed(() =>
    api.GET("/api/v1/documents/{document_id}", {
      params: { path: { document_id: documentId } },
    }),
  );
}

/** GET /documents/{id}/versions */
export function getVersions(documentId: string) {
  return authed(() =>
    api.GET("/api/v1/documents/{document_id}/versions", {
      params: { path: { document_id: documentId } },
    }),
  );
}

/** GET /documents/{id}/extractions */
export function getExtractions(documentId: string) {
  return authed(() =>
    api.GET("/api/v1/documents/{document_id}/extractions", {
      params: { path: { document_id: documentId } },
    }),
  );
}

/** GET /documents/{id}/download → presigned URL (900s TTL). */
export function getDownloadUrl(documentId: string) {
  return authed(() =>
    api.GET("/api/v1/documents/{document_id}/download", {
      params: { path: { document_id: documentId } },
    }),
  );
}
