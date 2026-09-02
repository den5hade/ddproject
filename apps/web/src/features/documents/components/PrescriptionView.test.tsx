import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PrescriptionView } from "./PrescriptionView";

describe("PrescriptionView", () => {
  it("renders medication details", () => {
    render(
      <PrescriptionView
        medications={[
          {
            name: "Амоксициллин",
            dosage: "500 мг",
            frequency: "3 раза в день",
            duration: "7 дней",
          },
        ]}
      />,
    );

    expect(screen.getByRole("listitem")).toBeVisible();
    expect(screen.getByText("Амоксициллин")).toBeVisible();
    expect(screen.getByText("Дозировка")).toBeVisible();
    expect(screen.getByText("500 мг")).toBeVisible();
    expect(screen.getByText("Частота")).toBeVisible();
    expect(screen.getByText("3 раза в день")).toBeVisible();
    expect(screen.getByText("Длительность")).toBeVisible();
    expect(screen.getByText("7 дней")).toBeVisible();
  });

  it("renders doctor and issued date as secondary line", () => {
    render(
      <PrescriptionView
        medications={[{ name: "Парацетамол" }]}
        doctor="Иванова А. А."
        issuedAt="2026-08-01"
      />,
    );

    expect(
      screen.getByText(/Врач: Иванова А\. А\./),
    ).toBeVisible();
    expect(screen.getByText(/Дата выдачи: 2026-08-01/)).toBeVisible();
  });

  it("omits the doctor block when absent", () => {
    render(<PrescriptionView medications={[{ name: "Аспирин" }]} />);
    expect(screen.queryByText(/Врач:/)).not.toBeInTheDocument();
  });

  it("renders no rows for empty medication list", () => {
    const { container } = render(<PrescriptionView medications={[]} />);
    expect(container.querySelector('[role="listitem"]')).toBeNull();
  });
});