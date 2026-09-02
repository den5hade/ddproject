/*
 * Tolerant normalizer for extracted medical data (SG §35–36).
 * The AI worker schema does not exist yet (stub workers), so the
 * viewer must handle any plausible shape gracefully and return null
 * when nothing usable is present → UI shows «Информация ещё
 * извлекается».
 *
 * Supported input shapes for `data`:
 *   1. [{name|title|label, value|result, unit?, reference?|norm?}, ...]
 *   2. { results | observations | items: [ ...as above ] }
 *   3. { Hemoglobin: {value, unit, reference}, ... }
 *   4. { Hemoglobin: "135 g/L", ... }            (flat primitives)
 */

export interface Observation {
  name: string;
  value: string;
  unit?: string;
  reference?: string;
  /** Canonical numeric reference bounds (envelope keys from the canonical schema). */
  referenceMin?: number;
  referenceMax?: number;
  /** Canonical flag (e.g. lab result outside expected range). */
  flagged?: boolean;
}

const NAME_KEYS = ["name", "title", "label", "indicator", "parameter"] as const;
const VALUE_KEYS = ["value", "result", "measured", "reading"] as const;
const UNIT_KEYS = ["unit", "units"] as const;
const REF_KEYS = ["reference", "reference_range", "ref", "norm", "range"] as const;

function pick(record: Record<string, unknown>, keys: readonly string[]): unknown {
  for (const key of keys) {
    if (key in record && record[key] !== null && record[key] !== undefined) {
      return record[key];
    }
  }
  return undefined;
}

function stringify(value: unknown): string | undefined {
  if (value === null || value === undefined) return undefined;
  if (typeof value === "string") {
    const trimmed = value.trim();
    return trimmed === "" ? undefined : trimmed;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return undefined;
}

function toObservation(entry: unknown, fallbackName?: string): Observation | null {
  if (entry === null || typeof entry !== "object") {
    // Flat primitive under a key: value only
    const value = stringify(entry);
    if (value && fallbackName) return { name: fallbackName, value };
    return null;
  }
  const record = entry as Record<string, unknown>;

  const name = stringify(pick(record, NAME_KEYS)) ?? fallbackName;
  let value = stringify(pick(record, VALUE_KEYS));

  // Value embedded in nested object {value: {...}} or numeric fields
  if (!value) {
    const numericKeys = Object.keys(record).filter((key) =>
      /^value_|^result_/i.test(key),
    );
    for (const key of numericKeys) {
      value = stringify(record[key]);
      if (value) break;
    }
  }

  const unit = stringify(pick(record, UNIT_KEYS));
  const reference = stringify(pick(record, REF_KEYS));

  if (!name || !value) return null;
  return {
    name,
    value,
    unit,
    reference: reference ?? undefined,
  };
}

const LIST_CONTAINER_KEYS = ["results", "observations", "items", "parameters"] as const;

export function parseExtractionData(data: unknown): Observation[] | null {
  if (data === null || typeof data !== "object") return null;

  const record = data as Record<string, unknown>;

  // Shape 2: wrapped lists
  for (const key of LIST_CONTAINER_KEYS) {
    if (Array.isArray(record[key])) {
      const parsed = (record[key] as unknown[])
        .map((entry) => toObservation(entry))
        .filter((item): item is Observation => item !== null);
      if (parsed.length > 0) return parsed;
    }
  }

  // Shape 1: bare array at top level
  if (Array.isArray(data)) {
    const parsed = (data as unknown[])
      .map((entry) => toObservation(entry))
      .filter((item): item is Observation => item !== null);
    return parsed.length > 0 ? parsed : null;
  }

  // Shapes 3–4: keyed object
  const parsed: Observation[] = [];
  for (const [key, raw] of Object.entries(record)) {
    if (LIST_CONTAINER_KEYS.includes(key as (typeof LIST_CONTAINER_KEYS)[number])) {
      continue;
    }
    const observation = toObservation(raw, prettifyKey(key));
    if (observation) parsed.push(observation);
  }
  return parsed.length > 0 ? parsed : null;
}

/** "reference_range" → "Reference range" */
function prettifyKey(key: string): string {
  return key
    .replace(/[_-]+/g, " ")
    .replace(/^\p{Ll}/u, (c) => c.toUpperCase());
}
