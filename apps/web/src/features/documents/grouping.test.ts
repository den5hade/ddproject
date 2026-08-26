import { describe, expect, it } from "vitest";
import type { DocumentResponse } from "./api";
import { filterDocuments, groupDocumentsByMonth } from "./grouping";

function doc(id: string, type: string, createdAt: string): DocumentResponse {
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
    status: "completed",
    uploaded_by_account_id: null,
    created_at: createdAt,
    updated_at: createdAt,
  };
}

describe("filterDocuments", () => {
  const docs = [
    doc("1", "lab_result", "2026-08-01T10:00:00+03:00"),
    doc("2", "doctor_report", "2026-07-02T10:00:00+03:00"),
    doc("3", "prescription", "2026-07-03T10:00:00+03:00"),
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
  it("groups by YYYY-MM with ru month labels", () => {
    const groups = groupDocumentsByMonth([
      doc("a", "lab_result", "2026-08-15T09:00:00+03:00"),
      doc("b", "lab_result", "2026-08-01T09:00:00+03:00"),
      doc("c", "doctor_report", "2026-07-20T09:00:00+03:00"),
    ]);
    expect(groups).toHaveLength(2);
    expect(groups[0]).toMatchObject({ key: "2026-08", label: "Август 2026" });
    expect(groups[0].documents.map((d) => d.id)).toEqual(["a", "b"]);
    expect(groups[1]).toMatchObject({ key: "2026-07", label: "Июль 2026" });
  });

  it("returns an empty array for no documents", () => {
    expect(groupDocumentsByMonth([])).toEqual([]);
  });
});
