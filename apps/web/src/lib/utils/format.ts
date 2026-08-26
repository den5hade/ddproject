/*
 * Display formatters (ru locale). Server datetimes arrive as
 * Europe/Moscow ISO strings (+03:00) — format as-is.
 */

const DATE_LONG = new Intl.DateTimeFormat("ru-RU", {
  day: "numeric",
  month: "long",
  year: "numeric",
});

const DATE_SHORT = new Intl.DateTimeFormat("ru-RU", {
  day: "numeric",
  month: "short",
  year: "numeric",
});

const MONTH_YEAR = new Intl.DateTimeFormat("ru-RU", {
  month: "long",
  year: "numeric",
});

function toDate(iso: string): Date | null {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** «15 августа 2026» */
export function formatDateRu(iso: string): string {
  const date = toDate(iso);
  // ru-RU long dates end with an era suffix («… 2026 г.») — strip it
  return date ? DATE_LONG.format(date).replace(/\s*г\.$/, "") : "";
}

/** «15 авг. 2026» */
export function formatDateShortRu(iso: string): string {
  const date = toDate(iso);
  return date ? DATE_SHORT.format(date) : "";
}

/** «Август 2026» — list group headers (SG §56) */
export function formatMonthYearRu(iso: string): string {
  const date = toDate(iso);
  if (!date) return "";
  const formatted = MONTH_YEAR.format(date).replace(/\s*г\.$/, "");
  return formatted.charAt(0).toUpperCase() + formatted.slice(1);
}

/** Group key for month grouping: stable YYYY-MM. */
export function monthKey(iso: string): string {
  return iso.slice(0, 7);
}

export function greetingForHour(hour: number): "morning" | "afternoon" | "evening" {
  if (hour < 12) return "morning";
  if (hour < 18) return "afternoon";
  return "evening";
}

/** «589 Б» · «172,3 КБ» · «1,2 МБ» */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 }).format(kb)} КБ`;
  const mb = kb / 1024;
  return `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 }).format(mb)} МБ`;
}
