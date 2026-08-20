# Exception Handling Rules and Patterns

All API routes must translate domain exceptions into HTTP responses using the
centralised helper in `app/api/v1/http_errors.py`.

## Rules

1. **Never raise `JSONResponse`.** Every error response must go through
   `raise_for(exc)` which raises a FastAPI `HTTPException`. This ensures
   exception handlers, middleware, and OpenAPI docs see a consistent error
   transport.

2. **Never construct `HTTPException` inline in a route.** Use `raise_for(exc)`
   instead. The status code is determined by the exception type, not by the
   call-site.

3. **All domain exceptions must be registered** in the `_EXCEPTION_STATUS`
   mapping inside `http_errors.py`. An unregistered exception falls back to
   `400 Bad Request`, which is almost never the right answer.

4. **Always use `from exc`** when catching. The `raise_for` helper chains
   automatically, but any additional re-raise must preserve the chain.

5. **Dependencies** (auth guards, RBAC, ABAC) may still raise `HTTPException`
   directly because they don't map a domain exception — they fail before any
   domain logic runs.

## Pattern

```python
from app.api.v1.http_errors import raise_for
from app.domain.medical import DocumentNotFoundError

@router.get("/documents/{document_id}")
async def get_document(document_id: UUID, service: DocumentServiceDep):
    try:
        document = await service.get_document(document_id)
    except DocumentNotFoundError as exc:
        raise_for(exc)
    return ...
```

## Adding a new domain exception

1. Define the exception in the appropriate `app/domain/*.py` module.

2. Add an entry to `_EXCEPTION_STATUS` in `app/api/v1/http_errors.py`:

   ```python
   from app.domain.medical import MyNewError

   _EXCEPTION_STATUS = {
       ...,
       MyNewError: status.HTTP_422_UNPROCESSABLE_ENTITY,
   }
   ```

3. Catch and call `raise_for(exc)` in the route that can trigger it.

## Current mapping

| Domain exception | HTTP status |
|---|---|
| `RateLimitError` | 429 |
| `OtpVerificationError` | 400 |
| `RefreshTokenError` | 401 |
| `PersonNotFoundError` | 404 |
| `PatientAlreadyExistsError` | 409 |
| `DocumentNotFoundError` | 404 |
| `DocumentQuotaExceededError` | 429 |
| `FileTooLargeError` | 413 |
| `UnsupportedFileTypeError` | 415 |
| `StorageUnavailableError` | 503 |
| `JobNotFoundError` | 404 |
| `EncounterNotFoundError` | 404 |
| `PatientAccessGrantNotFoundError` | 404 |
| `RoleNotFoundError` | 404 |
| *(any unregistered)* | 400 (fallback) |

## Why `HTTPException` over `JSONResponse`

- Participates in FastAPI's exception-handler pipeline (`@app.exception_handler`).
- Appears in the OpenAPI schema under "Responses".
- Supports exception chaining (`from exc`) for clean tracebacks.
- Consistent with how FastAPI itself surfaces errors (validation, auth).
