from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.api.dependencies.auth import get_current_user, oauth2_scheme
from app.core.security import InvalidAccessTokenError
from app.db.session import get_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_db():
    yield MagicMock(spec=Session)


def _make_db_mock(user=None) -> MagicMock:
    db = MagicMock(spec=Session)
    db.scalar.return_value = user
    return db


def _make_active_user(user_id: int = 42) -> SimpleNamespace:
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=user_id,
        email="user@example.com",
        is_active=True,
        created_at=now,
        updated_at=now,
        hashed_password="$argon2id$fake",
    )


# ---------------------------------------------------------------------------
# oauth2_scheme configuration
# ---------------------------------------------------------------------------

def test_oauth2_scheme_token_url():
    url = oauth2_scheme.model.flows.password.tokenUrl
    assert url == "/api/v1/auth/login"


# ---------------------------------------------------------------------------
# get_current_user — dependency (no DB, no HTTP)
# ---------------------------------------------------------------------------

def test_valid_token_queries_user_by_id(monkeypatch):
    fake_user = _make_active_user(user_id=42)
    db = _make_db_mock(user=fake_user)
    monkeypatch.setattr(
        "app.api.dependencies.auth.decode_access_token",
        lambda t: "42",
    )
    result = get_current_user(token="any", db=db)
    assert result is fake_user
    db.scalar.assert_called_once()
    statement = db.scalar.call_args.args[0]
    params = statement.compile().params
    assert 42 in params.values()


def test_valid_token_returns_active_user(monkeypatch):
    fake_user = _make_active_user(user_id=7)
    db = _make_db_mock(user=fake_user)
    monkeypatch.setattr("app.api.dependencies.auth.decode_access_token", lambda t: "7")
    result = get_current_user(token="tok", db=db)
    assert result is fake_user


def test_does_not_call_add_commit_refresh(monkeypatch):
    fake_user = _make_active_user()
    db = _make_db_mock(user=fake_user)
    monkeypatch.setattr("app.api.dependencies.auth.decode_access_token", lambda t: "42")
    get_current_user(token="tok", db=db)
    db.add.assert_not_called()
    db.commit.assert_not_called()
    db.refresh.assert_not_called()


def test_invalid_token_raises_401(monkeypatch):
    db = _make_db_mock()
    monkeypatch.setattr(
        "app.api.dependencies.auth.decode_access_token",
        lambda t: (_ for _ in ()).throw(InvalidAccessTokenError()),
    )
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(token="bad", db=db)
    assert exc_info.value.status_code == 401


def test_non_numeric_subject_raises_401(monkeypatch):
    db = _make_db_mock()
    monkeypatch.setattr("app.api.dependencies.auth.decode_access_token", lambda t: "not-a-number")
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(token="tok", db=db)
    assert exc_info.value.status_code == 401


def test_subject_zero_raises_401(monkeypatch):
    db = _make_db_mock()
    monkeypatch.setattr("app.api.dependencies.auth.decode_access_token", lambda t: "0")
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(token="tok", db=db)
    assert exc_info.value.status_code == 401


def test_negative_subject_raises_401(monkeypatch):
    db = _make_db_mock()
    monkeypatch.setattr("app.api.dependencies.auth.decode_access_token", lambda t: "-5")
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(token="tok", db=db)
    assert exc_info.value.status_code == 401


def test_user_not_found_raises_401(monkeypatch):
    db = _make_db_mock(user=None)
    monkeypatch.setattr("app.api.dependencies.auth.decode_access_token", lambda t: "42")
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(token="tok", db=db)
    assert exc_info.value.status_code == 401


def test_inactive_user_raises_401(monkeypatch):
    fake_user = _make_active_user()
    fake_user.is_active = False
    db = _make_db_mock(user=fake_user)
    monkeypatch.setattr("app.api.dependencies.auth.decode_access_token", lambda t: "42")
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(token="tok", db=db)
    assert exc_info.value.status_code == 401


def _assert_401_detail(monkeypatch, decode_side_effect, db):
    monkeypatch.setattr("app.api.dependencies.auth.decode_access_token", decode_side_effect)
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(token="tok", db=db)
    exc = exc_info.value
    assert exc.status_code == 401
    assert exc.detail == "No se pudieron validar las credenciales."
    assert exc.headers.get("WWW-Authenticate") == "Bearer"


def test_invalid_token_detail_and_header(monkeypatch):
    db = _make_db_mock()
    _assert_401_detail(
        monkeypatch,
        lambda t: (_ for _ in ()).throw(InvalidAccessTokenError()),
        db,
    )


def test_non_numeric_subject_detail_and_header(monkeypatch):
    db = _make_db_mock()
    _assert_401_detail(monkeypatch, lambda t: "nope", db)


def test_user_not_found_detail_and_header(monkeypatch):
    db = _make_db_mock(user=None)
    monkeypatch.setattr("app.api.dependencies.auth.decode_access_token", lambda t: "42")
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(token="tok", db=db)
    exc = exc_info.value
    assert exc.status_code == 401
    assert exc.detail == "No se pudieron validar las credenciales."
    assert exc.headers.get("WWW-Authenticate") == "Bearer"


def test_subject_zero_detail_and_header(monkeypatch):
    db = _make_db_mock()
    _assert_401_detail(monkeypatch, lambda token: "0", db)


def test_negative_subject_detail_and_header(monkeypatch):
    db = _make_db_mock()
    _assert_401_detail(monkeypatch, lambda token: "-5", db)


def test_inactive_user_detail_and_header(monkeypatch):
    fake_user = _make_active_user()
    fake_user.is_active = False
    db = _make_db_mock(user=fake_user)
    _assert_401_detail(monkeypatch, lambda token: "42", db)


# ---------------------------------------------------------------------------
# Endpoint /auth/me
# ---------------------------------------------------------------------------

def test_me_without_token_returns_401():
    client = TestClient(app)
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401


def test_me_without_token_has_www_authenticate():
    client = TestClient(app)
    response = client.get("/api/v1/auth/me")
    assert response.headers.get("www-authenticate") == "Bearer"


def test_me_with_valid_user_returns_200():
    fake_user = _make_active_user()
    app.dependency_overrides[get_current_user] = lambda: fake_user
    try:
        client = TestClient(app)
        response = client.get("/api/v1/auth/me")
        assert response.status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_me_response_contains_expected_fields():
    fake_user = _make_active_user()
    app.dependency_overrides[get_current_user] = lambda: fake_user
    try:
        client = TestClient(app)
        data = client.get("/api/v1/auth/me").json()
        assert "id" in data
        assert "email" in data
        assert "is_active" in data
        assert "created_at" in data
        assert "updated_at" in data
    finally:
        app.dependency_overrides.clear()


def test_me_response_does_not_contain_sensitive_fields():
    fake_user = _make_active_user()
    app.dependency_overrides[get_current_user] = lambda: fake_user
    try:
        client = TestClient(app)
        data = client.get("/api/v1/auth/me").json()
        assert "password" not in data
        assert "hashed_password" not in data
        assert "access_token" not in data
    finally:
        app.dependency_overrides.clear()


def test_me_with_invalid_token_returns_401(monkeypatch):
    monkeypatch.setattr(
        "app.api.dependencies.auth.decode_access_token",
        lambda t: (_ for _ in ()).throw(InvalidAccessTokenError()),
    )
    app.dependency_overrides[get_db] = _fake_db
    try:
        client = TestClient(app)
        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer token-invalido"},
        )
        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()
