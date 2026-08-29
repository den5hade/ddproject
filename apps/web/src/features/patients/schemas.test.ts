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
      name: "",
      date_of_birth: "",
      sex: "",
      city: "",
      profession: "",
      height: "",
      weight: "",
    });
    expect(result.success).toBe(true);
  });

  it("rejects future dates of birth (mirrors backend validator)", () => {
    const result = profileFormSchema.safeParse({
      name: "",
      date_of_birth: "2100-01-01",
      sex: "",
      city: "",
      profession: "",
      height: "",
      weight: "",
    });
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.issues[0]?.message).toMatch(/будущем/);
    }
  });

  it("accepts today and past dates", () => {
    for (const dob of [today, "1990-05-15"]) {
      const result = profileFormSchema.safeParse({
        name: "",
        date_of_birth: dob,
        sex: "",
        city: "",
        profession: "",
        height: "",
        weight: "",
      });
      expect(result.success).toBe(true);
    }
  });

  it("restricts sex to backend enum values or empty", () => {
    const base = { name: "", date_of_birth: "", city: "", profession: "", height: "", weight: "" };
    expect(profileFormSchema.safeParse({ ...base, sex: "male" }).success).toBe(true);
    expect(profileFormSchema.safeParse({ ...base, sex: "robot" }).success).toBe(false);
  });

  it("caps name length at 255", () => {
    const result = profileFormSchema.safeParse({
      name: "a".repeat(256),
      date_of_birth: "",
      sex: "",
      city: "",
      profession: "",
      height: "",
      weight: "",
    });
    expect(result.success).toBe(false);
  });
});

describe("toPersonUpdate", () => {
  it("omits empty fields so PATCH never clears data unintentionally", () => {
    const body = toPersonUpdate({
      name: "Анна",
      date_of_birth: "",
      sex: "",
      city: "",
      profession: "",
      height: "",
      weight: "",
    });
    expect(Object.keys(body)).toEqual(["name"]);
    expect(body.name).toBe("Анна");
  });

  it("includes provided values only", () => {
    const body = toPersonUpdate({
      name: "",
      date_of_birth: today,
      sex: "female",
      city: "Москва",
      profession: "Врач",
      height: "170",
      weight: "65",
    });
    expect(body).toEqual({
      date_of_birth: today,
      sex: "female",
      city: "Москва",
      profession: "Врач",
      height: 170,
      weight: 65,
    } as Record<string, unknown>);
  });
});

describe("fromPerson round-trip", () => {
  it("maps API person → form defaults with nulls as empty strings", () => {
    const values = fromPerson({
      name: "Анна",
      date_of_birth: "1990-05-15T00:00:00+03:00",
      sex: null,
      city: null,
      profession: null,
      height: 165.5,
      weight: 60.0,
    });
    expect(values).toEqual({
      name: "Анна",
      date_of_birth: "1990-05-15",
      sex: "",
      city: "",
      profession: "",
      height: "165.5",
      weight: "60",
    });
    // And the values must validate
    expect(profileFormSchema.safeParse(values).success).toBe(true);
  });
});
