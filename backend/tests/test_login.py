from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.db.session import get_db
from app.schemas.auth import TokenResponse
from app.services.users import InvalidCredentialsError, authenticate_user


# ---------------------------------------------------------------------------
# TokenResponse schema
# ---------------------------------------------------------------------------

def test_token_response_has_access_token_and_token_type():
    tr = TokenResponse(access_token="tok")
    assert hasattr(tr, "access_token")
    assert hasattr(tr, "token_type")


def test_token_type_default_is_bearer():
    tr = TokenResponse(access_token="tok")
    assert tr.token_type == "bearer"


def test_token_response_has_no_sensitive_fields():
    fields = TokenResponse.model_fields
    assert "password" not in fields
    assert "hashed_password" not in fields
    assert "email" not in fields


# ---------------------------------------------------------------------------
# authenticate_user service (no DB)
# ---------------------------------------------------------------------------

def _make_active_user(email: str = "user@example.com") -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        email=email,
        hashed_password="hashed",
        is_active=True,
    )


def _db_with_user(user=None) -> MagicMock:
    db = MagicMock(spec=Session)
    db.scalar.return_value = user
    return db


def test_authenticate_normalizes_email(monkeypatch):
    user = _make_active_user("user@example.com")
    db = _db_with_user(user)
    monkeypatch.setattr(
        "app.services.users.verify_password",
        lambda password, hashed_password: True,
    )

    result = authenticate_user(
        db,
        " USER@Example.COM ",
        "pass",
    )

    statement = db.scalar.call_args.args[0]
    statement_params = statement.compile().params

    assert result is user
    assert "user@example.com" in statement_params.values()
    assert " USER@Example.COM " not in statement_params.values()


def test_authenticate_calls_db_scalar(monkeypatch):
    user = _make_active_user()
    db = _db_with_user(user)
    monkeypatch.setattr("app.services.users.verify_password", lambda p, h: True)
    authenticate_user(db, "user@example.com", "pass")
    db.scalar.assert_called_once()


def test_authenticate_does_not_call_add_commit_refresh(monkeypatch):
    user = _make_active_user()
    db = _db_with_user(user)
    monkeypatch.setattr("app.services.users.verify_password", lambda p, h: True)
    authenticate_user(db, "user@example.com", "pass")
    db.add.assert_not_called()
    db.commit.assert_not_called()
    db.refresh.assert_not_called()


def test_authenticate_returns_user_on_valid_credentials(monkeypatch):
    user = _make_active_user()
    db = _db_with_user(user)
    monkeypatch.setattr("app.services.users.verify_password", lambda p, h: True)
    result = authenticate_user(db, "user@example.com", "correct")
    assert result is user


def test_authenticate_raises_when_user_not_found(monkeypatch):
    db = _db_with_user(None)
    monkeypatch.setattr("app.services.users.verify_password", lambda p, h: True)
    with pytest.raises(InvalidCredentialsError):
        authenticate_user(db, "noexiste@example.com", "pass")


def test_authenticate_raises_when_password_wrong(monkeypatch):
    user = _make_active_user()
    db = _db_with_user(user)
    monkeypatch.setattr("app.services.users.verify_password", lambda p, h: False)
    with pytest.raises(InvalidCredentialsError):
        authenticate_user(db, "user@example.com", "wrong")


def test_authenticate_raises_when_user_inactive(monkeypatch):
    user = _make_active_user()
    user.is_active = False
    db = _db_with_user(user)
    monkeypatch.setattr("app.services.users.verify_password", lambda p, h: True)
    with pytest.raises(InvalidCredentialsError):
        authenticate_user(db, "user@example.com", "pass")


# ---------------------------------------------------------------------------
# Endpoint tests
# ---------------------------------------------------------------------------

def _fake_db():
    yield MagicMock(spec=Session)


def _make_fake_user(user_id: int = 1) -> SimpleNamespace:
    return SimpleNamespace(id=user_id, email="usuario@example.com", is_active=True)


def test_login_endpoint_returns_200(monkeypatch):
    fake_user = _make_fake_user()
    monkeypatch.setattr("app.api.routes.auth.authenticate_user", lambda db, u, p: fake_user)
    monkeypatch.setattr("app.api.routes.auth.create_access_token", lambda sub: "fake.jwt.token")
    app.dependency_overrides[get_db] = _fake_db
    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/auth/login",
            data={"username": "usuario@example.com", "password": "Segura01"},
        )
        assert response.status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_login_response_contains_access_token_and_token_type(monkeypatch):
    fake_user = _make_fake_user()
    monkeypatch.setattr("app.api.routes.auth.authenticate_user", lambda db, u, p: fake_user)
    monkeypatch.setattr("app.api.routes.auth.create_access_token", lambda sub: "fake.jwt.token")
    app.dependency_overrides[get_db] = _fake_db
    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/auth/login",
            data={"username": "usuario@example.com", "password": "Segura01"},
        )
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
    finally:
        app.dependency_overrides.clear()


def test_login_calls_create_access_token_with_user_id(monkeypatch):
    fake_user = _make_fake_user(user_id=42)
    captured = []
    monkeypatch.setattr("app.api.routes.auth.authenticate_user", lambda db, u, p: fake_user)
    monkeypatch.setattr(
        "app.api.routes.auth.create_access_token",
        lambda sub: captured.append(sub) or "tok",
    )
    app.dependency_overrides[get_db] = _fake_db
    try:
        client = TestClient(app)
        client.post(
            "/api/v1/auth/login",
            data={"username": "usuario@example.com", "password": "Segura01"},
        )
        assert captured == ["42"]
    finally:
        app.dependency_overrides.clear()


def test_login_returns_401_on_invalid_credentials(monkeypatch):
    def _raise(*_):
        raise InvalidCredentialsError

    monkeypatch.setattr("app.api.routes.auth.authenticate_user", _raise)
    app.dependency_overrides[get_db] = _fake_db
    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/auth/login",
            data={"username": "x@x.com", "password": "Segura01"},
        )
        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_login_401_has_www_authenticate_header(monkeypatch):
    def _raise(*_):
        raise InvalidCredentialsError

    monkeypatch.setattr("app.api.routes.auth.authenticate_user", _raise)
    app.dependency_overrides[get_db] = _fake_db
    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/auth/login",
            data={"username": "x@x.com", "password": "Segura01"},
        )
        assert response.headers.get("www-authenticate") == "Bearer"
    finally:
        app.dependency_overrides.clear()


def test_login_401_detail_message(monkeypatch):
    def _raise(*_):
        raise InvalidCredentialsError

    monkeypatch.setattr("app.api.routes.auth.authenticate_user", _raise)
    app.dependency_overrides[get_db] = _fake_db
    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/auth/login",
            data={"username": "x@x.com", "password": "Segura01"},
        )
        assert response.json()["detail"] == "Correo electrónico o contraseña incorrectos."
    finally:
        app.dependency_overrides.clear()


def test_login_does_not_call_create_token_on_invalid_credentials(monkeypatch):
    token_calls = []

    def _raise(*_):
        raise InvalidCredentialsError

    monkeypatch.setattr("app.api.routes.auth.authenticate_user", _raise)
    monkeypatch.setattr(
        "app.api.routes.auth.create_access_token",
        lambda sub: token_calls.append(sub) or "tok",
    )
    app.dependency_overrides[get_db] = _fake_db
    try:
        client = TestClient(app)
        client.post(
            "/api/v1/auth/login",
            data={"username": "x@x.com", "password": "Segura01"},
        )
        assert token_calls == []
    finally:
        app.dependency_overrides.clear()


def test_login_returns_422_when_credentials_missing():
    app.dependency_overrides[get_db] = _fake_db
    try:
        client = TestClient(app)
        response = client.post("/api/v1/auth/login", data={})
        assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()
