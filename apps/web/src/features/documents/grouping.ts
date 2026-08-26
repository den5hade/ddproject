import type { DocumentResponse } from "./api";
import { monthKey, formatMonthYearRu } from "@/lib/utils/format";

/*
 * Documents list grouping + filtering (SG §56 chips).
 * Pure helpers — unit-tested.
 */

export type DocumentFilter = "all" | "laboratory" | "visits" | "other";

const FILTER_TYPES: Record<Exclude<DocumentFilter, "all">, ReadonlySet<string>> = {
  laboratory: new Set(["lab_result"]),
  visits: new Set([
    "doctor_report",
    "discharge_summary",
    "imaging_report",
    "referral",
  ]),
  other: new Set(["prescription", "medical_certificate", "other"]),
};

export function filterDocuments(
  documents: DocumentResponse[],
  filter: DocumentFilter,
): DocumentResponse[] {
  if (filter === "all") return documents;
  const types = FILTER_TYPES[filter];
  return documents.filter((d) => types.has(d.document_type));
}

export interface MonthGroup {
  key: string;
  label: string;
  documents: DocumentResponse[];
}

/** Groups by month (YYYY-MM), preserving the incoming order within groups. */
export function groupDocumentsByMonth(
  documents: DocumentResponse[],
): MonthGroup[] {
  const groups = new Map<string, MonthGroup>();
  for (const document of documents) {
    const key = monthKey(document.created_at);
    let group = groups.get(key);
    if (!group) {
      group = { key, label: formatMonthYearRu(document.created_at), documents: [] };
      groups.set(key, group);
    }
    group.documents.push(document);
  }
  return [...groups.values()];
}
