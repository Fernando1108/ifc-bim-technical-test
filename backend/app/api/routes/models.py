from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_user
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models.user import User
from app.schemas.ifc_model import IfcModelResponse
from app.services.ifc_background import process_ifc_model_background
from app.services.ifc_models import IfcModelPersistenceError, persist_ifc_model
from app.services.ifc_queries import (
    IfcModelQueryError,
    get_ifc_model_for_owner,
    list_ifc_models_for_owner,
)
from app.services.ifc_storage import (
    EmptyIfcFileError,
    IfcFileTooLargeError,
    IfcStorageError,
    InvalidIfcExtensionError,
    InvalidIfcFilenameError,
    save_ifc_file,
)

router = APIRouter(prefix="/models", tags=["models"])


@router.get(
    "",
    response_model=list[IfcModelResponse],
    status_code=status.HTTP_200_OK,
)
def list_models(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[IfcModelResponse]:
    """
    List all IFC models belonging to the authenticated user.

    Returns an empty list when the user has no models.
    Results are ordered by creation time descending.
    """
    try:
        models = list_ifc_models_for_owner(db, current_user.id)
    except IfcModelQueryError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno al consultar los modelos.",
        )
    return models


@router.get(
    "/{model_id}",
    response_model=IfcModelResponse,
    status_code=status.HTTP_200_OK,
)
def get_model(
    model_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> IfcModelResponse:
    """
    Retrieve a single IFC model by id, scoped to the authenticated user.

    Returns 404 both when the model does not exist and when it belongs to a
    different user — this prevents IDOR and avoids leaking resource existence.
    """
    try:
        model = get_ifc_model_for_owner(db, model_id, current_user.id)
    except IfcModelQueryError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno al consultar el modelo.",
        )
    if model is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Modelo IFC no encontrado.",
        )
    return model


@router.post(
    "",
    response_model=IfcModelResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_ifc(
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = ...,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> IfcModelResponse:
    """
    Upload an IFC file and register it as a new model in PENDING state.

    - Requires a valid Bearer JWT.
    - Accepts only files with .ifc extension (case-insensitive).
    - Stores the file locally using a UUID-based name.
    - Responds HTTP 201 with the model metadata (excludes storage_path and owner_id).
    - Schedules background IFC processing only after successful persistence.
    """
    try:
        stored = await save_ifc_file(file, settings)
    except (InvalidIfcFilenameError, InvalidIfcExtensionError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except EmptyIfcFileError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo está vacío.",
        )
    except IfcFileTooLargeError:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="El archivo supera el tamaño máximo permitido.",
        )
    except IfcStorageError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno al procesar el archivo.",
        )

    try:
        ifc_model = persist_ifc_model(db, current_user, stored)
    except IfcModelPersistenceError:
        # Best-effort cleanup: remove the stored file to avoid orphans.
        # A failure here must not replace the original error or leak path details.
        try:
            final_path = settings.ifc_storage_dir / stored.storage_path
            final_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno al registrar el modelo.",
        )

    # Schedule background processing only after successful persistence.
    # The response is returned immediately with status PENDING.
    background_tasks.add_task(process_ifc_model_background, ifc_model.id)

    return IfcModelResponse.model_validate(ifc_model)
