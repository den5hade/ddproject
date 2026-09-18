"""Phase 4i registry-verification extension point tests."""

import asyncio
from datetime import UTC, datetime

import pytest
from app.domain.organization import OrganizationVerificationStatus
from app.domain.registry import (
    OrganizationRegistryProvider,
    OrganizationVerificationError,
    OrganizationVerificationResult,
)


class FakeRegistryProvider:
    """Test-only provider structurally satisfying the outbound port."""

    def __init__(
        self,
        status: OrganizationVerificationStatus = OrganizationVerificationStatus.VERIFIED,
    ):
        self._status = status

    async def verify(self, inn: str, ogrn: str) -> OrganizationVerificationResult:
        return OrganizationVerificationResult(
            status=self._status,
            provider="fake",
            verified_at=datetime.now(UTC),
        )


def test_fake_provider_satisfies_protocol() -> None:
    provider = FakeRegistryProvider()
    assert isinstance(provider, OrganizationRegistryProvider)


def test_provider_verify_returns_result() -> None:
    provider = FakeRegistryProvider()

    async def scenario() -> None:
        result = await provider.verify("7707083893", "1027700132195")
        assert isinstance(result, OrganizationVerificationResult)
        assert result.status is OrganizationVerificationStatus.VERIFIED

    asyncio.run(scenario())


def test_result_roundtrip_with_optionals() -> None:
    moment = datetime(2026, 9, 18, 10, 0, tzinfo=UTC)
    result = OrganizationVerificationResult(
        status=OrganizationVerificationStatus.REJECTED,
        provider="federal_registry",
        verified_at=moment,
        error_code="REGISTRY_MISMATCH",
        error_message="INN does not match registry",
    )
    assert result.status is OrganizationVerificationStatus.REJECTED
    assert result.provider == "federal_registry"
    assert result.verified_at == moment
    assert result.error_code == "REGISTRY_MISMATCH"
    assert result.error_message == "INN does not match registry"


def test_result_is_frozen() -> None:
    result = OrganizationVerificationResult.verified("fake")
    with pytest.raises(AttributeError):
        result.status = OrganizationVerificationStatus.REJECTED  # type: ignore[misc]


def test_verified_helper() -> None:
    result = OrganizationVerificationResult.verified("fake")
    assert result.status is OrganizationVerificationStatus.VERIFIED
    assert result.provider == "fake"
    assert result.verified_at.tzinfo is not None


def test_rejected_helper() -> None:
    result = OrganizationVerificationResult.rejected(
        "fake", error_code="NOT_FOUND", error_message="not in registry"
    )
    assert result.status is OrganizationVerificationStatus.REJECTED
    assert result.error_code == "NOT_FOUND"


@pytest.mark.parametrize(
    "status",
    [
        OrganizationVerificationStatus.UNVERIFIED,
        OrganizationVerificationStatus.PENDING,
    ],
)
def test_result_rejects_internal_states(status: OrganizationVerificationStatus) -> None:
    with pytest.raises(OrganizationVerificationError):
        OrganizationVerificationResult(
            status=status, provider="fake", verified_at=datetime.now(UTC)
        )


def test_result_normalizes_naive_datetime() -> None:
    result = OrganizationVerificationResult(
        status=OrganizationVerificationStatus.VERIFIED,
        provider="fake",
        verified_at=datetime(2026, 9, 18, 10, 0),
    )
    assert result.verified_at.tzinfo is not None
    assert result.verified_at == datetime(2026, 9, 18, 10, 0, tzinfo=UTC)