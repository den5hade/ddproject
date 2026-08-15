from uuid import uuid4

import pytest
from app.core.security import (
    ExpiredTokenError,
    InvalidTokenError,
    constant_time_equals,
    create_access_token,
    decode_access_token,
    generate_otp,
    generate_refresh_token,
    hash_refresh_token,
)
from app.domain.user_type import UserType


def test_jwt_roundtrip():
    user_id, session_id = uuid4(), uuid4()
    token = create_access_token(user_id, UserType.USER, session_id)
    claims = decode_access_token(token)
    assert claims["sub"] == str(user_id)
    assert claims["sid"] == str(session_id)
    assert claims["user_type"] == "user"
    assert claims["type"] == "access"


def test_jwt_expired_token_rejected():
    token = create_access_token(uuid4(), UserType.USER, uuid4(), expires_minutes=-1)
    with pytest.raises(ExpiredTokenError):
        decode_access_token(token)


def test_jwt_tampered_token_rejected():
    token = create_access_token(uuid4(), UserType.USER, uuid4())
    tampered = token[:-2] + ("a" if token[-2] != "a" else "b") + token[-1]
    with pytest.raises(InvalidTokenError):
        decode_access_token(tampered)


def test_refresh_token_hmac_hex_and_not_recoverable():
    refresh = generate_refresh_token()
    digest = hash_refresh_token(refresh)
    assert len(digest) == 64
    assert digest != refresh
    assert hash_refresh_token(refresh) == digest  # deterministic


def test_generate_otp_is_six_digits():
    code = generate_otp()
    assert code.isdigit()
    assert len(code) == 6


def test_constant_time_equals():
    assert constant_time_equals("abc", "abc")
    assert not constant_time_equals("abc", "abd")