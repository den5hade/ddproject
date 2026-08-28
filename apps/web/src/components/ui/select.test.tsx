import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { SelectDropdown, type SelectOption } from "./select";

const OPTIONS: SelectOption[] = [
  { value: "male", label: "Мужской" },
  { value: "female", label: "Женский" },
  { value: "unspecified", label: "Не указан" },
];

function setup(overrides: Partial<Parameters<typeof SelectDropdown>[0]> = {}) {
  const onChange = vi.fn();
  const utils = render(
    <SelectDropdown
      label="Пол"
      value=""
      options={OPTIONS}
      placeholder="Не выбрано"
      onChange={onChange}
      {...overrides}
    />,
  );
  return { onChange, ...utils };
}

describe("SelectDropdown", () => {
  it("shows the placeholder when no value matches", () => {
    setup();
    expect(screen.getByRole("combobox", { name: "Пол" })).toBeVisible();
    expect(screen.getByText("Не выбрано")).toBeVisible();
  });

  it("shows the selected option label", () => {
    setup({ value: "female" });
    expect(screen.getByText("Женский")).toBeVisible();
  });

  it("opens a listbox with all options and selects on click", async () => {
    const user = userEvent.setup();
    const { onChange } = setup();

    await user.click(screen.getByRole("combobox"));
    const listbox = screen.getByRole("listbox", { name: "Пол" });
    expect(listbox).toBeVisible();
    expect(screen.getAllByRole("option")).toHaveLength(OPTIONS.length);

    await user.click(screen.getByRole("option", { name: "Мужской" }));
    expect(onChange).toHaveBeenCalledWith("male");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("marks the selected option aria-selected", async () => {
    const user = userEvent.setup();
    setup({ value: "unspecified" });

    await user.click(screen.getByRole("combobox"));
    expect(
      screen.getByRole("option", { name: "Не указан" }),
    ).toHaveAttribute("aria-selected", "true");
  });

  it("closes on outside pointerdown", async () => {
    const user = userEvent.setup();
    setup();

    await user.click(screen.getByRole("combobox"));
    expect(screen.getByRole("listbox")).toBeVisible();

    await user.click(document.body);
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("closes on Escape", async () => {
    const user = userEvent.setup();
    setup();

    await user.click(screen.getByRole("combobox"));
    expect(screen.getByRole("listbox")).toBeVisible();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });
});
