"""
Read-only analytics service for persisted BIM data.

All queries are scoped by model_id.
Joins with spatial_nodes always include model_id in the ON clause.
No commit, flush, or rollback.
Never opens IFC files or invokes IfcOpenShell.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import and_, func, nullslast, select
from sqlalchemy.orm import Session, aliased

from app.models.element import IfcElement
from app.models.spatial_node import SpatialNode


class IfcAnalyticsQueryError(Exception):
    """Raised when an unexpected DB error occurs during analytics queries."""


# ---------------------------------------------------------------------------
# Internal transport types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TypeCountRow:
    ifc_type: str
    count: int


@dataclass(frozen=True)
class StoreyCountRow:
    global_id: str
    name: Optional[str]
    elevation: Optional[float]
    count: int


@dataclass(frozen=True)
class IfcAnalyticsData:
    total_elements: int
    total_spatial_nodes: int
    total_properties: int
    by_ifc_type: list[TypeCountRow]
    by_storey: list[StoreyCountRow]
    without_storey_count: int


@dataclass(frozen=True)
class ElementStoreyRow:
    global_id: str
    name: Optional[str]
    elevation: Optional[float]


@dataclass(frozen=True)
class ElementPageRow:
    ifc_entity_id: int
    global_id: str
    ifc_type: str
    name: Optional[str]
    object_type: Optional[str]
    tag: Optional[str]
    predefined_type: Optional[str]
    type_ifc_type: Optional[str]
    type_name: Optional[str]
    storey: Optional[ElementStoreyRow]


@dataclass(frozen=True)
class IfcElementPageData:
    total: int
    limit: int
    offset: int
    items: list[ElementPageRow] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def get_ifc_model_analytics(
    db: Session,
    model_id: int,
    total_elements: int,
    total_spatial_nodes: int,
    total_properties: int,
) -> IfcAnalyticsData:
    """
    Return aggregated analytics for the model identified by model_id.

    Totals are passed in from the IfcModel record (already authorized).
    Aggregations are computed from the elements and spatial_nodes tables.

    Raises IfcAnalyticsQueryError on unexpected DB failure.
    Does not commit, flush, or rollback.
    """
    try:
        by_ifc_type = _query_by_ifc_type(db, model_id)
    except Exception as exc:
        raise IfcAnalyticsQueryError(
            "Error al consultar la información analítica IFC."
        ) from exc

    try:
        by_storey = _query_by_storey(db, model_id)
    except Exception as exc:
        raise IfcAnalyticsQueryError(
            "Error al consultar la información analítica IFC."
        ) from exc

    try:
        without_storey_count = _query_without_storey_count(db, model_id)
    except Exception as exc:
        raise IfcAnalyticsQueryError(
            "Error al consultar la información analítica IFC."
        ) from exc

    return IfcAnalyticsData(
        total_elements=total_elements,
        total_spatial_nodes=total_spatial_nodes,
        total_properties=total_properties,
        by_ifc_type=by_ifc_type,
        by_storey=by_storey,
        without_storey_count=without_storey_count,
    )


def get_ifc_elements_page(
    db: Session,
    model_id: int,
    limit: int,
    offset: int,
) -> IfcElementPageData:
    """
    Return a paginated list of elements for the model identified by model_id.

    total represents ALL elements regardless of limit/offset.
    Pagination is applied in SQL (not in Python).
    Storey join is scoped by model_id.

    Raises IfcAnalyticsQueryError on unexpected DB failure.
    Does not commit, flush, or rollback.
    """
    try:
        total = _query_element_total(db, model_id)
    except Exception as exc:
        raise IfcAnalyticsQueryError(
            "Error al consultar la información analítica IFC."
        ) from exc

    try:
        items = _query_element_page(db, model_id, limit, offset)
    except Exception as exc:
        raise IfcAnalyticsQueryError(
            "Error al consultar la información analítica IFC."
        ) from exc

    return IfcElementPageData(
        total=total,
        limit=limit,
        offset=offset,
        items=items,
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _query_by_ifc_type(db: Session, model_id: int) -> list[TypeCountRow]:
    stmt = (
        select(IfcElement.ifc_type, func.count().label("count"))
        .where(IfcElement.model_id == model_id)
        .group_by(IfcElement.ifc_type)
        .order_by(func.count().desc(), IfcElement.ifc_type.asc())
    )
    rows = db.execute(stmt).all()
    return [TypeCountRow(ifc_type=r.ifc_type, count=r.count) for r in rows]


def _query_by_storey(db: Session, model_id: int) -> list[StoreyCountRow]:
    storey_alias = aliased(SpatialNode)
    stmt = (
        select(
            storey_alias.global_id,
            storey_alias.name,
            storey_alias.elevation,
            func.count(IfcElement.id).label("count"),
        )
        .join(
            storey_alias,
            and_(
                IfcElement.resolved_storey_id == storey_alias.id,
                storey_alias.model_id == IfcElement.model_id,
                storey_alias.ifc_type == "IfcBuildingStorey",
            ),
        )
        .where(IfcElement.model_id == model_id)
        .group_by(
            storey_alias.global_id,
            storey_alias.name,
            storey_alias.elevation,
        )
        .order_by(
            nullslast(storey_alias.elevation.asc()),
            storey_alias.name.asc(),
            storey_alias.global_id.asc(),
        )
    )
    rows = db.execute(stmt).all()
    return [
        StoreyCountRow(
            global_id=r.global_id,
            name=r.name,
            elevation=r.elevation,
            count=r.count,
        )
        for r in rows
    ]


def _query_without_storey_count(db: Session, model_id: int) -> int:
    stmt = (
        select(func.count())
        .select_from(IfcElement)
        .where(IfcElement.model_id == model_id)
        .where(IfcElement.resolved_storey_id.is_(None))
    )
    return db.scalar(stmt) or 0


def _query_element_total(db: Session, model_id: int) -> int:
    stmt = (
        select(func.count())
        .select_from(IfcElement)
        .where(IfcElement.model_id == model_id)
    )
    return db.scalar(stmt) or 0


def _query_element_page(
    db: Session,
    model_id: int,
    limit: int,
    offset: int,
) -> list[ElementPageRow]:
    storey_alias = aliased(SpatialNode)
    stmt = (
        select(IfcElement, storey_alias)
        .outerjoin(
            storey_alias,
            and_(
                IfcElement.resolved_storey_id == storey_alias.id,
                storey_alias.model_id == IfcElement.model_id,
            ),
        )
        .where(IfcElement.model_id == model_id)
        .order_by(IfcElement.ifc_entity_id.asc(), IfcElement.id.asc())
        .offset(offset)
        .limit(limit)
    )
    rows = db.execute(stmt).all()
    result = []
    for element, storey in rows:
        storey_data = (
            ElementStoreyRow(
                global_id=storey.global_id,
                name=storey.name,
                elevation=storey.elevation,
            )
            if storey is not None
            else None
        )
        result.append(
            ElementPageRow(
                ifc_entity_id=element.ifc_entity_id,
                global_id=element.global_id,
                ifc_type=element.ifc_type,
                name=element.name,
                object_type=element.object_type,
                tag=element.tag,
                predefined_type=element.predefined_type,
                type_ifc_type=element.type_ifc_type,
                type_name=element.type_name,
                storey=storey_data,
            )
        )
    return result
