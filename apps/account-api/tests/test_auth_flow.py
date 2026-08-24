import pytest
from app.core.security import decode_access_token, hash_refresh_token
from app.domain.account import AccountStatus
from app.models.account import Account
from app.models.auth_session import AuthSessionRow
from app.repositories.account import AccountRepository
from app.repositories.auth_sessions import AuthSessionRepository
from app.services.auth import AuthService, ClientInfo
from app.services.otp import OtpService
from sqlalchemy import func, or_, select

IDENTITY = "user@example.com"
PHONE_IDENTITY = "+15551234567"


async def _request_otp(client) -> None:
    response = await client.post("/api/v1/auth/request-otp", json={"identity": IDENTITY})
    assert response.status_code == 202


async def _stored_code(fake_redis, identity: str = IDENTITY) -> str:
    code = await fake_redis.get(f"otp:code:{identity}")
    assert code is not None
    return code


async def _read_account(db_factory, identity: str) -> Account:
    async with db_factory() as session:
        result = await session.execute(
            select(Account).where(
                or_(
                    Account.email == identity,
                    Account.email_normalized == identity,
                    Account.phone == identity,
                    Account.phone_e164 == identity,
                )
            )
        )
        return result.scalar_one()


async def _set_status(db_factory, identity: str, new_status: AccountStatus) -> None:
    async with db_factory() as session:
        account = await _read_account_in(session, identity)
        account.status = new_status
        await session.commit()


async def _read_account_in(session, identity: str) -> Account:
    result = await session.execute(
        select(Account).where(
            or_(
                Account.email == identity,
                Account.email_normalized == identity,
                Account.phone == identity,
                Account.phone_e164 == identity,
            )
        )
    )
    return result.scalar_one()


async def _count_sessions(db_factory) -> int:
    async with db_factory() as session:
        result = await session.execute(select(func.count()).select_from(AuthSessionRow))
        return result.scalar_one()


async def _session_by_hmac(db_factory, refresh_token: str):
    async with db_factory() as session:
        result = await session.execute(
            select(AuthSessionRow).where(
                AuthSessionRow.refresh_token_hmac == hash_refresh_token(refresh_token)
            )
        )
        row = result.scalar_one()
        return row.id, row.revoked_at


async def test_request_otp_rate_limit(app_client):
    await _request_otp(app_client)
    response = await app_client.post(
        "/api/v1/auth/request-otp", json={"identity": IDENTITY}
    )
    assert response.status_code == 429


async def test_full_auth_flow(app_client, fake_redis, db_factory):
    await _request_otp(app_client)
    code = await _stored_code(fake_redis)

    verify = await app_client.post(
        "/api/v1/auth/verify", json={"identity": IDENTITY, "code": code}
    )
    assert verify.status_code == 200
    tokens = verify.json()
    access_token, refresh_token = tokens["access_token"], tokens["refresh_token"]
    assert tokens["token_type"] == "bearer"

    claims = decode_access_token(access_token)
    assert claims["user_type"] == "user"
    assert await _count_sessions(db_factory) == 1

    old_id, old_revoked = await _session_by_hmac(db_factory, refresh_token)
    assert old_revoked is None

    me = await app_client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert me.status_code == 200
    assert me.json()["email"] == IDENTITY

    refreshed = await app_client.post(
        "/api/v1/auth/refresh", json={"refresh_token": refresh_token}
    )
    assert refreshed.status_code == 200
    new_tokens = refreshed.json()
    assert await _count_sessions(db_factory) == 2

    _old_id, old_revoked = await _session_by_hmac(db_factory, refresh_token)
    assert old_revoked is not None

    logout = await app_client.post(
        "/api/v1/auth/logout", json={"refresh_token": new_tokens["refresh_token"]}
    )
    assert logout.status_code == 204

    reuse = await app_client.post(
        "/api/v1/auth/refresh", json={"refresh_token": new_tokens["refresh_token"]}
    )
    assert reuse.status_code == 401


async def test_wrong_otp_rejected(app_client, fake_redis):
    await _request_otp(app_client)
    response = await app_client.post(
        "/api/v1/auth/verify", json={"identity": IDENTITY, "code": "000000"}
    )
    assert response.status_code == 400


async def test_me_requires_token(app_client):
    response = await app_client.get("/api/v1/auth/me")
    assert response.status_code == 401


async def test_blocked_account_login_forbidden(app_client, fake_redis, db_factory):
    await _request_otp(app_client)
    code = await _stored_code(fake_redis)
    await _set_status(db_factory, IDENTITY, AccountStatus.BLOCKED)
    response = await app_client.post(
        "/api/v1/auth/verify", json={"identity": IDENTITY, "code": code}
    )
    assert response.status_code == 403


async def test_deleted_account_login_forbidden(app_client, fake_redis, db_factory):
    await _request_otp(app_client)
    code = await _stored_code(fake_redis)
    await _set_status(db_factory, IDENTITY, AccountStatus.DELETED)
    response = await app_client.post(
        "/api/v1/auth/verify", json={"identity": IDENTITY, "code": code}
    )
    assert response.status_code == 403


async def test_blocked_account_tokens_and_refresh_rejected(
    app_client, fake_redis, db_factory
):
    await _request_otp(app_client)
    code = await _stored_code(fake_redis)
    verify = await app_client.post(
        "/api/v1/auth/verify", json={"identity": IDENTITY, "code": code}
    )
    assert verify.status_code == 200
    tokens = verify.json()

    await _set_status(db_factory, IDENTITY, AccountStatus.BLOCKED)

    me = await app_client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert me.status_code == 401

    refreshed = await app_client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert refreshed.status_code == 401


async def test_pending_account_promoted_on_first_login(app_client, fake_redis, db_factory):
    await _request_otp(app_client)
    account = await _read_account(db_factory, IDENTITY)
    assert account.status == AccountStatus.PENDING

    code = await _stored_code(fake_redis)
    verify = await app_client.post(
        "/api/v1/auth/verify", json={"identity": IDENTITY, "code": code}
    )
    assert verify.status_code == 200

    account = await _read_account(db_factory, IDENTITY)
    assert account.status == AccountStatus.ACTIVE


async def test_email_login_sets_email_verified_at_and_last_login(
    app_client, fake_redis, db_factory
):
    await _request_otp(app_client)
    code = await _stored_code(fake_redis)
    verify = await app_client.post(
        "/api/v1/auth/verify", json={"identity": IDENTITY, "code": code}
    )
    assert verify.status_code == 200

    account = await _read_account(db_factory, IDENTITY)
    assert account.email_verified_at is not None
    assert account.phone_verified_at is None
    assert account.last_login_at is not None


async def test_phone_login_sets_phone_verified_at(app_client, fake_redis, db_factory):
    response = await app_client.post(
        "/api/v1/auth/request-otp", json={"identity": PHONE_IDENTITY}
    )
    assert response.status_code == 202
    code = await _stored_code(fake_redis, PHONE_IDENTITY)
    verify = await app_client.post(
        "/api/v1/auth/verify", json={"identity": PHONE_IDENTITY, "code": code}
    )
    assert verify.status_code == 200

    account = await _read_account(db_factory, PHONE_IDENTITY)
    assert account.phone_verified_at is not None
    assert account.email_verified_at is None
    assert account.last_login_at is not None


@pytest.mark.parametrize("identity", ["not-an-email", "12345", "a@b"])
async def test_invalid_identity_rejected_without_side_effects(
    app_client, fake_redis, db_factory, identity
):
    response = await app_client.post("/api/v1/auth/request-otp", json={"identity": identity})
    assert response.status_code == 422
    assert await fake_redis.keys("otp:*") == []

    async with db_factory() as session:
        count = (
            await session.execute(select(func.count()).select_from(Account))
        ).scalar_one()
    assert count == 0


async def test_identity_canonicalized_across_requests(app_client, fake_redis):
    first = await app_client.post(
        "/api/v1/auth/request-otp", json={"identity": "User@Example.com"}
    )
    assert first.status_code == 202
    assert await fake_redis.get("otp:code:user@example.com") is not None
    assert await fake_redis.get("otp:code:User@Example.com") is None

    second = await app_client.post(
        "/api/v1/auth/request-otp", json={"identity": "user@example.com"}
    )
    assert second.status_code == 429


class _ExplodingSessionRepo:
    async def save(self, auth_session):
        raise RuntimeError("db down")


class _StubNotifier:
    async def send_otp(self, identity, channel, code, expires_at) -> None:
        return None


async def test_verify_failure_rolls_back_verification(
    db_session, fake_redis, monkeypatch
):
    identity = "rollback@example.com"
    otp_service = OtpService(fake_redis)
    accounts = AccountRepository(db_session)
    await accounts.get_or_create_by_identity(identity)
    await db_session.commit()
    code = await otp_service.issue(identity)

    monkeypatch.setattr(AuthSessionRepository, "save", _ExplodingSessionRepo.save)
    service = AuthService(
        db_session,
        otp_service=otp_service,
        notifier=_StubNotifier(),
    )
    client_info = ClientInfo(user_agent="test", ip_address="127.0.0.1")
    with pytest.raises(RuntimeError):
        await service.verify_otp(identity, code, client_info)

    await db_session.rollback()
    account = await accounts.get_by_identity(identity)
    assert account.email_verified_at is None
    assert account.phone_verified_at is None
    assert account.last_login_at is None