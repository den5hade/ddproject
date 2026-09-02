import { describe, expect, it } from "vitest";
import { normalizeCanonical } from "./canonical";

describe("normalizeCanonical", () => {
  it("parses a laboratory envelope into result observations", () => {
    const view = normalizeCanonical({
      document_date: "2026-08-01",
      language: "ru",
      type: "laboratory",
      subtype: "laboratory",
      fields: {
        results: [
          { name: "Гемоглобин", value: 135, unit: "g/L", reference_min: 120, reference_max: 160 },
          { name: "Лейкоциты", value: "6.2", unit: "×10⁹/L", flagged: true },
        ],
      },
    });
    expect(view).toEqual({
      kind: "laboratory",
      observations: [
        {
          name: "Гемоглобин",
          value: "135",
          unit: "g/L",
          referenceMin: 120,
          referenceMax: 160,
          flagged: false,
          reference: "120–160",
        },
        {
          name: "Лейкоциты",
          value: "6.2",
          unit: "×10⁹/L",
          referenceMin: undefined,
          referenceMax: undefined,
          flagged: true,
          reference: undefined,
        },
      ],
    });
  });

  it("parses a prescription envelope into medications", () => {
    const view = normalizeCanonical({
      type: "prescription",
      subtype: "prescription",
      language: "ru",
      fields: {
        medications: [
          { name: "Амоксициллин", dosage: "500 мг", frequency: "3 раза в день", duration: "7 дней" },
        ],
        doctor: "Иванова А. А.",
        issued_at: "2026-08-01",
      },
    });
    expect(view).toEqual({
      kind: "prescription",
      medications: [
        {
          name: "Амоксициллин",
          dosage: "500 мг",
          frequency: "3 раза в день",
          duration: "7 дней",
        },
      ],
      doctor: "Иванова А. А.",
      issuedAt: "2026-08-01",
    });
  });

  it("falls back to generic observations from the fields dict", () => {
    const view = normalizeCanonical({
      type: "generic",
      subtype: "generic",
      fields: { weight_kg: 72.4, temperature: 36.6 },
    });
    expect(view).toEqual({
      kind: "generic",
      observations: [
        { name: "Weight kg", value: "72.4", unit: undefined, reference: undefined, referenceMin: undefined, referenceMax: undefined, flagged: undefined },
        { name: "Temperature", value: "36.6", unit: undefined, reference: undefined, referenceMin: undefined, referenceMax: undefined, flagged: undefined },
      ],
    });
  });

  it("never surfaces envelope keys as observations", () => {
    const view = normalizeCanonical({
      document_date: "2026-08-01",
      language: "ru",
      type: "laboratory",
      fields: { results: [{ name: "pH", value: 7.4 }] },
      canonical_key: "docs/x/canonical.json",
      structured_key: "docs/x/structured.md",
    });
    expect(view?.kind).toBe("laboratory");
    const observations = (view as { kind: "laboratory"; observations: { name: string }[] })
      .observations;
    expect(observations).toHaveLength(1);
    expect(observations[0].name).toBe("pH");
  });

  it("handles legacy loose shapes (backward compatible)", () => {
    const view = normalizeCanonical([
      { name: "Гемоглобин", value: 135, unit: "g/L" },
    ]);
    expect(view).toEqual({
      kind: "legacy",
      observations: [
        { name: "Гемоглобин", value: "135", unit: "g/L", reference: undefined },
      ],
    });
  });

  it("returns null for garbage / empty / non-object", () => {
    expect(normalizeCanonical(null)).toBeNull();
    expect(normalizeCanonical("text")).toBeNull();
    expect(normalizeCanonical({})).toBeNull();
    expect(normalizeCanonical({ fields: {} })).toBeNull();
    expect(normalizeCanonical({ document_date: "x", fields: { results: [] } })).toBeNull();
  });
});