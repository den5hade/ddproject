from contracts.schemas.events import DocumentEvent


class DocumentConversionRequested(DocumentEvent):
    """marker orchestrator → marker-worker: convert the stored original to markdown."""

    storage_key: str
    mime_type: str
