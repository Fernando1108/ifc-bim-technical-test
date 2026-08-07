"""
Background runner for IFC processing.

Executes process_ifc_model in a background task after a successful upload.

Rules:
- Receives only model_id (not the request Session, IfcModel ORM object, or user).
- Creates its own independent SessionLocal and closes it in finally.
- Delegates all processing logic to process_ifc_model().
- Never raises from the background task — all errors are logged generically.
- Never logs physical paths, SQL, secrets, or raw exception strings.
"""
import logging

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.ifc_model import IfcModel
from app.services.ifc_processing import (
    IfcInvalidProcessingStateError,
    IfcProcessingPersistenceError,
    process_ifc_model,
)

logger = logging.getLogger(__name__)


def process_ifc_model_background(model_id: int) -> None:
    """
    Background task: open a fresh DB session and process the IFC model.

    Called by FastAPI BackgroundTasks after POST /models persists the record.
    The request session is already closed by this point — this function owns
    its own session lifecycle entirely.

    Guarantees:
    - SessionLocal() construction is covered by the top-level guard.
    - db.close() is best-effort: failures are logged and do not escape.
    - No exception ever propagates out of this function.
    """
    db = None
    try:
        db = SessionLocal()
        model = db.get(IfcModel, model_id)

        if model is None:
            logger.warning(
                "Modelo background no encontrado: %s.",
                model_id,
            )
            return

        settings = get_settings()
        process_ifc_model(db, model, settings)

    except IfcInvalidProcessingStateError:
        logger.error(
            "Estado inválido en el procesamiento background del modelo %s.",
            model_id,
        )
    except IfcProcessingPersistenceError:
        logger.error(
            "Error de persistencia en el procesamiento background del modelo %s.",
            model_id,
        )
    except Exception:
        logger.error(
            "No se pudo completar el procesamiento background del modelo %s.",
            model_id,
        )
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:
                logger.error(
                    "Error al cerrar la sesión background del modelo %s.",
                    model_id,
                )
