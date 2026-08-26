import type { DocumentStatus } from "./api";

/*
 * Upload state machine (plan §5.2) — pure reducer, unit-tested.
 *
 *  IDLE → VALIDATING → UPLOADING → QUEUED
 *                          ↓         ↘ FAILED(doc.status)
 *                        ERROR ⇄ RETRY(↺ UPLOADING)
 *                              ↘ CANCELLED
 *
 * QUEUED hands over to TanStack Query (list invalidation + detail
 * polling); FAILED arrives later via document status polling.
 */

export const ALLOWED_MIME_TYPES = [
  "application/pdf",
  "image/jpeg",
  "image/png",
  "image/tiff",
] as const;

/** Mirrors backend max_upload_bytes (50 MB). */
export const MAX_UPLOAD_BYTES = 50 * 1024 * 1024;

/** Value for <input accept>. */
export const UPLOAD_ACCEPT = [
  ...ALLOWED_MIME_TYPES,
  ".pdf",
  ".jpg",
  ".jpeg",
  ".png",
  ".tif",
  ".tiff",
].join(",");

export type UploadState =
  | { status: "idle" }
  | { status: "validating"; file: File }
  | {
      status: "uploading";
      file: File;
      progress: number; // 0–100
      attempt: number; // 1 = first try, 2 = after RETRY
    }
  | { status: "queued"; documentId: string; fileName: string }
  | { status: "failed"; documentId: string } // terminal backend status
  | { status: "error"; message: string; file: File | null; attempt: number }
  | { status: "cancelled" };

export type UploadEvent =
  | { type: "SELECT"; file: File }
  | { type: "VALIDATION_FAILED"; message: string }
  | { type: "UPLOAD_START"; attempt: number }
  | { type: "PROGRESS"; percent: number }
  | { type: "UPLOADED"; documentId: string }
  | { type: "FAILED_STATUS"; documentId: string } // terminal doc status failed
  | { type: "ERROR"; message: string }
  | { type: "RETRY" }
  | { type: "CANCEL" }
  | { type: "RESET" };

export const initialUploadState: UploadState = { status: "idle" };

export function validateUpload(file: File): string | null {
  if (!(ALLOWED_MIME_TYPES as readonly string[]).includes(file.type)) {
    return "Поддерживаются PDF, JPEG, PNG и TIFF";
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    return "Файл слишком большой — максимум 50 МБ";
  }
  if (file.size === 0) {
    return "Файл пустой";
  }
  return null;
}

export function uploadReducer(state: UploadState, event: UploadEvent): UploadState {
  switch (event.type) {
    case "SELECT":
      // Re-selecting mid-flow restarts cleanly
      return { status: "validating", file: event.file };

    case "VALIDATION_FAILED":
      return { status: "error", message: event.message, file: null, attempt: 0 };

    case "UPLOAD_START":
      return {
        status: "uploading",
        file: state.status === "validating" || state.status === "uploading" ? state.file : new File([], ""),
        progress: 0,
        attempt: event.attempt,
      };

    case "PROGRESS":
      if (state.status !== "uploading") return state;
      return {
        ...state,
        progress: Math.max(state.progress, Math.min(100, event.percent)),
      };

    case "UPLOADED":
      return { status: "queued", documentId: event.documentId, fileName: state.status === "uploading" ? state.file.name : "" };

    case "FAILED_STATUS":
      return { status: "failed", documentId: event.documentId };

    case "ERROR":
      if (state.status !== "uploading") return state;
      return {
        status: "error",
        message: event.message,
        file: state.file,
        attempt: state.attempt,
      };

    case "RETRY":
      return state.status === "error"
        ? {
            status: "uploading",
            file: state.file ?? new File([], ""),
            progress: 0,
            attempt: state.attempt + 1,
          }
        : state;

    case "CANCEL":
      if (state.status === "uploading" || state.status === "validating") {
        return { status: "cancelled" };
      }
      return state;

    case "RESET":
      return initialUploadState;

    default:
      return state;
  }
}

/** Terminal document statuses that stop polling (plan §5.2). */
const TERMINAL_STATUSES: ReadonlySet<DocumentStatus> = new Set([
  "completed",
  "failed",
  "deleted",
]);

export function isTerminalStatus(status: DocumentStatus): boolean {
  return TERMINAL_STATUSES.has(status);
}
