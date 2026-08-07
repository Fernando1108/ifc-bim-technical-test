"""
Tests for ifc_element_queries service and GET /api/v1/models/{model_id}/elements/{global_id}.

Service tests: MagicMock(spec=Session) — no PostgreSQL.
Endpoint tests: FastAPI TestClient + dependency_overrides — no PostgreSQL.
"""
from __future__ import annotations

import urllib.parse
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_user
from app.db.session import get_db
from app.main import app
from app.models.element import IfcElement
from app.models.element_property import ElementProperty
from app.models.spatial_node import SpatialNode
from app.services.ifc_element_queries import (
    IfcElementDetailData,
    IfcElementQueryError,
    get_ifc_element_detail,
)
from app.services.ifc_queries import IfcModelQueryError


# ---------------------------------------------------------------------------
# Helpers — shared fixtures
# ---------------------------------------------------------------------------

_MODEL_ROUTE = "app.api.routes.models"
_ELEM_QUERIES = f"{_MODEL_ROUTE}.get_ifc_element_detail"
_MODEL_QUERIES = f"{_MODEL_ROUTE}.get_ifc_model_for_owner"

_ELEM_URL = "/api/v1/models/{model_id}/elements/{global_id}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_fake_user(user_id: int = 42):
    return SimpleNamespace(id=user_id, email="u@test.com", is_active=True)


def _fake_db():
    yield MagicMock(spec=Session)


def _make_fake_model(**kwargs):
    now = _now()
    defaults = dict(
        id=1,
        owner_id=42,
        original_filename="model.ifc",
        file_size_bytes=100,
        sha256="a" * 64,
        status="COMPLETED",
        ifc_schema="IFC4",
        error_message=None,
        created_at=now,
        processing_started_at=now,
        processed_at=now,
        storage_path="uuid.ifc",
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _make_fake_element(**kwargs):
    defaults = dict(
        id=10,
        model_id=1,
        ifc_entity_id=200,
        global_id="abc123",
        ifc_type="IfcWall",
        name="Wall-001",
        description="A wall",
        object_type="LoadBearing",
        tag="W1",
        predefined_type="SOLIDWALL",
        type_global_id="type001",
        type_ifc_type="IfcWallType",
        type_name="WallType-001",
        direct_spatial_node_id=5,
        resolved_storey_id=6,
        parent_element_id=None,
        created_at=_now(),
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _make_fake_spatial(**kwargs):
    defaults = dict(
        id=5,
        model_id=1,
        ifc_entity_id=50,
        global_id="space001",
        ifc_type="IfcSpace",
        name="Room 101",
        description=None,
        long_name="Office 101",
        elevation=0.0,
        parent_id=None,
        created_at=_now(),
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _make_fake_storey(**kwargs):
    defaults = dict(
        id=6,
        model_id=1,
        ifc_entity_id=60,
        global_id="storey001",
        ifc_type="IfcBuildingStorey",
        name="Ground Floor",
        description=None,
        long_name="GF",
        elevation=0.0,
        parent_id=None,
        created_at=_now(),
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _make_fake_property(**kwargs):
    defaults = dict(
        id=100,
        element_id=10,
        group_type="PSET",
        group_name="Pset_WallCommon",
        property_name="IsExternal",
        value_kind="BOOLEAN",
        ifc_value_type="IfcBoolean",
        value_text=None,
        value_number=None,
        value_boolean=True,
        unit=None,
        created_at=_now(),
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _make_detail(element=None, direct_spatial=None, resolved_storey=None, properties=None):
    return IfcElementDetailData(
        element=element or _make_fake_element(),
        direct_spatial=direct_spatial,
        resolved_storey=resolved_storey,
        properties=properties or [],
    )


# ---------------------------------------------------------------------------
# TestClient shared fixture
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


def _url(model_id: int = 1, global_id: str = "abc123") -> str:
    encoded = urllib.parse.quote(global_id, safe="")
    return _ELEM_URL.format(model_id=model_id, global_id=encoded)


# ===========================================================================
# SERVICE TESTS — get_ifc_element_detail
# ===========================================================================

class TestGetIfcElementDetail:

    def _db(self, row=None, props=None):
        """Build a MagicMock Session for the standard case."""
        db = MagicMock(spec=Session)
        db.execute.return_value.first.return_value = row
        db.scalars.return_value.all.return_value = props if props is not None else []
        return db

    # ── 1. Query includes model_id in WHERE ──────────────────────────────────

    def test_filters_by_model_id(self):
        db = self._db(row=None)
        get_ifc_element_detail(db, model_id=77, global_id="X")
        stmt = db.execute.call_args[0][0]
        sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "77" in sql

    # ── 2. Query includes global_id in WHERE ─────────────────────────────────

    def test_filters_by_global_id(self):
        db = self._db(row=None)
        get_ifc_element_detail(db, model_id=1, global_id="UNIQUE_GLOBAL_ID_XYZ")
        stmt = db.execute.call_args[0][0]
        sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "UNIQUE_GLOBAL_ID_XYZ" in sql

    # ── 3. Element found → returns IfcElementDetailData ──────────────────────

    def test_element_found_returns_data(self):
        element = _make_fake_element()
        db = self._db(row=(element, None, None))
        result = get_ifc_element_detail(db, model_id=1, global_id="abc")
        assert result is not None
        assert isinstance(result, IfcElementDetailData)
        assert result.element is element

    # ── 4. Element not found → returns None ──────────────────────────────────

    def test_element_not_found_returns_none(self):
        db = self._db(row=None)
        result = get_ifc_element_detail(db, model_id=1, global_id="missing")
        assert result is None

    # ── 5. direct_spatial present in result ──────────────────────────────────

    def test_direct_spatial_present(self):
        element = _make_fake_element()
        spatial = _make_fake_spatial()
        db = self._db(row=(element, spatial, None))
        result = get_ifc_element_detail(db, model_id=1, global_id="abc")
        assert result is not None
        assert result.direct_spatial is spatial

    # ── 6. direct_spatial may be None ────────────────────────────────────────

    def test_direct_spatial_none_allowed(self):
        element = _make_fake_element(direct_spatial_node_id=None)
        db = self._db(row=(element, None, None))
        result = get_ifc_element_detail(db, model_id=1, global_id="abc")
        assert result is not None
        assert result.direct_spatial is None

    # ── 7. resolved_storey present in result ─────────────────────────────────

    def test_resolved_storey_present(self):
        element = _make_fake_element()
        storey = _make_fake_storey()
        db = self._db(row=(element, None, storey))
        result = get_ifc_element_detail(db, model_id=1, global_id="abc")
        assert result is not None
        assert result.resolved_storey is storey

    # ── 8. resolved_storey may be None ───────────────────────────────────────

    def test_resolved_storey_none_allowed(self):
        element = _make_fake_element(resolved_storey_id=None)
        db = self._db(row=(element, None, None))
        result = get_ifc_element_detail(db, model_id=1, global_id="abc")
        assert result is not None
        assert result.resolved_storey is None

    # ── 9. Properties NOT queried when element not found ─────────────────────

    def test_properties_not_queried_when_element_absent(self):
        db = self._db(row=None)
        get_ifc_element_detail(db, model_id=1, global_id="missing")
        db.scalars.assert_not_called()

    # ── 10. Returns PSET properties ──────────────────────────────────────────

    def test_returns_pset_properties(self):
        element = _make_fake_element()
        pset_prop = _make_fake_property(group_type="PSET")
        db = self._db(row=(element, None, None), props=[pset_prop])
        result = get_ifc_element_detail(db, model_id=1, global_id="abc")
        assert result is not None
        assert any(p.group_type == "PSET" for p in result.properties)

    # ── 11. Returns QTO properties ───────────────────────────────────────────

    def test_returns_qto_properties(self):
        element = _make_fake_element()
        qto_prop = _make_fake_property(group_type="QTO", group_name="Qto_WallBaseQuantities")
        db = self._db(row=(element, None, None), props=[qto_prop])
        result = get_ifc_element_detail(db, model_id=1, global_id="abc")
        assert result is not None
        assert any(p.group_type == "QTO" for p in result.properties)

    # ── 12. Properties ordered deterministically (inspect SQL) ───────────────

    def test_properties_ordered_deterministically(self):
        element = _make_fake_element()
        db = self._db(row=(element, None, None), props=[])
        get_ifc_element_detail(db, model_id=1, global_id="abc")

        props_stmt = db.scalars.call_args[0][0]
        sql = str(props_stmt.compile(compile_kwargs={"literal_binds": True})).upper()
        assert "GROUP_TYPE" in sql
        assert "GROUP_NAME" in sql
        assert "PROPERTY_NAME" in sql

    # ── 13. Main query error → IfcElementQueryError ──────────────────────────

    def test_main_query_error_raises(self):
        db = MagicMock(spec=Session)
        db.execute.side_effect = Exception("connection lost")
        with pytest.raises(IfcElementQueryError):
            get_ifc_element_detail(db, model_id=1, global_id="abc")

    # ── 14. Properties query error → IfcElementQueryError ────────────────────

    def test_properties_query_error_raises(self):
        element = _make_fake_element()
        db = MagicMock(spec=Session)
        db.execute.return_value.first.return_value = (element, None, None)
        db.scalars.side_effect = Exception("timeout")
        with pytest.raises(IfcElementQueryError):
            get_ifc_element_detail(db, model_id=1, global_id="abc")

    # ── 15. No db.commit ─────────────────────────────────────────────────────

    def test_no_commit(self):
        db = self._db(row=None)
        get_ifc_element_detail(db, model_id=1, global_id="abc")
        db.commit.assert_not_called()

    # ── 16. No db.flush ──────────────────────────────────────────────────────

    def test_no_flush(self):
        db = self._db(row=None)
        get_ifc_element_detail(db, model_id=1, global_id="abc")
        db.flush.assert_not_called()

    # ── 17. direct_spatial join is scoped to same model_id ───────────────────

    def test_direct_spatial_join_scoped_to_model_id(self):
        """The JOIN ON clause for direct_spatial must carry a model_id condition."""
        db = self._db(row=None)
        get_ifc_element_detail(db, model_id=55, global_id="X")
        stmt = db.execute.call_args[0][0]
        sql = str(stmt.compile(compile_kwargs={"literal_binds": True})).upper()
        # SQLAlchemy renders aliased joins as SPATIAL_NODES_1.MODEL_ID = ELEMENTS.MODEL_ID
        # Verify MODEL_ID appears inside the JOIN ON clauses (not just WHERE).
        # The first aliased table carries the model_id equality for direct_spatial.
        assert "SPATIAL_NODES_1.MODEL_ID" in sql

    # ── 18. resolved_storey join is scoped to same model_id ──────────────────

    def test_resolved_storey_join_scoped_to_model_id(self):
        """The JOIN ON clause for resolved_storey must carry a model_id condition."""
        db = self._db(row=None)
        get_ifc_element_detail(db, model_id=88, global_id="Y")
        stmt = db.execute.call_args[0][0]
        sql = str(stmt.compile(compile_kwargs={"literal_binds": True})).upper()
        # The second aliased table carries the model_id equality for resolved_storey.
        assert "SPATIAL_NODES_2.MODEL_ID" in sql

    # ── 19. IfcElementQueryError does not expose internal DB message ──────────

    def test_main_query_error_message_is_generic(self):
        secret_msg = "pg_secret_connection_string_xyz"
        db = MagicMock(spec=Session)
        db.execute.side_effect = Exception(secret_msg)
        with pytest.raises(IfcElementQueryError) as exc_info:
            get_ifc_element_detail(db, model_id=1, global_id="abc")
        assert secret_msg not in str(exc_info.value)

    # ── 20. Properties query error message is generic ────────────────────────

    def test_properties_query_error_message_is_generic(self):
        secret_msg = "column_name_leak_internal"
        element = _make_fake_element()
        db = MagicMock(spec=Session)
        db.execute.return_value.first.return_value = (element, None, None)
        db.scalars.side_effect = Exception(secret_msg)
        with pytest.raises(IfcElementQueryError) as exc_info:
            get_ifc_element_detail(db, model_id=1, global_id="abc")
        assert secret_msg not in str(exc_info.value)


# ===========================================================================
# ENDPOINT TESTS — GET /api/v1/models/{model_id}/elements/{global_id}
# ===========================================================================

class TestGetElementDetailEndpoint:

    # ── 1. 200 for authenticated, completed model, existing element ──────────

    def test_200_authenticated_completed_element(self, client):
        model = _make_fake_model(status="COMPLETED")
        detail = _make_detail(properties=[])
        with patch(_MODEL_QUERIES, return_value=model), \
             patch(_ELEM_QUERIES, return_value=detail):
            response = client.get(_url())
        assert response.status_code == 200

    # ── 2. Response contains expected element fields ─────────────────────────

    def test_response_contains_element_fields(self, client):
        element = _make_fake_element(
            ifc_entity_id=999,
            global_id="GID001",
            ifc_type="IfcDoor",
            name="Door-A",
            description="Main entrance",
            object_type="External",
            tag="D1",
            predefined_type="DOOR",
            type_global_id="TGID001",
            type_ifc_type="IfcDoorType",
            type_name="DoorType-A",
        )
        model = _make_fake_model()
        detail = _make_detail(element=element)
        with patch(_MODEL_QUERIES, return_value=model), \
             patch(_ELEM_QUERIES, return_value=detail):
            response = client.get(_url())
        body = response.json()
        assert body["ifc_entity_id"] == 999
        assert body["global_id"] == "GID001"
        assert body["ifc_type"] == "IfcDoor"
        assert body["name"] == "Door-A"
        assert body["description"] == "Main entrance"
        assert body["object_type"] == "External"
        assert body["tag"] == "D1"
        assert body["predefined_type"] == "DOOR"
        assert body["type_global_id"] == "TGID001"
        assert body["type_ifc_type"] == "IfcDoorType"
        assert body["type_name"] == "DoorType-A"

    # ── 3. direct_spatial serialized ─────────────────────────────────────────

    def test_direct_spatial_serialized(self, client):
        spatial = _make_fake_spatial(
            ifc_entity_id=50, global_id="SP001", ifc_type="IfcSpace",
            name="Room A", description="Desc", long_name="Long Name", elevation=3.5,
        )
        model = _make_fake_model()
        detail = _make_detail(direct_spatial=spatial)
        with patch(_MODEL_QUERIES, return_value=model), \
             patch(_ELEM_QUERIES, return_value=detail):
            response = client.get(_url())
        body = response.json()
        ds = body["direct_spatial"]
        assert ds is not None
        assert ds["ifc_entity_id"] == 50
        assert ds["global_id"] == "SP001"
        assert ds["ifc_type"] == "IfcSpace"
        assert ds["name"] == "Room A"
        assert ds["description"] == "Desc"
        assert ds["long_name"] == "Long Name"
        assert ds["elevation"] == 3.5

    # ── 4. resolved_storey serialized ────────────────────────────────────────

    def test_resolved_storey_serialized(self, client):
        storey = _make_fake_storey(
            ifc_entity_id=60, global_id="ST001", ifc_type="IfcBuildingStorey",
            name="Level 1", description=None, long_name="L1", elevation=4.0,
        )
        model = _make_fake_model()
        detail = _make_detail(resolved_storey=storey)
        with patch(_MODEL_QUERIES, return_value=model), \
             patch(_ELEM_QUERIES, return_value=detail):
            response = client.get(_url())
        body = response.json()
        rs = body["resolved_storey"]
        assert rs is not None
        assert rs["ifc_entity_id"] == 60
        assert rs["global_id"] == "ST001"
        assert rs["elevation"] == 4.0

    # ── 5. direct_spatial null → null in response ─────────────────────────────

    def test_direct_spatial_null_allowed(self, client):
        model = _make_fake_model()
        detail = _make_detail(direct_spatial=None)
        with patch(_MODEL_QUERIES, return_value=model), \
             patch(_ELEM_QUERIES, return_value=detail):
            response = client.get(_url())
        assert response.json()["direct_spatial"] is None

    # ── 6. resolved_storey null → null in response ────────────────────────────

    def test_resolved_storey_null_allowed(self, client):
        model = _make_fake_model()
        detail = _make_detail(resolved_storey=None)
        with patch(_MODEL_QUERIES, return_value=model), \
             patch(_ELEM_QUERIES, return_value=detail):
            response = client.get(_url())
        assert response.json()["resolved_storey"] is None

    # ── 7. TEXT property serialized ──────────────────────────────────────────

    def test_text_property_serialized(self, client):
        prop = _make_fake_property(
            value_kind="TEXT", ifc_value_type="IfcLabel",
            value_text="Concrete", value_number=None, value_boolean=None,
        )
        model = _make_fake_model()
        detail = _make_detail(properties=[prop])
        with patch(_MODEL_QUERIES, return_value=model), \
             patch(_ELEM_QUERIES, return_value=detail):
            response = client.get(_url())
        p = response.json()["properties"][0]
        assert p["value_kind"] == "TEXT"
        assert p["value_text"] == "Concrete"
        assert p["value_number"] is None
        assert p["value_boolean"] is None

    # ── 8. NUMBER property serialized ────────────────────────────────────────

    def test_number_property_serialized(self, client):
        prop = _make_fake_property(
            value_kind="NUMBER", ifc_value_type="IfcReal",
            value_text=None, value_number=2.5, value_boolean=None,
            unit="m",
        )
        model = _make_fake_model()
        detail = _make_detail(properties=[prop])
        with patch(_MODEL_QUERIES, return_value=model), \
             patch(_ELEM_QUERIES, return_value=detail):
            response = client.get(_url())
        p = response.json()["properties"][0]
        assert p["value_kind"] == "NUMBER"
        assert p["value_number"] == 2.5
        assert p["unit"] == "m"

    # ── 9. BOOLEAN property serialized ───────────────────────────────────────

    def test_boolean_property_serialized(self, client):
        prop = _make_fake_property(
            value_kind="BOOLEAN", ifc_value_type="IfcBoolean",
            value_text=None, value_number=None, value_boolean=False,
        )
        model = _make_fake_model()
        detail = _make_detail(properties=[prop])
        with patch(_MODEL_QUERIES, return_value=model), \
             patch(_ELEM_QUERIES, return_value=detail):
            response = client.get(_url())
        p = response.json()["properties"][0]
        assert p["value_kind"] == "BOOLEAN"
        assert p["value_boolean"] is False

    # ── 10. NULL property serialized ─────────────────────────────────────────

    def test_null_property_serialized(self, client):
        prop = _make_fake_property(
            value_kind="NULL", ifc_value_type=None,
            value_text=None, value_number=None, value_boolean=None,
        )
        model = _make_fake_model()
        detail = _make_detail(properties=[prop])
        with patch(_MODEL_QUERIES, return_value=model), \
             patch(_ELEM_QUERIES, return_value=detail):
            response = client.get(_url())
        p = response.json()["properties"][0]
        assert p["value_kind"] == "NULL"
        assert p["value_text"] is None
        assert p["value_number"] is None
        assert p["value_boolean"] is None

    # ── 11. PSET in properties list ───────────────────────────────────────────

    def test_pset_property_present(self, client):
        pset = _make_fake_property(group_type="PSET", group_name="Pset_WallCommon")
        model = _make_fake_model()
        detail = _make_detail(properties=[pset])
        with patch(_MODEL_QUERIES, return_value=model), \
             patch(_ELEM_QUERIES, return_value=detail):
            response = client.get(_url())
        props = response.json()["properties"]
        assert any(p["group_type"] == "PSET" for p in props)

    # ── 12. QTO in properties list ───────────────────────────────────────────

    def test_qto_property_present(self, client):
        qto = _make_fake_property(
            group_type="QTO", group_name="Qto_WallBaseQuantities",
            property_name="Length", value_kind="NUMBER",
            value_text=None, value_number=5.0, value_boolean=None,
        )
        model = _make_fake_model()
        detail = _make_detail(properties=[qto])
        with patch(_MODEL_QUERIES, return_value=model), \
             patch(_ELEM_QUERIES, return_value=detail):
            response = client.get(_url())
        props = response.json()["properties"]
        assert any(p["group_type"] == "QTO" for p in props)

    # ── 13. Non-existent model → 404 ─────────────────────────────────────────

    def test_model_not_found_404(self, client):
        with patch(_MODEL_QUERIES, return_value=None):
            response = client.get(_url(model_id=999))
        assert response.status_code == 404

    # ── 14. Model of another owner → same 404 ────────────────────────────────

    def test_model_other_owner_404(self, client):
        # get_ifc_model_for_owner returns None for wrong owner (IDOR guard)
        with patch(_MODEL_QUERIES, return_value=None):
            response = client.get(_url(model_id=1))
        assert response.status_code == 404

    # ── 15. Both 404s have the same detail message ────────────────────────────

    def test_both_404s_have_same_detail(self, client):
        with patch(_MODEL_QUERIES, return_value=None):
            r1 = client.get(_url(model_id=999))
            r2 = client.get(_url(model_id=1))
        assert r1.json()["detail"] == "Modelo IFC no encontrado."
        assert r2.json()["detail"] == "Modelo IFC no encontrado."

    # ── 16. PENDING model → 409 ──────────────────────────────────────────────

    def test_pending_model_409(self, client):
        model = _make_fake_model(status="PENDING")
        with patch(_MODEL_QUERIES, return_value=model):
            response = client.get(_url())
        assert response.status_code == 409
        assert response.json()["detail"] == "La información BIM del modelo no está disponible."

    # ── 17. PROCESSING model → 409 ───────────────────────────────────────────

    def test_processing_model_409(self, client):
        model = _make_fake_model(status="PROCESSING")
        with patch(_MODEL_QUERIES, return_value=model):
            response = client.get(_url())
        assert response.status_code == 409

    # ── 18. FAILED model → 409 ───────────────────────────────────────────────

    def test_failed_model_409(self, client):
        model = _make_fake_model(status="FAILED")
        with patch(_MODEL_QUERIES, return_value=model):
            response = client.get(_url())
        assert response.status_code == 409

    # ── 19. Non-COMPLETED statuses do NOT call element query ─────────────────

    def test_non_completed_statuses_do_not_call_element_query(self, client):
        for bad_status in ("PENDING", "PROCESSING", "FAILED"):
            model = _make_fake_model(status=bad_status)
            with patch(_MODEL_QUERIES, return_value=model), \
                 patch(_ELEM_QUERIES) as mock_elem:
                client.get(_url())
            mock_elem.assert_not_called()

    # ── 20. Element absent in authorized COMPLETED model → 404 ───────────────

    def test_element_not_found_404(self, client):
        model = _make_fake_model(status="COMPLETED")
        with patch(_MODEL_QUERIES, return_value=model), \
             patch(_ELEM_QUERIES, return_value=None):
            response = client.get(_url())
        assert response.status_code == 404
        assert response.json()["detail"] == "Elemento IFC no encontrado."

    # ── 21. IfcModelQueryError → 500 ─────────────────────────────────────────

    def test_model_query_error_500(self, client):
        with patch(_MODEL_QUERIES, side_effect=IfcModelQueryError("db gone")):
            response = client.get(_url())
        assert response.status_code == 500
        assert response.json()["detail"] == "Error interno al consultar el modelo."

    # ── 22. IfcElementQueryError → 500 ───────────────────────────────────────

    def test_element_query_error_500(self, client):
        model = _make_fake_model(status="COMPLETED")
        with patch(_MODEL_QUERIES, return_value=model), \
             patch(_ELEM_QUERIES, side_effect=IfcElementQueryError("timeout")):
            response = client.get(_url())
        assert response.status_code == 500
        assert response.json()["detail"] == "Error interno al consultar el elemento IFC."

    # ── 23. No JWT → 401 ─────────────────────────────────────────────────────

    def test_no_jwt_401(self, client_no_auth):
        response = client_no_auth.get(_url())
        assert response.status_code == 401

    # ── 24. Endpoint is read-only — no commit or flush ────────────────────────

    def test_endpoint_is_read_only(self, client):
        db_mock = MagicMock(spec=Session)

        def _override_db():
            yield db_mock

        app.dependency_overrides[get_db] = _override_db
        model = _make_fake_model(status="COMPLETED")
        detail = _make_detail()
        try:
            with patch(_MODEL_QUERIES, return_value=model), \
                 patch(_ELEM_QUERIES, return_value=detail):
                client.get(_url())
        finally:
            app.dependency_overrides[get_db] = _fake_db

        db_mock.commit.assert_not_called()
        db_mock.flush.assert_not_called()

    # ── 25. Response does NOT expose internal DB ids ──────────────────────────

    def test_response_does_not_contain_internal_fields(self, client):
        model = _make_fake_model()
        detail = _make_detail()
        with patch(_MODEL_QUERIES, return_value=model), \
             patch(_ELEM_QUERIES, return_value=detail):
            response = client.get(_url())
        body = response.json()
        forbidden = {
            "owner_id", "storage_path", "model_id",
            "parent_element_id", "direct_spatial_node_id",
            "resolved_storey_id", "element_id",
        }
        assert not forbidden.intersection(body.keys())

    # ── 26. direct_spatial does NOT expose DB id ──────────────────────────────

    def test_direct_spatial_no_db_id(self, client):
        spatial = _make_fake_spatial()
        model = _make_fake_model()
        detail = _make_detail(direct_spatial=spatial)
        with patch(_MODEL_QUERIES, return_value=model), \
             patch(_ELEM_QUERIES, return_value=detail):
            response = client.get(_url())
        ds = response.json()["direct_spatial"]
        assert ds is not None
        assert "id" not in ds
        assert "model_id" not in ds
        assert "parent_id" not in ds
        assert "created_at" not in ds

    # ── 27. resolved_storey does NOT expose DB id ─────────────────────────────

    def test_resolved_storey_no_db_id(self, client):
        storey = _make_fake_storey()
        model = _make_fake_model()
        detail = _make_detail(resolved_storey=storey)
        with patch(_MODEL_QUERIES, return_value=model), \
             patch(_ELEM_QUERIES, return_value=detail):
            response = client.get(_url())
        rs = response.json()["resolved_storey"]
        assert rs is not None
        assert "id" not in rs
        assert "model_id" not in rs

    # ── 28. Properties do NOT expose DB ids ───────────────────────────────────

    def test_properties_no_db_id(self, client):
        prop = _make_fake_property()
        model = _make_fake_model()
        detail = _make_detail(properties=[prop])
        with patch(_MODEL_QUERIES, return_value=model), \
             patch(_ELEM_QUERIES, return_value=detail):
            response = client.get(_url())
        p = response.json()["properties"][0]
        assert "id" not in p
        assert "element_id" not in p
        assert "created_at" not in p

    # ── 29. Realistic GlobalId with '$' and '_' is accepted ───────────────────

    def test_realistic_global_id_special_chars(self, client):
        realistic_gid = "2O2Fr$t4X7Zf8NOew3FLO_"
        element = _make_fake_element(global_id=realistic_gid)
        model = _make_fake_model()
        detail = _make_detail(element=element)
        with patch(_MODEL_QUERIES, return_value=model), \
             patch(_ELEM_QUERIES, return_value=detail):
            response = client.get(_url(global_id=realistic_gid))
        assert response.status_code == 200
        assert response.json()["global_id"] == realistic_gid
