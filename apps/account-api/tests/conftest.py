import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")
os.environ.setdefault("AUTH_HMAC_KEY", "test-hmac-key")
os.environ.setdefault("AUTH_OTP_PEPPER", "test-otp-pepper")
os.environ.setdefault("AUTH_PIN_PEPPER", "test-pin-pepper")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-0123456789abcdef")
os.environ.setdefault("JWT_ACCESS_EXPIRE_MINUTES", "15")
os.environ.setdefault("JWT_REFRESH_EXPIRE_DAYS", "30")

import fakeredis.aioredis
import pytest
from fastapi import Depends
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


@pytest.fixture
async def db_factory():
    from app.core.database import Base

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture
async def db_session(db_factory):
    async with db_factory() as session:
        yield session


@pytest.fixture
def fake_redis():
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture
async def app_client(db_factory, fake_redis):
    from app.core.database import get_db
    from app.dependencies.auth import get_auth_service, get_otp_service
    from app.main import app
    from app.services.auth import AuthService
    from app.services.notifications import RabbitNotificationGateway
    from app.services.otp import OtpService

    async def _override_get_db():
        async with db_factory() as session:
            yield session

    async def _override_get_otp_service() -> OtpService:
        return OtpService(fake_redis)

    async def _override_get_auth_service(session=Depends(get_db)) -> AuthService:
        return AuthService(
            session=session,
            otp_service=OtpService(fake_redis),
            notifier=RabbitNotificationGateway(None),
        )

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_otp_service] = _override_get_otp_service
    app.dependency_overrides[get_auth_service] = _override_get_auth_service

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()