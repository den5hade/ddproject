from contracts.schemas.events import DocumentEvent


class DocumentStored(DocumentEvent):
    """objectstorage-worker → account-api: file uploaded to S3, DB may be updated."""

    storage_key: str
    mime_type: str
    size_bytes: int
    checksum: str