"""Contract-level tests for the Classification 2.0 normalization types (Phase 4)."""

from dataclasses import FrozenInstanceError
from typing import Protocol

import pytest
from app.classification.normalize import NormalizedDocument, TextNormalizer


def test_normalized_document_fields():
    doc = NormalizedDocument(
        raw_text="# Title\n\nParagraph",
        headings=["Title"],
        tables=["| A | B |"],
        paragraphs=["Paragraph"],
        metadata={"client_type": "lab_result"},
    )
    assert doc.raw_text == "# Title\n\nParagraph"
    assert doc.headings == ["Title"]
    assert doc.tables == ["| A | B |"]
    assert doc.paragraphs == ["Paragraph"]
    assert doc.metadata == {"client_type": "lab_result"}


def test_normalized_document_metadata_defaults():
    doc = NormalizedDocument(
        raw_text="x",
        headings=[],
        tables=[],
        paragraphs=[],
    )
    assert doc.metadata == {}


def test_normalized_document_is_frozen():
    doc = NormalizedDocument(raw_text="x", headings=[], tables=[], paragraphs=[])
    with pytest.raises(FrozenInstanceError):
        doc.raw_text = "changed"  # type: ignore[misc]


def test_text_normalizer_is_protocol():
    assert issubclass(TextNormalizer, Protocol)


class _IdentityNormalizer(TextNormalizer):
    """Structurally conforming stub: identity transform for contract proof."""

    def normalize(self, markdown: str) -> NormalizedDocument:
        return NormalizedDocument(
            raw_text=markdown,
            headings=[],
            tables=[],
            paragraphs=[],
        )


def test_protocol_contract_signature_is_usable():
    normalizer: TextNormalizer = _IdentityNormalizer()
    doc = normalizer.normalize("# Hello")
    assert isinstance(doc, NormalizedDocument)
    assert doc.raw_text == "# Hello"