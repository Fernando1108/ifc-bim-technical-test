"""
Tests for the IFC processing service.

- Real IfcOpenShell calls for integration tests (no mock of ifcopenshell.open).
- MagicMock(spec=Session) for DB — no PostgreSQL required.
- tmp_path — no real repository storage touched.
"""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import ifcopenshell
import pytest
from sqlalchemy.orm import Session

from app.services.ifc_processing import (
    IfcInvalidProcessingStateError,
    IfcProcessingPersistenceError,
    process_ifc_model,
)


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
