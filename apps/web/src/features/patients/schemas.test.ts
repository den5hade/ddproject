import { describe, expect, it } from "vitest";
import {
  fromPerson,
  profileFormSchema,
  toPersonUpdate,
} from "./schemas";

describe("profileFormSchema", () => {
  it("accepts empty form (all optional)", () => {
    const result = profileFormSchema.safeParse({
      name: "",
      age: "",
      sex: "",
      city: "",
      profession: "",
      height: "",
      weight: "",
    });
    expect(result.success).toBe(true);
  });

  it("accepts valid age", () => {
    const result = profileFormSchema.safeParse({
      name: "",
      age: "25",
      sex: "",
      city: "",
      profession: "",
      height: "",
      weight: "",
    });
    expect(result.success).toBe(true);
  });

  it("rejects age > 150", () => {
    const result = profileFormSchema.safeParse({
      name: "",
      age: "151",
      sex: "",
      city: "",
      profession: "",
      height: "",
      weight: "",
    });
    expect(result.success).toBe(false);
  });

  it("restricts sex to backend enum values or empty", () => {
    const base = { name: "", age: "", city: "", profession: "", height: "", weight: "" };
    expect(profileFormSchema.safeParse({ ...base, sex: "male" }).success).toBe(true);
    expect(profileFormSchema.safeParse({ ...base, sex: "robot" }).success).toBe(false);
  });

  it("caps name length at 255", () => {
    const result = profileFormSchema.safeParse({
      name: "a".repeat(256),
      age: "",
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
      age: "",
      sex: "",
      city: "",
      profession: "",
      height: "",
      weight: "",
    });
    expect(Object.keys(body)).toEqual(["name"]);
    expect(body.name).toBe("Анна");
  });

  it("converts age to date_of_birth", () => {
    const body = toPersonUpdate({
      name: "",
      age: "30",
      sex: "female",
      city: "Москва",
      profession: "Врач",
      height: "170",
      weight: "65",
    });
    expect(body.date_of_birth).toBeDefined();
    expect(body.sex).toBe("female");
    expect(body.city).toBe("Москва");
    expect(body.profession).toBe("Врач");
    expect(body.height).toBe(170);
    expect(body.weight).toBe(65);
  });
});

describe("fromPerson round-trip", () => {
  it("converts date_of_birth to age string", () => {
    const today = new Date();
    const dob = new Date(today.getFullYear() - 25, today.getMonth(), today.getDate());
    const dobStr = dob.toISOString().slice(0, 10);

    const values = fromPerson({
      name: "Анна",
      date_of_birth: dobStr,
      sex: null,
      city: null,
      profession: null,
      height: 165.5,
      weight: 60.0,
    });
    expect(values.name).toBe("Анна");
    expect(values.age).toBe("25");
    expect(values.sex).toBe("");
    expect(values.city).toBe("");
    expect(values.height).toBe("165.5");
    expect(values.weight).toBe("60");
    // And the values must validate
    expect(profileFormSchema.safeParse(values).success).toBe(true);
  });

  it("returns empty age when date_of_birth is null", () => {
    const values = fromPerson({
      name: "Иван",
      date_of_birth: null,
      sex: null,
      city: null,
      profession: null,
      height: null,
      weight: null,
    });
    expect(values.age).toBe("");
  });
});
