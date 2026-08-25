import { describe, expect, it } from "vitest";
import { ApiError, parseApiError } from "./errors";

describe("parseApiError", () => {
  it("parses FastAPI string detail", () => {
    const err = parseApiError(429, { detail: "OTP sent recently" });
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(429);
    expect(err.message).toBe("OTP sent recently");
    expect(err.fields).toBeUndefined();
  });

  it("extracts field errors from 422 validation lists", () => {
    const err = parseApiError(422, {
      detail: [
        {
          loc: ["body", "identity"],
          msg: "Value error, identity is not a valid email or phone",
          type: "value_error",
        },
        {
          loc: ["body", "code"],
          msg: "String should match pattern '^\\d{6}$'",
          type: "string_pattern_mismatch",
        },
      ],
    });
    expect(err.status).toBe(422);
    expect(err.fields).toEqual({
      identity: "identity is not a valid email or phone",
      code: expect.stringContaining("Неверный формат"),
    });
  });

  it("falls back to a status-based Russian message for unknown bodies", () => {
    const err = parseApiError(503, undefined);
    expect(err.message).toBe("Сервис временно недоступен");
  });

  it("falls back to generic message for non-detail bodies", () => {
    const err = parseApiError(500, { something: "else" });
    expect(err.message).toBe("Ошибка сервера, попробуйте снова");
  });

  it("handles nested loc paths by joining them", () => {
    const err = parseApiError(422, {
      detail: [
        { loc: ["body", "person", "date_of_birth"], msg: "invalid date", type: "value_error" },
      ],
    });
    expect(err.fields?.["person.date_of_birth"]).toBe("invalid date");
  });
});
