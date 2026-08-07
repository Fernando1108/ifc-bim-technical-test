"""
Tests for process_ifc_model_background.

- No real PostgreSQL — SessionLocal is mocked.
- No real IfcOpenShell calls — process_ifc_model is mocked.
- Verifies session lifecycle (always closed), delegation, and error containment.
"""
from unittest.mock import MagicMock, call, patch

import pytest

from app.models.ifc_model import IfcModel
from app.services.ifc_background import process_ifc_model_background
from app.services.ifc_processing import (
    IfcInvalidProcessingStateError,
    IfcProcessingPersistenceError,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_mock_model(model_id: int = 42):
    return MagicMock(spec=IfcModel, id=model_id, status="PENDING")


def _make_mocks(model=None, db_get_side_effect=None, process_side_effect=None):
    """
    Build a tuple of mocks for all patched targets.

    Returns (mock_session_cls, mock_db, mock_get_settings_fn, mock_process).
    """
    mock_session_cls = MagicMock()
    mock_db = MagicMock()
    mock_session_cls.return_value = mock_db

    if db_get_side_effect is not None:
        mock_db.get.side_effect = db_get_side_effect
    else:
        mock_db.get.return_value = model

    mock_settings_instance = MagicMock()
    mock_get_settings_fn = MagicMock(return_value=mock_settings_instance)

    mock_process = MagicMock()
    if process_side_effect is not None:
        mock_process.side_effect = process_side_effect

    return mock_session_cls, mock_db, mock_get_settings_fn, mock_process, mock_settings_instance


def _run(model_id=42, *, model=None, db_get_side_effect=None, process_side_effect=None):
    """
    Patch all deps and run process_ifc_model_background(model_id).
    Returns (mock_session_cls, mock_db, mock_get_settings_fn, mock_process, mock_settings_instance).
    """
    mock_session_cls, mock_db, mock_get_settings_fn, mock_process, mock_settings_instance = (
        _make_mocks(
            model=model,
            db_get_side_effect=db_get_side_effect,
            process_side_effect=process_side_effect,
        )
    )

    with patch("app.services.ifc_background.SessionLocal", mock_session_cls), \
         patch("app.services.ifc_background.get_settings", mock_get_settings_fn), \
         patch("app.services.ifc_background.process_ifc_model", mock_process):
        process_ifc_model_background(model_id)

    return mock_session_cls, mock_db, mock_get_settings_fn, mock_process, mock_settings_instance


# ===========================================================================
# 1. Creates a new SessionLocal (not the request session)
# ===========================================================================

def test_creates_session_local():
    mock_session_cls, mock_db, *_ = _run(model=None)
    mock_session_cls.assert_called_once_with()


# ===========================================================================
# 2. Queries IfcModel by primary key
# ===========================================================================

def test_queries_ifc_model_by_id():
    _, mock_db, *_ = _run(model_id=99, model=None)
    mock_db.get.assert_called_once_with(IfcModel, 99)


# ===========================================================================
# 3. Found model → calls process_ifc_model exactly once
# ===========================================================================

def test_found_model_calls_process_ifc_model():
    model = _make_mock_model()
    _, _, _, mock_process, _ = _run(model=model)
    mock_process.assert_called_once()


# ===========================================================================
# 4. process_ifc_model receives (new_db, model, settings)
# ===========================================================================

def test_process_ifc_model_receives_db_model_settings():
    model = _make_mock_model(model_id=42)
    mock_session_cls, mock_db, mock_get_settings_fn, mock_process, mock_settings_instance = (
        _run(model_id=42, model=model)
    )
    mock_process.assert_called_once_with(mock_db, model, mock_settings_instance)


# ===========================================================================
# 5. get_settings is used by the background runner
# ===========================================================================

def test_get_settings_is_called():
    model = _make_mock_model()
    _, _, mock_get_settings_fn, _, _ = _run(model=model)
    mock_get_settings_fn.assert_called_once()


# ===========================================================================
# 6. Session is closed after successful processing
# ===========================================================================

def test_session_closed_after_success():
    model = _make_mock_model()
    _, mock_db, *_ = _run(model=model)
    mock_db.close.assert_called_once()


# ===========================================================================
# 7. Model not found → process_ifc_model NOT called
# ===========================================================================

def test_model_not_found_process_not_called():
    _, _, _, mock_process, _ = _run(model=None)
    mock_process.assert_not_called()


# ===========================================================================
# 8. Model not found → session still closed
# ===========================================================================

def test_model_not_found_session_closed():
    _, mock_db, *_ = _run(model=None)
    mock_db.close.assert_called_once()


# ===========================================================================
# 9. IfcInvalidProcessingStateError does not escape
# ===========================================================================

def test_invalid_state_error_does_not_escape():
    model = _make_mock_model()
    # Should not raise
    _run(model=model, process_side_effect=IfcInvalidProcessingStateError("bad state"))


# ===========================================================================
# 10. IfcInvalidProcessingStateError → session closed
# ===========================================================================

def test_invalid_state_error_session_closed():
    model = _make_mock_model()
    _, mock_db, *_ = _run(
        model=model,
        process_side_effect=IfcInvalidProcessingStateError("bad state"),
    )
    mock_db.close.assert_called_once()


# ===========================================================================
# 11. IfcProcessingPersistenceError does not escape
# ===========================================================================

def test_persistence_error_does_not_escape():
    model = _make_mock_model()
    _run(model=model, process_side_effect=IfcProcessingPersistenceError("db gone"))


# ===========================================================================
# 12. IfcProcessingPersistenceError → session closed
# ===========================================================================

def test_persistence_error_session_closed():
    model = _make_mock_model()
    _, mock_db, *_ = _run(
        model=model,
        process_side_effect=IfcProcessingPersistenceError("db gone"),
    )
    mock_db.close.assert_called_once()


# ===========================================================================
# 13. Unexpected error does not escape
# ===========================================================================

def test_unexpected_error_does_not_escape():
    model = _make_mock_model()
    _run(model=model, process_side_effect=RuntimeError("unexpected crash"))


# ===========================================================================
# 14. Unexpected error → session closed
# ===========================================================================

def test_unexpected_error_session_closed():
    model = _make_mock_model()
    _, mock_db, *_ = _run(
        model=model,
        process_side_effect=RuntimeError("unexpected crash"),
    )
    mock_db.close.assert_called_once()


# ===========================================================================
# 15. Failure in db.get → session not left open
# ===========================================================================

def test_db_get_failure_session_not_left_open():
    _, mock_db, *_ = _run(db_get_side_effect=Exception("Connection refused"))
    mock_db.close.assert_called_once()


# ===========================================================================
# 16. SessionLocal() itself raises → function does not escape, no process call
# ===========================================================================

def test_session_local_failure_does_not_escape():
    """If SessionLocal() raises, the exception must not propagate."""
    mock_session_cls = MagicMock(side_effect=Exception("Cannot connect to DB"))
    mock_process = MagicMock()

    with patch("app.services.ifc_background.SessionLocal", mock_session_cls), \
         patch("app.services.ifc_background.get_settings"), \
         patch("app.services.ifc_background.process_ifc_model", mock_process):
        process_ifc_model_background(42)   # must not raise

    mock_process.assert_not_called()


# ===========================================================================
# 17. db.close() raises → function does not escape
# ===========================================================================

def test_close_failure_does_not_escape():
    """If db.close() raises, the exception must not propagate."""
    model = _make_mock_model()
    mock_session_cls = MagicMock()
    mock_db = MagicMock()
    mock_session_cls.return_value = mock_db
    mock_db.get.return_value = model
    mock_db.close.side_effect = Exception("Cannot close connection")

    with patch("app.services.ifc_background.SessionLocal", mock_session_cls), \
         patch("app.services.ifc_background.get_settings"), \
         patch("app.services.ifc_background.process_ifc_model"):
        process_ifc_model_background(42)   # must not raise
