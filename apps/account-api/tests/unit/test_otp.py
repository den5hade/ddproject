import pytest
from app.services.otp import OtpService


@pytest.fixture
def otp_service(fake_redis) -> OtpService:
    return OtpService(fake_redis)


async def test_issue_then_verify(otp_service):
    code = await otp_service.issue("user@example.com")
    assert len(code) == 6
    assert await otp_service.verify("user@example.com", code) is True


async def test_wrong_code_fails_and_code_is_single_use(otp_service):
    await otp_service.issue("user@example.com")
    assert await otp_service.verify("user@example.com", "000000") is False
    code = await otp_service.issue("user@example.com")
    assert await otp_service.verify("user@example.com", code) is True
    assert await otp_service.verify("user@example.com", code) is False


async def test_attempts_burn_the_code(otp_service):
    await otp_service.issue("user@example.com")
    for _ in range(5):
        assert await otp_service.verify("user@example.com", "000000") is False
    assert await otp_service.verify("user@example.com", "000001") is False


async def test_rate_limit(otp_service):
    assert await otp_service.can_request("user@example.com") is True
    assert await otp_service.can_request("user@example.com") is False