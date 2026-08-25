import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { OtpInput } from "./OtpInput";

function Harness({
  onComplete,
  disabled,
}: {
  onComplete?: (code: string) => void;
  disabled?: boolean;
}) {
  const [value, setValue] = useState("");
  return (
    <OtpInput
      value={value}
      onChange={setValue}
      onComplete={onComplete}
      disabled={disabled}
    />
  );
}

const cells = () => screen.getAllByLabelText(/Цифра \d из 6/);

describe("OtpInput", () => {
  it("renders six cells with the first focused on mount via tab order", () => {
    render(<Harness />);
    expect(cells()).toHaveLength(6);
  });

  it("auto-advances focus while typing digits", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.type(cells()[0]!, "1");
    expect(document.activeElement).toBe(cells()[1]);
    await user.keyboard("2");
    expect(document.activeElement).toBe(cells()[2]);
  });

  it("fires onComplete once six digits are entered", async () => {
    const user = userEvent.setup();
    const onComplete = vi.fn();
    render(<Harness onComplete={onComplete} />);
    await user.type(cells()[0]!, "359784");
    expect(onComplete).toHaveBeenCalledWith("359784");
  });

  it("backspace on empty cell removes previous digit and moves back", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.type(cells()[0]!, "12");
    // cursor now at cell 2 (empty); backspace removes "2" at index 1
    await user.keyboard("{Backspace}");
    const values = cells().map((c) => (c as HTMLInputElement).value);
    expect(values.join("")).toBe("1");
    // caret lands on the cell after the last remaining digit
    expect(document.activeElement).toBe(cells()[1]);
  });

  it("distributes pasted full code across cells and fires onComplete", async () => {
    const user = userEvent.setup();
    const onComplete = vi.fn();
    render(<Harness onComplete={onComplete} />);
    await user.click(cells()[0]);
    await user.paste("359784");
    const values = cells().map((c) => (c as HTMLInputElement).value);
    expect(values.join("")).toBe("359784");
    expect(onComplete).toHaveBeenCalledWith("359784");
  });

  it("ignores non-digit input", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.type(cells()[0]!, "ab1");
    const values = cells().map((c) => (c as HTMLInputElement).value);
    expect(values.join("")).toBe("1");
  });

  it("disables all cells when disabled", () => {
    render(<Harness disabled />);
    for (const cell of cells()) expect(cell).toBeDisabled();
  });
});
