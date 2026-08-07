from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.main import app
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import RegisterRequest, UserResponse
from app.services.users import UserAlreadyExistsError, register_user


# ---------------------------------------------------------------------------
# RegisterRequest validation
# ---------------------------------------------------------------------------

def test_register_request_valid():
    req = RegisterRequest(email="user@example.com", password="Segura01")
    assert req.email == "user@example.com"


def test_register_request_rejects_invalid_email():
    with pytest.raises(ValidationError):
        RegisterRequest(email="no-es-email", password="Segura01")


def test_register_request_rejects_short_password():
    with pytest.raises(ValidationError):
        RegisterRequest(email="user@example.com", password="corta")


def test_register_request_rejects_long_password():
    with pytest.raises(ValidationError):
        RegisterRequest(email="user@example.com", password="x" * 129)


# ---------------------------------------------------------------------------
# UserResponse field exclusion
# ---------------------------------------------------------------------------

def test_user_response_has_no_password_fields():
    fields = UserResponse.model_fields
    assert "password" not in fields
    assert "hashed_password" not in fields


# ---------------------------------------------------------------------------
# register_user service (no DB)
# ---------------------------------------------------------------------------

def _make_db_mock(existing_user=None):
    db = MagicMock(spec=Session)
    db.scalar.return_value = existing_user
    return db


def test_register_user_normalizes_email():
    db = _make_db_mock()
    payload = RegisterRequest(email="USER@Example.COM", password="Segura01")
    db.refresh.side_effect = lambda u: None
    user = register_user(db, payload)
    assert user.email == "user@example.com"


def test_register_user_hashes_password():
    db = _make_db_mock()
    payload = RegisterRequest(email="a@b.com", password="Segura01")
    db.refresh.side_effect = lambda u: None
    user = register_user(db, payload)
    assert user.hashed_password != "Segura01"


def test_register_user_calls_db_add():
    db = _make_db_mock()
    payload = RegisterRequest(email="a@b.com", password="Segura01")
    db.refresh.side_effect = lambda u: None
    register_user(db, payload)
    db.add.assert_called_once()


def test_register_user_calls_db_commit():
    db = _make_db_mock()
    payload = RegisterRequest(email="a@b.com", password="Segura01")
    db.refresh.side_effect = lambda u: None
    register_user(db, payload)
    db.commit.assert_called_once()


def test_register_user_calls_db_refresh():
    db = _make_db_mock()
    payload = RegisterRequest(email="a@b.com", password="Segura01")
    db.refresh.side_effect = lambda u: None
    register_user(db, payload)
    db.refresh.assert_called_once()


def test_register_user_raises_when_email_exists():
    existing = User(email="a@b.com", hashed_password="hash")
    db = _make_db_mock(existing_user=existing)
    payload = RegisterRequest(email="a@b.com", password="Segura01")
    with pytest.raises(UserAlreadyExistsError):
        register_user(db, payload)


# ---------------------------------------------------------------------------
# Endpoint tests
# ---------------------------------------------------------------------------

def _fake_db():
    yield MagicMock(spec=Session)


def _make_fake_user() -> SimpleNamespace:
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=1,
        email="nuevo@example.com",
        is_active=True,
        created_at=now,
        updated_at=now,
        hashed_password="$argon2id$fake",
    )


def test_endpoint_returns_201(monkeypatch):
    fake_user = _make_fake_user()
    monkeypatch.setattr(
        "app.api.routes.auth.register_user",
        lambda db, payload: fake_user,
    )
    app.dependency_overrides[get_db] = _fake_db
    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/auth/register",
            json={"email": "nuevo@example.com", "password": "Segura01"},
        )
        assert response.status_code == 201
    finally:
        app.dependency_overrides.clear()


def test_endpoint_returns_expected_fields(monkeypatch):
    fake_user = _make_fake_user()
    monkeypatch.setattr(
        "app.api.routes.auth.register_user",
        lambda db, payload: fake_user,
    )
    app.dependency_overrides[get_db] = _fake_db
    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/auth/register",
            json={"email": "nuevo@example.com", "password": "Segura01"},
        )
        data = response.json()
        assert "id" in data
        assert "email" in data
        assert "is_active" in data
        assert "created_at" in data
        assert "updated_at" in data
    finally:
        app.dependency_overrides.clear()


def test_endpoint_does_not_return_password_fields(monkeypatch):
    fake_user = _make_fake_user()
    monkeypatch.setattr(
        "app.api.routes.auth.register_user",
        lambda db, payload: fake_user,
    )
    app.dependency_overrides[get_db] = _fake_db
    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/auth/register",
            json={"email": "nuevo@example.com", "password": "Segura01"},
        )
        data = response.json()
        assert "password" not in data
        assert "hashed_password" not in data
    finally:
        app.dependency_overrides.clear()


def test_endpoint_returns_409_on_duplicate(monkeypatch):
    def _raise(*_):
        raise UserAlreadyExistsError

    monkeypatch.setattr("app.api.routes.auth.register_user", _raise)
    app.dependency_overrides[get_db] = _fake_db
    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/auth/register",
            json={"email": "existe@example.com", "password": "Segura01"},
        )
        assert response.status_code == 409
    finally:
        app.dependency_overrides.clear()
