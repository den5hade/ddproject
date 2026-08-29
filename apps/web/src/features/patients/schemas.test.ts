import { describe, expect, it } from "vitest";
import {
  fromPerson,
  maskDateOfBirth,
  profileFormSchema,
  toPersonUpdate,
} from "./schemas";

const base = {
  name: "",
  date_of_birth: "",
  sex: "",
  city: "",
  profession: "",
  height: "",
  weight: "",
};

function withDob(dob: string) {
  return { ...base, date_of_birth: dob };
}

describe("maskDateOfBirth", () => {
  it("inserts dots as digits are typed", () => {
    expect(maskDateOfBirth("25")).toBe("25");
    expect(maskDateOfBirth("250119")).toBe("25.01.19");
    expect(maskDateOfBirth("25011990")).toBe("25.01.1990");
  });

  it("strips non-digits and caps at 8 digits", () => {
    expect(maskDateOfBirth("ab12..34")).toBe("12.34");
    expect(maskDateOfBirth("25011990123")).toBe("25.01.1990");
  });
});

describe("profileFormSchema", () => {
  it("accepts empty form (all optional)", () => {
    expect(profileFormSchema.safeParse(base).success).toBe(true);
  });

  it("accepts a valid date of birth", () => {
    expect(profileFormSchema.safeParse(withDob("25.01.1990")).success).toBe(true);
  });

  it("accepts a leap-year birthday", () => {
    expect(profileFormSchema.safeParse(withDob("29.02.2000")).success).toBe(true);
  });

  it("rejects malformed date of birth", () => {
    expect(profileFormSchema.safeParse(withDob("25-01-1990")).success).toBe(false);
    expect(profileFormSchema.safeParse(withDob("25011990")).success).toBe(false);
    expect(profileFormSchema.safeParse(withDob("25 января 1990")).success).toBe(false);
  });

  it("rejects impossible calendar dates", () => {
    expect(profileFormSchema.safeParse(withDob("30.02.2000")).success).toBe(false);
    expect(profileFormSchema.safeParse(withDob("31.04.2000")).success).toBe(false);
    expect(profileFormSchema.safeParse(withDob("29.02.2001")).success).toBe(false);
  });

  it("rejects a date in the future", () => {
    const future = new Date();
    future.setFullYear(future.getFullYear() + 1);
    const dob = `${String(future.getDate()).padStart(2, "0")}.${String(future.getMonth() + 1).padStart(2, "0")}.${future.getFullYear()}`;
    expect(profileFormSchema.safeParse(withDob(dob)).success).toBe(false);
  });

  it("restricts sex to backend enum values or empty", () => {
    expect(profileFormSchema.safeParse({ ...base, sex: "male" }).success).toBe(true);
    expect(profileFormSchema.safeParse({ ...base, sex: "robot" }).success).toBe(false);
  });

  it("caps name length at 255", () => {
    const result = profileFormSchema.safeParse({ ...base, name: "a".repeat(256) });
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

  it("converts ДД.ММ.ГГГГ to ISO date_of_birth", () => {
    const body = toPersonUpdate({
      name: "",
      date_of_birth: "30.05.1994",
      sex: "female",
      city: "Москва",
      profession: "Врач",
      height: "170",
      weight: "65",
    });
    expect(body.date_of_birth).toBe("1994-05-30");
    expect(body.sex).toBe("female");
    expect(body.city).toBe("Москва");
    expect(body.profession).toBe("Врач");
    expect(body.height).toBe(170);
    expect(body.weight).toBe(65);
  });
});

describe("fromPerson round-trip", () => {
  it("converts ISO date_of_birth to ДД.ММ.ГГГГ string", () => {
    const values = fromPerson({
      name: "Анна",
      date_of_birth: "1994-05-30",
      sex: null,
      city: null,
      profession: null,
      height: 165.5,
      weight: 60.0,
    });
    expect(values.name).toBe("Анна");
    expect(values.date_of_birth).toBe("30.05.1994");
    expect(values.sex).toBe("");
    expect(values.city).toBe("");
    expect(values.height).toBe("165.5");
    expect(values.weight).toBe("60");
    // And the values must validate
    expect(profileFormSchema.safeParse(values).success).toBe(true);
  });

  it("returns empty date_of_birth when it is null", () => {
    const values = fromPerson({
      name: "Иван",
      date_of_birth: null,
      sex: null,
      city: null,
      profession: null,
      height: null,
      weight: null,
    });
    expect(values.date_of_birth).toBe("");
  });
});