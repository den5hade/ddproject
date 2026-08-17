# Analytics API

> Status: **deferred** (milestone M6 / Phase 7). The tables (`observations`,
> `diagnoses`, `medications`, `patient_consents`) are not yet created; this
> page documents the intended behavior.

## Intended endpoints

```text
GET /patients/{id}/analytics/observations     time series per observation
GET /patients/{id}/timeline                    assembled from encounters/documents/observations
GET /patients/{id}/analytics/summary           AI-generated summary (later)
```

## Principles

- Start with **deterministic** analytics (numeric trends), not AI.
  Example: `Hemoglobin Jan 125 → Mar 131 → Jun 135`.
- Observations are normalized rows extracted from `document_extractions.data`
  (see [data/DB_MODELS.md](../data/DB_MODELS.md) §deferred).
- AI summary is additive and never the sole source of numeric analytics.

## Authorization

Patient owner or grant flag `can_view_analytics`. All views audited.
