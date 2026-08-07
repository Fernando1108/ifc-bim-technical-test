"""
Read-only query service for IfcModel.

All access is strictly scoped by owner_id.
Authorization is embedded in the SQL query — never post-filtered in Python.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ifc_model import IfcModel


class IfcModelQueryError(Exception):
    """Raised when an unexpected DB error occurs during an IFC model query."""


def list_ifc_models_for_owner(
    db: Session,
    owner_id: int,
) -> list[IfcModel]:
    """
    Return all IfcModels belonging to owner_id, ordered by creation time descending.

    Order is deterministic: primary key is used as a tie-breaker when two records
    share the same created_at timestamp.

    Does not commit, flush, or refresh.
    Raises IfcModelQueryError on unexpected DB failure.
    """
    try:
        stmt = (
            select(IfcModel)
            .where(IfcModel.owner_id == owner_id)
            .order_by(IfcModel.created_at.desc(), IfcModel.id.desc())
        )
        return list(db.scalars(stmt).all())
    except Exception as exc:
        raise IfcModelQueryError(
            "Error al consultar los modelos IFC."
        ) from exc


def get_ifc_model_for_owner(
    db: Session,
    model_id: int,
    owner_id: int,
) -> IfcModel | None:
    """
    Return the IfcModel with the given id that belongs to owner_id, or None.

    Authorization is part of the SQL query — both model_id and owner_id are
    evaluated simultaneously. A missing record and a record owned by a different
    user are indistinguishable: both return None.

    Does not commit, flush, or refresh.
    Raises IfcModelQueryError on unexpected DB failure.
    """
    try:
        stmt = (
            select(IfcModel)
            .where(IfcModel.id == model_id)
            .where(IfcModel.owner_id == owner_id)
        )
        return db.scalars(stmt).first()
    except Exception as exc:
        raise IfcModelQueryError(
            "Error al consultar el modelo IFC."
        ) from exc
