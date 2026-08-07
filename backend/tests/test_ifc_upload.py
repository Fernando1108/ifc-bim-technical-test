"""
Tests for POST /api/v1/models (IFC upload endpoint) and persist_ifc_model service.

Uses FastAPI TestClient with dependency overrides.
No real PostgreSQL connection is made.
"""
import io
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_user
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.main import app
from app.services.ifc_models import IfcModelPersistenceError, persist_ifc_model
from app.services.ifc_storage import StoredIfcFile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_JWT_SECRET = "test_jwt_secret_key_for_upload_tests_abcdef"


def _make_settings(tmp_path) -> Settings:
    return Settings(
        postgres_db="test_db",
        postgres_user="test_user",
        postgres_password="test_password_local",
        jwt_secret_key=_JWT_SECRET,
        ifc_storage_dir=tmp_path,
        ifc_max_file_size_mb=50,
    )


def _make_settings_small_limit(tmp_path) -> Settings:
    return Settings(
        postgres_db="test_db",
        postgres_user="test_user",
        postgres_password="test_password_local",
        jwt_secret_key=_JWT_SECRET,
        ifc_storage_dir=tmp_path,
        ifc_max_file_size_mb=1,
    )


def _make_fake_user(user_id: int = 42) -> SimpleNamespace:
    return SimpleNamespace(
        id=user_id,
        email="user@example.com",
        is_active=True,
    )


def _make_fake_model(**kwargs) -> SimpleNamespace:
    now = datetime.now(timezone.utc)
    defaults = dict(
        id=1,
        original_filename="model.ifc",
        file_size_bytes=100,
        sha256="abc123def456",
        status="PENDING",
        ifc_schema=None,
        error_message=None,
        created_at=now,
        processing_started_at=None,
        processed_at=None,
        # deliberately excluded from schema:
        owner_id=42,
        storage_path="some-uuid.ifc",
        updated_at=now,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _fake_db():
    yield MagicMock(spec=Session)


SAMPLE_IFC = b"ISO-10303-21;\nHEADER;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n"

_UPLOAD_URL = "/api/v1/models"


def _upload_file(client: TestClient, content: bytes = SAMPLE_IFC, filename: str = "model.ifc"):
    return client.post(
        _UPLOAD_URL,
        files={"file": (filename, io.BytesIO(content), "application/octet-stream")},
    )


# ---------------------------------------------------------------------------
# 1. Endpoint está protegido (requiere JWT)
# ---------------------------------------------------------------------------

def test_endpoint_requires_auth(tmp_path):
    fake_settings = _make_settings(tmp_path)
    app.dependency_overrides[get_settings] = lambda: fake_settings
    app.dependency_overrides[get_db] = _fake_db
    try:
        client = TestClient(app)
        response = _upload_file(client)
        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 2. Request válido responde 201
# ---------------------------------------------------------------------------

def test_valid_request_returns_201(tmp_path, monkeypatch):
    fake_settings = _make_settings(tmp_path)
    fake_user = _make_fake_user()
    fake_model = _make_fake_model()

    monkeypatch.setattr(
        "app.api.routes.models.persist_ifc_model",
        lambda db, user, stored: fake_model,
    )

    app.dependency_overrides[get_current_user] = lambda: fake_user
    app.dependency_overrides[get_settings] = lambda: fake_settings
    app.dependency_overrides[get_db] = _fake_db
    try:
        client = TestClient(app)
        response = _upload_file(client)
        assert response.status_code == 201
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 3. Respuesta no contiene owner_id
# ---------------------------------------------------------------------------

def test_response_does_not_contain_owner_id(tmp_path, monkeypatch):
    fake_settings = _make_settings(tmp_path)
    fake_user = _make_fake_user()
    fake_model = _make_fake_model()

    monkeypatch.setattr(
        "app.api.routes.models.persist_ifc_model",
        lambda db, user, stored: fake_model,
    )

    app.dependency_overrides[get_current_user] = lambda: fake_user
    app.dependency_overrides[get_settings] = lambda: fake_settings
    app.dependency_overrides[get_db] = _fake_db
    try:
        client = TestClient(app)
        data = _upload_file(client).json()
        assert "owner_id" not in data
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 4. Respuesta no contiene storage_path
# ---------------------------------------------------------------------------

def test_response_does_not_contain_storage_path(tmp_path, monkeypatch):
    fake_settings = _make_settings(tmp_path)
    fake_user = _make_fake_user()
    fake_model = _make_fake_model()

    monkeypatch.setattr(
        "app.api.routes.models.persist_ifc_model",
        lambda db, user, stored: fake_model,
    )

    app.dependency_overrides[get_current_user] = lambda: fake_user
    app.dependency_overrides[get_settings] = lambda: fake_settings
    app.dependency_overrides[get_db] = _fake_db
    try:
        client = TestClient(app)
        data = _upload_file(client).json()
        assert "storage_path" not in data
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 5. owner_id persistido proviene de current_user.id
# ---------------------------------------------------------------------------

def test_owner_id_comes_from_current_user(tmp_path, monkeypatch):
    fake_settings = _make_settings(tmp_path)
    fake_user = _make_fake_user(user_id=99)
    fake_model = _make_fake_model()
    captured: dict = {}

    def _fake_persist(db, user, stored):
        captured["owner_id"] = user.id
        return fake_model

    monkeypatch.setattr("app.api.routes.models.persist_ifc_model", _fake_persist)

    app.dependency_overrides[get_current_user] = lambda: fake_user
    app.dependency_overrides[get_settings] = lambda: fake_settings
    app.dependency_overrides[get_db] = _fake_db
    try:
        client = TestClient(app)
        _upload_file(client)
        assert captured["owner_id"] == 99
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 6. Status inicial es PENDING
# ---------------------------------------------------------------------------

def test_initial_status_is_pending(tmp_path, monkeypatch):
    fake_settings = _make_settings(tmp_path)
    fake_user = _make_fake_user()
    fake_model = _make_fake_model(status="PENDING")

    monkeypatch.setattr(
        "app.api.routes.models.persist_ifc_model",
        lambda db, user, stored: fake_model,
    )

    app.dependency_overrides[get_current_user] = lambda: fake_user
    app.dependency_overrides[get_settings] = lambda: fake_settings
    app.dependency_overrides[get_db] = _fake_db
    try:
        client = TestClient(app)
        data = _upload_file(client).json()
        assert data["status"] == "PENDING"
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 7. original_filename persistido está normalizado
# ---------------------------------------------------------------------------

def test_original_filename_is_normalized(tmp_path, monkeypatch):
    fake_settings = _make_settings(tmp_path)
    fake_user = _make_fake_user()
    fake_model = _make_fake_model()
    captured: dict = {}

    def _fake_persist(db, user, stored):
        captured["original_filename"] = stored.original_filename
        return fake_model

    monkeypatch.setattr("app.api.routes.models.persist_ifc_model", _fake_persist)

    app.dependency_overrides[get_current_user] = lambda: fake_user
    app.dependency_overrides[get_settings] = lambda: fake_settings
    app.dependency_overrides[get_db] = _fake_db
    try:
        client = TestClient(app)
        # Upload with a path-traversal filename
        client.post(
            _UPLOAD_URL,
            files={
                "file": (
                    "../../secret/model.ifc",
                    io.BytesIO(SAMPLE_IFC),
                    "application/octet-stream",
                )
            },
        )
        filename = captured.get("original_filename", "")
        assert "/" not in filename
        assert "\\" not in filename
        assert filename == "model.ifc"
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 8. file_size_bytes correcto
# ---------------------------------------------------------------------------

def test_file_size_bytes_correct(tmp_path, monkeypatch):
    fake_settings = _make_settings(tmp_path)
    fake_user = _make_fake_user()
    content = b"A" * 512
    fake_model = _make_fake_model(file_size_bytes=512)
    captured: dict = {}

    def _fake_persist(db, user, stored):
        captured["file_size_bytes"] = stored.file_size_bytes
        return fake_model

    monkeypatch.setattr("app.api.routes.models.persist_ifc_model", _fake_persist)

    app.dependency_overrides[get_current_user] = lambda: fake_user
    app.dependency_overrides[get_settings] = lambda: fake_settings
    app.dependency_overrides[get_db] = _fake_db
    try:
        client = TestClient(app)
        _upload_file(client, content=content)
        assert captured["file_size_bytes"] == 512
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 9. sha256 correcto
# ---------------------------------------------------------------------------

def test_sha256_correct(tmp_path, monkeypatch):
    import hashlib

    fake_settings = _make_settings(tmp_path)
    fake_user = _make_fake_user()
    content = b"sha256 test content"
    expected_sha = hashlib.sha256(content).hexdigest()
    fake_model = _make_fake_model(sha256=expected_sha)
    captured: dict = {}

    def _fake_persist(db, user, stored):
        captured["sha256"] = stored.sha256
        return fake_model

    monkeypatch.setattr("app.api.routes.models.persist_ifc_model", _fake_persist)

    app.dependency_overrides[get_current_user] = lambda: fake_user
    app.dependency_overrides[get_settings] = lambda: fake_settings
    app.dependency_overrides[get_db] = _fake_db
    try:
        client = TestClient(app)
        _upload_file(client, content=content)
        assert captured["sha256"] == expected_sha
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 10. Extensión inválida devuelve 400
# ---------------------------------------------------------------------------

def test_invalid_extension_returns_400(tmp_path, monkeypatch):
    fake_settings = _make_settings(tmp_path)
    fake_user = _make_fake_user()

    monkeypatch.setattr(
        "app.api.routes.models.persist_ifc_model",
        lambda db, user, stored: _make_fake_model(),
    )

    app.dependency_overrides[get_current_user] = lambda: fake_user
    app.dependency_overrides[get_settings] = lambda: fake_settings
    app.dependency_overrides[get_db] = _fake_db
    try:
        client = TestClient(app)
        response = _upload_file(client, filename="model.txt")
        assert response.status_code == 400
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 11. Archivo vacío devuelve 400
# ---------------------------------------------------------------------------

def test_empty_file_returns_400(tmp_path, monkeypatch):
    fake_settings = _make_settings(tmp_path)
    fake_user = _make_fake_user()

    monkeypatch.setattr(
        "app.api.routes.models.persist_ifc_model",
        lambda db, user, stored: _make_fake_model(),
    )

    app.dependency_overrides[get_current_user] = lambda: fake_user
    app.dependency_overrides[get_settings] = lambda: fake_settings
    app.dependency_overrides[get_db] = _fake_db
    try:
        client = TestClient(app)
        response = _upload_file(client, content=b"")
        assert response.status_code == 400
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 12. Archivo demasiado grande devuelve 413
# ---------------------------------------------------------------------------

def test_oversized_file_returns_413(tmp_path, monkeypatch):
    fake_settings = _make_settings_small_limit(tmp_path)  # 1 MB limit
    fake_user = _make_fake_user()

    monkeypatch.setattr(
        "app.api.routes.models.persist_ifc_model",
        lambda db, user, stored: _make_fake_model(),
    )

    app.dependency_overrides[get_current_user] = lambda: fake_user
    app.dependency_overrides[get_settings] = lambda: fake_settings
    app.dependency_overrides[get_db] = _fake_db
    try:
        client = TestClient(app)
        oversized = b"x" * (1024 * 1024 + 1)
        response = _upload_file(client, content=oversized)
        assert response.status_code == 413
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 13. Error del storage devuelve 500 genérico
# ---------------------------------------------------------------------------

def test_storage_error_returns_500(tmp_path, monkeypatch):
    from app.services.ifc_storage import IfcStorageError

    fake_settings = _make_settings(tmp_path)
    fake_user = _make_fake_user()

    async def _failing_save(upload, settings):
        await upload.close()
        raise IfcStorageError("Simulated filesystem error")

    monkeypatch.setattr("app.api.routes.models.save_ifc_file", _failing_save)

    app.dependency_overrides[get_current_user] = lambda: fake_user
    app.dependency_overrides[get_settings] = lambda: fake_settings
    app.dependency_overrides[get_db] = _fake_db
    try:
        client = TestClient(app)
        response = _upload_file(client)
        assert response.status_code == 500
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 14. Error de persistencia hace rollback en DB
# ---------------------------------------------------------------------------

def test_persistence_error_does_rollback(tmp_path):
    fake_settings = _make_settings(tmp_path)
    fake_user = _make_fake_user()

    mock_db = MagicMock(spec=Session)
    mock_db.commit.side_effect = Exception("Simulated DB failure")

    def _failing_db():
        yield mock_db

    app.dependency_overrides[get_current_user] = lambda: fake_user
    app.dependency_overrides[get_settings] = lambda: fake_settings
    app.dependency_overrides[get_db] = _failing_db
    try:
        client = TestClient(app)
        client.post(
            _UPLOAD_URL,
            files={"file": ("model.ifc", io.BytesIO(SAMPLE_IFC), "application/octet-stream")},
        )
        mock_db.rollback.assert_called_once()
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 15. Error de persistencia elimina el archivo final
# ---------------------------------------------------------------------------

def test_persistence_error_removes_stored_file(tmp_path):
    fake_settings = _make_settings(tmp_path)
    fake_user = _make_fake_user()

    mock_db = MagicMock(spec=Session)
    mock_db.commit.side_effect = Exception("Simulated DB failure")

    def _failing_db():
        yield mock_db

    app.dependency_overrides[get_current_user] = lambda: fake_user
    app.dependency_overrides[get_settings] = lambda: fake_settings
    app.dependency_overrides[get_db] = _failing_db
    try:
        client = TestClient(app)
        response = client.post(
            _UPLOAD_URL,
            files={"file": ("model.ifc", io.BytesIO(SAMPLE_IFC), "application/octet-stream")},
        )
        assert response.status_code == 500
        ifc_files = list(fake_settings.ifc_storage_dir.glob("*.ifc"))
        assert len(ifc_files) == 0
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 16. Errores 500 no exponen filesystem path ni detalle SQL
# ---------------------------------------------------------------------------

def test_storage_error_response_is_generic(tmp_path, monkeypatch):
    from app.services.ifc_storage import IfcStorageError

    fake_settings = _make_settings(tmp_path)
    fake_user = _make_fake_user()

    async def _failing_save(upload, settings):
        await upload.close()
        raise IfcStorageError("Internal path: /app/storage/secret.ifc")

    monkeypatch.setattr("app.api.routes.models.save_ifc_file", _failing_save)

    app.dependency_overrides[get_current_user] = lambda: fake_user
    app.dependency_overrides[get_settings] = lambda: fake_settings
    app.dependency_overrides[get_db] = _fake_db
    try:
        client = TestClient(app)
        response = _upload_file(client)
        body = response.text
        assert "/app/storage" not in body
        assert "secret.ifc" not in body
        assert response.status_code == 500
    finally:
        app.dependency_overrides.clear()


def test_persistence_error_response_is_generic(tmp_path):
    fake_settings = _make_settings(tmp_path)
    fake_user = _make_fake_user()

    mock_db = MagicMock(spec=Session)
    mock_db.commit.side_effect = Exception("SQL: UNIQUE constraint failed: ifc_models.sha256")

    def _failing_db():
        yield mock_db

    app.dependency_overrides[get_current_user] = lambda: fake_user
    app.dependency_overrides[get_settings] = lambda: fake_settings
    app.dependency_overrides[get_db] = _failing_db
    try:
        client = TestClient(app)
        response = client.post(
            _UPLOAD_URL,
            files={"file": ("model.ifc", io.BytesIO(SAMPLE_IFC), "application/octet-stream")},
        )
        body = response.text
        assert "SQL" not in body
        assert "constraint" not in body.lower()
        assert "ifc_models" not in body
    finally:
        app.dependency_overrides.clear()


# ===========================================================================
# persist_ifc_model unit tests (no endpoint, no HTTP)
# ===========================================================================

def _make_stored() -> StoredIfcFile:
    return StoredIfcFile(
        original_filename="model.ifc",
        storage_path="550e8400-e29b-41d4-a716-446655440000.ifc",
        file_size_bytes=256,
        sha256="deadbeefcafe1234" * 4,
    )


def _make_user_ns(user_id: int = 42) -> SimpleNamespace:
    return SimpleNamespace(id=user_id, email="u@test.com", is_active=True)


# ---------------------------------------------------------------------------
# 6-a. persist_ifc_model sends correct fields to db.add
# ---------------------------------------------------------------------------

def test_persist_sets_owner_id():
    stored = _make_stored()
    user = _make_user_ns(user_id=77)
    mock_db = MagicMock(spec=Session)
    persist_ifc_model(mock_db, user, stored)
    model = mock_db.add.call_args[0][0]
    assert model.owner_id == 77


def test_persist_sets_status_pending():
    stored = _make_stored()
    user = _make_user_ns()
    mock_db = MagicMock(spec=Session)
    persist_ifc_model(mock_db, user, stored)
    model = mock_db.add.call_args[0][0]
    assert model.status == "PENDING"


def test_persist_sets_original_filename():
    stored = _make_stored()
    user = _make_user_ns()
    mock_db = MagicMock(spec=Session)
    persist_ifc_model(mock_db, user, stored)
    model = mock_db.add.call_args[0][0]
    assert model.original_filename == stored.original_filename


def test_persist_sets_storage_path():
    stored = _make_stored()
    user = _make_user_ns()
    mock_db = MagicMock(spec=Session)
    persist_ifc_model(mock_db, user, stored)
    model = mock_db.add.call_args[0][0]
    assert model.storage_path == stored.storage_path


def test_persist_sets_file_size_bytes():
    stored = _make_stored()
    user = _make_user_ns()
    mock_db = MagicMock(spec=Session)
    persist_ifc_model(mock_db, user, stored)
    model = mock_db.add.call_args[0][0]
    assert model.file_size_bytes == stored.file_size_bytes


def test_persist_sets_sha256():
    stored = _make_stored()
    user = _make_user_ns()
    mock_db = MagicMock(spec=Session)
    persist_ifc_model(mock_db, user, stored)
    model = mock_db.add.call_args[0][0]
    assert model.sha256 == stored.sha256


# ---------------------------------------------------------------------------
# 6-b. persist_ifc_model calls DB methods in order
# ---------------------------------------------------------------------------

def test_persist_calls_add_flush_refresh_commit():
    stored = _make_stored()
    user = _make_user_ns()
    mock_db = MagicMock(spec=Session)
    persist_ifc_model(mock_db, user, stored)
    mock_db.add.assert_called_once()
    mock_db.flush.assert_called_once()
    mock_db.refresh.assert_called_once()
    mock_db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# 7. refresh failure → rollback called, commit NOT called
# ---------------------------------------------------------------------------

def test_refresh_failure_rollback_no_commit():
    stored = _make_stored()
    user = _make_user_ns()
    mock_db = MagicMock(spec=Session)
    mock_db.refresh.side_effect = Exception("DB connection lost during refresh")

    with pytest.raises(IfcModelPersistenceError):
        persist_ifc_model(mock_db, user, stored)

    mock_db.rollback.assert_called_once()
    mock_db.commit.assert_not_called()


def test_flush_failure_rollback_no_commit():
    stored = _make_stored()
    user = _make_user_ns()
    mock_db = MagicMock(spec=Session)
    mock_db.flush.side_effect = Exception("Integrity error during flush")

    with pytest.raises(IfcModelPersistenceError):
        persist_ifc_model(mock_db, user, stored)

    mock_db.rollback.assert_called_once()
    mock_db.commit.assert_not_called()


# ---------------------------------------------------------------------------
# 8. unlink fails after persist error → still 500, no leak
# ---------------------------------------------------------------------------

def test_persistence_error_with_failing_unlink_returns_500(tmp_path, monkeypatch):
    fake_settings = _make_settings(tmp_path)
    fake_user = _make_fake_user()

    def _failing_persist(db, user, stored):
        raise IfcModelPersistenceError("DB error")

    monkeypatch.setattr("app.api.routes.models.persist_ifc_model", _failing_persist)

    def _failing_unlink(self, *args, **kwargs):
        raise PermissionError("Cannot delete: /app/storage/secret.ifc")

    monkeypatch.setattr("pathlib.Path.unlink", _failing_unlink)

    app.dependency_overrides[get_current_user] = lambda: fake_user
    app.dependency_overrides[get_settings] = lambda: fake_settings
    app.dependency_overrides[get_db] = _fake_db
    try:
        client = TestClient(app)
        response = _upload_file(client)
        assert response.status_code == 500
        body = response.text
        assert "/app/storage" not in body
        assert "secret.ifc" not in body
        assert "PermissionError" not in body
        assert "Cannot delete" not in body
    finally:
        app.dependency_overrides.clear()
        # monkeypatch restores Path.unlink automatically after the test.
