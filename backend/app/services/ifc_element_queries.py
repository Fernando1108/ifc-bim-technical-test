"""
Read-only query service for IFC element detail.

Retrieves element identity, spatial context, and properties exclusively
from PostgreSQL. Never reopens the IFC file or invokes IfcOpenShell.

All DB access is side-effect free: no commit, flush, or rollback.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import and_, select
from sqlalchemy.orm import Session, aliased

from app.models.element import IfcElement
from app.models.element_property import ElementProperty
from app.models.spatial_node import SpatialNode


class IfcElementQueryError(Exception):
    """Raised when an unexpected DB error occurs during an IFC element query."""


@dataclass(frozen=True)
class IfcElementDetailData:
    element: IfcElement
    direct_spatial: Optional[SpatialNode]
    resolved_storey: Optional[SpatialNode]
    properties: list[ElementProperty]


def get_ifc_element_detail(
    db: Session,
    model_id: int,
    global_id: str,
) -> Optional[IfcElementDetailData]:
    """
    Return the full BIM detail of the element identified by (model_id, global_id).

    Uses two aliased SpatialNode instances to resolve both the direct spatial
    parent and the resolved storey in a single SQL query via OUTER JOIN.

    Returns None when no element matches.
    Raises IfcElementQueryError on unexpected DB failure.
    Does not commit, flush, or refresh.
    """
    try:
        direct_alias = aliased(SpatialNode)
        storey_alias = aliased(SpatialNode)

        stmt = (
            select(IfcElement, direct_alias, storey_alias)
            .outerjoin(
                direct_alias,
                and_(
                    IfcElement.direct_spatial_node_id == direct_alias.id,
                    direct_alias.model_id == IfcElement.model_id,
                ),
            )
            .outerjoin(
                storey_alias,
                and_(
                    IfcElement.resolved_storey_id == storey_alias.id,
                    storey_alias.model_id == IfcElement.model_id,
                ),
            )
            .where(IfcElement.model_id == model_id)
            .where(IfcElement.global_id == global_id)
        )

        row = db.execute(stmt).first()
    except Exception as exc:
        raise IfcElementQueryError(
            "Error al consultar el elemento IFC."
        ) from exc

    if row is None:
        return None

    element, direct_spatial, resolved_storey = row

    try:
        props_stmt = (
            select(ElementProperty)
            .where(ElementProperty.element_id == element.id)
            .order_by(
                ElementProperty.group_type,
                ElementProperty.group_name,
                ElementProperty.property_name,
                ElementProperty.id,
            )
        )
        properties = list(db.scalars(props_stmt).all())
    except Exception as exc:
        raise IfcElementQueryError(
            "Error al consultar las propiedades del elemento IFC."
        ) from exc

    return IfcElementDetailData(
        element=element,
        direct_spatial=direct_spatial,
        resolved_storey=resolved_storey,
        properties=properties,
    )
