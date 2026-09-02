import { api, authed } from "@/lib/api/client";
import { parseApiError } from "@/lib/api/errors";
import {
  getAccessToken,
  refreshTokens,
} from "@/features/auth/session";
import type { components } from "@/lib/api/schema";

export type DocumentResponse = components["schemas"]["DocumentResponse"];
export type DocumentVersionResponse =
  components["schemas"]["DocumentVersionResponse"];
export type DocumentExtractionResponse =
  components["schemas"]["DocumentExtractionResponse"];
export type DownloadUrlResponse = components["schemas"]["DownloadUrlResponse"];
export type DocumentStatus = components["schemas"]["DocumentStatus"];
export type CanonicalDataResponse =
  components["schemas"]["CanonicalDataResponse"];

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

/**
 * GET /documents/{id}/canonical — persisted canonical data of the latest
 * succeeded extraction (DB-only, no S3 round-trip). 404 when the document
 * has not been processed yet.
 */
export function getCanonical(documentId: string) {
  return authed(() =>
    api.GET("/api/v1/documents/{document_id}/canonical", {
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

/*
 * Multipart upload transport (plan §5.2, decision D5).
 * XHR (not fetch) for upload progress + abort. Silent 401 refresh
 * with a single replay, mirroring authed() semantics.
 */

export interface UploadOptions {
  documentType?: string;
  title?: string;
  encounterId?: string;
  onProgress?: (percent: number) => void;
}

export interface UploadHandle {
  promise: Promise<DocumentResponse>;
  abort: () => void;
}

export function uploadDocument(
  patientId: string,
  file: File,
  options: UploadOptions = {},
): UploadHandle {
  const xhr = new XMLHttpRequest();
  let aborted = false;

  const promise = new Promise<DocumentResponse>((resolve, reject) => {
    const send = () => {
      const token = getAccessToken();
      xhr.open("POST", `/api/v1/patients/${patientId}/documents`);
      if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
      xhr.responseType = "json";

      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable && !aborted) {
          options.onProgress?.(Math.round((event.loaded / event.total) * 100));
        }
      };

      xhr.onload = async () => {
        if (aborted) return;
        if (xhr.status === 201) {
          resolve(xhr.response as DocumentResponse);
          return;
        }
        // Single silent refresh + replay on expired access token
        if (
          xhr.status === 401 &&
          getAccessToken() !== null &&
          (await refreshTokens())
        ) {
          send();
          return;
        }
        reject(parseApiError(xhr.status, xhr.response));
      };

      xhr.onerror = () => {
        if (!aborted) reject(parseApiError(0, undefined));
      };

      xhr.onabort = () => {
        /* CANCEL event dispatched by the caller; no error surfaced */
      };

      const form = new FormData();
      form.append("upload", file);
      form.append("document_type", options.documentType ?? "other");
      form.append("title", options.title ?? "");
      if (options.encounterId) {
        form.append("encounter_id", options.encounterId);
      }
      xhr.send(form);
    };

    send();
  });

  return {
    promise,
    abort: () => {
      aborted = true;
      xhr.abort();
    },
  };
}
