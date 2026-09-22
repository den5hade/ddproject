"""Canonical validation metadata composition (YAML frontmatter blocks)."""

from datetime import UTC, datetime
from typing import Any


def build_validation_meta(
    *,
    status: str = "valid",
    schema_valid: bool = True,
    warnings: list[str] | None = None,
    validated_at: str | None = None,
) -> dict[str, Any]:
    """Compose the Python-built ``validation`` block of the canonical frontmatter."""
    return {
        "status": status,
        "schema_valid": schema_valid,
        "warnings": warnings or [],
        "validated_at": validated_at or datetime.now(UTC).isoformat(),
    }