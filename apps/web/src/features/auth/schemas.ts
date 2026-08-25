import { z } from "zod";

/*
 * Mirrors backend Identity.parse rules (apps/account-api/app/domain/identity.py):
 * - email  ^[^@\s]+@[^@\s]+\.[^@\s]+$
 * - phone  ^\+[1-9]\d{7,14}$   (E.164)
 * Backend lowercases emails; we mirror that client-side before submit.
 */

export const EMAIL_PATTERN = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
export const PHONE_PATTERN = /^\+[1-9]\d{7,14}$/;

export function normalizeIdentity(value: string): string {
  return EMAIL_PATTERN.test(value) ? value.toLowerCase() : value;
}

const identityField = z
  .string()
  .trim()
  .min(3, "Минимум 3 символа")
  .max(255, "Максимум 255 символов")
  .refine(
    (value) => EMAIL_PATTERN.test(value) || PHONE_PATTERN.test(value),
    "Укажите корректный email или телефон в формате +7…",
  );

export const identityFormSchema = z.object({
  identity: identityField,
});

export const otpFormSchema = z.object({
  code: z.string().regex(/^\d{6}$/, "Код состоит из 6 цифр"),
});

export type IdentityFormValues = z.infer<typeof identityFormSchema>;
