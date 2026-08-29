import { z } from "zod";
import type { PersonUpdate } from "./api";

/*
 * Profile form schema. Backend stores date_of_birth, but the UI
 * shows age in full years. toPersonUpdate converts age → date_of_birth,
 * fromPerson converts date_of_birth → age.
 */

const SEX_VALUES = ["male", "female", "unspecified"] as const;

const optionalName = z
  .string()
  .trim()
  .max(255, "Максимум 255 символов");

export const profileFormSchema = z.object({
  name: optionalName,
  age: z
    .string()
    .regex(/^(\d{1,3})?$/, "Возраст: 0–150")
    .refine(
      (v) => v === "" || (Number(v) >= 0 && Number(v) <= 150),
      "Возраст: 0–150",
    ),
  sex: z.enum(["", ...SEX_VALUES]),
  city: optionalName,
  profession: optionalName,
  height: z
    .string()
    .regex(/^(\d+\.?\d*)?$/, "Только числа")
    .refine(
      (v) => v === "" || (Number(v) >= 0 && Number(v) <= 300),
      "Рост: 0–300 см",
    ),
  weight: z
    .string()
    .regex(/^(\d+\.?\d*)?$/, "Только числа")
    .refine(
      (v) => v === "" || (Number(v) >= 0 && Number(v) <= 500),
      "Вес: 0–500 кг",
    ),
});

export type ProfileFormValues = z.infer<typeof profileFormSchema>;

/** Convert age in years → approximate date_of_birth (YYYY-MM-DD). */
function ageToDateOfBirth(ageStr: string): string | undefined {
  const age = Number(ageStr);
  if (!age || age < 0 || age > 150) return undefined;
  const now = new Date();
  const dob = new Date(now.getFullYear() - age, now.getMonth(), now.getDate());
  return dob.toISOString().slice(0, 10);
}

/** Convert date_of_birth (YYYY-MM-DD) → age in full years. */
function dateOfBirthToAge(dob: string): string {
  const birth = new Date(dob);
  const now = new Date();
  let age = now.getFullYear() - birth.getFullYear();
  const monthDiff = now.getMonth() - birth.getMonth();
  if (monthDiff < 0 || (monthDiff === 0 && now.getDate() < birth.getDate())) {
    age--;
  }
  return age >= 0 ? String(age) : "";
}

/** "" → omit key entirely so PATCH never clears fields unintentionally. */
export function toPersonUpdate(values: ProfileFormValues): PersonUpdate {
  const body: PersonUpdate = {};
  const assign = <K extends keyof PersonUpdate>(key: K, raw: string) => {
    if (raw !== "") body[key] = raw as PersonUpdate[K];
  };
  assign("name", values.name);
  const dob = ageToDateOfBirth(values.age);
  if (dob) body.date_of_birth = dob;
  if (values.sex !== "") body.sex = values.sex;
  assign("city", values.city);
  assign("profession", values.profession);
  if (values.height !== "") body.height = Number(values.height);
  if (values.weight !== "") body.weight = Number(values.weight);
  return body;
}

/** Reverse mapping for form default values from the API person object. */
export function fromPerson(person: {
  name?: string | null;
  date_of_birth?: string | null;
  sex?: string | null;
  city?: string | null;
  profession?: string | null;
  height?: number | null;
  weight?: number | null;
}): ProfileFormValues {
  return {
    name: person.name ?? "",
    age: person.date_of_birth ? dateOfBirthToAge(person.date_of_birth.slice(0, 10)) : "",
    sex: (person.sex as ProfileFormValues["sex"]) ?? "",
    city: person.city ?? "",
    profession: person.profession ?? "",
    height: person.height != null ? String(person.height) : "",
    weight: person.weight != null ? String(person.weight) : "",
  };
}
