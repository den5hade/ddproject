import { z } from "zod";
import type { PersonUpdate } from "./api";

/*
 * Profile form schema. Mirrors backend PersonUpdate constraints
 * (apps/account-api/app/schemas/profile.py), including the
 * date_of_birth-not-in-future validator.
 */

const SEX_VALUES = ["male", "female", "unspecified"] as const;

const optionalName = z
  .string()
  .trim()
  .max(255, "Максимум 255 символов");

export const profileFormSchema = z.object({
  name: optionalName,
  date_of_birth: z
    .string()
    .regex(/^(\d{4}-\d{2}-\d{2})?$/, "Формат даты: ГГГГ-ММ-ДД")
    .refine(
      (value) => !value || value <= new Date().toISOString().slice(0, 10),
      "Дата рождения не может быть в будущем",
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

/** "" → omit key entirely so PATCH never clears fields unintentionally. */
export function toPersonUpdate(values: ProfileFormValues): PersonUpdate {
  const body: PersonUpdate = {};
  const assign = <K extends keyof PersonUpdate>(key: K, raw: string) => {
    if (raw !== "") body[key] = raw as PersonUpdate[K];
  };
  assign("name", values.name);
  assign("date_of_birth", values.date_of_birth);
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
    date_of_birth: person.date_of_birth?.slice(0, 10) ?? "",
    sex: (person.sex as ProfileFormValues["sex"]) ?? "",
    city: person.city ?? "",
    profession: person.profession ?? "",
    height: person.height != null ? String(person.height) : "",
    weight: person.weight != null ? String(person.weight) : "",
  };
}
