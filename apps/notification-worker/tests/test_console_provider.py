import pytest
from app.providers.console import ConsoleProvider


@pytest.mark.asyncio
async def test_console_provider_sends_without_error():
    provider = ConsoleProvider()
    await provider.send(to="user@example.com", channel="email", code="123456")