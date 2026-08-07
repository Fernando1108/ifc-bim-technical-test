from sqlalchemy.orm import Session

from app.models.ifc_model import IfcModel
from app.models.user import User
from app.services.ifc_storage import StoredIfcFile


class IfcModelPersistenceError(Exception):
    pass


def persist_ifc_model(
    db: Session,
    current_user: User,
    stored: StoredIfcFile,
) -> IfcModel:
    """
    Persist a stored IFC file as an IfcModel record.

    Transaction order: add → flush → refresh → commit.
    Using flush before commit means the INSERT is sent to the DB engine and
    server-generated values (id, created_at, etc.) are available for refresh.
    Only after a successful refresh does commit confirm the transaction.
    If any step fails, rollback is called and IfcModelPersistenceError is raised.
    The caller is responsible for cleaning up the stored file when this raises.
    """
    model = IfcModel(
        owner_id=current_user.id,
        original_filename=stored.original_filename,
        storage_path=stored.storage_path,
        file_size_bytes=stored.file_size_bytes,
        sha256=stored.sha256,
        status="PENDING",
    )
    try:
        db.add(model)
        db.flush()       # send INSERT; server assigns id, timestamps
        db.refresh(model)  # load server-generated values
        db.commit()      # confirm only if flush+refresh succeeded
    except Exception as exc:
        db.rollback()
        raise IfcModelPersistenceError(
            "Error al registrar el modelo en la base de datos."
        ) from exc
    return model
