"""Extraction strategies: how each document type is turned into a canonical doc.

Placeholder base. During M0 a single prompt-driven extraction path is used
(``canonical.yaml`` per document type via ``PromptManager``); typed extraction
strategies land in the canonical-core milestone.
"""


class ExtractionStrategy:
    """Base type for document-type-specific canonical extraction."""