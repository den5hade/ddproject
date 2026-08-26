import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { DocumentStatus } from "../api";
import { ProcessingStatus } from "./ProcessingStatus";

/*
 * SG §31 wording map: pending/uploaded→Загружен, processing→Обрабатывается,
 * completed→Готов, failed→Требует внимания. Color never alone (SG §6):
 * every chip carries text.
 */
const EXPECTED: Array<[DocumentStatus, string]> = [
  ["pending", "Загружен"],
  ["uploaded", "Загружен"],
  ["processing", "Обрабатывается"],
  ["completed", "Готов"],
  ["failed", "Требует внимания"],
];

describe("ProcessingStatus", () => {
  it.each(EXPECTED)("renders %s → «%s» with text content", (status, label) => {
    render(<ProcessingStatus status={status} />);
    const chip = screen.getByText(label);
    expect(chip).toBeInTheDocument();
  });

  it("uses an animated dots indicator while processing instead of an icon", () => {
    const { container } = render(<ProcessingStatus status="processing" />);
    expect(container.querySelector(".animate-pulse")).not.toBeNull();
  });

  it("falls back to Загружен for unknown statuses", () => {
    render(<ProcessingStatus status={"unknown" as DocumentStatus} />);
    expect(screen.getByText("Загружен")).toBeInTheDocument();
  });
});
