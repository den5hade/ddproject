"""PII gate: the boundary where sensitive data can escape.

Public API surface for the PII gate contract (M4 Phases 1–7: domain types, wire
schemas, detector contract, masking, redaction, policy, gate, canonical-output
guard, and the persistence/provenance surface). M4 defines the contract only —
detection, policy evaluation, gate wiring and the detectors themselves land in
M5, along with every cross-package edit §4.9 records as
documented-not-made. PII presence alone never blocks: ``BLOCK`` is reserved for
``PIICategory.SECRET`` and fail-closed conditions.

The gate is a document-level capability and stays free of any runtime
``app.classification`` or ``packages.canonical`` import (ORDER §8): the shared
``NormalizedDocument`` is borrowed type-only.
"""

from app.pii.aggregation import PIIAggregator, PIIAggregatorBase
from app.pii.canonical_guard import (
    CANONICAL_POLICY_DESTINATION,
    CANONICAL_POLICY_STAGE,
    DECISION_REMEDIATION,
    CanonicalPIIInspector,
    CanonicalPIIInspectorBase,
    CanonicalPIIViolation,
    PIIRemediation,
    walk_string_leaves,
)
from app.pii.detectors import (
    DETECTOR_VERSION,
    CompositePIIDetector,
    PatternPIIDetector,
    PIIDetector,
    PIIDetectorBase,
    SecretPIIDetector,
    StructuredFieldPIIDetector,
)
from app.pii.exceptions import (
    InvalidPIIInputError,
    PIIDecisionError,
    PIIDetectorError,
    PIIError,
    PIIPolicyError,
    PIIRedactionError,
)
from app.pii.gate import DECISION_OUTCOMES, PIIGate, PIIGateBase
from app.pii.masking import (
    FINGERPRINT_PREFIX,
    FIXED_MASKS,
    MASK_RULES,
    hash_pii_value,
    mask_pii_value,
)
from app.pii.models import (
    PIIAction,
    PIIAuditRecord,
    PIICategory,
    PIIDecision,
    PIIDecisionResult,
    PIIDestination,
    PIIFinding,
    PIIFindingSummary,
    PIIRiskLevel,
    PIIScanResult,
    PIIScanStage,
    PIISource,
)
from app.pii.persistence import (
    DECISION_AUDIT_EVENTS,
    PII_ARTIFACT_FILENAME,
    PII_AUDIT_EVENTS,
    PII_META_BLOCK_KEY,
    PII_META_OPTIONAL_KEYS,
    PII_META_REQUIRED_KEYS,
    PII_REDACTED_EVENT,
)
from app.pii.policy import (
    CATEGORY_RISK,
    DEFAULT_POLICY,
    PII_CATEGORY_GROUPS,
    PII_POLICY_VERSION,
    REDACT_ON_EXTERNAL,
    PIIPolicy,
    PIIPolicyContext,
    PIIRule,
    PolicyEngine,
    PolicyEngineBase,
)
from app.pii.redaction import (
    PIIRedactor,
    PlaceholderRedactor,
    RedactorBase,
    placeholder_for,
)

__all__ = [
    "CANONICAL_POLICY_DESTINATION",
    "CANONICAL_POLICY_STAGE",
    "CATEGORY_RISK",
    "CanonicalPIIInspector",
    "CanonicalPIIInspectorBase",
    "CanonicalPIIViolation",
    "CompositePIIDetector",
    "DECISION_AUDIT_EVENTS",
    "DECISION_OUTCOMES",
    "DECISION_REMEDIATION",
    "DEFAULT_POLICY",
    "DETECTOR_VERSION",
    "FINGERPRINT_PREFIX",
    "FIXED_MASKS",
    "InvalidPIIInputError",
    "MASK_RULES",
    "PIIAction",
    "PIIAggregator",
    "PIIAggregatorBase",
    "PIIAuditRecord",
    "PIICategory",
    "PIIDecision",
    "PIIDecisionError",
    "PIIDecisionResult",
    "PIIDestination",
    "PIIDetector",
    "PIIDetectorBase",
    "PIIDetectorError",
    "PIIError",
    "PIIFinding",
    "PIIFindingSummary",
    "PIIGate",
    "PIIGateBase",
    "PIIPolicy",
    "PIIPolicyContext",
    "PIIPolicyError",
    "PIIRedactionError",
    "PIIRedactor",
    "PIIRemediation",
    "PIIRiskLevel",
    "PIIRule",
    "PIIScanResult",
    "PIIScanStage",
    "PIISource",
    "PII_ARTIFACT_FILENAME",
    "PII_AUDIT_EVENTS",
    "PII_CATEGORY_GROUPS",
    "PII_META_BLOCK_KEY",
    "PII_META_OPTIONAL_KEYS",
    "PII_META_REQUIRED_KEYS",
    "PII_POLICY_VERSION",
    "PII_REDACTED_EVENT",
    "PatternPIIDetector",
    "PlaceholderRedactor",
    "PolicyEngine",
    "PolicyEngineBase",
    "REDACT_ON_EXTERNAL",
    "RedactorBase",
    "SecretPIIDetector",
    "StructuredFieldPIIDetector",
    "hash_pii_value",
    "mask_pii_value",
    "placeholder_for",
    "walk_string_leaves",
]
