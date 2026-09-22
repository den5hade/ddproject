"""Canonical schema registry (planned milestone).

During M0 registered schemas come from ``packages/canonical``'s
``CANONICAL_MODELS``; the web registry is a later milestone.
"""

from app.canonical.registry.registry import SchemaRegistry

__all__ = ["SchemaRegistry"]