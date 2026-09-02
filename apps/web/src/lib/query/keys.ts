/*
 * Central query keys factory (plan §5.3).
 * Always use these helpers — never inline key arrays at call sites.
 */
export const keys = {
  me: () => ["me"] as const,
  patientMe: () => ["patient", "me"] as const,
  documents: (patientId: string) => ["documents", patientId] as const,
  document: (documentId: string) => ["document", documentId] as const,
  versions: (documentId: string) =>
    ["document", documentId, "versions"] as const,
  extractions: (documentId: string) =>
    ["document", documentId, "extractions"] as const,
  canonical: (documentId: string) =>
    ["document", documentId, "canonical"] as const,
  downloadUrl: (documentId: string) =>
    ["document", documentId, "download-url"] as const,
};
