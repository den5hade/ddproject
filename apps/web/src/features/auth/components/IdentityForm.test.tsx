import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { IdentityForm } from "./IdentityForm";

describe("IdentityForm", () => {
  it("renders label, input and submit button", () => {
    render(<IdentityForm pending={false} onSubmit={vi.fn()} />);
    expect(screen.getByLabelText(/email|телефон/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Получить код" }),
    ).toBeInTheDocument();
  });

  it("rejects an invalid identity with a ru message", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<IdentityForm pending={false} onSubmit={onSubmit} />);

    await user.type(screen.getByLabelText(/email|телефон/i), "not-an-email");
    await user.click(screen.getByRole("button"));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /корректный email или телефон/i,
    );
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("accepts a valid email and lowercases before submit", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<IdentityForm pending={false} onSubmit={onSubmit} />);

    const input = screen.getByLabelText(/email|телефон/i);
    await user.type(input, "User@Example.COM");
    await user.click(screen.getByRole("button"));

    await vi.waitFor(() => expect(onSubmit).toHaveBeenCalled());
    // Mirrors backend Identity.parse: full lowercase
    expect(onSubmit).toHaveBeenCalledWith("user@example.com");
  });

  it("accepts a valid E.164 phone", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<IdentityForm pending={false} onSubmit={onSubmit} />);

    await user.type(screen.getByLabelText(/email|телефон/i), "+14155551234");
    await user.click(screen.getByRole("button"));

    await vi.waitFor(() => expect(onSubmit).toHaveBeenCalledWith("+14155551234"));
  });

  it("disables the button while pending", () => {
    render(<IdentityForm pending onSubmit={vi.fn()} />);
    expect(screen.getByRole("button")).toBeDisabled();
  });

  it("shows serverError when no field error is present", async () => {
    const user = userEvent.setup();
    render(
      <IdentityForm
        pending={false}
        serverError="Код уже отправлен. Подождите минуту."
        onSubmit={vi.fn()}
      />,
    );
    // Server error renders immediately (no field error yet)
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Код уже отправлен. Подождите минуту.",
    );
    void user;
  });
});
