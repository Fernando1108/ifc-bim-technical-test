from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.core.security import (
    JWT_ALGORITHM,
    InvalidAccessTokenError,
    create_access_token,
    decode_access_token,
)

_TEST_SECRET = "test_jwt_secret_key_only_for_automated_tests_123456"


def _decode_raw(token: str) -> dict:
    """Decode a test token with the known test secret for payload inspection."""
    return jwt.decode(token, _TEST_SECRET, algorithms=[JWT_ALGORITHM])


# ---------------------------------------------------------------------------
# create_access_token
# ---------------------------------------------------------------------------

def test_create_returns_string():
    assert isinstance(create_access_token("42"), str)


def test_token_has_three_segments():
    token = create_access_token("42")
    assert len(token.split(".")) == 3


def test_decode_returns_original_subject():
    assert decode_access_token(create_access_token("42")) == "42"


def test_different_subjects_produce_different_subjects():
    t1 = create_access_token("1")
    t2 = create_access_token("2")
    assert decode_access_token(t1) != decode_access_token(t2)


def test_payload_contains_sub_iat_exp():
    token = create_access_token("99")
    payload = _decode_raw(token)
    assert "sub" in payload
    assert "iat" in payload
    assert "exp" in payload


def test_exp_is_after_iat():
    token = create_access_token("99")
    payload = _decode_raw(token)
    assert payload["exp"] > payload["iat"]


def test_token_does_not_contain_sensitive_fields():
    token = create_access_token("7")
    payload = _decode_raw(token)
    assert "password" not in payload
    assert "hashed_password" not in payload
    assert "email" not in payload


def test_create_rejects_empty_subject():
    with pytest.raises(ValueError):
        create_access_token("")


def test_create_rejects_whitespace_only_subject():
    with pytest.raises(ValueError):
        create_access_token("   ")


# ---------------------------------------------------------------------------
# decode_access_token
# ---------------------------------------------------------------------------

def test_decode_rejects_wrong_secret():
    token = jwt.encode({"sub": "1"}, "wrong_secret_long_enough_for_hs256_xxxxxxxxxx", algorithm=JWT_ALGORITHM)
    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(token)


def test_decode_rejects_expired_token():
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    payload = {
        "sub": "1",
        "iat": past - timedelta(minutes=30),
        "exp": past,
    }
    expired_token = jwt.encode(payload, _TEST_SECRET, algorithm=JWT_ALGORITHM)
    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(expired_token)


def test_decode_rejects_token_without_sub():
    payload = {
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=30),
    }
    token = jwt.encode(payload, _TEST_SECRET, algorithm=JWT_ALGORITHM)
    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(token)


def test_decode_rejects_token_with_empty_sub():
    payload = {
        "sub": "",
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=30),
    }
    token = jwt.encode(payload, _TEST_SECRET, algorithm=JWT_ALGORITHM)
    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(token)


def test_decode_rejects_invalid_string():
    with pytest.raises(InvalidAccessTokenError):
        decode_access_token("token-invalido")


def test_decode_expired_raises_invalid_access_token_error():
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    payload = {"sub": "1", "iat": past - timedelta(minutes=30), "exp": past}
    expired = jwt.encode(payload, _TEST_SECRET, algorithm=JWT_ALGORITHM)
    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(expired)


def test_decode_wrong_secret_raises_invalid_access_token_error():
    token = jwt.encode({"sub": "1"}, "otro_secreto_largo_suficiente_para_hs256_xxxxx", algorithm=JWT_ALGORITHM)
    with pytest.raises(InvalidAccessTokenError):
        decode_access_token(token)
