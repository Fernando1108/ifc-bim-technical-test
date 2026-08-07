"""
IFC processing service.

Transitions an IfcModel through:
    PENDING → PROCESSING → COMPLETED
    PENDING → PROCESSING → FAILED  (on invalid/inaccessible/corrupt IFC,
                                    or on extraction failure)

Full processing pipeline (in order):
    1. Parse IFC with IfcOpenShell.
    2. Extract and persist spatial hierarchy (IfcProject … IfcSpace).
    3. Extract and persist elements/types/containment.
    4. Extract and persist PropertySets and Quantities.
    5. Persist COMPLETED.

Uses IfcOpenShell as the canonical IFC parser.
"""
from datetime import datetime, timezone
from pathlib import Path

import ifcopenshell
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.ifc_model import IfcModel
from app.services.ifc_elements import (
    IfcElementExtractionError,
    extract_and_persist_elements,
)
from app.services.ifc_properties import (
    IfcPropertyExtractionError,
    extract_and_persist_element_properties,
)
from app.services.ifc_spatial import (
    IfcSpatialExtractionError,
    extract_and_persist_spatial_structure,
)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class IfcProcessingError(Exception):
    """Base for IFC processing errors."""


class IfcInvalidProcessingStateError(IfcProcessingError):
    """Model is not in PENDING state — processing refused."""


class IfcProcessingPersistenceError(IfcProcessingError):
    """A required DB commit failed during processing."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_ifc_path(settings: Settings, storage_path: str) -> Path:
    """
    Safely resolve the physical path of an IFC file.

    Validates that storage_path is a bare filename:
      - not absolute
      - exactly one path component
      - Path(storage_path).name == storage_path

    Raises IfcProcessingError if the invariant is violated.
    Never includes the physical path in the exception message.
    """
    p = Path(storage_path)

    if p.is_absolute() or len(p.parts) != 1 or p.name != storage_path:
        raise IfcProcessingError(
            "La ruta de almacenamiento del modelo es inválida."
        )

    return settings.ifc_storage_dir / storage_path


def _persist_failed(
    db: Session,
    model: IfcModel,
    error_message: str,
) -> IfcModel:
    """
    Roll back any uncommitted state, mark the model as FAILED, and commit.

    Never leaks path, traceback, or IfcOpenShell exception details.

    Raises IfcProcessingPersistenceError if the FAILED commit itself fails.
    """
    db.rollback()

    model.status = "FAILED"
    model.ifc_schema = None
    model.error_message = error_message
    model.processed_at = datetime.now(timezone.utc)

    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        raise IfcProcessingPersistenceError(
            "Error al persistir el estado FAILED."
        ) from exc

    return model


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------

def process_ifc_model(
    db: Session,
    model: IfcModel,
    settings: Settings,
) -> IfcModel:
    """
    Process a persisted IfcModel using IfcOpenShell.

    Only PENDING models are accepted. Processing order:
      1. Guard: reject if not PENDING (IfcInvalidProcessingStateError).
      2. Transition to PROCESSING and commit (IfcProcessingPersistenceError on failure).
      3. Resolve storage_path defensively (FAILED if invalid).
      4. Open file with IfcOpenShell (FAILED if missing, corrupt, or not valid IFC).
      5. Extract spatial hierarchy (FAILED if IfcSpatialExtractionError).
      6. Extract elements (FAILED if IfcElementExtractionError).
      7. Extract properties/quantities (FAILED if IfcPropertyExtractionError).
      8. Transition to COMPLETED and commit (IfcProcessingPersistenceError on failure).

    Returns the model after processing (COMPLETED or FAILED).

    Raises:
        IfcInvalidProcessingStateError: model.status is not "PENDING".
        IfcProcessingPersistenceError:  a required DB commit failed.
    """
    # ------------------------------------------------------------------
    # 1. Guard: only PENDING models may be processed
    # ------------------------------------------------------------------
    if model.status != "PENDING":
        raise IfcInvalidProcessingStateError(
            f"El modelo está en estado '{model.status}' "
            "y no puede volver a procesarse."
        )

    # ------------------------------------------------------------------
    # 2. Transition to PROCESSING and commit
    # ------------------------------------------------------------------
    model.status = "PROCESSING"
    model.processing_started_at = datetime.now(timezone.utc)
    model.processed_at = None
    model.error_message = None

    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        raise IfcProcessingPersistenceError(
            "Error al persistir el estado PROCESSING."
        ) from exc

    # ------------------------------------------------------------------
    # 3. Defensive path resolution — treat violations as FAILED
    # ------------------------------------------------------------------
    try:
        full_path = _resolve_ifc_path(settings, model.storage_path)
    except IfcProcessingError:
        return _persist_failed(db, model, "No se pudo procesar el archivo IFC.")

    # ------------------------------------------------------------------
    # 4. Parse IFC with IfcOpenShell
    # ------------------------------------------------------------------
    try:
        ifc_file = ifcopenshell.open(str(full_path))
        ifc_schema = ifc_file.schema
    except Exception:
        return _persist_failed(db, model, "No se pudo procesar el archivo IFC.")

    # ------------------------------------------------------------------
    # 5. Extract spatial hierarchy
    # ------------------------------------------------------------------
    try:
        spatial_nodes = extract_and_persist_spatial_structure(db, model, ifc_file)
    except IfcSpatialExtractionError:
        return _persist_failed(db, model, "No se pudo procesar el archivo IFC.")

    # ------------------------------------------------------------------
    # 6. Extract elements
    # ------------------------------------------------------------------
    try:
        elements = extract_and_persist_elements(db, model, ifc_file, spatial_nodes)
    except IfcElementExtractionError:
        return _persist_failed(db, model, "No se pudo procesar el archivo IFC.")

    # ------------------------------------------------------------------
    # 7. Extract properties / quantities
    # ------------------------------------------------------------------
    try:
        extract_and_persist_element_properties(db, model, ifc_file, elements)
    except IfcPropertyExtractionError:
        return _persist_failed(db, model, "No se pudo procesar el archivo IFC.")

    # ------------------------------------------------------------------
    # 8. Persist COMPLETED — only reached when all extractors succeeded
    # ------------------------------------------------------------------
    model.ifc_schema = ifc_schema
    model.status = "COMPLETED"
    model.error_message = None
    model.processed_at = datetime.now(timezone.utc)

    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        raise IfcProcessingPersistenceError(
            "Error al persistir el estado COMPLETED."
        ) from exc

    return model
