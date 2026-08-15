from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.domain.auth_session import AuthSession
from app.domain.events import SessionRevokedEvent
from app.domain.user_type import UserType


def _session(**kwargs) -> AuthSession:
    defaults = dict(
        account_id=uuid4(),
        user_type=UserType.USER,
        refresh_token_hmac="0" * 64,
        user_agent="pytest",
        ip_address="127.0.0.1",
    )
    defaults.update(kwargs)
    return AuthSession.create(**defaults)


def test_create_sets_id_and_is_valid():
    session = _session()
    assert session.id is not None
    assert session.is_valid()
    assert session.revoked_at is None
    assert session.pop_events() == []


def test_revoke_adds_event_and_invalidates():
    session = _session()
    session.revoke()
    assert not session.is_valid()
    assert session.revoked_at is not None
    events = session.pop_events()
    assert len(events) == 1
    assert isinstance(events[0], SessionRevokedEvent)
    assert events[0].session_id == session.id


def test_expired_session_is_invalid():
    past = datetime.now(UTC) - timedelta(seconds=1)
    session = _session(expires_at=past)
    assert not session.is_valid()


def test_touch_updates_last_used_at():
    session = _session()
    original = session.last_used_at
    session.touch()
    assert session.last_used_at >= original