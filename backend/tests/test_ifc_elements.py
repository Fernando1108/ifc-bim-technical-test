"""
Tests for the ifc_elements service.

Uses real IfcOpenShell to build in-memory IFC files.
Uses FakeSession — no PostgreSQL required.
SpatialNode objects are created manually with pre-assigned DB ids
(simulating what extract_and_persist_spatial_structure would produce).
"""
import pytest
import ifcopenshell
import ifcopenshell.guid

from app.models.element import IfcElement
from app.models.spatial_node import SpatialNode
from app.services.ifc_elements import (
    IfcElementExtractionError,
    extract_and_persist_elements,
)


# ===========================================================================
# Fake session
# ===========================================================================

class FakeSession:
    def __init__(self):
        self._objects: list = []
        self.flush_count = 0
        self.add_all_count = 0
        self._next_id = 1
        self.committed = False
        self.rolled_back = False

    def add_all(self, objects):
        self.add_all_count += 1
        self._objects.extend(objects)

    def flush(self):
        self.flush_count += 1
        for obj in self._objects:
            if getattr(obj, "id", None) is None:
                obj.id = self._next_id
                self._next_id += 1

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


class FailingSession(FakeSession):
    """Raises RuntimeError on the Nth flush (1-based)."""

    def __init__(self, fail_on: int):
        super().__init__()
        self._fail_on = fail_on

    def flush(self):
        if self.flush_count + 1 == self._fail_on:
            self.flush_count += 1
            raise RuntimeError("Simulated DB flush error")
        super().flush()


# ===========================================================================
# Fake model
# ===========================================================================

class FakeModel:
    def __init__(self, model_id: int = 1):
        self.id = model_id
        self.spatial_node_count = 0
        self.element_count = 0
        self.property_count = 0
        self.status = "PROCESSING"
        self.ifc_schema = None
        self.error_message = None
        self.processing_started_at = None
        self.processed_at = None


# ===========================================================================
# SpatialNode helper
# ===========================================================================

def _make_sn(
    *,
    db_id: int,
    ifc_entity_id: int,
    ifc_type: str,
    global_id: str,
    model_id: int = 1,
    parent_id: int | None = None,
    name: str | None = None,
) -> SpatialNode:
    """Build a SpatialNode with a pre-assigned DB id (post-flush simulation)."""
    sn = SpatialNode(
        model_id=model_id,
        ifc_entity_id=ifc_entity_id,
        global_id=global_id,
        ifc_type=ifc_type,
        name=name,
    )
    sn.id = db_id
    sn.parent_id = parent_id
    return sn


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture
def ifc4_setup():
    """
    IFC4 file with full element fixture.

    Spatial IFC entities: Project, Site, Building, Storey1, Space1.
    Elements:
      - wall:     in Storey1, has WallType (IfcRelDefinesByType),
                  Name/Description/ObjectType/Tag/PredefinedType set.
      - door:     in Space1 (Space1.parent = Storey1 → resolves to Storey1).
      - assembly: in Storey1, parent of beam.
      - beam:     child of assembly via IfcRelAggregates,
                  no direct containment → inherits storey from assembly.

    SpatialNodes returned with DB ids 10 (storey) and 11 (space).
    """
    f = ifcopenshell.file(schema="IFC4")
    guid = ifcopenshell.guid

    # Spatial structure
    project  = f.create_entity("IfcProject", GlobalId=guid.new(), Name="P")
    site     = f.create_entity("IfcSite", GlobalId=guid.new(), Name="Site")
    building = f.create_entity("IfcBuilding", GlobalId=guid.new(), Name="Bldg")
    storey   = f.create_entity("IfcBuildingStorey", GlobalId=guid.new(), Name="Storey1")
    space    = f.create_entity("IfcSpace", GlobalId=guid.new(), Name="Space1")

    f.create_entity("IfcRelAggregates", GlobalId=guid.new(),
                    RelatingObject=project, RelatedObjects=[site])
    f.create_entity("IfcRelAggregates", GlobalId=guid.new(),
                    RelatingObject=site, RelatedObjects=[building])
    f.create_entity("IfcRelAggregates", GlobalId=guid.new(),
                    RelatingObject=building, RelatedObjects=[storey])
    f.create_entity("IfcRelAggregates", GlobalId=guid.new(),
                    RelatingObject=storey, RelatedObjects=[space])

    # Elements
    wall = f.create_entity(
        "IfcWall",
        GlobalId=guid.new(),
        Name="W1",
        Description="WallDesc",
        ObjectType="LoadBearing",
        Tag="W-001",
        PredefinedType="NOTDEFINED",
    )
    door = f.create_entity("IfcDoor", GlobalId=guid.new(), Name="D1")
    assembly = f.create_entity(
        "IfcBuildingElementProxy", GlobalId=guid.new(), Name="Assembly"
    )
    beam = f.create_entity("IfcBeam", GlobalId=guid.new(), Name="Beam1")

    # Type for wall
    wall_type = f.create_entity(
        "IfcWallType", GlobalId=guid.new(), Name="WallTypeA", PredefinedType="NOTDEFINED"
    )
    f.create_entity(
        "IfcRelDefinesByType",
        GlobalId=guid.new(),
        RelatingType=wall_type,
        RelatedObjects=[wall],
    )

    # Containment: wall + assembly in Storey1, door in Space1
    f.create_entity(
        "IfcRelContainedInSpatialStructure",
        GlobalId=guid.new(),
        RelatingStructure=storey,
        RelatedElements=[wall, assembly],
    )
    f.create_entity(
        "IfcRelContainedInSpatialStructure",
        GlobalId=guid.new(),
        RelatingStructure=space,
        RelatedElements=[door],
    )

    # Decomposition: assembly → beam
    f.create_entity(
        "IfcRelAggregates",
        GlobalId=guid.new(),
        RelatingObject=assembly,
        RelatedObjects=[beam],
    )

    # SpatialNodes with DB ids (storey.id() and space.id() are STEP entity ids)
    storey_sn = _make_sn(
        db_id=10,
        ifc_entity_id=storey.id(),
        ifc_type="IfcBuildingStorey",
        global_id=str(storey.GlobalId),
        name="Storey1",
        parent_id=None,
    )
    space_sn = _make_sn(
        db_id=11,
        ifc_entity_id=space.id(),
        ifc_type="IfcSpace",
        global_id=str(space.GlobalId),
        name="Space1",
        parent_id=10,  # Space's spatial parent is Storey
    )
    spatial_nodes = [storey_sn, space_sn]

    return f, {
        "wall": wall, "door": door, "assembly": assembly, "beam": beam,
        "wall_type": wall_type, "storey": storey, "space": space,
        "storey_sn": storey_sn, "space_sn": space_sn,
    }, spatial_nodes


@pytest.fixture
def ifc2x3_setup():
    """IFC2X3 file: Storey + Wall via IfcRelContainedInSpatialStructure."""
    f = ifcopenshell.file(schema="IFC2X3")
    guid = ifcopenshell.guid

    storey = f.create_entity("IfcBuildingStorey", GlobalId=guid.new(), Name="Storey2X3")
    wall   = f.create_entity("IfcWall", GlobalId=guid.new(), Name="Wall2X3")
    f.create_entity(
        "IfcRelContainedInSpatialStructure",
        GlobalId=guid.new(),
        RelatingStructure=storey,
        RelatedElements=[wall],
    )

    storey_sn = _make_sn(
        db_id=20,
        ifc_entity_id=storey.id(),
        ifc_type="IfcBuildingStorey",
        global_id=str(storey.GlobalId),
        name="Storey2X3",
    )
    return f, {"wall": wall, "storey": storey, "storey_sn": storey_sn}, [storey_sn]


# ===========================================================================
# Helper
# ===========================================================================

def _run(ifc_file, spatial_nodes, model=None, db=None):
    if model is None:
        model = FakeModel()
    if db is None:
        db = FakeSession()
    elements = extract_and_persist_elements(db, model, ifc_file, spatial_nodes)
    return elements, model, db


# ===========================================================================
# 1. IFC4 extracts all IfcElement
# ===========================================================================

def test_ifc4_extracts_all_elements(ifc4_setup):
    f, ents, sn = ifc4_setup
    elements, _, _ = _run(f, sn)
    assert len(elements) == 4


# ===========================================================================
# 2. IFC2X3 works
# ===========================================================================

def test_ifc2x3_works(ifc2x3_setup):
    f, ents, sn = ifc2x3_setup
    elements, _, _ = _run(f, sn)
    assert len(elements) == 1
    assert elements[0].ifc_type == "IfcWall"


# ===========================================================================
# 3. Ordering by entity.id()
# ===========================================================================

def test_ordering_by_entity_id(ifc4_setup):
    f, _, sn = ifc4_setup
    elements, _, _ = _run(f, sn)
    eids = [el.ifc_entity_id for el in elements]
    assert eids == sorted(eids)


# ===========================================================================
# 4–7. model_id, ifc_entity_id, GlobalId, ifc_type
# ===========================================================================

def test_model_id_set(ifc4_setup):
    f, _, _ = ifc4_setup
    model = FakeModel(model_id=99)
    # Pass empty spatial_nodes — no model_id mismatch, test only verifies element.model_id
    elements, _, _ = _run(f, [], model=model)
    assert all(el.model_id == 99 for el in elements)


def test_ifc_entity_id_set(ifc4_setup):
    f, ents, sn = ifc4_setup
    elements, _, _ = _run(f, sn)
    eids = {el.ifc_entity_id for el in elements}
    for key in ("wall", "door", "assembly", "beam"):
        assert ents[key].id() in eids


def test_global_id_set(ifc4_setup):
    f, ents, sn = ifc4_setup
    elements, _, _ = _run(f, sn)
    gids = {el.global_id for el in elements}
    for key in ("wall", "door", "assembly", "beam"):
        assert str(ents[key].GlobalId) in gids


def test_ifc_type_set(ifc4_setup):
    f, ents, sn = ifc4_setup
    elements, _, _ = _run(f, sn)
    types = {el.ifc_type for el in elements}
    assert "IfcWall" in types
    assert "IfcDoor" in types
    assert "IfcBeam" in types


# ===========================================================================
# 8–12. Scalar attributes
# ===========================================================================

def _wall_elem(elements, ents):
    return next(el for el in elements if el.ifc_entity_id == ents["wall"].id())


def test_name_persisted(ifc4_setup):
    f, ents, sn = ifc4_setup
    elements, _, _ = _run(f, sn)
    assert _wall_elem(elements, ents).name == "W1"


def test_description_persisted(ifc4_setup):
    f, ents, sn = ifc4_setup
    elements, _, _ = _run(f, sn)
    assert _wall_elem(elements, ents).description == "WallDesc"


def test_object_type_persisted(ifc4_setup):
    f, ents, sn = ifc4_setup
    elements, _, _ = _run(f, sn)
    assert _wall_elem(elements, ents).object_type == "LoadBearing"


def test_tag_persisted(ifc4_setup):
    f, ents, sn = ifc4_setup
    elements, _, _ = _run(f, sn)
    assert _wall_elem(elements, ents).tag == "W-001"


def test_predefined_type_persisted(ifc4_setup):
    f, ents, sn = ifc4_setup
    elements, _, _ = _run(f, sn)
    assert _wall_elem(elements, ents).predefined_type is not None


# ===========================================================================
# 13–16. GlobalId validation and error handling
# ===========================================================================

class _NullGlobalIdFile:
    def __init__(self, real_file, patched_eid: int):
        self._real = real_file
        self._eid = patched_eid

    def by_type(self, ifc_type: str):
        return [
            _NullGlobalIdProxy(e) if e.id() == self._eid else e
            for e in self._real.by_type(ifc_type)
        ]


class _NullGlobalIdProxy:
    def __init__(self, entity):
        self._e = entity

    def __getattr__(self, name):
        if name == "GlobalId":
            return None
        return getattr(self._e, name)

    def id(self):
        return self._e.id()

    def is_a(self):
        return self._e.is_a()


class _BlankGlobalIdProxy(_NullGlobalIdProxy):
    def __getattr__(self, name):
        if name == "GlobalId":
            return "   "
        return getattr(self._e, name)


def test_global_id_none_raises(ifc4_setup):
    f, ents, sn = ifc4_setup
    broken = _NullGlobalIdFile(f, ents["wall"].id())
    with pytest.raises(IfcElementExtractionError):
        extract_and_persist_elements(FakeSession(), FakeModel(), broken, sn)


def test_global_id_empty_raises(ifc4_setup):
    f, ents, sn = ifc4_setup

    class _Patch:
        def by_type(self, t):
            return [
                _BlankGlobalIdProxy(e) if e.id() == ents["wall"].id() else e
                for e in f.by_type(t)
            ]

    with pytest.raises(IfcElementExtractionError):
        extract_and_persist_elements(FakeSession(), FakeModel(), _Patch(), sn)


def test_error_message_generic(ifc4_setup):
    f, ents, sn = ifc4_setup
    broken = _NullGlobalIdFile(f, ents["wall"].id())
    with pytest.raises(IfcElementExtractionError) as exc_info:
        extract_and_persist_elements(FakeSession(), FakeModel(), broken, sn)
    assert "No se pudieron extraer los elementos del archivo IFC." in str(exc_info.value)


def test_error_cause_preserved(ifc4_setup):
    f, ents, sn = ifc4_setup
    broken = _NullGlobalIdFile(f, ents["wall"].id())
    with pytest.raises(IfcElementExtractionError) as exc_info:
        extract_and_persist_elements(FakeSession(), FakeModel(), broken, sn)
    assert exc_info.value.__cause__ is not None


# ===========================================================================
# 17–20. Type info (IfcRelDefinesByType)
# ===========================================================================

def test_type_global_id_set(ifc4_setup):
    f, ents, sn = ifc4_setup
    elements, _, _ = _run(f, sn)
    wall_el = _wall_elem(elements, ents)
    assert wall_el.type_global_id == str(ents["wall_type"].GlobalId)


def test_type_ifc_type_set(ifc4_setup):
    f, ents, sn = ifc4_setup
    elements, _, _ = _run(f, sn)
    assert _wall_elem(elements, ents).type_ifc_type == "IfcWallType"


def test_type_name_set(ifc4_setup):
    f, ents, sn = ifc4_setup
    elements, _, _ = _run(f, sn)
    assert _wall_elem(elements, ents).type_name == "WallTypeA"


def test_no_type_fields_null(ifc4_setup):
    """Element without IfcRelDefinesByType → all type_* fields are None."""
    f, ents, sn = ifc4_setup
    elements, _, _ = _run(f, sn)
    door_el = next(el for el in elements if el.ifc_entity_id == ents["door"].id())
    assert door_el.type_global_id is None
    assert door_el.type_ifc_type is None
    assert door_el.type_name is None


# ===========================================================================
# 21–25. Direct containment and spatial resolution
# ===========================================================================

def test_direct_containment_storey(ifc4_setup):
    f, ents, sn = ifc4_setup
    elements, _, _ = _run(f, sn)
    wall_el = _wall_elem(elements, ents)
    assert wall_el.direct_spatial_node_id == ents["storey_sn"].id


def test_direct_containment_space(ifc4_setup):
    f, ents, sn = ifc4_setup
    elements, _, _ = _run(f, sn)
    door_el = next(el for el in elements if el.ifc_entity_id == ents["door"].id())
    assert door_el.direct_spatial_node_id == ents["space_sn"].id


def test_space_resolved_to_storey(ifc4_setup):
    """Door is contained in Space; Space.parent_id = Storey → resolved = Storey."""
    f, ents, sn = ifc4_setup
    elements, _, _ = _run(f, sn)
    door_el = next(el for el in elements if el.ifc_entity_id == ents["door"].id())
    assert door_el.resolved_storey_id == ents["storey_sn"].id


def test_isolated_element_direct_none():
    """Element with no containment rel → direct_spatial_node_id=None."""
    f = ifcopenshell.file(schema="IFC4")
    f.create_entity("IfcWall", GlobalId=ifcopenshell.guid.new(), Name="Isolated")
    elements, _, _ = _run(f, [])
    assert elements[0].direct_spatial_node_id is None


def test_isolated_element_resolved_none():
    """Element with no containment → resolved_storey_id=None."""
    f = ifcopenshell.file(schema="IFC4")
    f.create_entity("IfcWall", GlobalId=ifcopenshell.guid.new(), Name="Isolated")
    elements, _, _ = _run(f, [])
    assert elements[0].resolved_storey_id is None


# ===========================================================================
# 26–28. Parent element and storey inheritance
# ===========================================================================

def test_parent_element_id(ifc4_setup):
    """Beam is child of assembly via IfcRelAggregates."""
    f, ents, sn = ifc4_setup
    elements, _, _ = _run(f, sn)
    by_eid = {el.ifc_entity_id: el for el in elements}
    assembly_el = by_eid[ents["assembly"].id()]
    beam_el = by_eid[ents["beam"].id()]
    assert beam_el.parent_element_id == assembly_el.id


def test_child_inherits_storey_from_parent(ifc4_setup):
    """Beam has no direct containment → inherits storey from assembly."""
    f, ents, sn = ifc4_setup
    elements, _, _ = _run(f, sn)
    by_eid = {el.ifc_entity_id: el for el in elements}
    beam_el = by_eid[ents["beam"].id()]
    assert beam_el.direct_spatial_node_id is None
    assert beam_el.resolved_storey_id == ents["storey_sn"].id


def test_direct_wins_over_parent_inheritance():
    """Direct containment wins over parent element inheritance."""
    f = ifcopenshell.file(schema="IFC4")
    guid = ifcopenshell.guid

    storey_a_entity = f.create_entity("IfcBuildingStorey", GlobalId=guid.new(), Name="SA")
    storey_b_entity = f.create_entity("IfcBuildingStorey", GlobalId=guid.new(), Name="SB")
    parent_wall = f.create_entity("IfcWall", GlobalId=guid.new(), Name="PW")
    child_door = f.create_entity("IfcDoor", GlobalId=guid.new(), Name="CD")

    # parent_wall in storey_a, child_door in storey_b
    f.create_entity("IfcRelContainedInSpatialStructure",
                    GlobalId=guid.new(), RelatingStructure=storey_a_entity,
                    RelatedElements=[parent_wall])
    f.create_entity("IfcRelContainedInSpatialStructure",
                    GlobalId=guid.new(), RelatingStructure=storey_b_entity,
                    RelatedElements=[child_door])
    # child_door is also child of parent_wall
    f.create_entity("IfcRelAggregates", GlobalId=guid.new(),
                    RelatingObject=parent_wall, RelatedObjects=[child_door])

    storey_a_sn = _make_sn(db_id=30, ifc_entity_id=storey_a_entity.id(),
                            ifc_type="IfcBuildingStorey", global_id=str(storey_a_entity.GlobalId))
    storey_b_sn = _make_sn(db_id=31, ifc_entity_id=storey_b_entity.id(),
                            ifc_type="IfcBuildingStorey", global_id=str(storey_b_entity.GlobalId))

    elements, _, _ = _run(f, [storey_a_sn, storey_b_sn])
    by_eid = {el.ifc_entity_id: el for el in elements}
    child_el = by_eid[child_door.id()]
    # Direct containment in storey_b wins
    assert child_el.direct_spatial_node_id == storey_b_sn.id
    assert child_el.resolved_storey_id == storey_b_sn.id


# ===========================================================================
# 29–31. Relation edge cases
# ===========================================================================

def test_spatial_agg_not_element_parent(ifc4_setup):
    """Spatial IfcRelAggregates (building→storey) must not create parent_element_id."""
    f, ents, sn = ifc4_setup
    elements, _, _ = _run(f, sn)
    # All elements should have parent_element_id=None except beam
    by_eid = {el.ifc_entity_id: el for el in elements}
    wall_el = by_eid[ents["wall"].id()]
    assert wall_el.parent_element_id is None


def test_unsupported_entity_in_containment_ignored():
    """IfcRelContainedInSpatialStructure with IfcAnnotation → ignored."""
    f = ifcopenshell.file(schema="IFC4")
    guid = ifcopenshell.guid
    storey_e = f.create_entity("IfcBuildingStorey", GlobalId=guid.new(), Name="S")
    wall = f.create_entity("IfcWall", GlobalId=guid.new(), Name="W")
    # IfcAnnotation is not an IfcElement, won't be in el_by_eid
    ann = f.create_entity("IfcAnnotation", GlobalId=guid.new(), Name="Ann")
    f.create_entity("IfcRelContainedInSpatialStructure", GlobalId=guid.new(),
                    RelatingStructure=storey_e, RelatedElements=[wall, ann])
    storey_sn = _make_sn(db_id=40, ifc_entity_id=storey_e.id(),
                          ifc_type="IfcBuildingStorey", global_id=str(storey_e.GlobalId))
    elements, _, _ = _run(f, [storey_sn])
    # Only wall extracted (annotation not IfcElement)
    assert len(elements) == 1
    assert elements[0].direct_spatial_node_id == storey_sn.id


def test_first_relation_wins_for_type():
    """When two IfcRelDefinesByType cover same element, first by rel.id() wins."""
    f = ifcopenshell.file(schema="IFC4")
    guid = ifcopenshell.guid
    wall = f.create_entity("IfcWall", GlobalId=guid.new(), Name="W")
    type_first = f.create_entity("IfcWallType", GlobalId=guid.new(),
                                  Name="First", PredefinedType="NOTDEFINED")
    type_second = f.create_entity("IfcWallType", GlobalId=guid.new(),
                                   Name="Second", PredefinedType="NOTDEFINED")
    # rel_a created before rel_b → rel_a.id() < rel_b.id()
    f.create_entity("IfcRelDefinesByType", GlobalId=guid.new(),
                    RelatingType=type_first, RelatedObjects=[wall])
    f.create_entity("IfcRelDefinesByType", GlobalId=guid.new(),
                    RelatingType=type_second, RelatedObjects=[wall])
    elements, _, _ = _run(f, [])
    assert elements[0].type_name == "First"


def test_first_relation_wins_for_containment():
    """Two IfcRelContainedInSpatialStructure for same element → lower rel.id() wins."""
    f = ifcopenshell.file(schema="IFC4")
    guid = ifcopenshell.guid

    storey_a = f.create_entity("IfcBuildingStorey", GlobalId=guid.new(), Name="SA")
    storey_b = f.create_entity("IfcBuildingStorey", GlobalId=guid.new(), Name="SB")
    wall = f.create_entity("IfcWall", GlobalId=guid.new(), Name="W")

    rel_a = f.create_entity("IfcRelContainedInSpatialStructure", GlobalId=guid.new(),
                             RelatingStructure=storey_a, RelatedElements=[wall])
    rel_b = f.create_entity("IfcRelContainedInSpatialStructure", GlobalId=guid.new(),
                             RelatingStructure=storey_b, RelatedElements=[wall])
    assert rel_a.id() < rel_b.id()

    sn_a = _make_sn(db_id=70, ifc_entity_id=storey_a.id(),
                    ifc_type="IfcBuildingStorey", global_id=str(storey_a.GlobalId))
    sn_b = _make_sn(db_id=71, ifc_entity_id=storey_b.id(),
                    ifc_type="IfcBuildingStorey", global_id=str(storey_b.GlobalId))

    elements, _, _ = _run(f, [sn_a, sn_b])
    assert elements[0].direct_spatial_node_id == sn_a.id


def test_first_relation_wins_for_aggregates():
    """Two IfcRelAggregates covering same child → lower rel.id() parent wins."""
    f = ifcopenshell.file(schema="IFC4")
    guid = ifcopenshell.guid

    parent_a = f.create_entity("IfcWall", GlobalId=guid.new(), Name="PA")
    parent_b = f.create_entity("IfcWall", GlobalId=guid.new(), Name="PB")
    child = f.create_entity("IfcDoor", GlobalId=guid.new(), Name="C")

    rel_a = f.create_entity("IfcRelAggregates", GlobalId=guid.new(),
                             RelatingObject=parent_a, RelatedObjects=[child])
    rel_b = f.create_entity("IfcRelAggregates", GlobalId=guid.new(),
                             RelatingObject=parent_b, RelatedObjects=[child])
    assert rel_a.id() < rel_b.id()

    elements, _, _ = _run(f, [])
    by_eid = {el.ifc_entity_id: el for el in elements}
    parent_a_el = by_eid[parent_a.id()]
    child_el = by_eid[child.id()]
    assert child_el.parent_element_id == parent_a_el.id


def test_direct_containment_no_storey_falls_back_to_parent():
    """Direct containment in a spatial node that can't resolve a storey
    falls back to the parent element's storey."""
    f = ifcopenshell.file(schema="IFC4")
    guid = ifcopenshell.guid

    storey_entity = f.create_entity("IfcBuildingStorey", GlobalId=guid.new(), Name="S")
    orphan_space = f.create_entity("IfcSpace", GlobalId=guid.new(), Name="Orphan")
    parent_wall = f.create_entity("IfcWall", GlobalId=guid.new(), Name="PW")
    child_door = f.create_entity("IfcDoor", GlobalId=guid.new(), Name="CD")

    # parent_wall contained in storey
    f.create_entity("IfcRelContainedInSpatialStructure", GlobalId=guid.new(),
                    RelatingStructure=storey_entity, RelatedElements=[parent_wall])
    # child_door contained in orphan_space (no storey ancestor)
    f.create_entity("IfcRelContainedInSpatialStructure", GlobalId=guid.new(),
                    RelatingStructure=orphan_space, RelatedElements=[child_door])
    # child_door is child of parent_wall
    f.create_entity("IfcRelAggregates", GlobalId=guid.new(),
                    RelatingObject=parent_wall, RelatedObjects=[child_door])

    storey_sn = _make_sn(db_id=60, ifc_entity_id=storey_entity.id(),
                         ifc_type="IfcBuildingStorey", global_id=str(storey_entity.GlobalId))
    # orphan_space SpatialNode has no parent → spatial walk finds no storey
    orphan_sn = _make_sn(db_id=61, ifc_entity_id=orphan_space.id(),
                         ifc_type="IfcSpace", global_id=str(orphan_space.GlobalId),
                         parent_id=None)

    elements, _, _ = _run(f, [storey_sn, orphan_sn])
    by_eid = {el.ifc_entity_id: el for el in elements}
    child_el = by_eid[child_door.id()]

    # direct containment recorded in orphan_space
    assert child_el.direct_spatial_node_id == orphan_sn.id
    # storey resolved via parent_wall → storey_sn
    assert child_el.resolved_storey_id == storey_sn.id


def test_type_global_id_runtime_error_raises():
    """RuntimeError accessing RelatingType.GlobalId → IfcElementExtractionError
    with RuntimeError as __cause__."""
    f = ifcopenshell.file(schema="IFC4")
    guid = ifcopenshell.guid
    wall = f.create_entity("IfcWall", GlobalId=guid.new(), Name="W")

    class _BrokenType:
        def __getattr__(self, name):
            if name == "GlobalId":
                raise RuntimeError("broken GlobalId")
            raise AttributeError(name)

        def is_a(self):
            return "IfcWallType"

    class _Rel:
        def id(self):
            return 99999

        @property
        def RelatingType(self):
            return _BrokenType()

        @property
        def RelatedObjects(self):
            return [wall]

    class _FileWithBrokenRel:
        def by_type(self, ifc_type):
            if ifc_type == "IfcRelDefinesByType":
                return [_Rel()]
            return f.by_type(ifc_type)

    with pytest.raises(IfcElementExtractionError) as exc_info:
        extract_and_persist_elements(FakeSession(), FakeModel(), _FileWithBrokenRel(), [])
    assert isinstance(exc_info.value.__cause__, RuntimeError)


# ===========================================================================
# 32–33. Cycle protection
# ===========================================================================

def test_spatial_cycle_no_infinite_loop():
    """SpatialNode chain with cycle → resolved_storey_id=None, no hang."""
    f = ifcopenshell.file(schema="IFC4")
    guid = ifcopenshell.guid
    wall = f.create_entity("IfcWall", GlobalId=guid.new(), Name="W")

    # Cyclic spatial nodes: sn_a.parent_id = sn_b.id, sn_b.parent_id = sn_a.id
    sn_a = _make_sn(db_id=50, ifc_entity_id=9998, ifc_type="IfcSpace",
                    global_id=guid.new())
    sn_b = _make_sn(db_id=51, ifc_entity_id=9999, ifc_type="IfcSpace",
                    global_id=guid.new())
    sn_a.parent_id = 51
    sn_b.parent_id = 50

    # containment rel pointing to a REAL entity id — but we set ifc_entity_id
    # to match wall-containing storey. Instead, just set direct via containment.
    # Build a small IFC file where wall is contained in sn_a's "entity"
    storey_e = f.create_entity("IfcBuildingStorey", GlobalId=guid.new(), Name="S")
    f.create_entity("IfcRelContainedInSpatialStructure", GlobalId=guid.new(),
                    RelatingStructure=storey_e, RelatedElements=[wall])

    # Create sn_cycle that points at storey_e but is cyclic with sn_b
    sn_cycle = _make_sn(db_id=52, ifc_entity_id=storey_e.id(),
                        ifc_type="IfcSpace", global_id=str(storey_e.GlobalId))
    sn_cycle.parent_id = 51

    elements, _, _ = _run(f, [sn_a, sn_b, sn_cycle])
    # Should not hang; resolved may be None (no IfcBuildingStorey in chain)
    assert elements[0].resolved_storey_id is None


def test_element_cycle_no_infinite_loop():
    """Cyclic parent_element chain → resolved_storey_id=None, no hang."""
    f = ifcopenshell.file(schema="IFC4")
    guid = ifcopenshell.guid
    wall = f.create_entity("IfcWall", GlobalId=guid.new(), Name="W")
    door = f.create_entity("IfcDoor", GlobalId=guid.new(), Name="D")
    # wall → [door] and door → [wall] → cycle
    f.create_entity("IfcRelAggregates", GlobalId=guid.new(),
                    RelatingObject=wall, RelatedObjects=[door])
    f.create_entity("IfcRelAggregates", GlobalId=guid.new(),
                    RelatingObject=door, RelatedObjects=[wall])
    elements, _, _ = _run(f, [])
    for el in elements:
        # Should terminate without hanging; neither has direct containment
        assert el.resolved_storey_id is None


# ===========================================================================
# 34–36. spatial_nodes parameter validation
# ===========================================================================

def test_empty_spatial_nodes_works(ifc4_setup):
    """Empty spatial_nodes list → extraction proceeds, all FK fields None."""
    f, ents, _ = ifc4_setup
    elements, _, _ = _run(f, [])
    assert len(elements) == 4
    for el in elements:
        assert el.direct_spatial_node_id is None
        assert el.resolved_storey_id is None


def test_spatial_node_wrong_model_raises(ifc4_setup):
    """SpatialNode from different model → IfcElementExtractionError."""
    f, _, sn = ifc4_setup
    bad_sn = _make_sn(db_id=99, ifc_entity_id=1, ifc_type="IfcBuildingStorey",
                      global_id=ifcopenshell.guid.new(), model_id=999)
    with pytest.raises(IfcElementExtractionError):
        extract_and_persist_elements(FakeSession(), FakeModel(model_id=1), f, [bad_sn])


def test_spatial_node_no_id_raises(ifc4_setup):
    """SpatialNode without DB id → IfcElementExtractionError."""
    f, _, sn = ifc4_setup
    un_flushed = SpatialNode(model_id=1, ifc_entity_id=1,
                              global_id=ifcopenshell.guid.new(),
                              ifc_type="IfcBuildingStorey")
    # un_flushed.id is None by default
    with pytest.raises(IfcElementExtractionError):
        extract_and_persist_elements(FakeSession(), FakeModel(), f, [un_flushed])


# ===========================================================================
# 37–39. No elements
# ===========================================================================

def test_no_elements_returns_empty():
    f = ifcopenshell.file(schema="IFC4")
    elements, _, _ = _run(f, [])
    assert elements == []


def test_no_elements_count_zero():
    f = ifcopenshell.file(schema="IFC4")
    _, model, _ = _run(f, [])
    assert model.element_count == 0


def test_no_elements_no_flush():
    f = ifcopenshell.file(schema="IFC4")
    db = FakeSession()
    _run(f, [], db=db)
    assert db.flush_count == 0
    assert db.add_all_count == 0


# ===========================================================================
# 40–43. Flush and counter discipline
# ===========================================================================

def test_success_two_flushes(ifc4_setup):
    f, _, sn = ifc4_setup
    db = FakeSession()
    _run(f, sn, db=db)
    assert db.flush_count == 2


def test_element_count_correct(ifc4_setup):
    f, _, sn = ifc4_setup
    _, model, _ = _run(f, sn)
    assert model.element_count == 4


def test_spatial_node_count_not_modified(ifc4_setup):
    f, _, sn = ifc4_setup
    model = FakeModel()
    model.spatial_node_count = 7
    _run(f, sn, model=model)
    assert model.spatial_node_count == 7


def test_property_count_not_modified(ifc4_setup):
    f, _, sn = ifc4_setup
    model = FakeModel()
    model.property_count = 42
    _run(f, sn, model=model)
    assert model.property_count == 42


# ===========================================================================
# 44–45. Transaction discipline
# ===========================================================================

def test_no_commit(ifc4_setup):
    f, _, sn = ifc4_setup
    db = FakeSession()
    _run(f, sn, db=db)
    assert db.committed is False


def test_no_rollback(ifc4_setup):
    f, _, sn = ifc4_setup
    db = FakeSession()
    _run(f, sn, db=db)
    assert db.rolled_back is False


# ===========================================================================
# 46–48. Model state not touched
# ===========================================================================

def test_no_status_modification(ifc4_setup):
    f, _, sn = ifc4_setup
    model = FakeModel()
    model.status = "PROCESSING"
    _run(f, sn, model=model)
    assert model.status == "PROCESSING"


def test_no_ifc_schema_modification(ifc4_setup):
    f, _, sn = ifc4_setup
    model = FakeModel()
    model.ifc_schema = "IFC4"
    _run(f, sn, model=model)
    assert model.ifc_schema == "IFC4"


def test_no_error_message_modification(ifc4_setup):
    f, _, sn = ifc4_setup
    model = FakeModel()
    model.error_message = "prior"
    _run(f, sn, model=model)
    assert model.error_message == "prior"


# ===========================================================================
# 49–51. Error propagation
# ===========================================================================

def test_first_flush_failure_raises(ifc4_setup):
    f, _, sn = ifc4_setup
    db = FailingSession(fail_on=1)
    with pytest.raises(IfcElementExtractionError):
        extract_and_persist_elements(db, FakeModel(), f, sn)


def test_second_flush_failure_raises(ifc4_setup):
    f, _, sn = ifc4_setup
    db = FailingSession(fail_on=2)
    with pytest.raises(IfcElementExtractionError):
        extract_and_persist_elements(db, FakeModel(), f, sn)


def test_by_type_error_raises(ifc4_setup):
    """Error in ifc_file.by_type() → IfcElementExtractionError."""
    f, _, sn = ifc4_setup

    class _BrokenFile:
        def by_type(self, t):
            raise RuntimeError("Simulated IfcOpenShell crash")

    with pytest.raises(IfcElementExtractionError) as exc_info:
        extract_and_persist_elements(FakeSession(), FakeModel(), _BrokenFile(), sn)
    assert exc_info.value.__cause__ is not None


# ===========================================================================
# 52. Exports
# ===========================================================================

def test_exports_from_services():
    from app.services import IfcElementExtractionError as E
    from app.services import extract_and_persist_elements as fn
    assert E is IfcElementExtractionError
    assert callable(fn)
