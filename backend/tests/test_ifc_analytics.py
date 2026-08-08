"""
Tests for ifc_analytics service and:
  GET /api/v1/models/{model_id}/analytics
  GET /api/v1/models/{model_id}/elements

Service tests: MagicMock(spec=Session) — no PostgreSQL.
Endpoint tests: FastAPI TestClient + dependency_overrides — no PostgreSQL.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_user
from app.db.session import get_db
from app.main import app
from app.services.ifc_analytics import (
    ElementPageRow,
    ElementStoreyRow,
    IfcAnalyticsData,
    IfcAnalyticsQueryError,
    IfcElementPageData,
    StoreyCountRow,
    TypeCountRow,
    get_ifc_elements_page,
    get_ifc_model_analytics,
)
from app.services.ifc_queries import IfcModelQueryError


# ---------------------------------------------------------------------------
# Shared constants for patching
# ---------------------------------------------------------------------------

_ROUTES = "app.api.routes.models"
_ANALYTICS_FN = f"{_ROUTES}.get_ifc_model_analytics"
_ELEMENTS_FN = f"{_ROUTES}.get_ifc_elements_page"
_MODEL_QUERY = f"{_ROUTES}.get_ifc_model_for_owner"

_ANALYTICS_URL = "/api/v1/models/{model_id}/analytics"
_ELEMENTS_URL = "/api/v1/models/{model_id}/elements"


def _analytics_url(model_id: int = 1) -> str:
    return _ANALYTICS_URL.format(model_id=model_id)


def _elements_url(model_id: int = 1, **params) -> str:
    base = _ELEMENTS_URL.format(model_id=model_id)
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{base}?{qs}"
    return base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_fake_user(user_id: int = 42):
    return SimpleNamespace(id=user_id, email="u@test.com")


def _fake_db():
    yield MagicMock(spec=Session)


def _make_fake_model(**kwargs):
    now = _now()
    defaults = dict(
        id=1,
        owner_id=42,
        original_filename="model.ifc",
        storage_path="uuid.ifc",
        file_size_bytes=1024,
        sha256="a" * 64,
        status="COMPLETED",
        ifc_schema="IFC4",
        error_message=None,
        element_count=10,
        spatial_node_count=5,
        property_count=50,
        created_at=now,
        processing_started_at=now,
        processed_at=now,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _make_analytics_data(**kwargs) -> IfcAnalyticsData:
    defaults = dict(
        total_elements=10,
        total_spatial_nodes=5,
        total_properties=50,
        by_ifc_type=[TypeCountRow(ifc_type="IfcWall", count=5)],
        by_storey=[StoreyCountRow(global_id="S1", name="Ground", elevation=0.0, count=5)],
        without_storey_count=0,
    )
    defaults.update(kwargs)
    return IfcAnalyticsData(**defaults)


def _make_element_page(**kwargs) -> IfcElementPageData:
    defaults = dict(
        total=2,
        limit=50,
        offset=0,
        items=[
            ElementPageRow(
                ifc_entity_id=10,
                global_id="GID001",
                ifc_type="IfcWall",
                name="Wall-001",
                object_type=None,
                tag=None,
                predefined_type=None,
                type_ifc_type=None,
                type_name=None,
                storey=ElementStoreyRow(global_id="S1", name="Ground", elevation=0.0),
            ),
        ],
    )
    defaults.update(kwargs)
    return IfcElementPageData(**defaults)


# ---------------------------------------------------------------------------
# TestClient fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    app.dependency_overrides[get_current_user] = lambda: _make_fake_user()
    app.dependency_overrides[get_db] = _fake_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def client_no_auth():
    app.dependency_overrides.clear()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ===========================================================================
# SERVICE TESTS — get_ifc_model_analytics
# ===========================================================================

class TestGetIfcModelAnalytics:

    # ── 1. Totals propagated from IfcModel ──────────────────────────────────

    def test_totals_propagated_from_model(self):
        db = MagicMock(spec=Session)
        db.execute.return_value.all.return_value = []
        db.scalar.return_value = 0
        result = get_ifc_model_analytics(
            db, model_id=1,
            total_elements=99,
            total_spatial_nodes=12,
            total_properties=300,
        )
        assert result.total_elements == 99
        assert result.total_spatial_nodes == 12
        assert result.total_properties == 300

    # ── 2. by_ifc_type grouping ──────────────────────────────────────────────

    def test_by_ifc_type_grouping(self):
        fake_type_rows = [
            SimpleNamespace(ifc_type="IfcWall", count=5),
            SimpleNamespace(ifc_type="IfcDoor", count=2),
        ]
        db = MagicMock(spec=Session)
        db.execute.side_effect = [
            MagicMock(**{"all.return_value": fake_type_rows}),
            MagicMock(**{"all.return_value": []}),
        ]
        db.scalar.return_value = 0
        result = get_ifc_model_analytics(
            db, model_id=1, total_elements=7, total_spatial_nodes=0, total_properties=0
        )
        assert len(result.by_ifc_type) == 2
        assert result.by_ifc_type[0].ifc_type == "IfcWall"
        assert result.by_ifc_type[0].count == 5

    # ── 3. by_ifc_type ORDER BY in SQL (count DESC, type ASC) ───────────────

    def test_by_ifc_type_order_in_sql(self):
        db = MagicMock(spec=Session)
        db.execute.return_value.all.return_value = []
        db.scalar.return_value = 0
        get_ifc_model_analytics(
            db, model_id=7, total_elements=0, total_spatial_nodes=0, total_properties=0
        )
        stmt = db.execute.call_args_list[0][0][0]
        sql = str(stmt.compile(compile_kwargs={"literal_binds": True})).upper()
        assert "IFC_TYPE" in sql
        assert "COUNT" in sql
        assert "GROUP BY" in sql

    # ── 4. by_storey grouping ────────────────────────────────────────────────

    def test_by_storey_grouping(self):
        fake_type_rows = []
        fake_storey_rows = [
            SimpleNamespace(global_id="S1", name="Ground", elevation=0.0, count=3),
            SimpleNamespace(global_id="S2", name="First", elevation=3.5, count=2),
        ]
        db = MagicMock(spec=Session)
        db.execute.side_effect = [
            MagicMock(**{"all.return_value": fake_type_rows}),
            MagicMock(**{"all.return_value": fake_storey_rows}),
        ]
        db.scalar.return_value = 0
        result = get_ifc_model_analytics(
            db, model_id=1, total_elements=5, total_spatial_nodes=0, total_properties=0
        )
        assert len(result.by_storey) == 2
        assert result.by_storey[0].global_id == "S1"
        assert result.by_storey[0].elevation == 0.0

    # ── 5. by_storey join scoped by model_id ────────────────────────────────

    def test_by_storey_join_scoped_by_model_id(self):
        db = MagicMock(spec=Session)
        db.execute.return_value.all.return_value = []
        db.scalar.return_value = 0
        get_ifc_model_analytics(
            db, model_id=99, total_elements=0, total_spatial_nodes=0, total_properties=0
        )
        assert db.execute.call_count >= 2
        stmt = db.execute.call_args_list[1][0][0]
        sql = str(stmt.compile(compile_kwargs={"literal_binds": True})).upper()
        assert "SPATIAL_NODES" in sql
        assert "MODEL_ID" in sql

    # ── 6. elevation=0 is preserved (not treated as NULL/falsy) ─────────────

    def test_elevation_zero_preserved(self):
        fake_storey_rows = [
            SimpleNamespace(global_id="S1", name="Ground", elevation=0.0, count=1),
        ]
        db = MagicMock(spec=Session)
        db.execute.side_effect = [
            MagicMock(**{"all.return_value": []}),
            MagicMock(**{"all.return_value": fake_storey_rows}),
        ]
        db.scalar.return_value = 0
        result = get_ifc_model_analytics(
            db, model_id=1, total_elements=1, total_spatial_nodes=0, total_properties=0
        )
        assert result.by_storey[0].elevation == 0.0

    # ── 7. storey name null is allowed ──────────────────────────────────────

    def test_storey_name_null_allowed(self):
        fake_storey_rows = [
            SimpleNamespace(global_id="S1", name=None, elevation=1.0, count=2),
        ]
        db = MagicMock(spec=Session)
        db.execute.side_effect = [
            MagicMock(**{"all.return_value": []}),
            MagicMock(**{"all.return_value": fake_storey_rows}),
        ]
        db.scalar.return_value = 0
        result = get_ifc_model_analytics(
            db, model_id=1, total_elements=2, total_spatial_nodes=0, total_properties=0
        )
        assert result.by_storey[0].name is None

    # ── 8. without_storey_count ──────────────────────────────────────────────

    def test_without_storey_count(self):
        db = MagicMock(spec=Session)
        db.execute.return_value.all.return_value = []
        db.scalar.return_value = 7
        result = get_ifc_model_analytics(
            db, model_id=1, total_elements=7, total_spatial_nodes=0, total_properties=0
        )
        assert result.without_storey_count == 7

    # ── 9. model with no elements ────────────────────────────────────────────

    def test_model_with_no_elements(self):
        db = MagicMock(spec=Session)
        db.execute.return_value.all.return_value = []
        db.scalar.return_value = 0
        result = get_ifc_model_analytics(
            db, model_id=1, total_elements=0, total_spatial_nodes=0, total_properties=0
        )
        assert result.by_ifc_type == []
        assert result.by_storey == []
        assert result.without_storey_count == 0

    # ── 10. DB error → IfcAnalyticsQueryError (generic message) ─────────────

    def test_db_error_raises_analytics_query_error(self):
        secret = "pg_internal_connection_detail"
        db = MagicMock(spec=Session)
        db.execute.side_effect = Exception(secret)
        with pytest.raises(IfcAnalyticsQueryError) as exc_info:
            get_ifc_model_analytics(
                db, model_id=1, total_elements=0, total_spatial_nodes=0, total_properties=0
            )
        assert secret not in str(exc_info.value)

    # ── 11. No db.commit ─────────────────────────────────────────────────────

    def test_no_commit(self):
        db = MagicMock(spec=Session)
        db.execute.return_value.all.return_value = []
        db.scalar.return_value = 0
        get_ifc_model_analytics(
            db, model_id=1, total_elements=0, total_spatial_nodes=0, total_properties=0
        )
        db.commit.assert_not_called()

    # ── 12. No db.flush ──────────────────────────────────────────────────────

    def test_no_flush(self):
        db = MagicMock(spec=Session)
        db.execute.return_value.all.return_value = []
        db.scalar.return_value = 0
        get_ifc_model_analytics(
            db, model_id=1, total_elements=0, total_spatial_nodes=0, total_properties=0
        )
        db.flush.assert_not_called()


# ===========================================================================
# SERVICE TESTS — get_ifc_elements_page
# ===========================================================================

class TestGetIfcElementsPage:

    def _db(self, total=0, rows=None):
        db = MagicMock(spec=Session)
        db.scalar.return_value = total
        execute_result = MagicMock()
        execute_result.all.return_value = rows if rows is not None else []
        db.execute.return_value = execute_result
        return db

    def _make_row(self, ifc_entity_id=10, global_id="G1", ifc_type="IfcWall",
                  name="Wall", object_type=None, tag=None, predefined_type=None,
                  type_ifc_type=None, type_name=None, storey=None):
        element = SimpleNamespace(
            ifc_entity_id=ifc_entity_id,
            global_id=global_id,
            ifc_type=ifc_type,
            name=name,
            object_type=object_type,
            tag=tag,
            predefined_type=predefined_type,
            type_ifc_type=type_ifc_type,
            type_name=type_name,
        )
        return (element, storey)

    # ── 1. total independent of pagination ───────────────────────────────────

    def test_total_independent_of_pagination(self):
        db = self._db(total=100, rows=[])
        result = get_ifc_elements_page(db, model_id=1, limit=10, offset=90)
        assert result.total == 100

    # ── 2. limit/offset applied in SQL ──────────────────────────────────────

    def test_limit_offset_applied_in_sql(self):
        db = self._db(total=100, rows=[])
        get_ifc_elements_page(db, model_id=1, limit=25, offset=50)
        stmt = db.execute.call_args[0][0]
        sql = str(stmt.compile(compile_kwargs={"literal_binds": True})).upper()
        assert "25" in sql
        assert "50" in sql

    # ── 3. deterministic order in SQL ───────────────────────────────────────

    def test_deterministic_order_in_sql(self):
        db = self._db(total=0, rows=[])
        get_ifc_elements_page(db, model_id=1, limit=50, offset=0)
        stmt = db.execute.call_args[0][0]
        sql = str(stmt.compile(compile_kwargs={"literal_binds": True})).upper()
        assert "IFC_ENTITY_ID" in sql
        assert "ORDER BY" in sql

    # ── 4. storey nullable ───────────────────────────────────────────────────

    def test_storey_nullable(self):
        row = self._make_row(storey=None)
        db = self._db(total=1, rows=[row])
        result = get_ifc_elements_page(db, model_id=1, limit=50, offset=0)
        assert result.items[0].storey is None

    # ── 5. storey join scoped by model_id ────────────────────────────────────

    def test_storey_join_scoped_by_model_id(self):
        db = self._db(total=0, rows=[])
        get_ifc_elements_page(db, model_id=55, limit=50, offset=0)
        stmt = db.execute.call_args[0][0]
        sql = str(stmt.compile(compile_kwargs={"literal_binds": True})).upper()
        assert "SPATIAL_NODES" in sql
        assert "MODEL_ID" in sql

    # ── 6. expected fields in items ──────────────────────────────────────────

    def test_expected_fields_in_items(self):
        storey_ns = SimpleNamespace(global_id="S1", name="Ground", elevation=0.5)
        row = self._make_row(
            ifc_entity_id=99, global_id="GID999", ifc_type="IfcDoor",
            name="Door-1", object_type="External", tag="D1",
            predefined_type="DOOR", type_ifc_type="IfcDoorType",
            type_name="DT1", storey=storey_ns,
        )
        db = self._db(total=1, rows=[row])
        result = get_ifc_elements_page(db, model_id=1, limit=50, offset=0)
        item = result.items[0]
        assert item.ifc_entity_id == 99
        assert item.global_id == "GID999"
        assert item.ifc_type == "IfcDoor"
        assert item.name == "Door-1"
        assert item.object_type == "External"
        assert item.tag == "D1"
        assert item.predefined_type == "DOOR"
        assert item.type_ifc_type == "IfcDoorType"
        assert item.type_name == "DT1"
        assert item.storey is not None
        assert item.storey.global_id == "S1"
        assert item.storey.elevation == 0.5

    # ── 7. DB error → IfcAnalyticsQueryError (generic) ──────────────────────

    def test_db_error_raises_generic(self):
        secret = "pg_connection_secret_xyz"
        db = MagicMock(spec=Session)
        db.scalar.side_effect = Exception(secret)
        with pytest.raises(IfcAnalyticsQueryError) as exc_info:
            get_ifc_elements_page(db, model_id=1, limit=50, offset=0)
        assert secret not in str(exc_info.value)

    # ── 8. No commit ─────────────────────────────────────────────────────────

    def test_no_commit(self):
        db = self._db(total=0, rows=[])
        get_ifc_elements_page(db, model_id=1, limit=50, offset=0)
        db.commit.assert_not_called()

    # ── 9. No flush ──────────────────────────────────────────────────────────

    def test_no_flush(self):
        db = self._db(total=0, rows=[])
        get_ifc_elements_page(db, model_id=1, limit=50, offset=0)
        db.flush.assert_not_called()


# ===========================================================================
# ROUTE TESTS — GET /api/v1/models/{model_id}/analytics
# ===========================================================================

class TestGetModelAnalyticsEndpoint:

    # ── 1. No JWT → 401 ──────────────────────────────────────────────────────

    def test_no_jwt_401(self, client_no_auth):
        response = client_no_auth.get(_analytics_url())
        assert response.status_code == 401

    # ── 2. Owner + COMPLETED → 200 ───────────────────────────────────────────

    def test_owner_completed_200(self, client):
        model = _make_fake_model(status="COMPLETED")
        data = _make_analytics_data()
        with patch(_MODEL_QUERY, return_value=model), \
             patch(_ANALYTICS_FN, return_value=data):
            response = client.get(_analytics_url())
        assert response.status_code == 200
        body = response.json()
        assert body["total_elements"] == 10
        assert body["total_spatial_nodes"] == 5
        assert body["total_properties"] == 50
        assert len(body["by_ifc_type"]) == 1
        assert body["by_ifc_type"][0]["ifc_type"] == "IfcWall"
        assert len(body["by_storey"]) == 1
        assert body["without_storey_count"] == 0

    # ── 3. Wrong owner → 404 ─────────────────────────────────────────────────

    def test_wrong_owner_404(self, client):
        with patch(_MODEL_QUERY, return_value=None):
            response = client.get(_analytics_url())
        assert response.status_code == 404
        assert response.json()["detail"] == "Modelo IFC no encontrado."

    # ── 4. Model not found → 404 ─────────────────────────────────────────────

    def test_model_not_found_404(self, client):
        with patch(_MODEL_QUERY, return_value=None):
            response = client.get(_analytics_url(model_id=999))
        assert response.status_code == 404

    # ── 5. PENDING → 409 ─────────────────────────────────────────────────────

    def test_pending_409(self, client):
        model = _make_fake_model(status="PENDING")
        with patch(_MODEL_QUERY, return_value=model):
            response = client.get(_analytics_url())
        assert response.status_code == 409
        assert response.json()["detail"] == "La información analítica del modelo no está disponible."

    # ── 6. PROCESSING → 409 ──────────────────────────────────────────────────

    def test_processing_409(self, client):
        model = _make_fake_model(status="PROCESSING")
        with patch(_MODEL_QUERY, return_value=model):
            response = client.get(_analytics_url())
        assert response.status_code == 409

    # ── 7. FAILED → 409 ──────────────────────────────────────────────────────

    def test_failed_409(self, client):
        model = _make_fake_model(status="FAILED")
        with patch(_MODEL_QUERY, return_value=model):
            response = client.get(_analytics_url())
        assert response.status_code == 409

    # ── 8. IfcModelQueryError → 500 ──────────────────────────────────────────

    def test_model_query_error_500(self, client):
        with patch(_MODEL_QUERY, side_effect=IfcModelQueryError("db gone")):
            response = client.get(_analytics_url())
        assert response.status_code == 500
        assert response.json()["detail"] == "Error interno al consultar el modelo."

    # ── 9. IfcAnalyticsQueryError → 500 ──────────────────────────────────────

    def test_analytics_query_error_500(self, client):
        model = _make_fake_model(status="COMPLETED")
        with patch(_MODEL_QUERY, return_value=model), \
             patch(_ANALYTICS_FN, side_effect=IfcAnalyticsQueryError("timeout")):
            response = client.get(_analytics_url())
        assert response.status_code == 500
        assert response.json()["detail"] == "Error interno al consultar la información analítica."

    # ── 10. Analytics NOT queried when status guard fires ─────────────────────

    def test_analytics_not_queried_on_non_completed(self, client):
        for bad_status in ("PENDING", "PROCESSING", "FAILED"):
            model = _make_fake_model(status=bad_status)
            with patch(_MODEL_QUERY, return_value=model), \
                 patch(_ANALYTICS_FN) as mock_analytics:
                client.get(_analytics_url())
            mock_analytics.assert_not_called()

    # ── 11. Analytics NOT queried when ownership fails ────────────────────────

    def test_analytics_not_queried_on_ownership_fail(self, client):
        with patch(_MODEL_QUERY, return_value=None), \
             patch(_ANALYTICS_FN) as mock_analytics:
            client.get(_analytics_url())
        mock_analytics.assert_not_called()


# ===========================================================================
# ROUTE TESTS — GET /api/v1/models/{model_id}/elements
# ===========================================================================

class TestListModelElementsEndpoint:

    # ── 1. No JWT → 401 ──────────────────────────────────────────────────────

    def test_no_jwt_401(self, client_no_auth):
        response = client_no_auth.get(_elements_url())
        assert response.status_code == 401

    # ── 2. Owner + COMPLETED → 200 ───────────────────────────────────────────

    def test_owner_completed_200(self, client):
        model = _make_fake_model(status="COMPLETED")
        page = _make_element_page()
        with patch(_MODEL_QUERY, return_value=model), \
             patch(_ELEMENTS_FN, return_value=page):
            response = client.get(_elements_url())
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 2
        assert body["limit"] == 50
        assert body["offset"] == 0
        assert len(body["items"]) == 1
        item = body["items"][0]
        assert item["ifc_entity_id"] == 10
        assert item["global_id"] == "GID001"
        assert item["storey"]["global_id"] == "S1"

    # ── 3. Wrong owner → 404 ─────────────────────────────────────────────────

    def test_wrong_owner_404(self, client):
        with patch(_MODEL_QUERY, return_value=None):
            response = client.get(_elements_url())
        assert response.status_code == 404
        assert response.json()["detail"] == "Modelo IFC no encontrado."

    # ── 4. Model not found → 404 ─────────────────────────────────────────────

    def test_model_not_found_404(self, client):
        with patch(_MODEL_QUERY, return_value=None):
            response = client.get(_elements_url(model_id=999))
        assert response.status_code == 404

    # ── 5. Non-COMPLETED → 409 ───────────────────────────────────────────────

    def test_non_completed_409(self, client):
        for bad_status in ("PENDING", "PROCESSING", "FAILED"):
            model = _make_fake_model(status=bad_status)
            with patch(_MODEL_QUERY, return_value=model):
                response = client.get(_elements_url())
            assert response.status_code == 409

    # ── 6. limit=0 → 422 ─────────────────────────────────────────────────────

    def test_limit_zero_422(self, client):
        response = client.get(_elements_url(limit=0))
        assert response.status_code == 422

    # ── 7. limit=101 → 422 ───────────────────────────────────────────────────

    def test_limit_101_422(self, client):
        response = client.get(_elements_url(limit=101))
        assert response.status_code == 422

    # ── 8. offset=-1 → 422 ───────────────────────────────────────────────────

    def test_offset_negative_422(self, client):
        response = client.get(_elements_url(offset=-1))
        assert response.status_code == 422

    # ── 9. IfcAnalyticsQueryError → 500 ──────────────────────────────────────

    def test_analytics_query_error_500(self, client):
        model = _make_fake_model(status="COMPLETED")
        with patch(_MODEL_QUERY, return_value=model), \
             patch(_ELEMENTS_FN, side_effect=IfcAnalyticsQueryError("timeout")):
            response = client.get(_elements_url())
        assert response.status_code == 500
        assert response.json()["detail"] == "Error interno al consultar la información analítica."

    # ── 10. Elements NOT queried when status guard fires ──────────────────────

    def test_elements_not_queried_on_non_completed(self, client):
        for bad_status in ("PENDING", "PROCESSING", "FAILED"):
            model = _make_fake_model(status=bad_status)
            with patch(_MODEL_QUERY, return_value=model), \
                 patch(_ELEMENTS_FN) as mock_elements:
                client.get(_elements_url())
            mock_elements.assert_not_called()

    # ── 11. Elements NOT queried when ownership fails ─────────────────────────

    def test_elements_not_queried_on_ownership_fail(self, client):
        with patch(_MODEL_QUERY, return_value=None), \
             patch(_ELEMENTS_FN) as mock_elements:
            client.get(_elements_url())
        mock_elements.assert_not_called()

    # ── 12. storey null in item → null in response ────────────────────────────

    def test_storey_null_in_response(self, client):
        model = _make_fake_model(status="COMPLETED")
        page = IfcElementPageData(
            total=1, limit=50, offset=0,
            items=[
                ElementPageRow(
                    ifc_entity_id=1, global_id="G1", ifc_type="IfcWall",
                    name=None, object_type=None, tag=None, predefined_type=None,
                    type_ifc_type=None, type_name=None, storey=None,
                )
            ],
        )
        with patch(_MODEL_QUERY, return_value=model), \
             patch(_ELEMENTS_FN, return_value=page):
            response = client.get(_elements_url())
        assert response.status_code == 200
        assert response.json()["items"][0]["storey"] is None

    # ── 13. Response items do NOT expose forbidden fields ─────────────────────

    def test_response_items_no_forbidden_fields(self, client):
        model = _make_fake_model(status="COMPLETED")
        page = _make_element_page()
        with patch(_MODEL_QUERY, return_value=model), \
             patch(_ELEMENTS_FN, return_value=page):
            response = client.get(_elements_url())
        item = response.json()["items"][0]
        forbidden = {
            "id", "model_id", "resolved_storey_id", "direct_spatial_node_id",
            "parent_element_id", "owner_id", "storage_path", "created_at",
        }
        assert not forbidden.intersection(item.keys())

    # ── 14. IfcModelQueryError → 500 ─────────────────────────────────────────

    def test_model_query_error_500(self, client):
        with patch(_MODEL_QUERY, side_effect=IfcModelQueryError("gone")):
            response = client.get(_elements_url())
        assert response.status_code == 500
        assert response.json()["detail"] == "Error interno al consultar el modelo."
