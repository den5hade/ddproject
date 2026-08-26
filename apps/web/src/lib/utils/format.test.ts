import { describe, expect, it } from "vitest";
import {
  formatDateRu,
  formatDateShortRu,
  formatMonthYearRu,
  greetingForHour,
  monthKey,
} from "./format";

describe("formatDateRu", () => {
  it("formats a Moscow ISO datetime as a long ru date", () => {
    expect(formatDateRu("2026-08-15T10:00:00+03:00")).toBe(
      "15 августа 2026",
    );
  });

  it("returns empty string for invalid input", () => {
    expect(formatDateRu("not-a-date")).toBe("");
  });
});

describe("formatDateShortRu", () => {
  it("formats a short ru date", () => {
    expect(formatDateShortRu("2026-08-15T10:00:00+03:00")).toMatch(
      /15 авг\.? 2026/,
    );
  });
});

describe("formatMonthYearRu", () => {
  it("capitalizes the month name for group headers", () => {
    expect(formatMonthYearRu("2026-08-01T00:00:00+03:00")).toBe(
      "Август 2026",
    );
  });
});

describe("monthKey", () => {
  it("extracts a stable YYYY-MM group key", () => {
    expect(monthKey("2026-08-15T10:00:00+03:00")).toBe("2026-08");
  });
});

describe("greetingForHour", () => {
  it.each([
    [5, "morning"],
    [11, "morning"],
    [12, "afternoon"],
    [17, "afternoon"],
    [18, "evening"],
    [23, "evening"],
  ] as const)("maps %i → %s", (hour, expected) => {
    expect(greetingForHour(hour)).toBe(expected);
  });
});
