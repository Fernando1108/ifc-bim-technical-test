"""
Tests for the ifc_spatial service.

Uses real IfcOpenShell to build in-memory IFC files.
Uses FakeSession — no PostgreSQL required.
"""
import pytest
import ifcopenshell
import ifcopenshell.guid

from app.models.spatial_node import SpatialNode
from app.services.ifc_spatial import (
    IfcSpatialExtractionError,
    extract_and_persist_spatial_structure,
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
            if isinstance(obj, SpatialNode) and obj.id is None:
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
            raise RuntimeError("Simulated DB error")
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
# Fixtures
# ===========================================================================

@pytest.fixture
def ifc4_file():
    """IFC4 hierarchy: Project → Site → Building → Storey → Space."""
    f = ifcopenshell.file(schema="IFC4")
    project = f.create_entity(
        "IfcProject",
        GlobalId=ifcopenshell.guid.new(),
        Name="TestProject",
        Description="ProjDesc",
    )
    site = f.create_entity(
        "IfcSite",
        GlobalId=ifcopenshell.guid.new(),
        Name="TestSite",
        Description="SiteDesc",
    )
    building = f.create_entity(
        "IfcBuilding",
        GlobalId=ifcopenshell.guid.new(),
        Name="TestBuilding",
        LongName="BuildingLong",
    )
    storey = f.create_entity(
        "IfcBuildingStorey",
        GlobalId=ifcopenshell.guid.new(),
        Name="TestStorey",
        Elevation=3.5,
    )
    space = f.create_entity(
        "IfcSpace",
        GlobalId=ifcopenshell.guid.new(),
        Name="TestSpace",
    )
    f.create_entity(
        "IfcRelAggregates",
        GlobalId=ifcopenshell.guid.new(),
        RelatingObject=project,
        RelatedObjects=[site],
    )
    f.create_entity(
        "IfcRelAggregates",
        GlobalId=ifcopenshell.guid.new(),
        RelatingObject=site,
        RelatedObjects=[building],
    )
    f.create_entity(
        "IfcRelAggregates",
        GlobalId=ifcopenshell.guid.new(),
        RelatingObject=building,
        RelatedObjects=[storey],
    )
    f.create_entity(
        "IfcRelAggregates",
        GlobalId=ifcopenshell.guid.new(),
        RelatingObject=storey,
        RelatedObjects=[space],
    )
    return f, {
        "project": project,
        "site": site,
        "building": building,
        "storey": storey,
        "space": space,
    }


@pytest.fixture
def ifc2x3_file():
    """IFC2X3 hierarchy: Project → Site → Building → Storey."""
    f = ifcopenshell.file(schema="IFC2X3")
    project = f.create_entity("IfcProject", GlobalId=ifcopenshell.guid.new(), Name="Proj2X3")
    site = f.create_entity("IfcSite", GlobalId=ifcopenshell.guid.new(), Name="Site2X3")
    building = f.create_entity("IfcBuilding", GlobalId=ifcopenshell.guid.new(), Name="Bldg2X3")
    storey = f.create_entity(
        "IfcBuildingStorey", GlobalId=ifcopenshell.guid.new(), Name="Storey2X3"
    )
    f.create_entity(
        "IfcRelAggregates",
        GlobalId=ifcopenshell.guid.new(),
        RelatingObject=project,
        RelatedObjects=[site],
    )
    f.create_entity(
        "IfcRelAggregates",
        GlobalId=ifcopenshell.guid.new(),
        RelatingObject=site,
        RelatedObjects=[building],
    )
    f.create_entity(
        "IfcRelAggregates",
        GlobalId=ifcopenshell.guid.new(),
        RelatingObject=building,
        RelatedObjects=[storey],
    )
    return f, {"project": project, "site": site, "building": building, "storey": storey}


# ===========================================================================
# Helper
# ===========================================================================

def _run(ifc_file, model=None, db=None):
    if model is None:
        model = FakeModel()
    if db is None:
        db = FakeSession()
    nodes = extract_and_persist_spatial_structure(db, model, ifc_file)
    return nodes, model, db


# ===========================================================================
# 1. IFC4 creates all nodes
# ===========================================================================

def test_ifc4_creates_all_nodes(ifc4_file):
    ifc_f, _ = ifc4_file
    nodes, model, _ = _run(ifc_f)
    assert len(nodes) == 5
    assert model.spatial_node_count == 5


# ===========================================================================
# 2. IFC2X3 works (not hardcoded to IFC4)
# ===========================================================================

def test_ifc2x3_works(ifc2x3_file):
    ifc_f, _ = ifc2x3_file
    nodes, _, _ = _run(ifc_f)
    assert len(nodes) == 4


# ===========================================================================
# 3. model_id correct
# ===========================================================================

def test_model_id_set(ifc4_file):
    ifc_f, _ = ifc4_file
    model = FakeModel(model_id=42)
    nodes, _, _ = _run(ifc_f, model=model)
    assert all(n.model_id == 42 for n in nodes)


# ===========================================================================
# 4. ifc_entity_id correct
# ===========================================================================

def test_ifc_entity_id_set(ifc4_file):
    ifc_f, entities = ifc4_file
    nodes, _, _ = _run(ifc_f)
    node_eids = {n.ifc_entity_id for n in nodes}
    for entity in entities.values():
        assert entity.id() in node_eids


# ===========================================================================
# 5. GlobalId correct
# ===========================================================================

def test_global_id_set(ifc4_file):
    ifc_f, entities = ifc4_file
    nodes, _, _ = _run(ifc_f)
    node_gids = {n.global_id for n in nodes}
    for entity in entities.values():
        assert str(entity.GlobalId) in node_gids


# ===========================================================================
# 6. ifc_type correct
# ===========================================================================

def test_ifc_type_set(ifc4_file):
    ifc_f, entities = ifc4_file
    nodes, _, _ = _run(ifc_f)
    node_types = {n.ifc_type for n in nodes}
    for entity in entities.values():
        assert entity.is_a() in node_types


# ===========================================================================
# 7. Name persisted
# ===========================================================================

def test_name_persisted(ifc4_file):
    ifc_f, _ = ifc4_file
    nodes, _, _ = _run(ifc_f)
    project_node = next(n for n in nodes if n.ifc_type == "IfcProject")
    assert project_node.name == "TestProject"


# ===========================================================================
# 8. Description persisted
# ===========================================================================

def test_description_persisted(ifc4_file):
    ifc_f, _ = ifc4_file
    nodes, _, _ = _run(ifc_f)
    project_node = next(n for n in nodes if n.ifc_type == "IfcProject")
    assert project_node.description == "ProjDesc"


# ===========================================================================
# 9. LongName persisted when present
# ===========================================================================

def test_long_name_persisted(ifc4_file):
    ifc_f, _ = ifc4_file
    nodes, _, _ = _run(ifc_f)
    building_node = next(n for n in nodes if n.ifc_type == "IfcBuilding")
    assert building_node.long_name == "BuildingLong"


# ===========================================================================
# 10. Elevation persisted as float
# ===========================================================================

def test_elevation_persisted_as_float(ifc4_file):
    ifc_f, _ = ifc4_file
    nodes, _, _ = _run(ifc_f)
    storey_node = next(n for n in nodes if n.ifc_type == "IfcBuildingStorey")
    assert storey_node.elevation == pytest.approx(3.5)
    assert isinstance(storey_node.elevation, float)


# ===========================================================================
# 11–15. Parent/child hierarchy
# ===========================================================================

def test_project_has_no_parent(ifc4_file):
    ifc_f, entities = ifc4_file
    nodes, _, _ = _run(ifc_f)
    by_eid = {n.ifc_entity_id: n for n in nodes}
    assert by_eid[entities["project"].id()].parent_id is None


def test_site_parent_is_project(ifc4_file):
    ifc_f, entities = ifc4_file
    nodes, _, _ = _run(ifc_f)
    by_eid = {n.ifc_entity_id: n for n in nodes}
    assert by_eid[entities["site"].id()].parent_id == by_eid[entities["project"].id()].id


def test_building_parent_is_site(ifc4_file):
    ifc_f, entities = ifc4_file
    nodes, _, _ = _run(ifc_f)
    by_eid = {n.ifc_entity_id: n for n in nodes}
    assert by_eid[entities["building"].id()].parent_id == by_eid[entities["site"].id()].id


def test_storey_parent_is_building(ifc4_file):
    ifc_f, entities = ifc4_file
    nodes, _, _ = _run(ifc_f)
    by_eid = {n.ifc_entity_id: n for n in nodes}
    assert by_eid[entities["storey"].id()].parent_id == by_eid[entities["building"].id()].id


def test_space_parent_is_storey(ifc4_file):
    ifc_f, entities = ifc4_file
    nodes, _, _ = _run(ifc_f)
    by_eid = {n.ifc_entity_id: n for n in nodes}
    assert by_eid[entities["space"].id()].parent_id == by_eid[entities["storey"].id()].id


# ===========================================================================
# 16. Two storeys share same building parent
# ===========================================================================

def test_two_storeys_share_building_parent():
    f = ifcopenshell.file(schema="IFC4")
    building = f.create_entity("IfcBuilding", GlobalId=ifcopenshell.guid.new(), Name="B")
    storey1 = f.create_entity("IfcBuildingStorey", GlobalId=ifcopenshell.guid.new(), Name="S1")
    storey2 = f.create_entity("IfcBuildingStorey", GlobalId=ifcopenshell.guid.new(), Name="S2")
    f.create_entity(
        "IfcRelAggregates",
        GlobalId=ifcopenshell.guid.new(),
        RelatingObject=building,
        RelatedObjects=[storey1, storey2],
    )
    nodes, _, _ = _run(f)
    by_eid = {n.ifc_entity_id: n for n in nodes}
    building_id = by_eid[building.id()].id
    assert by_eid[storey1.id()].parent_id == building_id
    assert by_eid[storey2.id()].parent_id == building_id


# ===========================================================================
# 17. Isolated entity without relation → parent_id=None
# ===========================================================================

def test_isolated_entity_has_no_parent():
    f = ifcopenshell.file(schema="IFC4")
    f.create_entity("IfcSpace", GlobalId=ifcopenshell.guid.new(), Name="Isolated")
    nodes, _, _ = _run(f)
    assert len(nodes) == 1
    assert nodes[0].parent_id is None


# ===========================================================================
# 18. Relations to unsupported entities are ignored
# ===========================================================================

def test_unsupported_entities_in_rel_ignored():
    f = ifcopenshell.file(schema="IFC4")
    building = f.create_entity("IfcBuilding", GlobalId=ifcopenshell.guid.new(), Name="B")
    storey = f.create_entity("IfcBuildingStorey", GlobalId=ifcopenshell.guid.new(), Name="S")
    wall = f.create_entity("IfcWall", GlobalId=ifcopenshell.guid.new(), Name="W")
    f.create_entity(
        "IfcRelAggregates",
        GlobalId=ifcopenshell.guid.new(),
        RelatingObject=building,
        RelatedObjects=[storey, wall],
    )
    nodes, _, _ = _run(f)
    # wall excluded from nodes
    assert len(nodes) == 2
    by_eid = {n.ifc_entity_id: n for n in nodes}
    assert wall.id() not in by_eid
    # storey correctly parented to building
    assert by_eid[storey.id()].parent_id == by_eid[building.id()].id


# ===========================================================================
# 19. Deterministic ordering by entity.id()
# ===========================================================================

def test_deterministic_ordering():
    f = ifcopenshell.file(schema="IFC4")
    # Create space first (lower STEP id), then project
    space = f.create_entity("IfcSpace", GlobalId=ifcopenshell.guid.new(), Name="ZZZ")
    project = f.create_entity("IfcProject", GlobalId=ifcopenshell.guid.new(), Name="AAA")
    nodes, _, _ = _run(f)
    assert len(nodes) == 2
    assert nodes[0].ifc_entity_id == space.id()
    assert nodes[1].ifc_entity_id == project.id()
    assert nodes[0].ifc_entity_id < nodes[1].ifc_entity_id


# ===========================================================================
# 20–22. Counters
# ===========================================================================

def test_spatial_node_count_correct(ifc4_file):
    ifc_f, _ = ifc4_file
    _, model, _ = _run(ifc_f)
    assert model.spatial_node_count == 5


def test_element_count_not_modified(ifc4_file):
    ifc_f, _ = ifc4_file
    model = FakeModel()
    model.element_count = 7
    _run(ifc_f, model=model)
    assert model.element_count == 7


def test_property_count_not_modified(ifc4_file):
    ifc_f, _ = ifc4_file
    model = FakeModel()
    model.property_count = 99
    _run(ifc_f, model=model)
    assert model.property_count == 99


# ===========================================================================
# 23–25. No structure → empty list, count=0, no flush
# ===========================================================================

def test_no_structure_returns_empty_list():
    f = ifcopenshell.file(schema="IFC4")
    nodes, _, _ = _run(f)
    assert nodes == []


def test_no_structure_count_zero():
    f = ifcopenshell.file(schema="IFC4")
    _, model, _ = _run(f)
    assert model.spatial_node_count == 0


def test_no_structure_no_flush():
    f = ifcopenshell.file(schema="IFC4")
    db = FakeSession()
    _run(f, db=db)
    assert db.flush_count == 0
    assert db.add_all_count == 0


# ===========================================================================
# 26–28. Transaction discipline
# ===========================================================================

def test_success_two_flushes(ifc4_file):
    ifc_f, _ = ifc4_file
    db = FakeSession()
    _run(ifc_f, db=db)
    assert db.flush_count == 2


def test_no_commit(ifc4_file):
    ifc_f, _ = ifc4_file
    db = FakeSession()
    _run(ifc_f, db=db)
    assert db.committed is False


def test_no_rollback(ifc4_file):
    ifc_f, _ = ifc4_file
    db = FakeSession()
    _run(ifc_f, db=db)
    assert db.rolled_back is False


# ===========================================================================
# 29–32. Error handling
# ===========================================================================

def test_first_flush_failure_raises(ifc4_file):
    ifc_f, _ = ifc4_file
    db = FailingSession(fail_on=1)
    with pytest.raises(IfcSpatialExtractionError):
        extract_and_persist_spatial_structure(db, FakeModel(), ifc_f)


def test_second_flush_failure_raises(ifc4_file):
    ifc_f, _ = ifc4_file
    db = FailingSession(fail_on=2)
    with pytest.raises(IfcSpatialExtractionError):
        extract_and_persist_spatial_structure(db, FakeModel(), ifc_f)


def test_error_message_generic(ifc4_file):
    ifc_f, _ = ifc4_file
    db = FailingSession(fail_on=1)
    with pytest.raises(IfcSpatialExtractionError) as exc_info:
        extract_and_persist_spatial_structure(db, FakeModel(), ifc_f)
    assert "No se pudo extraer la estructura espacial del archivo IFC." in str(exc_info.value)


def test_original_exception_preserved(ifc4_file):
    ifc_f, _ = ifc4_file
    db = FailingSession(fail_on=1)
    with pytest.raises(IfcSpatialExtractionError) as exc_info:
        extract_and_persist_spatial_structure(db, FakeModel(), ifc_f)
    assert exc_info.value.__cause__ is not None


# ===========================================================================
# 33–35. Model fields not touched
# ===========================================================================

def test_no_status_modification(ifc4_file):
    ifc_f, _ = ifc4_file
    model = FakeModel()
    model.status = "PROCESSING"
    _run(ifc_f, model=model)
    assert model.status == "PROCESSING"


def test_no_ifc_schema_modification(ifc4_file):
    ifc_f, _ = ifc4_file
    model = FakeModel()
    model.ifc_schema = "IFC4"
    _run(ifc_f, model=model)
    assert model.ifc_schema == "IFC4"


def test_no_error_message_modification(ifc4_file):
    ifc_f, _ = ifc4_file
    model = FakeModel()
    model.error_message = "prior error"
    _run(ifc_f, model=model)
    assert model.error_message == "prior error"


# ===========================================================================
# 36. Exports from app.services
# ===========================================================================

def test_exports_from_services():
    from app.services import IfcSpatialExtractionError as E
    from app.services import extract_and_persist_spatial_structure as fn
    assert E is IfcSpatialExtractionError
    assert callable(fn)


# ===========================================================================
# 37–41. Global error guard — collection/relation errors → IfcSpatialExtractionError
# ===========================================================================

class _BrokenByType:
    """Wraps a real IFC file but raises on a specific by_type call."""

    def __init__(self, real_file, fail_on_type: str):
        self._real = real_file
        self._fail_on = fail_on_type

    def by_type(self, ifc_type: str):
        if ifc_type == self._fail_on:
            raise RuntimeError(f"Simulated IfcOpenShell failure for {ifc_type}")
        return self._real.by_type(ifc_type)


def test_collection_error_raises_extraction_error(ifc4_file):
    """Error during ifc_file.by_type() → IfcSpatialExtractionError."""
    ifc_f, _ = ifc4_file
    broken = _BrokenByType(ifc_f, fail_on_type="IfcProject")
    db = FakeSession()
    with pytest.raises(IfcSpatialExtractionError):
        extract_and_persist_spatial_structure(db, FakeModel(), broken)


def test_collection_error_cause_preserved(ifc4_file):
    """Original exception from by_type() is preserved as __cause__."""
    ifc_f, _ = ifc4_file
    broken = _BrokenByType(ifc_f, fail_on_type="IfcSite")
    db = FakeSession()
    with pytest.raises(IfcSpatialExtractionError) as exc_info:
        extract_and_persist_spatial_structure(db, FakeModel(), broken)
    assert isinstance(exc_info.value.__cause__, RuntimeError)


def test_rel_aggregates_error_raises_extraction_error(ifc4_file):
    """Error reading IfcRelAggregates → IfcSpatialExtractionError."""
    ifc_f, _ = ifc4_file
    broken = _BrokenByType(ifc_f, fail_on_type="IfcRelAggregates")
    db = FakeSession()
    with pytest.raises(IfcSpatialExtractionError):
        extract_and_persist_spatial_structure(db, FakeModel(), broken)


def test_no_commit_after_collection_error(ifc4_file):
    """Service does not commit after collection failure."""
    ifc_f, _ = ifc4_file
    broken = _BrokenByType(ifc_f, fail_on_type="IfcProject")
    db = FakeSession()
    with pytest.raises(IfcSpatialExtractionError):
        extract_and_persist_spatial_structure(db, FakeModel(), broken)
    assert db.committed is False


def test_no_rollback_after_collection_error(ifc4_file):
    """Service does not rollback after collection failure (caller's responsibility)."""
    ifc_f, _ = ifc4_file
    broken = _BrokenByType(ifc_f, fail_on_type="IfcProject")
    db = FakeSession()
    with pytest.raises(IfcSpatialExtractionError):
        extract_and_persist_spatial_structure(db, FakeModel(), broken)
    assert db.rolled_back is False


# ===========================================================================
# 42–44. GlobalId validation
# ===========================================================================

class _NullGlobalIdFile:
    """Wraps a real IFC file but overrides one entity to return None GlobalId."""

    def __init__(self, real_file, patched_entity_id: int):
        self._real = real_file
        self._patched_id = patched_entity_id

    def by_type(self, ifc_type: str):
        return [
            _NullGlobalIdProxy(e) if e.id() == self._patched_id else e
            for e in self._real.by_type(ifc_type)
        ]


class _NullGlobalIdProxy:
    """Delegates all attribute access to the real entity except GlobalId → None."""

    def __init__(self, entity):
        self._entity = entity

    def __getattr__(self, name):
        if name == "GlobalId":
            return None
        return getattr(self._entity, name)

    def id(self):
        return self._entity.id()

    def is_a(self):
        return self._entity.is_a()


class _EmptyGlobalIdProxy(_NullGlobalIdProxy):
    """Like _NullGlobalIdProxy but GlobalId returns empty string."""

    def __getattr__(self, name):
        if name == "GlobalId":
            return "   "
        return getattr(self._entity, name)


def test_null_global_id_raises_extraction_error(ifc4_file):
    """Entity with GlobalId=None → IfcSpatialExtractionError."""
    ifc_f, entities = ifc4_file
    broken = _NullGlobalIdFile(ifc_f, patched_entity_id=entities["project"].id())
    db = FakeSession()
    with pytest.raises(IfcSpatialExtractionError):
        extract_and_persist_spatial_structure(db, FakeModel(), broken)


def test_empty_global_id_raises_extraction_error(ifc4_file):
    """Entity with blank GlobalId → IfcSpatialExtractionError."""
    ifc_f, entities = ifc4_file
    # wrap whole file: replace project entity's GlobalId with whitespace
    real_project = entities["project"]

    class _FilePatch:
        def by_type(self, ifc_type):
            return [
                _EmptyGlobalIdProxy(e) if e.id() == real_project.id() else e
                for e in ifc_f.by_type(ifc_type)
            ]

    db = FakeSession()
    with pytest.raises(IfcSpatialExtractionError):
        extract_and_persist_spatial_structure(db, FakeModel(), _FilePatch())


def test_null_global_id_cause_is_value_error(ifc4_file):
    """__cause__ of IfcSpatialExtractionError is ValueError for missing GlobalId."""
    ifc_f, entities = ifc4_file
    broken = _NullGlobalIdFile(ifc_f, patched_entity_id=entities["site"].id())
    db = FakeSession()
    with pytest.raises(IfcSpatialExtractionError) as exc_info:
        extract_and_persist_spatial_structure(db, FakeModel(), broken)
    assert isinstance(exc_info.value.__cause__, ValueError)
