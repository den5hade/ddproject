/*
 * Normalizer for the canonical extraction envelope (plan backend Phases A–G).
 *
 * The backend persists `canonical.json` — the single source of truth — into
 * `document_extractions.data` and exposes it via `GET /documents/{id}/canonical`
 * as `CanonicalDataResponse.data`. The canonical object has the shape:
 *
 *   {
 *     "document_date": "…", "language": "ru",
 *     "type": "laboratory" | "prescription" | "generic",
 *     "subtype": "…",
 *     "fields": { … doc-type-specific payload … },
 *     "canonical_key": "…", "structured_key": "…"   // enriched, added by the pipeline
 *   }
 *
 * This module maps it into a viewer-friendly discriminated union. It never
 * surfaces envelope keys (document_date, language, type, subtype, …) as
 * observations — those are metadata, not lab results.
 *
 * Legacy shapes (pre-canonical `extraction.data`) are still recognized so old
 * documents keep rendering (see `extraction.ts` for the loose normalizer).
 */

import { parseExtractionData, type Observation } from "./extraction";

export interface Medication {
  name: string;
  dosage?: string;
  frequency?: string;
  duration?: string;
}

export type ExtractionView =
  | { kind: "laboratory"; observations: Observation[] }
  | { kind: "prescription"; medications: Medication[]; doctor?: string; issuedAt?: string }
  | { kind: "generic"; observations: Observation[] }
  | { kind: "legacy"; observations: Observation[] };

const CANONICAL_ENVELOPE_KEYS = new Set([
  "document_date",
  "language",
  "type",
  "subtype",
  "subtype_value",
  "schema_name",
  "schema_version",
  "canonical_key",
  "structured_key",
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function asNumber(value: unknown): number | undefined {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    const parsed = Number(value.replace(",", "."));
    if (Number.isFinite(parsed)) return parsed;
  }
  return undefined;
}

function asString(value: unknown): string | undefined {
  if (typeof value === "string") {
    const trimmed = value.trim();
    return trimmed === "" ? undefined : trimmed;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return undefined;
}

function formatRange(min: number | undefined, max: number | undefined): string | undefined {
  if (min === undefined && max === undefined) return undefined;
  if (min !== undefined && max !== undefined) return `${min}–${max}`;
  if (min !== undefined) return `≥ ${min}`;
  return `≤ ${max}`;
}

const OBSERVATION_KEYS = [
  "name",
  "title",
  "label",
  "indicator",
  "parameter",
] as const;

function toResultObservation(entry: unknown): Observation | null {
  if (!isRecord(entry)) return null;
  const name = OBSERVATION_KEYS.map((key) => asString(entry[key]))
    .find((value): value is string => value !== undefined);
  const rawValue = asString(entry["value"] ?? entry["result"]);
  if (!name || rawValue === undefined) return null;

  return {
    name,
    value: rawValue,
    unit: asString(entry["unit"] ?? entry["units"]),
    referenceMin: asNumber(entry["reference_min"] ?? entry["referenceMin"]),
    referenceMax: asNumber(entry["reference_max"] ?? entry["referenceMax"]),
    flagged: entry["flagged"] === true,
    reference: formatRange(
      asNumber(entry["reference_min"] ?? entry["referenceMin"]),
      asNumber(entry["reference_max"] ?? entry["referenceMax"]),
    ),
  };
}

function toMedication(entry: unknown): Medication | null {
  if (!isRecord(entry)) return null;
  const name = asString(entry["name"]);
  if (!name) return null;
  return {
    name,
    dosage: asString(entry["dosage"]),
    frequency: asString(entry["frequency"]),
    duration: asString(entry["duration"]),
  };
}

function listOf<T>(value: unknown, mapper: (entry: unknown) => T | null): T[] | null {
  if (!Array.isArray(value)) return null;
  const mapped = value
    .map(mapper)
    .filter((item): item is T => item !== null);
  return mapped.length > 0 ? mapped : null;
}

/**
 * Detect the canonical envelope: `fields` present (plus any of the
 * administrative keys). A raw list or unrelated object is NOT canonical.
 */
function isCanonicalEnvelope(record: Record<string, unknown>): boolean {
  if (!("fields" in record)) return false;
  return (
    "document_date" in record ||
    "language" in record ||
    "type" in record ||
    "subtype" in record
  );
}

export function normalizeCanonical(data: unknown): ExtractionView | null {
  if (!isRecord(data)) {
    // Legacy shape 1: bare array → keep old behavior.
    if (Array.isArray(data)) {
      const observations = parseExtractionData(data);
      return observations ? { kind: "legacy", observations } : null;
    }
    return null;
  }

  // Strip canonical envelope keys so generic / legacy parsing never treats
  // metadata as observations.
  const payload: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(data)) {
    if (!CANONICAL_ENVELOPE_KEYS.has(key)) payload[key] = value;
  }

  const fields = "fields" in data ? data["fields"] : undefined;

  if (isCanonicalEnvelope(data) && isRecord(fields)) {
    const observations = listOf(fields["results"], toResultObservation);
    if (observations) {
      return { kind: "laboratory", observations };
    }
    const medications = listOf(fields["medications"], toMedication);
    if (medications) {
      return {
        kind: "prescription",
        medications,
        doctor: asString(fields["doctor"]),
        issuedAt: asString(fields["issued_at"] ?? fields["issuedAt"]),
      };
    }
    const generic = parseExtractionData(fields);
    if (generic) return { kind: "generic", observations: generic };
    return null;
  }

  // No canonical envelope → legacy / loose shapes (extraction.ts).
  const observations = parseExtractionData(payload);
  return observations ? { kind: "legacy", observations } : null;
}