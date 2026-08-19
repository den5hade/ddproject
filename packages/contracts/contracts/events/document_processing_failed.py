from contracts.schemas.events import DocumentEvent


class DocumentProcessingFailed(DocumentEvent):
    """any worker → account-api: a pipeline step failed permanently for this version."""

    job_type: str
    error_code: str | None = None
    error_message: str | None = None