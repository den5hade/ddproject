from app.core.security import decode_access_token, hash_refresh_token
from app.models.auth_session import AuthSessionRow
from sqlalchemy import func, select

IDENTITY = "user@example.com"


async def _request_otp(client) -> None:
    response = await client.post("/api/v1/auth/request-otp", json={"identity": IDENTITY})
    assert response.status_code == 202


async def _stored_code(fake_redis) -> str:
    code = await fake_redis.get(f"otp:code:{IDENTITY}")
    assert code is not None
    return code


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