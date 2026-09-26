"""PII infrastructure errors."""


class PIIError(Exception):
    """Base error for PII detection/filtering failures."""


class InvalidPIIInputError(PIIError):
    """Raised when the PII gate receives input violating the contract."""


class PIIDetectorError(PIIError):
    """Raised when a detector fails to scan a document."""


class PIIPolicyError(PIIError):
    """Raised when policy configuration is missing or inconsistent."""


class PIIRedactionError(PIIError):
    """Raised when redaction cannot produce a replacement string."""


class PIIDecisionError(PIIError):
    """Raised when no gate decision can be produced — the fail-closed path.

    The gate must never degrade to "no findings, therefore allow". When the
    gate itself cannot decide, this error is raised and the pipeline must not
    proceed to extraction (plan §0, "Fail closed on gate failure").
    """
