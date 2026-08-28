import { useCallback, useReducer, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import * as api from "./api";
import { isProcessing } from "./api";
import {
  initialUploadState,
  uploadReducer,
  validateUpload,
} from "./uploadMachine";
import type { DocumentStatus } from "./api";
import { keys } from "@/lib/query/keys";
import { strings } from "@/lib/i18n/strings";

export { isProcessing };
export type { DocumentStatus };

export function useMyPatientDocuments(patientId: string | undefined) {
  return useQuery({
    queryKey: keys.documents(patientId ?? "_"),
    queryFn: () => api.listPatientDocuments(patientId!),
    enabled: patientId !== undefined,
    staleTime: 30_000,
  });
}

export function useVersions(documentId: string | undefined) {
  return useQuery({
    queryKey: keys.versions(documentId ?? "_"),
    queryFn: () => api.getVersions(documentId!),
    enabled: documentId !== undefined,
  });
}

export function useExtractions(documentId: string | undefined) {
  return useQuery({
    queryKey: keys.extractions(documentId ?? "_"),
    queryFn: () => api.getExtractions(documentId!),
    enabled: documentId !== undefined,
  });
}

/** Presigned URL is short-lived (900s) — never stale-cache it long. */
export function useDownloadUrl(documentId: string | undefined) {
  return useQuery({
    queryKey: keys.downloadUrl(documentId ?? "_"),
    queryFn: () => api.getDownloadUrl(documentId!),
    enabled: documentId !== undefined,
    staleTime: 5 * 60_000,
    gcTime: 6 * 60_000,
  });
}

/**
 * Polls a single document while it is still moving (plan §5.2, D6).
 * refetchInterval returns false → polling stops automatically on
 * terminal statuses (completed / failed / deleted).
 */
export function useDocumentWithPolling(documentId: string | undefined) {
  return useQuery({
    queryKey: keys.document(documentId ?? "_"),
    queryFn: () => api.getDocument(documentId!),
    enabled: documentId !== undefined,
    refetchOnWindowFocus: false,
    refetchInterval: (query) =>
      query.state.data && isProcessing(query.state.data.status) ? 4000 : false,
  });
}

/**
 * Drives the upload state machine against the XHR transport
 * (plan §5.2). QUEUED success invalidates the list cache and toasts
 * once (SG §49).
 */
export function useUploader(patientId: string | undefined) {
  const [state, dispatch] = useReducer(uploadReducer, initialUploadState);
  const abortRef = useRef<(() => void) | null>(null);
  const queryClient = useQueryClient();

  const start = useCallback(
    (file: File) => {
      if (!patientId || state.status === "uploading") return;
      dispatch({ type: "SELECT", file });

      const validationError = validateUpload(file);
      if (validationError) {
        dispatch({ type: "VALIDATION_FAILED", message: validationError });
        return;
      }

      const handle = api.uploadDocument(patientId, file, {
        onProgress: (percent) => dispatch({ type: "PROGRESS", percent }),
      });
      abortRef.current = handle.abort;

      // UPLOAD_START is dispatched synchronously after SELECT so the UI
      // shows the progress row immediately.
      dispatch({ type: "UPLOAD_START", attempt: 1 });

      handle.promise
        .then((document) => {
          abortRef.current = null;
          dispatch({ type: "UPLOADED", documentId: document.id });
          void queryClient.invalidateQueries({
            queryKey: keys.documents(patientId),
          });
          toast(strings.documents.uploadedToast, {
            description: document.title || document.original_filename,
          });
        })
        .catch((err: unknown) => {
          abortRef.current = null;
          const message =
            err instanceof Error && err.message
              ? err.message
              : strings.common.errorTitle;
          dispatch({ type: "ERROR", message });
        });
    },
    [patientId, queryClient, state.status],
  );

  const cancel = useCallback(() => {
    abortRef.current?.();
    abortRef.current = null;
    dispatch({ type: "CANCEL" });
  }, []);

  return { state, start, cancel };
}
