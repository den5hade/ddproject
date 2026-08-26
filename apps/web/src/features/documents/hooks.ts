import { useQuery } from "@tanstack/react-query";
import * as api from "./api";
import { isProcessing } from "./api";
import type { DocumentStatus } from "./api";
import { keys } from "@/lib/query/keys";

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
    refetchInterval: (query) =>
      query.state.data && isProcessing(query.state.data.status) ? 4000 : false,
  });
}
