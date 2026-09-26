"""AST helpers for the PII package import guards (M4 Phase 3).

The PII gate is a document-level capability: ``app/pii/`` must not import
infrastructure (S3 / RabbitMQ / storage) and must not import classification
domain types, pipeline internals or ``packages.canonical`` models. The single
sanctioned exception is ``app.classification.normalize.NormalizedDocument``,
imported **type-only** under ``if TYPE_CHECKING:`` — the one normalizer feeds
both classification and the PII gate, so reusing the type is the point
(``PII GATE/IMPL_ARCH.md`` Phase 2; plan §4.6).

A substring scan over source lines cannot tell a runtime import from a
type-only one, so these helpers parse the module instead. Both test modules
import from here rather than keeping private copies: a boundary control that
exists twice is a control that can drift.

Deliberately stdlib-only (``ast`` + ``pathlib``) — M4 adds no dependency.
"""

import ast
from pathlib import Path

PII_PACKAGE_DIR = Path(__file__).resolve().parents[2] / "app" / "pii"
"""``apps/ai-worker/app/pii`` — every ``*.py`` in it is under the guards."""

FORBIDDEN_INFRA_SUBSTRINGS = ("s3", "rabbit", "storage")
"""Substrings that mark a persistence/messaging import (mirrors the M1 guard)."""

FORBIDDEN_DOMAIN_PREFIXES = (
    "app.classification",
    "app.pipeline",
    "app.llm",
    "packages.canonical",
    "pdf_storage",
    "pdf_messaging",
)
"""Package prefixes ``app/pii/`` may never import at runtime.

``app.classification`` is listed because its *domain* types (``DocumentType``,
``ClassificationResult``, …) would invert the dependency between two
document-level capabilities. ``app.classification.normalize`` is likewise
listed: the allowed borrow of ``NormalizedDocument`` is type-only, and if it
ever becomes a runtime import the guard must fail — a runtime import would
mean PII cannot be exercised without classification being importable.
"""

ALLOWED_TYPE_ONLY_IMPORTS = {
    ("app.classification.normalize", "NormalizedDocument"),
    ("app.pipeline.context", "ProcessingContext"),
}
"""The complete set of type-only borrows ``app/pii/`` is permitted.

Anything else — a second classification type, a pipeline context field, a
canonical model — fails ``test_pii_package_type_only_imports_are_narrow``.

``ProcessingContext`` was added in Phase 5, and only because ORDER §8 fixes
``PIIGate.inspect(document: NormalizedDocument, context: ProcessingContext)``:
the gate's whole architectural point is that it is a *document-level*
capability threaded through the pipeline, so its signature must name the
pipeline's own context. This mirrors what ``app/classification/service.py``
already does at `:39-40` for the identical reason, and the same objection
applies to both — a type-only borrow creates no runtime edge, so ``app/pii/``
stays importable with no pipeline installed. The runtime guard below is what
actually protects the boundary, and it is unchanged: ``app.pipeline`` still may
not be imported at runtime.
"""


def _is_type_checking_guard(node: ast.If) -> bool:
    test = node.test
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    if isinstance(test, ast.Attribute):
        return test.attr == "TYPE_CHECKING"
    return False


def _nodes_outside_type_checking(tree: ast.Module) -> set[int]:
    """ids of nodes not nested in an ``if TYPE_CHECKING:`` body."""
    guarded: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and _is_type_checking_guard(node):
            for statement in node.body:
                guarded.update(id(child) for child in ast.walk(statement))
    return guarded


def _imported_names(tree: ast.Module, type_only: bool) -> set[tuple[str, str]]:
    """``(module, imported_name)`` pairs; ``module`` is ``""`` for ``import x``.

    Keys on the *imported* symbol, not the local alias, so
    ``import NormalizedDocument as ND`` is recognised as the allowed borrow
    while ``import DocumentType`` is not.
    """
    guarded = _nodes_outside_type_checking(tree)
    found: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        is_import = isinstance(node, ast.Import | ast.ImportFrom)
        if not is_import:
            continue
        in_type_only_block = id(node) in guarded
        if in_type_only_block is not type_only:
            continue
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add((alias.name, ""))
        else:
            module = node.module or ""
            for alias in node.names:
                found.add((module, alias.name))
    return found


def pii_source_files() -> list[Path]:
    """Every ``app/pii/*.py`` file, so the guards cover the whole package."""
    return sorted(PII_PACKAGE_DIR.glob("*.py"))


def runtime_imports(path: Path) -> set[tuple[str, str]]:
    """``(module, name)`` pairs imported when the module is actually imported."""
    return _imported_names(ast.parse(path.read_text(encoding="utf-8")), type_only=False)


def type_only_imports(path: Path) -> set[tuple[str, str]]:
    """``(module, name)`` pairs imported only for type annotations."""
    return _imported_names(ast.parse(path.read_text(encoding="utf-8")), type_only=True)


def module_names(path: Path) -> set[str]:
    """Runtime module paths only — for substring-based infrastructure guards."""
    return {module for module, _ in runtime_imports(path)}


def imports_forbidden_infrastructure(path: Path) -> set[str]:
    """Runtime modules matching the infrastructure substrings."""
    return {
        module
        for module in module_names(path)
        if any(needle in module.lower() for needle in FORBIDDEN_INFRA_SUBSTRINGS)
    }


def imports_forbidden_domains(path: Path) -> set[str]:
    """Runtime modules matching the forbidden domain prefixes."""
    return {module for module in module_names(path) if module.startswith(FORBIDDEN_DOMAIN_PREFIXES)}


def unexpected_type_only_imports(path: Path) -> set[tuple[str, str]]:
    """Type-only borrows outside ``ALLOWED_TYPE_ONLY_IMPORTS``."""
    return type_only_imports(path) - ALLOWED_TYPE_ONLY_IMPORTS
