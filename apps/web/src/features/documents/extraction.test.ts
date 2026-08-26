import { describe, expect, it } from "vitest";
import { parseExtractionData } from "./extraction";

describe("parseExtractionData", () => {
  it("parses a list of observation objects (shape 1)", () => {
    const result = parseExtractionData([
      { name: "Гемоглобин", value: 135, unit: "g/L", reference: "120–160" },
      { name: "Лейкоциты", value: "6.2", unit: "×10⁹/L" },
    ]);
    expect(result).toEqual([
      {
        name: "Гемоглобин",
        value: "135",
        unit: "g/L",
        reference: "120–160",
      },
      { name: "Лейкоциты", value: "6.2", unit: "×10⁹/L", reference: undefined },
    ]);
  });

  it("parses wrapped lists under results/observations/items (shape 2)", () => {
    const result = parseExtractionData({
      results: [{ label: "Глюкоза", result: "5.4", unit: "mmol/L" }],
    });
    expect(result).toEqual([
      { name: "Глюкоза", value: "5.4", unit: "mmol/L", reference: undefined },
    ]);
  });

  it("parses keyed objects with structured values (shape 3)", () => {
    const result = parseExtractionData({
      hemoglobin: { value: 135, unit: "g/L", norm: "120-160" },
    });
    expect(result).toEqual([
      { name: "Hemoglobin", value: "135", unit: "g/L", reference: "120-160" },
    ]);
  });

  it("parses flat primitive maps (shape 4)", () => {
    const result = parseExtractionData({ weight_kg: "72.4", temperature: 36.6 });
    expect(result).toEqual([
      { name: "Weight kg", value: "72.4", unit: undefined, reference: undefined },
      { name: "Temperature", value: "36.6", unit: undefined, reference: undefined },
    ]);
  });

  it("returns null for null/empty/unusable data", () => {
    expect(parseExtractionData(null)).toBeNull();
    expect(parseExtractionData({})).toBeNull();
    expect(parseExtractionData({ results: [] })).toBeNull();
    expect(parseExtractionData("text")).toBeNull();
  });

  it("skips entries without both name and value", () => {
    const result = parseExtractionData([{ name: "Только имя" }, "мусор"]);
    expect(result).toBeNull();
  });

  it("accepts title/label as name keys and result as value key", () => {
    const result = parseExtractionData([{ title: "pH", result: 7.4 }]);
    expect(result).toEqual([
      { name: "pH", value: "7.4", unit: undefined, reference: undefined },
    ]);
  });
});
