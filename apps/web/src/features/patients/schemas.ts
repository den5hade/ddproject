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
  first_name: optionalName,
  last_name: optionalName,
  middle_name: optionalName.max(255, "Максимум 255 символов"),
  date_of_birth: z
    .string()
    .regex(/^(\d{4}-\d{2}-\d{2})?$/, "Формат даты: ГГГГ-ММ-ДД")
    .refine(
      (value) => !value || value <= new Date().toISOString().slice(0, 10),
      "Дата рождения не может быть в будущем",
    ),
  sex: z.enum(["", ...SEX_VALUES]),
});

export type ProfileFormValues = z.infer<typeof profileFormSchema>;

/** "" → omit key entirely so PATCH never clears fields unintentionally. */
export function toPersonUpdate(values: ProfileFormValues): PersonUpdate {
  const body: PersonUpdate = {};
  const assign = <K extends keyof PersonUpdate>(key: K, raw: string) => {
    if (raw !== "") body[key] = raw as PersonUpdate[K];
  };
  assign("first_name", values.first_name);
  assign("last_name", values.last_name);
  assign("middle_name", values.middle_name);
  assign("date_of_birth", values.date_of_birth);
  if (values.sex !== "") body.sex = values.sex;
  return body;
}

/** Reverse mapping for form default values from the API person object. */
export function fromPerson(person: {
  first_name?: string | null;
  last_name?: string | null;
  middle_name?: string | null;
  date_of_birth?: string | null;
  sex?: string | null;
}): ProfileFormValues {
  return {
    first_name: person.first_name ?? "",
    last_name: person.last_name ?? "",
    middle_name: person.middle_name ?? "",
    date_of_birth: person.date_of_birth?.slice(0, 10) ?? "",
    sex: (person.sex as ProfileFormValues["sex"]) ?? "",
  };
}
