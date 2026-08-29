import { z } from "zod";
import type { PersonUpdate } from "./api";

/*
 * Profile form schema. The UI collects date_of_birth in a masked
 * ДД.ММ.ГГГГ input; toPersonUpdate converts it to the ISO YYYY-MM-DD
 * format the API stores, fromPerson converts back for prefill.
 */

const SEX_VALUES = ["male", "female", "unspecified"] as const;

const optionalName = z
  .string()
  .trim()
  .max(255, "Максимум 255 символов");

const FULL_DOB = /^(\d{2}\.\d{2}\.\d{4})?$/;
const DOB_REQUIRED = "ДД.ММ.ГГГГ";
const DATE_INVALID = "Такой даты не существует";
const DATE_FUTURE = "Дата не может быть в будущем";

const dateOfBirthField = z
  .string()
  .trim()
  .regex(FULL_DOB, DOB_REQUIRED)
  .refine((v) => v === "" || isRealCalendarDate(parseMask(v)), DATE_INVALID)
  .refine((v) => v === "" || !isFutureDate(parseMask(v)), DATE_FUTURE);

export const profileFormSchema = z.object({
  name: optionalName,
  date_of_birth: dateOfBirthField,
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

/** Digits-only → masked ДД.ММ.ГГГГ (typing mask, capped at 8 digits). */
export function maskDateOfBirth(input: string): string {
  const digits = input.replace(/\D/g, "").slice(0, 8);
  return [digits.slice(0, 2), digits.slice(2, 4), digits.slice(4, 8)]
    .filter(Boolean)
    .join(".");
}

type MaskParts = { day: number; month: number; year: number };

function parseMask(mask: string): MaskParts | null {
  if (!/^\d{2}\.\d{2}\.\d{4}$/.test(mask)) return null;
  const [day, month, year] = mask.split(".").map(Number);
  return { day, month, year };
}

/** Reject overflow dates like 30.02 or 31.04 via UTC-normalization round-trip. */
function isRealCalendarDate(parts: MaskParts | null): boolean {
  if (!parts) return false;
  const date = new Date(Date.UTC(parts.year, parts.month - 1, parts.day));
  return (
    date.getUTCFullYear() === parts.year &&
    date.getUTCMonth() === parts.month - 1 &&
    date.getUTCDate() === parts.day
  );
}

function isFutureDate(parts: MaskParts | null): boolean {
  if (!parts) return false;
  const birth = new Date(parts.year, parts.month - 1, parts.day);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return birth > today;
}

/** ДД.ММ.ГГГГ → YYYY-MM-DD (or undefined for incomplete masks). */
function maskToIso(mask: string): string | undefined {
  const parts = parseMask(mask);
  if (!parts) return undefined;
  return `${parts.year}-${String(parts.month).padStart(2, "0")}-${String(parts.day).padStart(2, "0")}`;
}

/** YYYY-MM-DD → ДД.ММ.ГГГГ (or "" for malformed input). */
function isoToMask(iso: string): string {
  const [year, month, day] = iso.split("-");
  if (!year || !month || !day) return "";
  return `${day}.${month}.${year}`;
}

/** "" → omit key entirely so PATCH never clears fields unintentionally. */
export function toPersonUpdate(values: ProfileFormValues): PersonUpdate {
  const body: PersonUpdate = {};
  const assign = <K extends keyof PersonUpdate>(key: K, raw: string) => {
    if (raw !== "") body[key] = raw as PersonUpdate[K];
  };
  assign("name", values.name);
  const dob = maskToIso(values.date_of_birth);
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
    date_of_birth: person.date_of_birth ? isoToMask(person.date_of_birth.slice(0, 10)) : "",
    sex: (person.sex as ProfileFormValues["sex"]) ?? "",
    city: person.city ?? "",
    profession: person.profession ?? "",
    height: person.height != null ? String(person.height) : "",
    weight: person.weight != null ? String(person.weight) : "",
  };
}