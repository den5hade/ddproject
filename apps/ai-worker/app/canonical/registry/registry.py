"""Registered canonical schemas and their extraction/rendering hooks.

During M0 the registry is populated from the installed ``canonical`` package's
model index (``CANONICAL_MODELS``); a web-hosted schema registry is planned.
"""


class SchemaRegistry:
    """Lookup of canonical schemas by document type.

    Empty by design during M0: typing/dispatch uses the heuristic classifier
    plus prompt-per-document-type; typed strategies arrive in later milestones.
    """