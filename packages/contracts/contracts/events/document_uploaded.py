from contracts.schemas.events import DocumentEvent


class DocumentUploaded(DocumentEvent):
    """account-api → marker-worker: original is stored; conversion may begin."""

    storage_key: str