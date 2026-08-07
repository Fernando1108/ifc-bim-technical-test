"""
IFC elements extraction and persistence service.

Extracts all IfcElement subtypes, resolves type info, direct spatial
containment, parent element decomposition, and resolved storey.

Does NOT commit or rollback — transaction control belongs to the caller.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.element import IfcElement
from app.models.ifc_model import IfcModel
from app.models.spatial_node import SpatialNode

_ERR_MSG = "No se pudieron extraer los elementos del archivo IFC."


class IfcElementExtractionError(Exception):
    """Raised when elements cannot be extracted or persisted."""


# ---------------------------------------------------------------------------
# Attribute helpers
# ---------------------------------------------------------------------------

def _required_global_id(entity) -> str:
    value = entity.GlobalId
    if value is None:
        raise ValueError("Element entity without GlobalId")
    value = str(value)
    if not value.strip():
        raise ValueError("Element entity without GlobalId")
    return value


def _optional_str(entity, attr: str) -> str | None:
    """Return str(attr) if present and non-None, else None.

    AttributeError (attribute absent from schema) → None.
    Any other error propagates.
    """
    try:
        val = getattr(entity, attr)
    except AttributeError:
        return None
    return str(val) if val is not None else None


def _type_global_id(rel_type) -> str | None:
    """Get GlobalId from a type entity.

    None or blank → None (not an error — types may lack GlobalId).
    AttributeError (attribute absent from schema) → None.
    Unexpected errors propagate to the global guard.
    """
    try:
        val = rel_type.GlobalId
    except AttributeError:
        return None
    if val is None:
        return None
    s = str(val)
    return s if s.strip() else None


# ---------------------------------------------------------------------------
# Storey resolution helpers (iterative, memoized, cycle-safe)
# ---------------------------------------------------------------------------

def _find_storey_for_sn(
    sn_id: int,
    sn_by_id: dict[int, SpatialNode],
    memo: dict[int, int | None],
) -> int | None:
    """Walk SpatialNode.parent_id to find the closest IfcBuildingStorey.

    Memoizes intermediate results. Cycle → None.
    """
    path: list[int] = []
    in_path: set[int] = set()
    cur: int | None = sn_id

    while cur is not None:
        if cur in memo:
            result = memo[cur]
            for x in path:
                memo[x] = result
            return result
        if cur in in_path:
            for x in path:
                memo[x] = None
            return None
        node = sn_by_id.get(cur)
        if node is None:
            for x in path:
                memo[x] = None
            return None
        if node.ifc_type == "IfcBuildingStorey":
            result = node.id
            path.append(cur)
            for x in path:
                memo[x] = result
            return result
        path.append(cur)
        in_path.add(cur)
        cur = node.parent_id

    for x in path:
        memo[x] = None
    return None


def _resolve_element_storey(
    el_id: int,
    el_by_id: dict[int, IfcElement],
    sn_by_id: dict[int, SpatialNode],
    sn_memo: dict[int, int | None],
    el_memo: dict[int, int | None],
) -> int | None:
    """Resolve resolved_storey_id for an element.

    Priority: direct containment → walk spatial tree.
    Fallback: inherit from parent_element chain.
    Memoizes. Cycle → None.
    """
    path: list[int] = []
    in_path: set[int] = set()
    cur: int | None = el_id

    while cur is not None:
        if cur in el_memo:
            result = el_memo[cur]
            for x in path:
                el_memo[x] = result
            return result
        if cur in in_path:
            for x in path:
                el_memo[x] = None
            return None
        elem = el_by_id.get(cur)
        if elem is None:
            for x in path:
                el_memo[x] = None
            return None
        # Try direct containment first — resolve via spatial tree
        if elem.direct_spatial_node_id is not None:
            result = _find_storey_for_sn(elem.direct_spatial_node_id, sn_by_id, sn_memo)
            if result is not None:
                path.append(cur)
                for x in path:
                    el_memo[x] = result
                return result
            # Direct containment exists but spatial tree can't resolve storey;
            # fall through to parent_element_id chain.
        # No direct containment (or direct didn't resolve) — inherit from parent element
        path.append(cur)
        in_path.add(cur)
        cur = elem.parent_element_id

    for x in path:
        el_memo[x] = None
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_and_persist_elements(
    db: Session,
    model: IfcModel,
    ifc_file,
    spatial_nodes: list[SpatialNode],
) -> list[IfcElement]:
    """
    Extract and persist all IfcElement entities from ifc_file.

    Resolves:
    - type info via IfcRelDefinesByType
    - direct spatial containment via IfcRelContainedInSpatialStructure
    - element decomposition via IfcRelAggregates (elements only)
    - resolved storey (spatial walk + parent element inheritance)

    All relation resolution uses first-match-wins ordered by rel.id()
    for determinism in IFC files with duplicate assignments.

    Transaction control is the caller's responsibility.
    Never calls db.commit() or db.rollback().

    Args:
        db:             SQLAlchemy session (no commit/rollback called).
        model:          IfcModel being processed (element_count updated).
        ifc_file:       Open ifcopenshell file object.
        spatial_nodes:  SpatialNode list from extract_and_persist_spatial_structure.
                        May be empty; must all belong to model with DB ids.

    Returns:
        Persisted IfcElement list (empty when no elements found).

    Raises:
        IfcElementExtractionError: wraps any unexpected error during
            validation, collection, transformation, or persistence.
    """
    try:
        # ------------------------------------------------------------------
        # 0. Validate spatial_nodes input
        # ------------------------------------------------------------------
        for sn in spatial_nodes:
            if sn.model_id != model.id:
                raise ValueError("SpatialNode belongs to a different model")
            if sn.id is None:
                raise ValueError(
                    "SpatialNode has no DB id — flush spatial structure first"
                )

        sn_by_id: dict[int, SpatialNode] = {sn.id: sn for sn in spatial_nodes}
        sn_by_eid: dict[int, SpatialNode] = {sn.ifc_entity_id: sn for sn in spatial_nodes}

        # ------------------------------------------------------------------
        # 1. Collect IfcElement — deduplicated, ordered by STEP id
        # ------------------------------------------------------------------
        seen: set[int] = set()
        entities: list = []
        for entity in ifc_file.by_type("IfcElement"):
            eid = entity.id()
            if eid not in seen:
                seen.add(eid)
                entities.append(entity)

        entities.sort(key=lambda e: e.id())

        if not entities:
            model.element_count = 0
            return []

        # ------------------------------------------------------------------
        # 2. PASO 1 — build elements (relations = None), flush for PKs
        # ------------------------------------------------------------------
        elements: list[IfcElement] = [
            IfcElement(
                model_id=model.id,
                ifc_entity_id=entity.id(),
                global_id=_required_global_id(entity),
                ifc_type=entity.is_a(),
                name=_optional_str(entity, "Name"),
                description=_optional_str(entity, "Description"),
                object_type=_optional_str(entity, "ObjectType"),
                tag=_optional_str(entity, "Tag"),
                predefined_type=_optional_str(entity, "PredefinedType"),
                type_global_id=None,
                type_ifc_type=None,
                type_name=None,
                direct_spatial_node_id=None,
                resolved_storey_id=None,
                parent_element_id=None,
            )
            for entity in entities
        ]

        db.add_all(elements)
        db.flush()

        # ------------------------------------------------------------------
        # 3. Build element mappings (DB ids now assigned)
        # ------------------------------------------------------------------
        el_by_eid: dict[int, IfcElement] = {el.ifc_entity_id: el for el in elements}
        el_by_id: dict[int, IfcElement] = {el.id: el for el in elements}

        # ------------------------------------------------------------------
        # 4. Resolve type info (IfcRelDefinesByType) — first rel wins
        # ------------------------------------------------------------------
        assigned_type: set[int] = set()
        for rel in sorted(ifc_file.by_type("IfcRelDefinesByType"), key=lambda r: r.id()):
            rel_type = rel.RelatingType
            for elem_entity in rel.RelatedObjects:
                elem = el_by_eid.get(elem_entity.id())
                if elem is None or elem.id in assigned_type:
                    continue
                elem.type_global_id = _type_global_id(rel_type)
                elem.type_ifc_type = rel_type.is_a()
                elem.type_name = _optional_str(rel_type, "Name")
                assigned_type.add(elem.id)

        # ------------------------------------------------------------------
        # 5. Resolve direct containment — first rel wins
        # ------------------------------------------------------------------
        assigned_containment: set[int] = set()
        for rel in sorted(
            ifc_file.by_type("IfcRelContainedInSpatialStructure"),
            key=lambda r: r.id(),
        ):
            sn = sn_by_eid.get(rel.RelatingStructure.id())
            if sn is None:
                continue
            for child in rel.RelatedElements:
                elem = el_by_eid.get(child.id())
                if elem is None or elem.id in assigned_containment:
                    continue
                elem.direct_spatial_node_id = sn.id
                assigned_containment.add(elem.id)

        # ------------------------------------------------------------------
        # 6. Resolve parent element via IfcRelAggregates — first rel wins
        #    Only when both RelatingObject AND child are IfcElement
        # ------------------------------------------------------------------
        assigned_parent: set[int] = set()
        for rel in sorted(ifc_file.by_type("IfcRelAggregates"), key=lambda r: r.id()):
            parent_elem = el_by_eid.get(rel.RelatingObject.id())
            if parent_elem is None:
                continue
            for child in rel.RelatedObjects:
                child_elem = el_by_eid.get(child.id())
                if child_elem is None or child_elem.id in assigned_parent:
                    continue
                child_elem.parent_element_id = parent_elem.id
                assigned_parent.add(child_elem.id)

        # ------------------------------------------------------------------
        # 7. Resolve storey (iterative, memoized, cycle-safe)
        # ------------------------------------------------------------------
        sn_storey_memo: dict[int, int | None] = {}
        el_storey_memo: dict[int, int | None] = {}

        for elem in elements:
            elem.resolved_storey_id = _resolve_element_storey(
                elem.id, el_by_id, sn_by_id, sn_storey_memo, el_storey_memo
            )

        # ------------------------------------------------------------------
        # 8. PASO 2 — flush updated relations
        # ------------------------------------------------------------------
        db.flush()

        # ------------------------------------------------------------------
        # 9. Update counter
        # ------------------------------------------------------------------
        model.element_count = len(elements)

        return elements

    except IfcElementExtractionError:
        raise
    except Exception as exc:
        raise IfcElementExtractionError(_ERR_MSG) from exc
