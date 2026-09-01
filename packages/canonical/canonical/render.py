"""Deterministic Python rendering of a canonical document into markdown + YAML.

``canonical.json`` remains the single source of truth; these functions only
produce the human-oriented ``structured.md`` output.
"""

import yaml

from canonical.metadata import FrontmatterMeta
from canonical.schemas import BaseCanonical

__all__ = ["render_document", "render_frontmatter", "render_markdown"]


def render_frontmatter(meta: FrontmatterMeta) -> str:
    """Render the YAML frontmatter block from metadata (never from the LLM)."""
    body = yaml.safe_dump(
        meta.to_dict(),
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )
    return f"---\n{body}---"


def _render_laboratory(canonical: BaseCanonical) -> str:
    fields = canonical.fields
    if fields is None or not fields.results:
        return "### Результаты\n\n_(нет данных)_\n"
    lines = ["### Результаты", ""]
    for item in fields.results:
        flag = " ⚠" if item.flagged else ""
        value = item.value if item.value is not None else "—"
        unit = f" {item.unit}" if item.unit else ""
        ref = ""
        if item.reference_min is not None or item.reference_max is not None:
            lo = item.reference_min if item.reference_min is not None else "∞"
            hi = item.reference_max if item.reference_max is not None else "∞"
            ref = f" (реф. {lo}–{hi})"
        lines.append(f"- **{item.name}**: {value}{unit}{ref}{flag}")
    lines.append("")
    return "\n".join(lines)


def _render_prescription(canonical: BaseCanonical) -> str:
    fields = canonical.fields
    lines = ["### Назначения", ""]
    if fields is None or not fields.medications:
        lines.append("_(нет данных)_\n")
        return "\n".join(lines)
    for med in fields.medications:
        parts = [f"**{med.name}**"]
        for key in ("dosage", "frequency", "duration"):
            value = getattr(med, key)
            if value:
                parts.append(value)
        lines.append(f"- {' · '.join(parts)}")
    if fields.doctor:
        lines.append("")
        lines.append(f"Врач: {fields.doctor}")
    lines.append("")
    return "\n".join(lines)


def _render_generic(canonical: BaseCanonical) -> str:
    fields = canonical.fields or {}
    lines = ["### Содержание", ""]
    if not fields:
        lines.append("_(нет данных)_\n")
        return "\n".join(lines)
    for key, value in fields.items():
        lines.append(f"- **{key}**: {value}")
    lines.append("")
    return "\n".join(lines)


def render_markdown(canonical: BaseCanonical) -> str:
    """Render the markdown body for a canonical document.

    Only the doc-type-specific payload is rendered here; all administrative
    metadata is produced separately as YAML frontmatter.
    """
    schema = canonical.schema_name
    if schema == "laboratory":
        return _render_laboratory(canonical)
    if schema == "prescription":
        return _render_prescription(canonical)
    return _render_generic(canonical)


def render_document(canonical: BaseCanonical, meta: FrontmatterMeta) -> str:
    """Render the full ``structured.md``: YAML frontmatter + markdown body."""
    frontmatter = render_frontmatter(meta)
    body = render_markdown(canonical)
    return f"{frontmatter}\n\n{body}"
