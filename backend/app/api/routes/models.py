from pathlib import Path, PureWindowsPath

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_user
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models.user import User
from app.schemas.ifc_analytics import (
    IfcAnalyticsElementItem,
    IfcAnalyticsElementPage,
    IfcAnalyticsElementStorey,
    IfcAnalyticsStoreyCount,
    IfcAnalyticsTypeCount,
    IfcModelAnalyticsResponse,
)
from app.schemas.ifc_element import (
    IfcElementDetailResponse,
    IfcElementPropertyResponse,
    IfcSpatialNodeSummary,
)
from app.schemas.ifc_model import IfcModelResponse
from app.services.ifc_background import process_ifc_model_background
from app.services.ifc_analytics import (
    IfcAnalyticsQueryError,
    get_ifc_elements_page,
    get_ifc_model_analytics,
)
from app.services.ifc_element_queries import (
    IfcElementQueryError,
    get_ifc_element_detail,
)
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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_model_ifc_path(settings: Settings, storage_path: str) -> Path:
    """
    Safely resolve the physical path of a stored IFC file.

    Validates that storage_path is a bare filename (no directory components,
    not absolute). Then resolves the candidate path and confirms it stays
    inside the storage root — protecting against path traversal and symlink
    escape attacks.

    Raises ValueError with a generic message on any invariant violation.
    Never includes the physical path or storage_path in the exception.
    """
    # POSIX check: rejects /etc/passwd, ../secret.ifc, subdir/model.ifc
    p = Path(storage_path)
    if p.is_absolute() or len(p.parts) != 1 or p.name != storage_path:
        raise ValueError("Invalid storage path")

    # Windows check: rejects C:\secret.ifc, C:model.ifc, subdir\model.ifc,
    # \\server\share\model.ifc — even when running on Linux where Path()
    # would not flag Windows-style paths as absolute or multi-component.
    wp = PureWindowsPath(storage_path)
    if wp.is_absolute() or wp.drive or len(wp.parts) != 1 or wp.name != storage_path:
        raise ValueError("Invalid storage path (Windows semantics)")

    try:
        storage_root = settings.ifc_storage_dir.resolve()
        candidate = (storage_root / storage_path).resolve()
    except Exception as exc:
        raise ValueError("Path resolution failed") from exc

    if candidate.parent != storage_root:
        raise ValueError("Path escapes storage root")

    return candidate


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


@router.get(
    "/{model_id}/file",
    status_code=status.HTTP_200_OK,
    response_class=FileResponse,
)
def download_ifc_file(
    model_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    """
    Stream the raw IFC file for a COMPLETED model owned by the authenticated user.

    Security guarantees:
    - Requires valid Bearer JWT.
    - IDOR-protected: model_id + owner_id evaluated together in SQL.
    - Only COMPLETED models are served; PENDING/PROCESSING/FAILED → 409.
    - storage_path validated as a bare filename before filesystem access.
    - Candidate path resolved and confirmed to remain inside the storage root
      (protects against path traversal and symlink escape).
    - Physical existence verified via is_file() before responding.
    - No storage_path or physical paths exposed in error messages or responses.
    - Read-only: no DB writes, commits, or flushes.
    """
    # 1. Fetch model, enforce ownership (IDOR guard)
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

    # 2. Status guard — only COMPLETED models are available for download
    if model.status != "COMPLETED":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El archivo IFC no está disponible para visualización.",
        )

    # 3. Resolve path defensively — reject traversal, absolute paths, symlink escape
    try:
        candidate = _resolve_model_ifc_path(settings, model.storage_path)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno al acceder al archivo IFC.",
        )

    # 4. Verify the file exists and is a regular file
    try:
        is_regular_file = candidate.is_file()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno al acceder al archivo IFC.",
        )

    if not is_regular_file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Archivo IFC no disponible.",
        )

    # 5. Stream file — original_filename used for Content-Disposition, not storage_path
    return FileResponse(
        path=candidate,
        media_type="application/octet-stream",
        filename=model.original_filename,
    )


@router.get(
    "/{model_id}/analytics",
    response_model=IfcModelAnalyticsResponse,
    status_code=status.HTTP_200_OK,
)
def get_model_analytics(
    model_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> IfcModelAnalyticsResponse:
    """
    Return aggregated BIM analytics for a COMPLETED model owned by the authenticated user.

    Security guarantees:
    - Requires valid Bearer JWT.
    - IDOR-protected: model_id + owner_id evaluated together in SQL.
    - Only COMPLETED models have analytics available.
    - Never reopens the IFC file; all data comes exclusively from PostgreSQL.
    - Read-only: no DB writes, commits, flushes, or rollbacks.
    """
    # 1. Authorize model — IDOR guard
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

    # 2. Status guard — analytics only available for COMPLETED models
    if model.status != "COMPLETED":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La información analítica del modelo no está disponible.",
        )

    # 3. Query analytics
    try:
        data = get_ifc_model_analytics(
            db,
            model_id,
            total_elements=model.element_count,
            total_spatial_nodes=model.spatial_node_count,
            total_properties=model.property_count,
        )
    except IfcAnalyticsQueryError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno al consultar la información analítica.",
        )

    return IfcModelAnalyticsResponse(
        total_elements=data.total_elements,
        total_spatial_nodes=data.total_spatial_nodes,
        total_properties=data.total_properties,
        by_ifc_type=[
            IfcAnalyticsTypeCount(ifc_type=r.ifc_type, count=r.count)
            for r in data.by_ifc_type
        ],
        by_storey=[
            IfcAnalyticsStoreyCount(
                global_id=r.global_id,
                name=r.name,
                elevation=r.elevation,
                count=r.count,
            )
            for r in data.by_storey
        ],
        without_storey_count=data.without_storey_count,
    )


@router.get(
    "/{model_id}/elements",
    response_model=IfcAnalyticsElementPage,
    status_code=status.HTTP_200_OK,
)
def list_model_elements(
    model_id: int,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> IfcAnalyticsElementPage:
    """
    Return a paginated list of BIM elements for a COMPLETED model owned by the
    authenticated user.

    Security guarantees:
    - Requires valid Bearer JWT.
    - IDOR-protected: model_id + owner_id evaluated together in SQL.
    - Only COMPLETED models have element data available.
    - Never reopens the IFC file; all data comes exclusively from PostgreSQL.
    - Pagination applied in SQL — does not load full table into Python.
    - Read-only: no DB writes, commits, flushes, or rollbacks.
    """
    # 1. Authorize model — IDOR guard
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

    # 2. Status guard
    if model.status != "COMPLETED":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La información analítica del modelo no está disponible.",
        )

    # 3. Query elements page
    try:
        page = get_ifc_elements_page(db, model_id, limit=limit, offset=offset)
    except IfcAnalyticsQueryError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno al consultar la información analítica.",
        )

    return IfcAnalyticsElementPage(
        total=page.total,
        limit=page.limit,
        offset=page.offset,
        items=[
            IfcAnalyticsElementItem(
                ifc_entity_id=item.ifc_entity_id,
                global_id=item.global_id,
                ifc_type=item.ifc_type,
                name=item.name,
                object_type=item.object_type,
                tag=item.tag,
                predefined_type=item.predefined_type,
                type_ifc_type=item.type_ifc_type,
                type_name=item.type_name,
                storey=(
                    IfcAnalyticsElementStorey(
                        global_id=item.storey.global_id,
                        name=item.storey.name,
                        elevation=item.storey.elevation,
                    )
                    if item.storey is not None
                    else None
                ),
            )
            for item in page.items
        ],
    )


@router.get(
    "/{model_id}/elements/{global_id}",
    response_model=IfcElementDetailResponse,
    status_code=status.HTTP_200_OK,
)
def get_element_detail(
    model_id: int,
    global_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> IfcElementDetailResponse:
    """
    Retrieve the persisted BIM detail of a single IFC element.

    Identified by model_id + global_id (IFC compressed GlobalId).

    Security guarantees:
    - Requires valid Bearer JWT.
    - IDOR-protected: model ownership is verified before the element is queried.
    - Only COMPLETED models have BIM data available.
    - Never reopens the IFC file; all data comes exclusively from PostgreSQL.
    - Read-only: no DB writes, commits, flushes, or rollbacks.
    - Missing model and wrong-owner model both return 404 (no IDOR leak).
    """
    # 1. Authorize model — IDOR guard
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

    # 2. Status guard — BIM data only available for COMPLETED models
    if model.status != "COMPLETED":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La información BIM del modelo no está disponible.",
        )

    # 3. Query element detail
    try:
        detail = get_ifc_element_detail(db, model_id, global_id)
    except IfcElementQueryError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno al consultar el elemento IFC.",
        )
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Elemento IFC no encontrado.",
        )

    # 4. Serialize — copy only permitted fields; no internal ids exposed
    return IfcElementDetailResponse(
        ifc_entity_id=detail.element.ifc_entity_id,
        global_id=detail.element.global_id,
        ifc_type=detail.element.ifc_type,
        name=detail.element.name,
        description=detail.element.description,
        object_type=detail.element.object_type,
        tag=detail.element.tag,
        predefined_type=detail.element.predefined_type,
        type_global_id=detail.element.type_global_id,
        type_ifc_type=detail.element.type_ifc_type,
        type_name=detail.element.type_name,
        direct_spatial=(
            IfcSpatialNodeSummary.model_validate(detail.direct_spatial)
            if detail.direct_spatial is not None
            else None
        ),
        resolved_storey=(
            IfcSpatialNodeSummary.model_validate(detail.resolved_storey)
            if detail.resolved_storey is not None
            else None
        ),
        properties=[
            IfcElementPropertyResponse.model_validate(p)
            for p in detail.properties
        ],
    )
