import { describe, expect, it } from "vitest";
import {
  fromPerson,
  profileFormSchema,
  toPersonUpdate,
} from "./schemas";

const today = new Date().toISOString().slice(0, 10);

describe("profileFormSchema", () => {
  it("accepts empty form (all optional)", () => {
    const result = profileFormSchema.safeParse({
      first_name: "",
      last_name: "",
      middle_name: "",
      date_of_birth: "",
      sex: "",
    });
    expect(result.success).toBe(true);
  });

  it("rejects future dates of birth (mirrors backend validator)", () => {
    const result = profileFormSchema.safeParse({
      first_name: "",
      last_name: "",
      middle_name: "",
      date_of_birth: "2100-01-01",
      sex: "",
    });
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.issues[0]?.message).toMatch(/будущем/);
    }
  });

  it("accepts today and past dates", () => {
    for (const dob of [today, "1990-05-15"]) {
      const result = profileFormSchema.safeParse({
        first_name: "",
        last_name: "",
        middle_name: "",
        date_of_birth: dob,
        sex: "",
      });
      expect(result.success).toBe(true);
    }
  });

  it("restricts sex to backend enum values or empty", () => {
    const base = { first_name: "", last_name: "", middle_name: "", date_of_birth: "" };
    expect(profileFormSchema.safeParse({ ...base, sex: "male" }).success).toBe(true);
    expect(profileFormSchema.safeParse({ ...base, sex: "robot" }).success).toBe(false);
  });

  it("caps name length at 255", () => {
    const result = profileFormSchema.safeParse({
      first_name: "a".repeat(256),
      last_name: "",
      middle_name: "",
      date_of_birth: "",
      sex: "",
    });
    expect(result.success).toBe(false);
  });
});

describe("toPersonUpdate", () => {
  it("omits empty fields so PATCH never clears data unintentionally", () => {
    const body = toPersonUpdate({
      first_name: "Анна",
      last_name: "",
      middle_name: "",
      date_of_birth: "",
      sex: "",
    });
    // PersonUpdate fields are nullable — assert no explicit-null keys sent
    expect(Object.keys(body)).toEqual(["first_name"]);
    expect(body.first_name).toBe("Анна");
  });

  it("includes provided values only", () => {
    const body = toPersonUpdate({
      first_name: "",
      last_name: "Смит",
      middle_name: "",
      date_of_birth: today,
      sex: "female",
    });
    expect(body).toEqual({
      last_name: "Смит",
      date_of_birth: today,
      sex: "female",
    } as Record<string, unknown>);
  });
});

describe("fromPerson round-trip", () => {
  it("maps API person → form defaults with nulls as empty strings", () => {
    const values = fromPerson({
      first_name: "Анна",
      last_name: null,
      middle_name: null,
      date_of_birth: "1990-05-15T00:00:00+03:00",
      sex: null,
    });
    expect(values).toEqual({
      first_name: "Анна",
      last_name: "",
      middle_name: "",
      date_of_birth: "1990-05-15",
      sex: "",
    });
    // And the values must validate
    expect(profileFormSchema.safeParse(values).success).toBe(true);
  });
});
