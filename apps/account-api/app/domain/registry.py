"""Registry verification extension point (Phase 4i).

Defines the outbound port (``OrganizationRegistryProvider`` Protocol) and the
value object (``OrganizationVerificationResult``) that a future concrete
provider — e.g. a Federal Registry integration — must implement.  The
Organization domain never couples directly to a specific government API
(spec §29).

No provider is shipped in 4i; ``organization_verifications`` persistence
(arch §76) is a future entity; audit actions ``ORGANIZATION_VERIFIED`` /
``ORGANIZATION_REJECTED`` arrive with the phase that fires them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from app.domain.organization import OrganizationVerificationStatus


class OrganizationVerificationError(Exception):
    """The result's status is not VERIFIED or REJECTED (guard violation)."""


class OrganizationVerificationProviderError(Exception):
    """The registry provider failed to produce a result."""


class OrganizationVerificationUnavailableError(Exception):
    """No registry provider is configured or reachable."""


@runtime_checkable
class OrganizationRegistryProvider(Protocol):
    """Outbound port consumed by a future ``OrganizationVerificationService``.

    A concrete implementation (``FederalRegistryProvider``) will be wired via
    dependency injection without touching ``OrganizationService`` — the
    accept criterion of Phase 4i.
    """

    async def verify(self, inn: str, ogrn: str) -> OrganizationVerificationResult: ...


@dataclass(frozen=True, slots=True)
class OrganizationVerificationResult:
    """Domain value object returned by a registry provider.

    ``status`` is constrained to ``VERIFIED | REJECTED`` — ``UNVERIFIED`` /
    ``PENDING`` are internal-only states that must never be emitted by a
    provider (Phase-1 / §7 locked invariant: the human API can only set
    ``PENDING``; ``VERIFIED`` / ``REJECTED`` are set exclusively by the
    registry provider).  Construction-time validation enforces this.
    """

    status: OrganizationVerificationStatus
    provider: str
    verified_at: datetime
    error_code: str | None = field(default=None, compare=False)
    error_message: str | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        if self.status not in (
            OrganizationVerificationStatus.VERIFIED,
            OrganizationVerificationStatus.REJECTED,
        ):
            raise OrganizationVerificationError(
                f"provider result status must be VERIFIED or REJECTED, got {self.status.value!r}"
            )
        if self.verified_at.tzinfo is None:
            object.__setattr__(
                self, "verified_at", self.verified_at.replace(tzinfo=UTC)
            )

    @classmethod
    def verified(
        cls,
        provider: str,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> OrganizationVerificationResult:
        return cls(
            status=OrganizationVerificationStatus.VERIFIED,
            provider=provider,
            verified_at=datetime.now(UTC),
            error_code=error_code,
            error_message=error_message,
        )

    @classmethod
    def rejected(
        cls,
        provider: str,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> OrganizationVerificationResult:
        return cls(
            status=OrganizationVerificationStatus.REJECTED,
            provider=provider,
            verified_at=datetime.now(UTC),
            error_code=error_code,
            error_message=error_message,
        )
