"""
IFC spatial structure extraction and persistence service.

Extracts IfcProject, IfcSite, IfcBuilding, IfcBuildingStorey, IfcSpace
from an open IFC file and persists them as SpatialNode rows using a
two-flush strategy.

Does NOT commit or rollback — transaction control belongs to the caller.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.ifc_model import IfcModel
from app.models.spatial_node import SpatialNode

_SUPPORTED_TYPES: frozenset[str] = frozenset(
    {
        "IfcProject",
        "IfcSite",
        "IfcBuilding",
        "IfcBuildingStorey",
        "IfcSpace",
    }
)

_ERR_MSG = "No se pudo extraer la estructura espacial del archivo IFC."


class IfcSpatialExtractionError(Exception):
    """Raised when the spatial structure cannot be extracted or persisted."""


def _required_global_id(entity) -> str:
    value = entity.GlobalId
    if value is None:
        raise ValueError("Spatial entity without GlobalId")
    value = str(value)
    if not value.strip():
        raise ValueError("Spatial entity without GlobalId")
    return value


def _optional_str(entity, attr: str) -> str | None:
    """Return str(attr) if present and non-None, else None.

    AttributeError (attribute absent from schema) → None.
    Any other unexpected error propagates to the caller.
    """
    try:
        val = getattr(entity, attr)
    except AttributeError:
        return None
    return str(val) if val is not None else None


def _optional_float(entity, attr: str) -> float | None:
    """Return float(attr) if present and non-None, else None.

    AttributeError → None.
    Conversion errors (ValueError, TypeError) propagate.
    """
    try:
        val = getattr(entity, attr)
    except AttributeError:
        return None
    return float(val) if val is not None else None


def extract_and_persist_spatial_structure(
    db: Session,
    model: IfcModel,
    ifc_file,
) -> list[SpatialNode]:
    """
    Extract and persist the IFC spatial structure for *model*.

    Collects IfcProject, IfcSite, IfcBuilding, IfcBuildingStorey, IfcSpace,
    resolves parent/child via IfcRelAggregates, and persists them as
    SpatialNode rows using a two-flush strategy.

    Transaction control is the caller's responsibility.
    Never calls db.commit() or db.rollback().

    Returns the persisted SpatialNode list (empty when none found).

    Raises:
        IfcSpatialExtractionError: wraps any unexpected error during
            collection, transformation, or persistence.
    """
    try:
        # --------------------------------------------------------------
        # 1. Collect supported entities — deduplicated, ordered by STEP id
        # --------------------------------------------------------------
        seen: set[int] = set()
        entities: list = []
        for ifc_type in _SUPPORTED_TYPES:
            for entity in ifc_file.by_type(ifc_type):
                eid = entity.id()
                if eid not in seen:
                    seen.add(eid)
                    entities.append(entity)

        entities.sort(key=lambda e: e.id())

        if not entities:
            model.spatial_node_count = 0
            return []

        # --------------------------------------------------------------
        # 2. PASO 1 — build nodes (parent_id=None), flush to obtain PKs
        # --------------------------------------------------------------
        nodes: list[SpatialNode] = [
            SpatialNode(
                model_id=model.id,
                ifc_entity_id=entity.id(),
                global_id=_required_global_id(entity),
                ifc_type=entity.is_a(),
                name=_optional_str(entity, "Name"),
                description=_optional_str(entity, "Description"),
                long_name=_optional_str(entity, "LongName"),
                elevation=_optional_float(entity, "Elevation"),
                parent_id=None,
            )
            for entity in entities
        ]

        db.add_all(nodes)
        db.flush()

        # --------------------------------------------------------------
        # 3. PASO 2 — resolve parent_id via IfcRelAggregates, flush
        # --------------------------------------------------------------
        node_by_eid: dict[int, SpatialNode] = {n.ifc_entity_id: n for n in nodes}

        for rel in ifc_file.by_type("IfcRelAggregates"):
            parent_entity = rel.RelatingObject
            parent_eid = parent_entity.id()
            if parent_eid not in node_by_eid:
                continue
            parent_node = node_by_eid[parent_eid]
            for child_entity in rel.RelatedObjects:
                child_eid = child_entity.id()
                if child_eid not in node_by_eid:
                    continue
                node_by_eid[child_eid].parent_id = parent_node.id

        db.flush()

        # --------------------------------------------------------------
        # 4. Update counter
        # --------------------------------------------------------------
        model.spatial_node_count = len(nodes)

        return nodes

    except IfcSpatialExtractionError:
        raise
    except Exception as exc:
        raise IfcSpatialExtractionError(_ERR_MSG) from exc
