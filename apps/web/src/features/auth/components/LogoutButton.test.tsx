import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { LogoutButton } from "./LogoutButton";

describe("LogoutButton", () => {
  it("renders «Выйти» and fires onLogout once per click", async () => {
    const user = userEvent.setup();
    const onLogout = vi.fn();
    render(<LogoutButton onLogout={onLogout} />);

    await user.click(screen.getByRole("button", { name: /выйти/i }));
    expect(onLogout).toHaveBeenCalledOnce();
  });
});
