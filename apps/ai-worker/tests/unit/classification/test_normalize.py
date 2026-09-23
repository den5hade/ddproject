"""Contract + implementation tests for Classification 2.0 normalization."""

from dataclasses import FrozenInstanceError
from typing import Protocol

import pytest
from app.classification.normalize import (
    MarkdownNormalizer,
    NormalizedDocument,
    TextNormalizer,
)

MARKER = """## Page 1

БЮДЖЕТНОЕ УЧРЕЖДЕНИЕ "ПОЛИКЛИНИКА № 2"

### Гематологические исследования

| Параметр | Результат | Ед. изм. | Референсные значения |
| :--- | :--- | :--- | :--- |
| HGB Гемоглобин | 147 | г/л | [122 - 181] |

**Дата** 27.06.2024
"""


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


# --- MarkdownNormalizer implementation (M2 Phase 1) -------------------------


def test_normalizer_extracts_headings():
    doc = MarkdownNormalizer().normalize(MARKER)
    assert doc.headings == ["page 1", "гематологические исследования"]
    assert doc.metadata["heading_count"] == 2


def test_normalizer_extracts_tables_as_whole_blocks():
    doc = MarkdownNormalizer().normalize(MARKER)
    assert len(doc.tables) == 1
    assert doc.metadata["table_count"] == 1
    table = doc.tables[0]
    assert "| параметр | результат | ед. изм. | референсные значения |" in table
    assert "| hgb гемоглобин | 147 | г/л | [122 - 181] |" in table


def test_normalizer_extracts_paragraphs():
    doc = MarkdownNormalizer().normalize(MARKER)
    assert doc.metadata["paragraph_count"] == 2
    assert any("бюджетное учреждение" in p for p in doc.paragraphs)
    assert any("дата" in p and "27.06.2024" in p for p in doc.paragraphs)


def test_normalizer_normalizes_whitespace_case_and_unicode():
    doc = MarkdownNormalizer().normalize(
        "РЕФЕРЕНСНЫЕ   ЗНАЧЕНИЯ\n\nреференсные\tзначения\n\nРеференсные значения\n"
    )
    assert "референсные значения" in doc.raw_text
    assert doc.raw_text.count("референсные значения") == 3


def test_normalizer_replaces_ocr_punctuation_variants():
    text = "рецепт — назначение\nприём – 09:30\nзначение\u00a0x"
    doc = MarkdownNormalizer().normalize(text)
    assert "-" in doc.raw_text
    assert "значение x" in doc.raw_text


def test_normalizer_empty_and_none_input():
    blank = MarkdownNormalizer().normalize("")
    assert blank.raw_text == ""
    assert blank.headings == []
    assert blank.tables == []
    assert blank.paragraphs == []

    none_doc = MarkdownNormalizer().normalize(None)  # type: ignore[arg-type]
    assert none_doc.raw_text == ""


def test_normalizer_preserves_caller_metadata():
    doc = MarkdownNormalizer().normalize(
        MARKER,
        metadata={"client_type": "lab_result"},
    )
    assert doc.metadata["client_type"] == "lab_result"
    assert doc.metadata["table_count"] == 1


def test_normalizer_treats_separate_table_blocks_independently():
    text = """| A | B |
| :--- | :--- |
| x | y |

| C | D |
| :--- | :--- |
| z | w |
"""
    doc = MarkdownNormalizer().normalize(text)
    assert len(doc.tables) == 2


def test_normalizer_is_usable_through_protocol():
    normalizer: TextNormalizer = MarkdownNormalizer()
    doc = normalizer.normalize("# Hello\n\nworld")
    assert doc.headings == ["hello"]
    assert doc.paragraphs == ["world"]