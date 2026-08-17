# AI Worker

Runs on the Main VPS. Consumes `document.converted`, extracts structured
medical data into PostgreSQL and embeddings into Qdrant.

## Purpose

Turn converted Markdown/JSON artifacts into validated, structured medical data.

## Pipeline

```text
Markdown/JSON
      │
      ▼
Document classification
      │
      ▼
Schema selection
      │
      ▼
LLM structured extraction
      │
      ▼
Pydantic validation
      │
      ▼
DocumentExtraction
      │
      ├───────────────┐
      ▼               ▼
 PostgreSQL          Embeddings
                      │
                      ▼
                    Qdrant
```

Source: `apps/ai-worker/app/pipeline/*` (`normalize`, `parser`, `extraction`,
`validation`, `chunking`, `embeddings`).

## Boundary rules

- **AI worker is not the owner of the medical database.**
- PostgreSQL is the source of truth; Qdrant is a search index.
- AI output must pass through Pydantic validation and domain rules before
  reaching PostgreSQL:

```text
LLM → structured output → Pydantic → domain service → repository → PostgreSQL
```

This controls exactly which data is allowed into the medical DB.

## Typed extraction schemas

LLM output is not saved raw. Each document type maps to a schema:

```text
LabResultSchema
ConsultationSchema
PrescriptionSchema
DiagnosisSchema
ImagingReportSchema
```

Example validation target:

```python
class LabResult(BaseModel):
    test_name: str
    value: float | None
    unit: str | None
    reference_min: float | None
    reference_max: float | None
```

## Queues

- Consumes: `document.extract` (DLQ: `document.extract.dlq`)
- Publishes: `document.analysis.completed` / failure events

## Failure & confidence

- Retry 3 attempts → DLQ.
- Low confidence → `EXTRACTION_REVIEW_REQUIRED` (not `COMPLETED`); a specialist
  can later review/correct the extraction.