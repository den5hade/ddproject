from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.domain.auth_session import AuthSession
from app.domain.user_type import UserType
from app.repositories.auth_sessions import AuthSessionRepository


async def _seed(db_session, hmac_value: str, *, expired: bool = False) -> AuthSession:
    ttl = (
        datetime.now(UTC) - timedelta(seconds=5)
        if expired
        else datetime.now(UTC) + timedelta(days=1)
    )
    auth_session = AuthSession.create(
        account_id=uuid4(),
        user_type=UserType.USER,
        refresh_token_hmac=hmac_value,
        user_agent="pytest",
        ip_address="127.0.0.1",
        expires_at=ttl,
    )
    await AuthSessionRepository(db_session).save(auth_session)
    await db_session.commit()
    return auth_session


async def test_revoke_if_valid_wins_exactly_once(db_session):
    repo = AuthSessionRepository(db_session)
    await _seed(db_session, "a" * 64)

    winner = await repo.revoke_if_valid("a" * 64)
    assert winner is not None
    assert winner.revoked_at is not None

    loser = await repo.revoke_if_valid("a" * 64)
    assert loser is None


async def test_revoke_if_valid_sets_last_used_at(db_session):
    repo = AuthSessionRepository(db_session)
    seeded = await _seed(db_session, "b" * 64)

    winner = await repo.revoke_if_valid("b" * 64)
    assert winner is not None
    assert winner.last_used_at >= seeded.created_at
    assert winner.last_used_at == winner.revoked_at


async def test_revoke_if_valid_ignores_expired_session(db_session):
    repo = AuthSessionRepository(db_session)
    await _seed(db_session, "c" * 64, expired=True)
    assert await repo.revoke_if_valid("c" * 64) is None


async def test_revoke_if_valid_unknown_hmac_is_none(db_session):
    repo = AuthSessionRepository(db_session)
    assert await repo.revoke_if_valid("d" * 64) is None
