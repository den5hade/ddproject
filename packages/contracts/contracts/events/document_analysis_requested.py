from contracts.schemas.events import DocumentEvent


class DocumentAnalysisRequested(DocumentEvent):
    """ai orchestrator → ai-worker: extract structured data from converted markdown."""

    output_storage_key: str
    mime_type: str
