from contracts.schemas.events import DocumentEvent


class DocumentConverted(DocumentEvent):
    """marker-worker → ai-worker / account-api: markdown/JSON artifact ready."""

    output_storage_key: str