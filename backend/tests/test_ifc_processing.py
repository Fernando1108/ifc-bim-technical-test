"""
Tests for the IFC processing service.

- Real IfcOpenShell calls for integration tests (no mock of ifcopenshell.open).
- MagicMock(spec=Session) for DB — no PostgreSQL required.
- tmp_path — no real repository storage touched.
- Extractor calls are patched for orchestration tests.
"""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import ifcopenshell
import pytest
from sqlalchemy.orm import Session

from app.services.ifc_processing import (
    IfcInvalidProcessingStateError,
    IfcProcessingPersistenceError,
    process_ifc_model,
)
from app.services.ifc_spatial import IfcSpatialExtractionError
from app.services.ifc_elements import IfcElementExtractionError
from app.services.ifc_properties import IfcPropertyExtractionError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_settings(storage_dir):
    return SimpleNamespace(ifc_storage_dir=storage_dir)


def _make_model(**kwargs):
    """Return a SimpleNamespace that mimics IfcModel attribute access."""
    defaults = dict(
        id=1,
        owner_id=1,
        original_filename="model.ifc",
        storage_path="00000000-0000-0000-0000-000000000000.ifc",
        file_size_bytes=1024,
        sha256="a" * 64,
        status="PENDING",
        ifc_schema=None,
        error_message=None,
        processing_started_at=None,
        processed_at=None,
        spatial_node_count=0,
        element_count=0,
        property_count=0,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _make_db() -> MagicMock:
    return MagicMock(spec=Session)


# ---------------------------------------------------------------------------
# Real IFC file helpers (no mock)
# ---------------------------------------------------------------------------

def _write_ifc4(path) -> None:
    """Write a minimal real IFC4 file using IfcOpenShell."""
    f = ifcopenshell.file(schema="IFC4")
    f.write(str(path))


def _write_ifc2x3(path) -> None:
    """Write a minimal real IFC2X3 file using IfcOpenShell."""
    f = ifcopenshell.file(schema="IFC2X3")
    f.write(str(path))


# ---------------------------------------------------------------------------
# Patch targets
# ---------------------------------------------------------------------------

_SPATIAL_PATH = "app.services.ifc_processing.extract_and_persist_spatial_structure"
_ELEMENTS_PATH = "app.services.ifc_processing.extract_and_persist_elements"
_PROPS_PATH = "app.services.ifc_processing.extract_and_persist_element_properties"


# ===========================================================================
# 1. Real IfcOpenShell — IFC4
# ===========================================================================

def test_ifc4_real_completed(tmp_path):
    """Real IFC4 file is processed to COMPLETED."""
    ifc_path = tmp_path / "model.ifc"
    _write_ifc4(ifc_path)

    settings = _make_settings(tmp_path)
    model = _make_model(storage_path=ifc_path.name)
    db = _make_db()

    result = process_ifc_model(db, model, settings)

    assert result.status == "COMPLETED"


def test_ifc4_real_schema(tmp_path):
    """Real IFC4 file sets ifc_schema to 'IFC4'."""
    ifc_path = tmp_path / "model.ifc"
    _write_ifc4(ifc_path)

    settings = _make_settings(tmp_path)
    model = _make_model(storage_path=ifc_path.name)
    db = _make_db()

    result = process_ifc_model(db, model, settings)

    assert result.ifc_schema == "IFC4"


# ===========================================================================
# 2. Real IfcOpenShell — IFC2X3 (not hardcoded to IFC4)
# ===========================================================================

def test_ifc2x3_real_schema(tmp_path):
    """Real IFC2X3 file sets ifc_schema to 'IFC2X3', not 'IFC4'."""
    ifc_path = tmp_path / "model.ifc"
    _write_ifc2x3(ifc_path)

    settings = _make_settings(tmp_path)
    model = _make_model(storage_path=ifc_path.name)
    db = _make_db()

    result = process_ifc_model(db, model, settings)

    assert result.ifc_schema == "IFC2X3"


# ===========================================================================
# 3. PENDING can begin processing
# ===========================================================================

def test_pending_can_begin_processing(tmp_path):
    """Model with status PENDING transitions without raising."""
    ifc_path = tmp_path / "model.ifc"
    _write_ifc4(ifc_path)

    settings = _make_settings(tmp_path)
    model = _make_model(storage_path=ifc_path.name, status="PENDING")
    db = _make_db()

    result = process_ifc_model(db, model, settings)

    assert result.status in {"COMPLETED", "FAILED"}


# ===========================================================================
# 4. PROCESSING state observed before ifcopenshell.open
# ===========================================================================

def test_processing_set_before_open(tmp_path):
    """model.status is 'PROCESSING' at the moment ifcopenshell.open is called."""
    ifc_path = tmp_path / "model.ifc"
    _write_ifc4(ifc_path)

    settings = _make_settings(tmp_path)
    model = _make_model(storage_path=ifc_path.name)
    db = _make_db()

    captured_status = []
    real_open = ifcopenshell.open

    def capturing_open(path):
        captured_status.append(model.status)
        return real_open(path)

    with patch("app.services.ifc_processing.ifcopenshell.open", side_effect=capturing_open):
        process_ifc_model(db, model, settings)

    assert captured_status == ["PROCESSING"]


# ===========================================================================
# 5. processing_started_at is set
# ===========================================================================

def test_processing_started_at_set(tmp_path):
    """processing_started_at is defined after successful processing."""
    ifc_path = tmp_path / "model.ifc"
    _write_ifc4(ifc_path)

    settings = _make_settings(tmp_path)
    model = _make_model(storage_path=ifc_path.name)
    db = _make_db()

    result = process_ifc_model(db, model, settings)

    assert result.processing_started_at is not None


# ===========================================================================
# 6. processed_at and error_message after COMPLETED
# ===========================================================================

def test_processed_at_set_on_success(tmp_path):
    """processed_at is defined after COMPLETED."""
    ifc_path = tmp_path / "model.ifc"
    _write_ifc4(ifc_path)

    settings = _make_settings(tmp_path)
    model = _make_model(storage_path=ifc_path.name)
    db = _make_db()

    result = process_ifc_model(db, model, settings)

    assert result.processed_at is not None


def test_error_message_none_on_success(tmp_path):
    """error_message is None after COMPLETED."""
    ifc_path = tmp_path / "model.ifc"
    _write_ifc4(ifc_path)

    settings = _make_settings(tmp_path)
    model = _make_model(storage_path=ifc_path.name)
    db = _make_db()

    result = process_ifc_model(db, model, settings)

    assert result.error_message is None


# ===========================================================================
# 7. Corrupt IFC file → FAILED
# ===========================================================================

def test_corrupt_ifc_failed(tmp_path):
    """Corrupt bytes produce FAILED status."""
    ifc_path = tmp_path / "model.ifc"
    ifc_path.write_bytes(b"this is not an IFC file at all")

    settings = _make_settings(tmp_path)
    model = _make_model(storage_path=ifc_path.name)
    db = _make_db()

    result = process_ifc_model(db, model, settings)

    assert result.status == "FAILED"


def test_corrupt_ifc_schema_none(tmp_path):
    """Corrupt file → ifc_schema remains None."""
    ifc_path = tmp_path / "model.ifc"
    ifc_path.write_bytes(b"garbage data")

    settings = _make_settings(tmp_path)
    model = _make_model(storage_path=ifc_path.name)
    db = _make_db()

    result = process_ifc_model(db, model, settings)

    assert result.ifc_schema is None


def test_corrupt_ifc_error_message(tmp_path):
    """Corrupt file → error_message is exactly the expected safe string."""
    ifc_path = tmp_path / "model.ifc"
    ifc_path.write_bytes(b"garbage data")

    settings = _make_settings(tmp_path)
    model = _make_model(storage_path=ifc_path.name)
    db = _make_db()

    result = process_ifc_model(db, model, settings)

    assert result.error_message == "No se pudo procesar el archivo IFC."


def test_error_message_no_physical_path(tmp_path):
    """error_message does not expose the physical storage directory."""
    ifc_path = tmp_path / "model.ifc"
    ifc_path.write_bytes(b"garbage data")

    settings = _make_settings(tmp_path)
    model = _make_model(storage_path=ifc_path.name)
    db = _make_db()

    result = process_ifc_model(db, model, settings)

    assert str(tmp_path) not in (result.error_message or "")


# ===========================================================================
# 8. Nonexistent file → FAILED
# ===========================================================================

def test_nonexistent_file_failed(tmp_path):
    """File that does not exist results in FAILED."""
    settings = _make_settings(tmp_path)
    model = _make_model(storage_path="does-not-exist.ifc")
    db = _make_db()

    result = process_ifc_model(db, model, settings)

    assert result.status == "FAILED"


# ===========================================================================
# 9. Invalid states — cannot reprocess
# ===========================================================================

def test_completed_cannot_reprocess(tmp_path):
    """COMPLETED model raises IfcInvalidProcessingStateError."""
    settings = _make_settings(tmp_path)
    model = _make_model(status="COMPLETED")
    db = _make_db()

    with pytest.raises(IfcInvalidProcessingStateError):
        process_ifc_model(db, model, settings)


def test_processing_cannot_reprocess(tmp_path):
    """PROCESSING model raises IfcInvalidProcessingStateError."""
    settings = _make_settings(tmp_path)
    model = _make_model(status="PROCESSING")
    db = _make_db()

    with pytest.raises(IfcInvalidProcessingStateError):
        process_ifc_model(db, model, settings)


def test_failed_cannot_reprocess(tmp_path):
    """FAILED model raises IfcInvalidProcessingStateError."""
    settings = _make_settings(tmp_path)
    model = _make_model(status="FAILED")
    db = _make_db()

    with pytest.raises(IfcInvalidProcessingStateError):
        process_ifc_model(db, model, settings)


def test_invalid_state_does_not_call_open(tmp_path):
    """ifcopenshell.open is never called when model is not PENDING."""
    settings = _make_settings(tmp_path)
    model = _make_model(status="COMPLETED")
    db = _make_db()

    with patch("app.services.ifc_processing.ifcopenshell.open") as mock_open:
        with pytest.raises(IfcInvalidProcessingStateError):
            process_ifc_model(db, model, settings)

    mock_open.assert_not_called()


# ===========================================================================
# 10. storage_path validation — rejected safely
# ===========================================================================

def test_absolute_storage_path_rejected_safely(tmp_path):
    """Absolute storage_path results in FAILED without exposing the path."""
    settings = _make_settings(tmp_path)
    model = _make_model(storage_path="/etc/passwd.ifc")
    db = _make_db()

    result = process_ifc_model(db, model, settings)

    assert result.status == "FAILED"
    assert "/etc" not in (result.error_message or "")


def test_directory_storage_path_rejected_safely(tmp_path):
    """storage_path with a directory component results in FAILED."""
    settings = _make_settings(tmp_path)
    model = _make_model(storage_path="subdir/model.ifc")
    db = _make_db()

    result = process_ifc_model(db, model, settings)

    assert result.status == "FAILED"


# ===========================================================================
# 11. Persistence — PROCESSING commit fails
# ===========================================================================

def test_processing_commit_failure_raises(tmp_path):
    """IfcProcessingPersistenceError raised when PROCESSING commit fails."""
    settings = _make_settings(tmp_path)
    model = _make_model()
    db = _make_db()
    db.commit.side_effect = Exception("DB gone")

    with pytest.raises(IfcProcessingPersistenceError):
        process_ifc_model(db, model, settings)


def test_processing_commit_failure_calls_rollback(tmp_path):
    """rollback is called when PROCESSING commit fails."""
    settings = _make_settings(tmp_path)
    model = _make_model()
    db = _make_db()
    db.commit.side_effect = Exception("DB gone")

    with pytest.raises(IfcProcessingPersistenceError):
        process_ifc_model(db, model, settings)

    db.rollback.assert_called()


def test_processing_commit_failure_open_not_called(tmp_path):
    """ifcopenshell.open is never called if PROCESSING commit fails."""
    settings = _make_settings(tmp_path)
    model = _make_model()
    db = _make_db()
    db.commit.side_effect = Exception("DB gone")

    with patch("app.services.ifc_processing.ifcopenshell.open") as mock_open:
        with pytest.raises(IfcProcessingPersistenceError):
            process_ifc_model(db, model, settings)

    mock_open.assert_not_called()


# ===========================================================================
# 12. Persistence — COMPLETED commit fails
# ===========================================================================

def _make_failing_on_nth_commit(n: int):
    """Return a commit side_effect that raises on the nth call."""
    call_count = 0

    def side_effect():
        nonlocal call_count
        call_count += 1
        if call_count == n:
            raise Exception(f"DB gone on commit #{n}")

    return side_effect


def test_completed_commit_failure_raises(tmp_path):
    """IfcProcessingPersistenceError raised when COMPLETED commit fails."""
    ifc_path = tmp_path / "model.ifc"
    _write_ifc4(ifc_path)

    settings = _make_settings(tmp_path)
    model = _make_model(storage_path=ifc_path.name)
    db = _make_db()
    db.commit.side_effect = _make_failing_on_nth_commit(2)

    with pytest.raises(IfcProcessingPersistenceError):
        process_ifc_model(db, model, settings)


def test_completed_commit_failure_calls_rollback(tmp_path):
    """rollback is called when COMPLETED commit fails."""
    ifc_path = tmp_path / "model.ifc"
    _write_ifc4(ifc_path)

    settings = _make_settings(tmp_path)
    model = _make_model(storage_path=ifc_path.name)
    db = _make_db()
    db.commit.side_effect = _make_failing_on_nth_commit(2)

    with pytest.raises(IfcProcessingPersistenceError):
        process_ifc_model(db, model, settings)

    db.rollback.assert_called()


# ===========================================================================
# 13. Persistence — FAILED commit fails
# ===========================================================================

def test_failed_commit_failure_raises(tmp_path):
    """IfcProcessingPersistenceError raised when FAILED commit fails."""
    # nonexistent file → ifcopenshell.open fails → _persist_failed → commit #2
    settings = _make_settings(tmp_path)
    model = _make_model(storage_path="does-not-exist.ifc")
    db = _make_db()
    db.commit.side_effect = _make_failing_on_nth_commit(2)

    with pytest.raises(IfcProcessingPersistenceError):
        process_ifc_model(db, model, settings)


def test_failed_commit_failure_calls_rollback(tmp_path):
    """rollback is called when FAILED commit fails."""
    settings = _make_settings(tmp_path)
    model = _make_model(storage_path="does-not-exist.ifc")
    db = _make_db()
    db.commit.side_effect = _make_failing_on_nth_commit(2)

    with pytest.raises(IfcProcessingPersistenceError):
        process_ifc_model(db, model, settings)

    db.rollback.assert_called()


# ===========================================================================
# 14. Orchestration — extractor order (spatial → elements → properties)
# ===========================================================================

def test_extractor_call_order(tmp_path):
    """Extractors are called in the required order: spatial, elements, properties."""
    ifc_path = tmp_path / "model.ifc"
    _write_ifc4(ifc_path)

    settings = _make_settings(tmp_path)
    model = _make_model(storage_path=ifc_path.name)
    db = _make_db()

    events = []

    with (
        patch(_SPATIAL_PATH, side_effect=lambda *a, **kw: events.append("spatial") or []) as _s,
        patch(_ELEMENTS_PATH, side_effect=lambda *a, **kw: events.append("elements") or []) as _e,
        patch(_PROPS_PATH, side_effect=lambda *a, **kw: events.append("properties") or []) as _p,
    ):
        process_ifc_model(db, model, settings)

    assert events == ["spatial", "elements", "properties"]


# ===========================================================================
# 15. Orchestration — output propagation
# ===========================================================================

def test_spatial_output_passed_to_elements(tmp_path):
    """Output of spatial extractor is passed verbatim to elements extractor."""
    ifc_path = tmp_path / "model.ifc"
    _write_ifc4(ifc_path)

    settings = _make_settings(tmp_path)
    model = _make_model(storage_path=ifc_path.name)
    db = _make_db()

    sentinel_nodes = [object(), object()]
    captured_elements_args = {}

    def fake_spatial(db, model, ifc_file):
        return sentinel_nodes

    def fake_elements(db, model, ifc_file, spatial_nodes):
        captured_elements_args["spatial_nodes"] = spatial_nodes
        return []

    with (
        patch(_SPATIAL_PATH, side_effect=fake_spatial),
        patch(_ELEMENTS_PATH, side_effect=fake_elements),
        patch(_PROPS_PATH, return_value=[]),
    ):
        process_ifc_model(db, model, settings)

    assert captured_elements_args["spatial_nodes"] is sentinel_nodes


def test_elements_output_passed_to_properties(tmp_path):
    """Output of elements extractor is passed verbatim to properties extractor."""
    ifc_path = tmp_path / "model.ifc"
    _write_ifc4(ifc_path)

    settings = _make_settings(tmp_path)
    model = _make_model(storage_path=ifc_path.name)
    db = _make_db()

    sentinel_elements = [object(), object(), object()]
    captured_props_args = {}

    def fake_elements(db, model, ifc_file, spatial_nodes):
        return sentinel_elements

    def fake_props(db, model, ifc_file, elements):
        captured_props_args["elements"] = elements
        return []

    with (
        patch(_SPATIAL_PATH, return_value=[]),
        patch(_ELEMENTS_PATH, side_effect=fake_elements),
        patch(_PROPS_PATH, side_effect=fake_props),
    ):
        process_ifc_model(db, model, settings)

    assert captured_props_args["elements"] is sentinel_elements


# ===========================================================================
# 16. Orchestration — extractor receives correct db/model/ifc_file
# ===========================================================================

def test_extractors_receive_same_db_model_ifc(tmp_path):
    """Each extractor receives the same db, model, and open ifc_file object."""
    ifc_path = tmp_path / "model.ifc"
    _write_ifc4(ifc_path)

    settings = _make_settings(tmp_path)
    model = _make_model(storage_path=ifc_path.name)
    db = _make_db()

    calls_log = []

    def log_spatial(db_arg, model_arg, ifc_arg):
        calls_log.append(("spatial", db_arg, model_arg, ifc_arg))
        return []

    def log_elements(db_arg, model_arg, ifc_arg, spatial_nodes):
        calls_log.append(("elements", db_arg, model_arg, ifc_arg))
        return []

    def log_props(db_arg, model_arg, ifc_arg, elements):
        calls_log.append(("props", db_arg, model_arg, ifc_arg))
        return []

    with (
        patch(_SPATIAL_PATH, side_effect=log_spatial),
        patch(_ELEMENTS_PATH, side_effect=log_elements),
        patch(_PROPS_PATH, side_effect=log_props),
    ):
        process_ifc_model(db, model, settings)

    assert len(calls_log) == 3
    # All receive the same db and model
    for name, db_arg, model_arg, ifc_arg in calls_log:
        assert db_arg is db
        assert model_arg is model
    # All receive the same ifc_file object
    ifc_objects = [entry[3] for entry in calls_log]
    assert ifc_objects[0] is ifc_objects[1]
    assert ifc_objects[1] is ifc_objects[2]


# ===========================================================================
# 17. COMPLETED set only after all extractors finish
# ===========================================================================

def test_completed_set_only_after_properties(tmp_path):
    """model.status is PROCESSING during properties extraction; COMPLETED only after."""
    ifc_path = tmp_path / "model.ifc"
    _write_ifc4(ifc_path)

    settings = _make_settings(tmp_path)
    model = _make_model(storage_path=ifc_path.name)
    db = _make_db()

    status_during_props = []

    def fake_props(db_arg, model_arg, ifc_arg, elements):
        status_during_props.append(model_arg.status)
        return []

    with (
        patch(_SPATIAL_PATH, return_value=[]),
        patch(_ELEMENTS_PATH, return_value=[]),
        patch(_PROPS_PATH, side_effect=fake_props),
    ):
        result = process_ifc_model(db, model, settings)

    assert status_during_props == ["PROCESSING"]
    assert result.status == "COMPLETED"


# ===========================================================================
# 18. Extraction failures → FAILED
# ===========================================================================

def test_spatial_failure_status_failed(tmp_path):
    """IfcSpatialExtractionError → status FAILED."""
    ifc_path = tmp_path / "model.ifc"
    _write_ifc4(ifc_path)

    settings = _make_settings(tmp_path)
    model = _make_model(storage_path=ifc_path.name)
    db = _make_db()

    with (
        patch(_SPATIAL_PATH, side_effect=IfcSpatialExtractionError("internal detail")),
        patch(_ELEMENTS_PATH) as mock_elements,
        patch(_PROPS_PATH) as mock_props,
    ):
        result = process_ifc_model(db, model, settings)

    assert result.status == "FAILED"
    mock_elements.assert_not_called()
    mock_props.assert_not_called()


def test_spatial_failure_ifc_schema_none(tmp_path):
    """IfcSpatialExtractionError → ifc_schema is None."""
    ifc_path = tmp_path / "model.ifc"
    _write_ifc4(ifc_path)

    settings = _make_settings(tmp_path)
    model = _make_model(storage_path=ifc_path.name)
    db = _make_db()

    with (
        patch(_SPATIAL_PATH, side_effect=IfcSpatialExtractionError("err")),
        patch(_ELEMENTS_PATH),
        patch(_PROPS_PATH),
    ):
        result = process_ifc_model(db, model, settings)

    assert result.ifc_schema is None


def test_spatial_failure_processed_at_set(tmp_path):
    """IfcSpatialExtractionError → processed_at is set."""
    ifc_path = tmp_path / "model.ifc"
    _write_ifc4(ifc_path)

    settings = _make_settings(tmp_path)
    model = _make_model(storage_path=ifc_path.name)
    db = _make_db()

    with (
        patch(_SPATIAL_PATH, side_effect=IfcSpatialExtractionError("err")),
        patch(_ELEMENTS_PATH),
        patch(_PROPS_PATH),
    ):
        result = process_ifc_model(db, model, settings)

    assert result.processed_at is not None


def test_spatial_failure_rollback_called(tmp_path):
    """IfcSpatialExtractionError → db.rollback() is called."""
    ifc_path = tmp_path / "model.ifc"
    _write_ifc4(ifc_path)

    settings = _make_settings(tmp_path)
    model = _make_model(storage_path=ifc_path.name)
    db = _make_db()

    with (
        patch(_SPATIAL_PATH, side_effect=IfcSpatialExtractionError("err")),
        patch(_ELEMENTS_PATH),
        patch(_PROPS_PATH),
    ):
        process_ifc_model(db, model, settings)

    db.rollback.assert_called()


def test_element_failure_status_failed(tmp_path):
    """IfcElementExtractionError → status FAILED, properties not called."""
    ifc_path = tmp_path / "model.ifc"
    _write_ifc4(ifc_path)

    settings = _make_settings(tmp_path)
    model = _make_model(storage_path=ifc_path.name)
    db = _make_db()

    with (
        patch(_SPATIAL_PATH, return_value=["sentinel_node"]),
        patch(_ELEMENTS_PATH, side_effect=IfcElementExtractionError("internal detail")),
        patch(_PROPS_PATH) as mock_props,
    ):
        result = process_ifc_model(db, model, settings)

    assert result.status == "FAILED"
    mock_props.assert_not_called()


def test_element_failure_rollback_called(tmp_path):
    """IfcElementExtractionError → db.rollback() is called."""
    ifc_path = tmp_path / "model.ifc"
    _write_ifc4(ifc_path)

    settings = _make_settings(tmp_path)
    model = _make_model(storage_path=ifc_path.name)
    db = _make_db()

    with (
        patch(_SPATIAL_PATH, return_value=[]),
        patch(_ELEMENTS_PATH, side_effect=IfcElementExtractionError("err")),
        patch(_PROPS_PATH),
    ):
        process_ifc_model(db, model, settings)

    db.rollback.assert_called()


def test_property_failure_status_failed(tmp_path):
    """IfcPropertyExtractionError → status FAILED."""
    ifc_path = tmp_path / "model.ifc"
    _write_ifc4(ifc_path)

    settings = _make_settings(tmp_path)
    model = _make_model(storage_path=ifc_path.name)
    db = _make_db()

    with (
        patch(_SPATIAL_PATH, return_value=[]),
        patch(_ELEMENTS_PATH, return_value=["sentinel_elem"]),
        patch(_PROPS_PATH, side_effect=IfcPropertyExtractionError("internal detail")),
    ):
        result = process_ifc_model(db, model, settings)

    assert result.status == "FAILED"


def test_property_failure_rollback_called(tmp_path):
    """IfcPropertyExtractionError → db.rollback() is called."""
    ifc_path = tmp_path / "model.ifc"
    _write_ifc4(ifc_path)

    settings = _make_settings(tmp_path)
    model = _make_model(storage_path=ifc_path.name)
    db = _make_db()

    with (
        patch(_SPATIAL_PATH, return_value=[]),
        patch(_ELEMENTS_PATH, return_value=[]),
        patch(_PROPS_PATH, side_effect=IfcPropertyExtractionError("err")),
    ):
        process_ifc_model(db, model, settings)

    db.rollback.assert_called()


# ===========================================================================
# 19. Safe error messages — no internal detail leaked
# ===========================================================================

def test_extraction_error_message_safe_no_internal_detail(tmp_path):
    """Internal extractor details are never exposed in error_message."""
    ifc_path = tmp_path / "model.ifc"
    _write_ifc4(ifc_path)

    settings = _make_settings(tmp_path)
    model = _make_model(storage_path=ifc_path.name)
    db = _make_db()

    internal_msg = (
        "/secret/path/model.ifc | SELECT * FROM users | #12345 | traceback-interno"
    )

    with (
        patch(_SPATIAL_PATH, side_effect=IfcSpatialExtractionError(internal_msg)),
        patch(_ELEMENTS_PATH),
        patch(_PROPS_PATH),
    ):
        result = process_ifc_model(db, model, settings)

    assert result.error_message == "No se pudo procesar el archivo IFC."
    assert "/secret/path" not in (result.error_message or "")
    assert "SELECT" not in (result.error_message or "")
    assert "#12345" not in (result.error_message or "")
    assert "traceback" not in (result.error_message or "")


# ===========================================================================
# 20. Commit counts
# ===========================================================================

def test_commit_count_on_success(tmp_path):
    """Exactly 2 commits on success: PROCESSING and COMPLETED."""
    ifc_path = tmp_path / "model.ifc"
    _write_ifc4(ifc_path)

    settings = _make_settings(tmp_path)
    model = _make_model(storage_path=ifc_path.name)
    db = _make_db()

    with (
        patch(_SPATIAL_PATH, return_value=[]),
        patch(_ELEMENTS_PATH, return_value=[]),
        patch(_PROPS_PATH, return_value=[]),
    ):
        process_ifc_model(db, model, settings)

    assert db.commit.call_count == 2


def test_commit_count_on_extraction_failure(tmp_path):
    """Exactly 2 commits on extraction failure: PROCESSING and FAILED."""
    ifc_path = tmp_path / "model.ifc"
    _write_ifc4(ifc_path)

    settings = _make_settings(tmp_path)
    model = _make_model(storage_path=ifc_path.name)
    db = _make_db()

    with (
        patch(_SPATIAL_PATH, side_effect=IfcSpatialExtractionError("err")),
        patch(_ELEMENTS_PATH),
        patch(_PROPS_PATH),
    ):
        process_ifc_model(db, model, settings)

    assert db.commit.call_count == 2


# ===========================================================================
# 21. Parse failure → no extractors called
# ===========================================================================

def test_parse_failure_no_extractors_called(tmp_path):
    """Corrupt IFC → spatial, elements, properties never called."""
    ifc_path = tmp_path / "model.ifc"
    ifc_path.write_bytes(b"not an ifc file")

    settings = _make_settings(tmp_path)
    model = _make_model(storage_path=ifc_path.name)
    db = _make_db()

    with (
        patch(_SPATIAL_PATH) as mock_spatial,
        patch(_ELEMENTS_PATH) as mock_elements,
        patch(_PROPS_PATH) as mock_props,
    ):
        process_ifc_model(db, model, settings)

    mock_spatial.assert_not_called()
    mock_elements.assert_not_called()
    mock_props.assert_not_called()


# ===========================================================================
# 22. Invalid path → no extractors called
# ===========================================================================

def test_invalid_path_no_extractors_called(tmp_path):
    """Invalid storage_path → no extractor is called."""
    settings = _make_settings(tmp_path)
    model = _make_model(storage_path="subdir/model.ifc")
    db = _make_db()

    with (
        patch(_SPATIAL_PATH) as mock_spatial,
        patch(_ELEMENTS_PATH) as mock_elements,
        patch(_PROPS_PATH) as mock_props,
    ):
        process_ifc_model(db, model, settings)

    mock_spatial.assert_not_called()
    mock_elements.assert_not_called()
    mock_props.assert_not_called()


# ===========================================================================
# 23. PROCESSING commit failure → no extractors called
# ===========================================================================

def test_processing_commit_failure_no_extractors(tmp_path):
    """PROCESSING commit failure → no extractor is called."""
    settings = _make_settings(tmp_path)
    model = _make_model()
    db = _make_db()
    db.commit.side_effect = Exception("DB gone")

    with (
        patch(_SPATIAL_PATH) as mock_spatial,
        patch(_ELEMENTS_PATH) as mock_elements,
        patch(_PROPS_PATH) as mock_props,
    ):
        with pytest.raises(IfcProcessingPersistenceError):
            process_ifc_model(db, model, settings)

    mock_spatial.assert_not_called()
    mock_elements.assert_not_called()
    mock_props.assert_not_called()


# ===========================================================================
# 24. Counters are not overwritten by process_ifc_model
# ===========================================================================

def test_counters_not_overwritten_on_success(tmp_path):
    """Extractor-set counters survive to COMPLETED; orchestrator does not touch them."""
    ifc_path = tmp_path / "model.ifc"
    _write_ifc4(ifc_path)

    settings = _make_settings(tmp_path)
    model = _make_model(storage_path=ifc_path.name)
    db = _make_db()

    def fake_spatial(db_arg, model_arg, ifc_arg):
        model_arg.spatial_node_count = 4
        return []

    def fake_elements(db_arg, model_arg, ifc_arg, spatial_nodes):
        model_arg.element_count = 10
        return []

    def fake_props(db_arg, model_arg, ifc_arg, elements):
        model_arg.property_count = 100
        return []

    with (
        patch(_SPATIAL_PATH, side_effect=fake_spatial),
        patch(_ELEMENTS_PATH, side_effect=fake_elements),
        patch(_PROPS_PATH, side_effect=fake_props),
    ):
        result = process_ifc_model(db, model, settings)

    assert result.status == "COMPLETED"
    assert result.spatial_node_count == 4
    assert result.element_count == 10
    assert result.property_count == 100


# ===========================================================================
# 25. COMPLETED commit failure — rollback called
# ===========================================================================

def test_completed_commit_failure_rollback_called_with_extractors(tmp_path):
    """db.rollback() called when COMPLETED commit fails (with patched extractors)."""
    ifc_path = tmp_path / "model.ifc"
    _write_ifc4(ifc_path)

    settings = _make_settings(tmp_path)
    model = _make_model(storage_path=ifc_path.name)
    db = _make_db()
    db.commit.side_effect = _make_failing_on_nth_commit(2)

    with (
        patch(_SPATIAL_PATH, return_value=[]),
        patch(_ELEMENTS_PATH, return_value=[]),
        patch(_PROPS_PATH, return_value=[]),
    ):
        with pytest.raises(IfcProcessingPersistenceError):
            process_ifc_model(db, model, settings)

    db.rollback.assert_called()


# ===========================================================================
# 26. FAILED commit failure via extraction path
# ===========================================================================

def test_failed_commit_failure_via_extraction_raises(tmp_path):
    """Extraction failure + FAILED commit failure → IfcProcessingPersistenceError."""
    ifc_path = tmp_path / "model.ifc"
    _write_ifc4(ifc_path)

    settings = _make_settings(tmp_path)
    model = _make_model(storage_path=ifc_path.name)
    db = _make_db()
    # commit #1 (PROCESSING) succeeds; commit #2 (FAILED) fails
    db.commit.side_effect = _make_failing_on_nth_commit(2)

    with (
        patch(_SPATIAL_PATH, side_effect=IfcSpatialExtractionError("err")),
        patch(_ELEMENTS_PATH),
        patch(_PROPS_PATH),
    ):
        with pytest.raises(IfcProcessingPersistenceError):
            process_ifc_model(db, model, settings)

    db.rollback.assert_called()


# ===========================================================================
# 27. Unsupported schema (SchemaError) → specific FAILED
# ===========================================================================

_OPEN_PATH = "app.services.ifc_processing.ifcopenshell.open"

_SCHEMA_ERROR = ifcopenshell.SchemaError("Unsupported schema: IFC5")


def _schema_error_patch():
    """Context manager: ifcopenshell.open raises SchemaError."""
    return patch(_OPEN_PATH, side_effect=_SCHEMA_ERROR)


def test_schema_error_status_failed(tmp_path):
    """SchemaError → status is FAILED."""
    settings = _make_settings(tmp_path)
    model = _make_model()
    db = _make_db()

    with _schema_error_patch():
        result = process_ifc_model(db, model, settings)

    assert result.status == "FAILED"


def test_schema_error_ifc_schema_none(tmp_path):
    """SchemaError → ifc_schema remains None."""
    settings = _make_settings(tmp_path)
    model = _make_model()
    db = _make_db()

    with _schema_error_patch():
        result = process_ifc_model(db, model, settings)

    assert result.ifc_schema is None


def test_schema_error_message_exact(tmp_path):
    """SchemaError → error_message is exactly the expected safe string."""
    settings = _make_settings(tmp_path)
    model = _make_model()
    db = _make_db()

    with _schema_error_patch():
        result = process_ifc_model(db, model, settings)

    assert result.error_message == "El esquema IFC del archivo no está soportado."


def test_schema_error_message_no_internal_detail(tmp_path):
    """SchemaError → public message does not leak schema name, exception text, or paths."""
    settings = _make_settings(tmp_path)
    model = _make_model()
    db = _make_db()

    with _schema_error_patch():
        result = process_ifc_model(db, model, settings)

    msg = result.error_message or ""
    assert "IFC5" not in msg
    assert "Unsupported schema" not in msg
    assert str(tmp_path) not in msg


def test_schema_error_no_extractors_called(tmp_path):
    """SchemaError → spatial, elements, and properties extractors are never called."""
    settings = _make_settings(tmp_path)
    model = _make_model()
    db = _make_db()

    with (
        _schema_error_patch(),
        patch(_SPATIAL_PATH) as mock_spatial,
        patch(_ELEMENTS_PATH) as mock_elements,
        patch(_PROPS_PATH) as mock_props,
    ):
        process_ifc_model(db, model, settings)

    mock_spatial.assert_not_called()
    mock_elements.assert_not_called()
    mock_props.assert_not_called()


def test_schema_error_distinct_from_corrupt(tmp_path):
    """SchemaError produces a different message than a corrupt/invalid file."""
    # Corrupt file → generic message
    ifc_path = tmp_path / "model.ifc"
    ifc_path.write_bytes(b"garbage data")

    settings = _make_settings(tmp_path)
    model_corrupt = _make_model(storage_path=ifc_path.name)
    db_corrupt = _make_db()
    result_corrupt = process_ifc_model(db_corrupt, model_corrupt, settings)

    # SchemaError → specific message
    model_schema = _make_model()
    db_schema = _make_db()
    with _schema_error_patch():
        result_schema = process_ifc_model(db_schema, model_schema, settings)

    assert result_corrupt.error_message == "No se pudo procesar el archivo IFC."
    assert result_schema.error_message == "El esquema IFC del archivo no está soportado."
    assert result_corrupt.error_message != result_schema.error_message
