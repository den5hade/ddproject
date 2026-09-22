"""Classification infrastructure errors."""


class ClassificationError(Exception):
    """Base error for classification failures."""


class InvalidClassificationInputError(ClassificationError):
    """Raised when classification receives input violating the contract."""


class SchemaResolutionError(ClassificationError):
    """Raised when a (document_type, document_subtype) pair cannot be resolved."""
