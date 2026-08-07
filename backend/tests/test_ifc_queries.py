"""
Tests for ifc_queries service and the GET /api/v1/models endpoints.

Service tests: MagicMock(spec=Session) — no PostgreSQL.
Endpoint tests: FastAPI TestClient + dependency overrides — no PostgreSQL.
"""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_user
from app.db.session import get_db
from app.main import app
from app.models.ifc_model import IfcModel
from app.services.ifc_queries import (
    IfcModelQueryError,
    get_ifc_model_for_owner,
    list_ifc_models_for_owner,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _now():
    return datetime.now(timezone.utc)


def _make_mock_model(model_id: int = 1, owner_id: int = 42, status: str = "PENDING"):
    m = MagicMock(spec=IfcModel)
    m.id = model_id
    m.owner_id = owner_id
    m.original_filename = "model.ifc"
    m.file_size_bytes = 100
    m.sha256 = "a" * 64
    m.status = status
    m.ifc_schema = None
    m.error_message = None
    m.created_at = _now()
    m.processing_started_at = None
    m.processed_at = None
    m.storage_path = f"{model_id}-uuid.ifc"
    m.updated_at = _now()
    return m


def _make_fake_model(**kwargs):
    """SimpleNamespace mimicking IfcModel for endpoint response serialization."""
    now = _now()
    defaults = dict(
        id=1,
        owner_id=42,
        original_filename="model.ifc",
        file_size_bytes=100,
        sha256="a" * 64,
        status="PENDING",
        ifc_schema=None,
        error_message=None,
        created_at=now,
        processing_started_at=None,
        processed_at=None,
        storage_path="some-uuid.ifc",
        updated_at=now,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _make_fake_user(user_id: int = 42):
    return SimpleNamespace(id=user_id, email="u@test.com", is_active=True)


def _fake_db():
    yield MagicMock(spec=Session)


_LIST_URL = "/api/v1/models"
_DETAIL_URL = "/api/v1/models/{}"


# ===========================================================================
# SERVICE TESTS — list_ifc_models_for_owner
# ===========================================================================

class TestListIfcModelsForOwner:

    def _mock_db(self, results=None):
        mock_db = MagicMock(spec=Session)
        mock_db.scalars.return_value.all.return_value = results if results is not None else []
        return mock_db

    # -----------------------------------------------------------------------
    # 1. Executes a query (scalars is called)
    # -----------------------------------------------------------------------

    def test_executes_query(self):
        mock_db = self._mock_db()
        list_ifc_models_for_owner(mock_db, owner_id=1)
        mock_db.scalars.assert_called_once()

    # -----------------------------------------------------------------------
    # 2. Filters by owner_id in SQL (inspect compiled statement)
    # -----------------------------------------------------------------------

    def test_filters_by_owner_id_in_sql(self):
        mock_db = self._mock_db()
        list_ifc_models_for_owner(mock_db, owner_id=42)

        stmt = mock_db.scalars.call_args[0][0]
        sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "42" in sql

    # -----------------------------------------------------------------------
    # 3. Returns all results from scalars().all()
    # -----------------------------------------------------------------------

    def test_returns_all_results(self):
        models = [_make_mock_model(1), _make_mock_model(2)]
        mock_db = self._mock_db(results=models)
        result = list_ifc_models_for_owner(mock_db, owner_id=1)
        assert result == models

    # -----------------------------------------------------------------------
    # 4. Empty result returns []
    # -----------------------------------------------------------------------

    def test_empty_returns_empty_list(self):
        mock_db = self._mock_db(results=[])
        result = list_ifc_models_for_owner(mock_db, owner_id=1)
        assert result == []

    # -----------------------------------------------------------------------
    # 5. Order: created_at DESC, id DESC (inspect compiled statement)
    # -----------------------------------------------------------------------

    def test_ordered_by_created_at_desc_then_id_desc(self):
        mock_db = self._mock_db()
        list_ifc_models_for_owner(mock_db, owner_id=1)

        stmt = mock_db.scalars.call_args[0][0]
        sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        upper = sql.upper()
        assert "CREATED_AT" in upper
        assert "ID" in upper
        # Both order columns are DESC
        assert upper.count("DESC") >= 2

    # -----------------------------------------------------------------------
    # 6. Does not commit
    # -----------------------------------------------------------------------

    def test_does_not_commit(self):
        mock_db = self._mock_db()
        list_ifc_models_for_owner(mock_db, owner_id=1)
        mock_db.commit.assert_not_called()

    # -----------------------------------------------------------------------
    # 7. DB error → IfcModelQueryError
    # -----------------------------------------------------------------------

    def test_db_error_raises_query_error(self):
        mock_db = MagicMock(spec=Session)
        mock_db.scalars.side_effect = Exception("DB gone")
        with pytest.raises(IfcModelQueryError):
            list_ifc_models_for_owner(mock_db, owner_id=1)


# ===========================================================================
# SERVICE TESTS — get_ifc_model_for_owner
# ===========================================================================

class TestGetIfcModelForOwner:

    def _mock_db(self, result=None):
        mock_db = MagicMock(spec=Session)
        mock_db.scalars.return_value.first.return_value = result
        return mock_db

    # -----------------------------------------------------------------------
    # 8. Executes a query with model_id
    # -----------------------------------------------------------------------

    def test_executes_query_with_model_id(self):
        mock_db = self._mock_db()
        get_ifc_model_for_owner(mock_db, model_id=5, owner_id=1)

        stmt = mock_db.scalars.call_args[0][0]
        sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "5" in sql

    # -----------------------------------------------------------------------
    # 9. Includes owner_id in the SQL query (IDOR guard)
    # -----------------------------------------------------------------------

    def test_includes_owner_id_in_sql(self):
        mock_db = self._mock_db()
        get_ifc_model_for_owner(mock_db, model_id=5, owner_id=99)

        stmt = mock_db.scalars.call_args[0][0]
        sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        # Both conditions must appear in SQL — authorisation is in the query
        assert "99" in sql
        assert "5" in sql

    # -----------------------------------------------------------------------
    # 10. Found → returns model
    # -----------------------------------------------------------------------

    def test_found_returns_model(self):
        model = _make_mock_model(model_id=7)
        mock_db = self._mock_db(result=model)
        result = get_ifc_model_for_owner(mock_db, model_id=7, owner_id=42)
        assert result is model

    # -----------------------------------------------------------------------
    # 11. Not found → returns None
    # -----------------------------------------------------------------------

    def test_not_found_returns_none(self):
        mock_db = self._mock_db(result=None)
        result = get_ifc_model_for_owner(mock_db, model_id=999, owner_id=42)
        assert result is None

    # -----------------------------------------------------------------------
    # 12. Does not commit
    # -----------------------------------------------------------------------

    def test_does_not_commit(self):
        mock_db = self._mock_db()
        get_ifc_model_for_owner(mock_db, model_id=1, owner_id=1)
        mock_db.commit.assert_not_called()

    # -----------------------------------------------------------------------
    # 13. DB error → IfcModelQueryError
    # -----------------------------------------------------------------------

    def test_db_error_raises_query_error(self):
        mock_db = MagicMock(spec=Session)
        mock_db.scalars.side_effect = Exception("Connection refused")
        with pytest.raises(IfcModelQueryError):
            get_ifc_model_for_owner(mock_db, model_id=1, owner_id=1)


# ===========================================================================
# ENDPOINT TESTS — GET /api/v1/models (list)
# ===========================================================================

class TestListModelsEndpoint:
    """Tests for GET /api/v1/models."""

    def _client(self, monkeypatch, user=None, service_result=None, raise_error=False):
        """Build a TestClient with all dependencies mocked."""
        fake_user = user or _make_fake_user()

        if raise_error:
            def _svc(db, owner_id):
                raise IfcModelQueryError("DB error")
        else:
            result = service_result if service_result is not None else []

            def _svc(db, owner_id):
                return result

        monkeypatch.setattr("app.api.routes.models.list_ifc_models_for_owner", _svc)

        app.dependency_overrides[get_current_user] = lambda: fake_user
        app.dependency_overrides[get_db] = _fake_db
        return TestClient(app)

    def _cleanup(self):
        app.dependency_overrides.clear()

    # -----------------------------------------------------------------------
    # 1. Authenticated request → 200
    # -----------------------------------------------------------------------

    def test_authenticated_returns_200(self, monkeypatch):
        client = self._client(monkeypatch)
        try:
            assert client.get(_LIST_URL).status_code == 200
        finally:
            self._cleanup()

    # -----------------------------------------------------------------------
    # 2. Empty list → []
    # -----------------------------------------------------------------------

    def test_empty_list(self, monkeypatch):
        client = self._client(monkeypatch, service_result=[])
        try:
            assert client.get(_LIST_URL).json() == []
        finally:
            self._cleanup()

    # -----------------------------------------------------------------------
    # 3. Multiple models serialize correctly
    # -----------------------------------------------------------------------

    def test_multiple_models_serialized(self, monkeypatch):
        models = [_make_fake_model(id=1), _make_fake_model(id=2)]
        client = self._client(monkeypatch, service_result=models)
        try:
            data = client.get(_LIST_URL).json()
            assert len(data) == 2
            ids = {m["id"] for m in data}
            assert ids == {1, 2}
        finally:
            self._cleanup()

    # -----------------------------------------------------------------------
    # 4-7. Status values preserved
    # -----------------------------------------------------------------------

    @pytest.mark.parametrize("st", ["PENDING", "PROCESSING", "COMPLETED", "FAILED"])
    def test_status_preserved(self, monkeypatch, st):
        models = [_make_fake_model(status=st)]
        client = self._client(monkeypatch, service_result=models)
        try:
            data = client.get(_LIST_URL).json()
            assert data[0]["status"] == st
        finally:
            self._cleanup()

    # -----------------------------------------------------------------------
    # 8. Response does not contain owner_id
    # -----------------------------------------------------------------------

    def test_no_owner_id_in_response(self, monkeypatch):
        client = self._client(monkeypatch, service_result=[_make_fake_model()])
        try:
            data = client.get(_LIST_URL).json()
            assert "owner_id" not in data[0]
        finally:
            self._cleanup()

    # -----------------------------------------------------------------------
    # 9. Response does not contain storage_path
    # -----------------------------------------------------------------------

    def test_no_storage_path_in_response(self, monkeypatch):
        client = self._client(monkeypatch, service_result=[_make_fake_model()])
        try:
            data = client.get(_LIST_URL).json()
            assert "storage_path" not in data[0]
        finally:
            self._cleanup()

    # -----------------------------------------------------------------------
    # 10. Response does not contain updated_at
    # -----------------------------------------------------------------------

    def test_no_updated_at_in_response(self, monkeypatch):
        client = self._client(monkeypatch, service_result=[_make_fake_model()])
        try:
            data = client.get(_LIST_URL).json()
            assert "updated_at" not in data[0]
        finally:
            self._cleanup()

    # -----------------------------------------------------------------------
    # 11. Service error → 500
    # -----------------------------------------------------------------------

    def test_service_error_returns_500(self, monkeypatch):
        client = self._client(monkeypatch, raise_error=True)
        try:
            assert client.get(_LIST_URL).status_code == 500
        finally:
            self._cleanup()

    # -----------------------------------------------------------------------
    # 12. 500 detail is exact
    # -----------------------------------------------------------------------

    def test_service_error_detail(self, monkeypatch):
        client = self._client(monkeypatch, raise_error=True)
        try:
            detail = client.get(_LIST_URL).json()["detail"]
            assert detail == "Error interno al consultar los modelos."
        finally:
            self._cleanup()


# ===========================================================================
# ENDPOINT TESTS — GET /api/v1/models/{model_id} (detail)
# ===========================================================================

class TestGetModelEndpoint:
    """Tests for GET /api/v1/models/{model_id}."""

    def _client(self, monkeypatch, user=None, service_result=None, raise_error=False):
        fake_user = user or _make_fake_user()

        if raise_error:
            def _svc(db, model_id, owner_id):
                raise IfcModelQueryError("DB error")
        else:
            result = service_result  # None or a model object

            def _svc(db, model_id, owner_id):
                return result

        monkeypatch.setattr("app.api.routes.models.get_ifc_model_for_owner", _svc)

        app.dependency_overrides[get_current_user] = lambda: fake_user
        app.dependency_overrides[get_db] = _fake_db
        return TestClient(app)

    def _cleanup(self):
        app.dependency_overrides.clear()

    # -----------------------------------------------------------------------
    # 1. Own model found → 200
    # -----------------------------------------------------------------------

    def test_own_model_returns_200(self, monkeypatch):
        model = _make_fake_model(id=7)
        client = self._client(monkeypatch, service_result=model)
        try:
            assert client.get(_DETAIL_URL.format(7)).status_code == 200
        finally:
            self._cleanup()

    # -----------------------------------------------------------------------
    # 2. Correct id returned
    # -----------------------------------------------------------------------

    def test_correct_id_returned(self, monkeypatch):
        model = _make_fake_model(id=77)
        client = self._client(monkeypatch, service_result=model)
        try:
            data = client.get(_DETAIL_URL.format(77)).json()
            assert data["id"] == 77
        finally:
            self._cleanup()

    # -----------------------------------------------------------------------
    # 3. Status preserved
    # -----------------------------------------------------------------------

    def test_status_preserved(self, monkeypatch):
        model = _make_fake_model(status="COMPLETED")
        client = self._client(monkeypatch, service_result=model)
        try:
            data = client.get(_DETAIL_URL.format(1)).json()
            assert data["status"] == "COMPLETED"
        finally:
            self._cleanup()

    # -----------------------------------------------------------------------
    # 4. No owner_id in response
    # -----------------------------------------------------------------------

    def test_no_owner_id(self, monkeypatch):
        client = self._client(monkeypatch, service_result=_make_fake_model())
        try:
            data = client.get(_DETAIL_URL.format(1)).json()
            assert "owner_id" not in data
        finally:
            self._cleanup()

    # -----------------------------------------------------------------------
    # 5. No storage_path in response
    # -----------------------------------------------------------------------

    def test_no_storage_path(self, monkeypatch):
        client = self._client(monkeypatch, service_result=_make_fake_model())
        try:
            data = client.get(_DETAIL_URL.format(1)).json()
            assert "storage_path" not in data
        finally:
            self._cleanup()

    # -----------------------------------------------------------------------
    # 6. No updated_at in response
    # -----------------------------------------------------------------------

    def test_no_updated_at(self, monkeypatch):
        client = self._client(monkeypatch, service_result=_make_fake_model())
        try:
            data = client.get(_DETAIL_URL.format(1)).json()
            assert "updated_at" not in data
        finally:
            self._cleanup()

    # -----------------------------------------------------------------------
    # 7. Service returns None → 404
    # -----------------------------------------------------------------------

    def test_not_found_returns_404(self, monkeypatch):
        client = self._client(monkeypatch, service_result=None)
        try:
            assert client.get(_DETAIL_URL.format(999)).status_code == 404
        finally:
            self._cleanup()

    # -----------------------------------------------------------------------
    # 8. 404 detail is exact
    # -----------------------------------------------------------------------

    def test_not_found_detail(self, monkeypatch):
        client = self._client(monkeypatch, service_result=None)
        try:
            detail = client.get(_DETAIL_URL.format(999)).json()["detail"]
            assert detail == "Modelo IFC no encontrado."
        finally:
            self._cleanup()

    # -----------------------------------------------------------------------
    # 9. Different owner (service returns None) → same 404 (IDOR prevention)
    # -----------------------------------------------------------------------

    def test_different_owner_same_404(self, monkeypatch):
        """Model belongs to another user — service returns None.
        Response must be identical to a non-existent model: 404 with same detail."""
        # Simulate service finding no result for this owner (another user's model)
        client = self._client(monkeypatch, service_result=None)
        try:
            resp = client.get(_DETAIL_URL.format(1))
            assert resp.status_code == 404
            assert resp.json()["detail"] == "Modelo IFC no encontrado."
        finally:
            self._cleanup()

    # -----------------------------------------------------------------------
    # 10. Service error → 500
    # -----------------------------------------------------------------------

    def test_service_error_returns_500(self, monkeypatch):
        client = self._client(monkeypatch, raise_error=True)
        try:
            assert client.get(_DETAIL_URL.format(1)).status_code == 500
        finally:
            self._cleanup()

    # -----------------------------------------------------------------------
    # 11. 500 detail is exact
    # -----------------------------------------------------------------------

    def test_service_error_detail(self, monkeypatch):
        client = self._client(monkeypatch, raise_error=True)
        try:
            detail = client.get(_DETAIL_URL.format(1)).json()["detail"]
            assert detail == "Error interno al consultar el modelo."
        finally:
            self._cleanup()


# ===========================================================================
# AUTHENTICATION TESTS
# ===========================================================================

class TestAuthRequired:
    """Both GET endpoints require a valid Bearer token."""

    def test_list_without_token_returns_401(self):
        # No dependency overrides — real get_current_user will reject missing token
        client = TestClient(app)
        assert client.get(_LIST_URL).status_code == 401

    def test_detail_without_token_returns_401(self):
        client = TestClient(app)
        assert client.get(_DETAIL_URL.format(1)).status_code == 401


# ===========================================================================
# ENDPOINT TESTS — GET /api/v1/models/{model_id}/file
# ===========================================================================

_FILE_URL = "/api/v1/models/{}/file"

_IFC_BYTES = b"ISO-10303-21; QA IFC; END-ISO-10303-21;"


def _make_completed_model(tmp_path, storage_filename="stored-model.ifc"):
    """Return a fake model with status COMPLETED and a resolvable storage_path."""
    return _make_fake_model(
        status="COMPLETED",
        storage_path=storage_filename,
        original_filename="proyecto.ifc",
    )


def _write_ifc(tmp_path, filename="stored-model.ifc", content=_IFC_BYTES):
    p = tmp_path / filename
    p.write_bytes(content)
    return p


class TestDownloadIfcFileEndpoint:
    """Tests for GET /api/v1/models/{model_id}/file."""

    def _client(
        self,
        monkeypatch,
        tmp_path,
        model=None,
        raise_error=False,
        user=None,
    ):
        fake_user = user or _make_fake_user()

        if raise_error:
            def _svc(db, model_id, owner_id):
                raise IfcModelQueryError("DB error")
        else:
            result = model

            def _svc(db, model_id, owner_id):
                return result

        monkeypatch.setattr("app.api.routes.models.get_ifc_model_for_owner", _svc)

        from app.core.config import get_settings
        from types import SimpleNamespace

        def _fake_settings():
            return SimpleNamespace(ifc_storage_dir=tmp_path)

        app.dependency_overrides[get_current_user] = lambda: fake_user
        app.dependency_overrides[get_db] = _fake_db
        app.dependency_overrides[get_settings] = _fake_settings
        return TestClient(app)

    def _cleanup(self):
        app.dependency_overrides.clear()

    # -----------------------------------------------------------------------
    # 1. COMPLETED own model with real file → 200
    # -----------------------------------------------------------------------

    def test_completed_own_model_returns_200(self, monkeypatch, tmp_path):
        _write_ifc(tmp_path)
        model = _make_completed_model(tmp_path)
        client = self._client(monkeypatch, tmp_path, model=model)
        try:
            resp = client.get(_FILE_URL.format(1))
            assert resp.status_code == 200
        finally:
            self._cleanup()

    # -----------------------------------------------------------------------
    # 2. Response content matches file bytes exactly
    # -----------------------------------------------------------------------

    def test_response_content_matches_file_bytes(self, monkeypatch, tmp_path):
        _write_ifc(tmp_path)
        model = _make_completed_model(tmp_path)
        client = self._client(monkeypatch, tmp_path, model=model)
        try:
            resp = client.get(_FILE_URL.format(1))
            assert resp.content == _IFC_BYTES
        finally:
            self._cleanup()

    # -----------------------------------------------------------------------
    # 3. Content-Type starts with application/octet-stream
    # -----------------------------------------------------------------------

    def test_content_type_octet_stream(self, monkeypatch, tmp_path):
        _write_ifc(tmp_path)
        model = _make_completed_model(tmp_path)
        client = self._client(monkeypatch, tmp_path, model=model)
        try:
            resp = client.get(_FILE_URL.format(1))
            assert resp.headers["content-type"].startswith("application/octet-stream")
        finally:
            self._cleanup()

    # -----------------------------------------------------------------------
    # 4. Content-Disposition contains original_filename, not storage_path
    # -----------------------------------------------------------------------

    def test_content_disposition_uses_original_filename(self, monkeypatch, tmp_path):
        _write_ifc(tmp_path)
        model = _make_completed_model(tmp_path)
        # original_filename="proyecto.ifc", storage_path="stored-model.ifc"
        assert model.original_filename != model.storage_path
        client = self._client(monkeypatch, tmp_path, model=model)
        try:
            resp = client.get(_FILE_URL.format(1))
            disposition = resp.headers.get("content-disposition", "")
            assert model.original_filename in disposition
            assert model.storage_path not in disposition
        finally:
            self._cleanup()

    # -----------------------------------------------------------------------
    # 5. PENDING → 409
    # -----------------------------------------------------------------------

    def test_pending_returns_409(self, monkeypatch, tmp_path):
        model = _make_fake_model(status="PENDING", storage_path="f.ifc")
        client = self._client(monkeypatch, tmp_path, model=model)
        try:
            resp = client.get(_FILE_URL.format(1))
            assert resp.status_code == 409
            assert resp.json()["detail"] == "El archivo IFC no está disponible para visualización."
        finally:
            self._cleanup()

    # -----------------------------------------------------------------------
    # 6. PROCESSING → 409
    # -----------------------------------------------------------------------

    def test_processing_returns_409(self, monkeypatch, tmp_path):
        model = _make_fake_model(status="PROCESSING", storage_path="f.ifc")
        client = self._client(monkeypatch, tmp_path, model=model)
        try:
            resp = client.get(_FILE_URL.format(1))
            assert resp.status_code == 409
            assert resp.json()["detail"] == "El archivo IFC no está disponible para visualización."
        finally:
            self._cleanup()

    # -----------------------------------------------------------------------
    # 7. FAILED → 409
    # -----------------------------------------------------------------------

    def test_failed_returns_409(self, monkeypatch, tmp_path):
        model = _make_fake_model(status="FAILED", storage_path="f.ifc")
        client = self._client(monkeypatch, tmp_path, model=model)
        try:
            resp = client.get(_FILE_URL.format(1))
            assert resp.status_code == 409
            assert resp.json()["detail"] == "El archivo IFC no está disponible para visualización."
        finally:
            self._cleanup()

    # -----------------------------------------------------------------------
    # 8. Model not found (service returns None) → 404
    # -----------------------------------------------------------------------

    def test_model_not_found_returns_404(self, monkeypatch, tmp_path):
        client = self._client(monkeypatch, tmp_path, model=None)
        try:
            resp = client.get(_FILE_URL.format(999))
            assert resp.status_code == 404
            assert resp.json()["detail"] == "Modelo IFC no encontrado."
        finally:
            self._cleanup()

    # -----------------------------------------------------------------------
    # 9. Different owner (service returns None) → same 404 as not found (IDOR)
    # -----------------------------------------------------------------------

    def test_different_owner_indistinguishable_404(self, monkeypatch, tmp_path):
        """IDOR guard: a model owned by another user must return identical 404."""
        client = self._client(monkeypatch, tmp_path, model=None)
        try:
            resp = client.get(_FILE_URL.format(1))
            assert resp.status_code == 404
            assert resp.json()["detail"] == "Modelo IFC no encontrado."
        finally:
            self._cleanup()

    # -----------------------------------------------------------------------
    # 10. IfcModelQueryError → 500
    # -----------------------------------------------------------------------

    def test_query_error_returns_500(self, monkeypatch, tmp_path):
        client = self._client(monkeypatch, tmp_path, raise_error=True)
        try:
            resp = client.get(_FILE_URL.format(1))
            assert resp.status_code == 500
            assert resp.json()["detail"] == "Error interno al consultar el modelo."
        finally:
            self._cleanup()

    # -----------------------------------------------------------------------
    # 11. COMPLETED but file missing → 404
    # -----------------------------------------------------------------------

    def test_completed_file_missing_returns_404(self, monkeypatch, tmp_path):
        model = _make_completed_model(tmp_path)
        # Do NOT create the file
        client = self._client(monkeypatch, tmp_path, model=model)
        try:
            resp = client.get(_FILE_URL.format(1))
            assert resp.status_code == 404
            assert resp.json()["detail"] == "Archivo IFC no disponible."
        finally:
            self._cleanup()

    # -----------------------------------------------------------------------
    # 12. Absolute storage_path → 500 (path traversal guard)
    # -----------------------------------------------------------------------

    def test_absolute_storage_path_returns_500(self, monkeypatch, tmp_path):
        model = _make_fake_model(status="COMPLETED", storage_path="/etc/passwd.ifc")
        client = self._client(monkeypatch, tmp_path, model=model)
        try:
            resp = client.get(_FILE_URL.format(1))
            assert resp.status_code == 500
            assert resp.json()["detail"] == "Error interno al acceder al archivo IFC."
            # Must not leak any path detail
            assert "/etc" not in resp.json()["detail"]
        finally:
            self._cleanup()

    # -----------------------------------------------------------------------
    # 13. Path traversal storage_path → 500
    # -----------------------------------------------------------------------

    def test_path_traversal_returns_500(self, monkeypatch, tmp_path):
        model = _make_fake_model(status="COMPLETED", storage_path="../secret.ifc")
        client = self._client(monkeypatch, tmp_path, model=model)
        try:
            resp = client.get(_FILE_URL.format(1))
            assert resp.status_code == 500
            assert resp.json()["detail"] == "Error interno al acceder al archivo IFC."
        finally:
            self._cleanup()

    # -----------------------------------------------------------------------
    # 14. Subdirectory storage_path → 500
    # -----------------------------------------------------------------------

    def test_subdirectory_storage_path_returns_500(self, monkeypatch, tmp_path):
        model = _make_fake_model(status="COMPLETED", storage_path="subdir/model.ifc")
        client = self._client(monkeypatch, tmp_path, model=model)
        try:
            resp = client.get(_FILE_URL.format(1))
            assert resp.status_code == 500
            assert resp.json()["detail"] == "Error interno al acceder al archivo IFC."
        finally:
            self._cleanup()

    # -----------------------------------------------------------------------
    # 15. Symlink pointing outside storage root → 500
    # -----------------------------------------------------------------------

    def test_symlink_escape_returns_500(self, monkeypatch, tmp_path):
        import os
        # Create a real file outside storage root
        outside = tmp_path.parent / "outside-secret.ifc"
        outside.write_bytes(b"secret")
        link_name = "linked-model.ifc"
        link_path = tmp_path / link_name
        try:
            link_path.symlink_to(outside)
        except (OSError, NotImplementedError):
            pytest.skip("Symlinks not supported on this platform")

        model = _make_fake_model(status="COMPLETED", storage_path=link_name)
        client = self._client(monkeypatch, tmp_path, model=model)
        try:
            resp = client.get(_FILE_URL.format(1))
            assert resp.status_code == 500
            assert resp.json()["detail"] == "Error interno al acceder al archivo IFC."
        finally:
            self._cleanup()
            outside.unlink(missing_ok=True)

    # -----------------------------------------------------------------------
    # 16. Directory with storage_path name → 404
    # -----------------------------------------------------------------------

    def test_directory_as_storage_path_returns_404(self, monkeypatch, tmp_path):
        dirname = "some-dir.ifc"
        (tmp_path / dirname).mkdir()
        model = _make_fake_model(status="COMPLETED", storage_path=dirname)
        client = self._client(monkeypatch, tmp_path, model=model)
        try:
            resp = client.get(_FILE_URL.format(1))
            assert resp.status_code == 404
            assert resp.json()["detail"] == "Archivo IFC no disponible."
        finally:
            self._cleanup()

    # -----------------------------------------------------------------------
    # 17. Endpoint is read-only — no DB commit or flush
    # -----------------------------------------------------------------------

    def test_endpoint_does_not_commit_or_flush(self, monkeypatch, tmp_path):
        _write_ifc(tmp_path)
        model = _make_completed_model(tmp_path)
        fake_db = MagicMock()
        fake_db_called = {"commit": 0, "flush": 0}

        def _tracking_db():
            db = MagicMock()
            db.commit.side_effect = lambda: fake_db_called.__setitem__("commit", fake_db_called["commit"] + 1)
            db.flush.side_effect = lambda: fake_db_called.__setitem__("flush", fake_db_called["flush"] + 1)
            yield db

        monkeypatch.setattr("app.api.routes.models.get_ifc_model_for_owner",
                            lambda db, model_id, owner_id: model)

        from app.core.config import get_settings
        from types import SimpleNamespace

        def _fake_settings():
            return SimpleNamespace(ifc_storage_dir=tmp_path)

        app.dependency_overrides[get_current_user] = lambda: _make_fake_user()
        app.dependency_overrides[get_db] = _tracking_db
        app.dependency_overrides[get_settings] = _fake_settings
        try:
            client = TestClient(app)
            client.get(_FILE_URL.format(1))
            assert fake_db_called["commit"] == 0
            assert fake_db_called["flush"] == 0
        finally:
            self._cleanup()

    # -----------------------------------------------------------------------
    # 18. No auth token → 401
    # -----------------------------------------------------------------------

    def test_no_auth_token_returns_401(self, tmp_path):
        # No dependency overrides — real get_current_user rejects missing token
        client = TestClient(app)
        assert client.get(_FILE_URL.format(1)).status_code == 401

    # -----------------------------------------------------------------------
    # 19. Sensitive storage_path not leaked in error response body
    # -----------------------------------------------------------------------

    def test_sensitive_path_not_leaked_in_error(self, monkeypatch, tmp_path):
        sensitive_path = "/very/secret/path/model.ifc"
        model = _make_fake_model(status="COMPLETED", storage_path=sensitive_path)
        client = self._client(monkeypatch, tmp_path, model=model)
        try:
            resp = client.get(_FILE_URL.format(1))
            body = resp.text
            assert sensitive_path not in body
            assert "/very/secret" not in body
            assert str(tmp_path) not in body
        finally:
            self._cleanup()

    # -----------------------------------------------------------------------
    # 20. Windows absolute path (C:\secret\model.ifc) → 500
    # -----------------------------------------------------------------------

    def test_windows_absolute_path_returns_500(self, monkeypatch, tmp_path):
        model = _make_fake_model(status="COMPLETED", storage_path=r"C:\secret\model.ifc")
        client = self._client(monkeypatch, tmp_path, model=model)
        try:
            resp = client.get(_FILE_URL.format(1))
            assert resp.status_code == 500
            assert resp.json()["detail"] == "Error interno al acceder al archivo IFC."
            body = resp.text
            assert r"C:\secret" not in body
            assert model.storage_path not in body
        finally:
            self._cleanup()

    # -----------------------------------------------------------------------
    # 21. Windows relative with backslash (subdir\model.ifc) → 500
    # -----------------------------------------------------------------------

    def test_windows_backslash_subdir_returns_500(self, monkeypatch, tmp_path):
        model = _make_fake_model(status="COMPLETED", storage_path=r"subdir\model.ifc")
        client = self._client(monkeypatch, tmp_path, model=model)
        try:
            resp = client.get(_FILE_URL.format(1))
            assert resp.status_code == 500
            assert resp.json()["detail"] == "Error interno al acceder al archivo IFC."
        finally:
            self._cleanup()

    # -----------------------------------------------------------------------
    # 22. Windows drive-relative path (C:model.ifc) → 500
    # -----------------------------------------------------------------------

    def test_windows_drive_relative_returns_500(self, monkeypatch, tmp_path):
        model = _make_fake_model(status="COMPLETED", storage_path=r"C:model.ifc")
        client = self._client(monkeypatch, tmp_path, model=model)
        try:
            resp = client.get(_FILE_URL.format(1))
            assert resp.status_code == 500
            assert resp.json()["detail"] == "Error interno al acceder al archivo IFC."
        finally:
            self._cleanup()

    # -----------------------------------------------------------------------
    # 23. Windows UNC path (\\server\share\model.ifc) → 500
    # -----------------------------------------------------------------------

    def test_windows_unc_path_returns_500(self, monkeypatch, tmp_path):
        model = _make_fake_model(status="COMPLETED", storage_path=r"\\server\share\model.ifc")
        client = self._client(monkeypatch, tmp_path, model=model)
        try:
            resp = client.get(_FILE_URL.format(1))
            assert resp.status_code == 500
            assert resp.json()["detail"] == "Error interno al acceder al archivo IFC."
        finally:
            self._cleanup()
