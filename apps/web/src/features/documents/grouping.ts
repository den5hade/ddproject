import type { DocumentResponse, DocumentStatus } from "./api";
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

/** Statuses still moving (no document_date yet): bucket into «Новые». */
const PENDING_STATUSES: ReadonlySet<DocumentStatus> = new Set([
  "pending",
  "uploaded",
  "processing",
]);

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

/** Sentinel key for documents with no document_date yet (processing/unknown). */
export const NEW_GROUP_KEY = "new";

/** Effective display date for a document: medical date, else upload time. */
function displayDate(document: DocumentResponse): string {
  return document.document_date ?? document.created_at ?? "";
}

/**
 * Documents that still have no document_date (processing, or unknown date)
 * are bucketed into the «Новые» group, shown first. Dated documents group by
 * their document_date's month (YYYY-MM), newest-first. Groups keep the
 * incoming order within themselves.
 */
export function groupDocumentsByMonth(
  documents: DocumentResponse[],
): MonthGroup[] {
  const pending: DocumentResponse[] = [];
  const dated: DocumentResponse[] = [];

  for (const document of documents) {
    if (
      PENDING_STATUSES.has(document.status) ||
      document.document_date === null ||
      document.document_date === undefined
    ) {
      pending.push(document);
    } else {
      dated.push(document);
    }
  }

  const groups: MonthGroup[] = [];
  if (pending.length > 0) {
    groups.push({ key: NEW_GROUP_KEY, label: "", documents: pending });
  }

  dated.sort((a, b) => displayDate(b).localeCompare(displayDate(a)));
  const byMonth = new Map<string, DocumentResponse[]>();
  for (const document of dated) {
    const key = monthKey(document.document_date!);
    const bucket = byMonth.get(key);
    if (bucket) bucket.push(document);
    else byMonth.set(key, [document]);
  }
  for (const [key, monthDocs] of byMonth) {
    groups.push({
      key,
      label: formatMonthYearRu(monthDocs[0].document_date!),
      documents: monthDocs,
    });
  }
  return groups;
}
