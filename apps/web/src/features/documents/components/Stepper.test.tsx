import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { DocumentStatus } from "../api";
import { ProcessingSteps } from "./Stepper";

const CASES: Array<[DocumentStatus, string[]]> = [
  ["pending", ["Загружен", "Обрабатывается", "Готов"]],
  ["processing", ["Загружен", "Обрабатывается", "Готов"]],
  ["completed", ["Загружен", "Обрабатывается", "Готов"]],
  ["failed", ["Загружен", "Обрабатывается", "Требует внимания"]],
];

describe.each(CASES)("ProcessingSteps for %s", (status, labels) => {
  it(`renders steps: ${labels.join(" → ")}`, () => {
    render(<ProcessingSteps status={status} />);
    const list = screen.getByRole("list", { name: "Статус обработки" });
    expect(list).toBeInTheDocument();
    for (const label of labels) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });
});

it("marks the active step with the slow pulse while processing", () => {
  const { container } = render(<ProcessingSteps status="processing" />);
  expect(container.querySelector(".animate-pulse")).not.toBeNull();
});

it("does not pulse when completed", () => {
  const { container } = render(<ProcessingSteps status="completed" />);
  expect(container.querySelector(".animate-pulse")).toBeNull();
});
