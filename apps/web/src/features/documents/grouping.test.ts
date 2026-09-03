import { describe, expect, it } from "vitest";
import type { DocumentResponse } from "./api";
import {
  NEW_GROUP_KEY,
  filterDocuments,
  groupDocumentsByMonth,
} from "./grouping";

function doc(
  id: string,
  type: string,
  date: { created_at: string; document_date?: string | null; status?: string },
): DocumentResponse {
  return {
    id,
    medical_record_id: "mr",
    encounter_id: null,
    document_type: type as DocumentResponse["document_type"],
    title: `t-${id}`,
    original_filename: `${id}.pdf`,
    mime_type: "application/pdf",
    size_bytes: 1,
    storage_key: "",
    status: (date.status ?? "completed") as DocumentResponse["status"],
    uploaded_by_account_id: null,
    created_at: date.created_at,
    updated_at: date.created_at,
    document_date: date.document_date,
  };
}

describe("filterDocuments", () => {
  const docs = [
    doc("1", "lab_result", { created_at: "2026-08-01T10:00:00+03:00" }),
    doc("2", "doctor_report", { created_at: "2026-07-02T10:00:00+03:00" }),
    doc("3", "prescription", { created_at: "2026-07-03T10:00:00+03:00" }),
  ];

  it("returns everything for 'all'", () => {
    expect(filterDocuments(docs, "all")).toHaveLength(3);
  });

  it("filters laboratory results", () => {
    expect(
      filterDocuments(docs, "laboratory").map((d) => d.id),
    ).toEqual(["1"]);
  });

  it("groups visit-related types together", () => {
    expect(filterDocuments(docs, "visits").map((d) => d.id)).toEqual(["2"]);
  });

  it("puts prescriptions into 'other'", () => {
    expect(filterDocuments(docs, "other").map((d) => d.id)).toEqual(["3"]);
  });
});

describe("groupDocumentsByMonth", () => {
  it("groups by document_date month with ru labels, newest first", () => {
    const groups = groupDocumentsByMonth([
      doc("a", "lab_result", {
        created_at: "2026-08-15T09:00:00+03:00",
        document_date: "2026-08-02T00:00:00+03:00",
      }),
      doc("b", "lab_result", {
        created_at: "2026-08-01T09:00:00+03:00",
        document_date: "2026-07-20T00:00:00+03:00",
      }),
      doc("c", "doctor_report", {
        created_at: "2026-07-20T09:00:00+03:00",
        document_date: "2026-08-10T00:00:00+03:00",
      }),
    ]);

    expect(groups).toHaveLength(2);
    expect(groups[0]).toMatchObject({ key: "2026-08", label: "Август 2026" });
    expect(groups[0].documents.map((d) => d.id)).toEqual(["c", "a"]);
    expect(groups[1]).toMatchObject({ key: "2026-07", label: "Июль 2026" });
    expect(groups[1].documents.map((d) => d.id)).toEqual(["b"]);
  });

  it("buckets processing docs and docs without document_date into «Новые» first", () => {
    const groups = groupDocumentsByMonth([
      doc("done", "lab_result", {
        created_at: "2026-08-01T09:00:00+03:00",
        document_date: "2026-08-15T00:00:00+03:00",
      }),
      doc("none", "lab_result", {
        created_at: "2026-09-01T09:00:00+03:00",
        document_date: null,
      }),
      doc("busy", "lab_result", {
        created_at: "2026-09-02T09:00:00+03:00",
        status: "processing",
      }),
    ]);

    expect(groups).toHaveLength(2);
    expect(groups[0].key).toBe(NEW_GROUP_KEY);
    expect(groups[0].documents.map((d) => d.id)).toEqual(["none", "busy"]);
    expect(groups[1]).toMatchObject({ key: "2026-08", label: "Август 2026" });
    expect(groups[1].documents.map((d) => d.id)).toEqual(["done"]);
  });

  it("omits the «Новые» group when every document has a date", () => {
    const groups = groupDocumentsByMonth([
      doc("a", "lab_result", {
        created_at: "2026-08-01T09:00:00+03:00",
        document_date: "2026-08-10T00:00:00+03:00",
      }),
    ]);
    expect(groups.map((g) => g.key)).toEqual(["2026-08"]);
  });

  it("returns an empty array for no documents", () => {
    expect(groupDocumentsByMonth([])).toEqual([]);
  });
});
