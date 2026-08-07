"""
Tests for the ifc_properties service.

Uses real IfcOpenShell to build in-memory IFC files.
Uses FakeSession — no PostgreSQL required.
IfcElement objects are created manually with pre-assigned DB ids
(simulating what extract_and_persist_elements would produce).
"""
import pytest
import ifcopenshell
import ifcopenshell.guid

from app.models.element import IfcElement
from app.models.element_property import ElementProperty
from app.services.ifc_properties import (
    IfcPropertyExtractionError,
    extract_and_persist_element_properties,
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
# IfcElement helper
# ===========================================================================

def _make_el(
    *,
    db_id: int,
    ifc_entity_id: int,
    model_id: int = 1,
    ifc_type: str = "IfcWall",
) -> IfcElement:
    """Build an IfcElement with a pre-assigned DB id (post-flush simulation)."""
    el = IfcElement(
        model_id=model_id,
        ifc_entity_id=ifc_entity_id,
        global_id=ifcopenshell.guid.new(),
        ifc_type=ifc_type,
    )
    el.id = db_id
    return el


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture
def ifc4_props():
    """
    IFC4 file with:
    - IfcWall element (wall_e)
    - Pset_WallCommon with Reference(TEXT), FireRating(TEXT),
      IsExternal(BOOLEAN), ThermalTransmittance(NUMBER), OptionalValue(NULL)
    - BaseQuantities with Length, Area, Volume
    - Both related to wall_e via IfcRelDefinesByProperties
    - Simulated IfcElement (wall_el) with DB id=1
    """
    f = ifcopenshell.file(schema="IFC4")
    guid = ifcopenshell.guid

    wall_e = f.create_entity("IfcWall", GlobalId=guid.new(), Name="W1")

    # Pset_WallCommon
    pset = f.create_entity(
        "IfcPropertySet",
        GlobalId=guid.new(),
        Name="Pset_WallCommon",
        HasProperties=[
            f.create_entity(
                "IfcPropertySingleValue",
                Name="Reference",
                NominalValue=f.create_entity("IfcLabel", "W-REF-01"),
            ),
            f.create_entity(
                "IfcPropertySingleValue",
                Name="FireRating",
                NominalValue=f.create_entity("IfcLabel", "2h"),
            ),
            f.create_entity(
                "IfcPropertySingleValue",
                Name="IsExternal",
                NominalValue=f.create_entity("IfcBoolean", True),
            ),
            f.create_entity(
                "IfcPropertySingleValue",
                Name="ThermalTransmittance",
                NominalValue=f.create_entity("IfcReal", 0.35),
            ),
            f.create_entity(
                "IfcPropertySingleValue",
                Name="OptionalValue",
                NominalValue=None,
            ),
        ],
    )

    # BaseQuantities
    qto = f.create_entity(
        "IfcElementQuantity",
        GlobalId=guid.new(),
        Name="BaseQuantities",
        Quantities=[
            f.create_entity("IfcQuantityLength", Name="Length", LengthValue=5.0),
            f.create_entity("IfcQuantityArea", Name="Area", AreaValue=10.0),
            f.create_entity("IfcQuantityVolume", Name="Volume", VolumeValue=2.5),
        ],
    )

    f.create_entity(
        "IfcRelDefinesByProperties",
        GlobalId=guid.new(),
        RelatingPropertyDefinition=pset,
        RelatedObjects=[wall_e],
    )
    f.create_entity(
        "IfcRelDefinesByProperties",
        GlobalId=guid.new(),
        RelatingPropertyDefinition=qto,
        RelatedObjects=[wall_e],
    )

    wall_el = _make_el(db_id=1, ifc_entity_id=wall_e.id())
    return f, wall_e, wall_el


@pytest.fixture
def ifc2x3_props():
    """
    IFC2X3 file with:
    - IfcWall
    - Pset_WallCommon with Reference (IfcLabel → TEXT)
    - BaseQuantities with Length (IfcQuantityLength → NUMBER)
    - Both related via IfcRelDefinesByProperties
    """
    f = ifcopenshell.file(schema="IFC2X3")
    guid = ifcopenshell.guid

    wall_e = f.create_entity("IfcWall", GlobalId=guid.new(), Name="Wall2X3")

    pset = f.create_entity(
        "IfcPropertySet",
        GlobalId=guid.new(),
        Name="Pset_WallCommon",
        HasProperties=[
            f.create_entity(
                "IfcPropertySingleValue",
                Name="Reference",
                NominalValue=f.create_entity("IfcLabel", "W2X3-REF"),
            ),
        ],
    )
    qto = f.create_entity(
        "IfcElementQuantity",
        GlobalId=guid.new(),
        Name="BaseQuantities",
        Quantities=[
            f.create_entity("IfcQuantityLength", Name="Length", LengthValue=3.0),
        ],
    )

    f.create_entity(
        "IfcRelDefinesByProperties",
        GlobalId=guid.new(),
        RelatingPropertyDefinition=pset,
        RelatedObjects=[wall_e],
    )
    f.create_entity(
        "IfcRelDefinesByProperties",
        GlobalId=guid.new(),
        RelatingPropertyDefinition=qto,
        RelatedObjects=[wall_e],
    )

    wall_el = _make_el(db_id=10, ifc_entity_id=wall_e.id())
    return f, wall_e, wall_el


# ===========================================================================
# Helper
# ===========================================================================

def _run(ifc_file, elements, *, model=None, db=None):
    if model is None:
        model = FakeModel()
    if db is None:
        db = FakeSession()
    props = extract_and_persist_element_properties(db, model, ifc_file, elements)
    return props, model, db


def _find(props, *, group_name=None, property_name=None):
    """Filter ElementProperty list by group_name and/or property_name."""
    result = props
    if group_name is not None:
        result = [p for p in result if p.group_name == group_name]
    if property_name is not None:
        result = [p for p in result if p.property_name == property_name]
    return result


# ===========================================================================
# 1–2. Basic extraction IFC4
# ===========================================================================

def test_ifc4_pset_extracted(ifc4_props):
    f, _, wall_el = ifc4_props
    props, _, _ = _run(f, [wall_el])
    pset_rows = [p for p in props if p.group_type == "PSET"]
    assert len(pset_rows) == 5  # Reference, FireRating, IsExternal, Thermal, Optional


def test_ifc4_qto_extracted(ifc4_props):
    f, _, wall_el = ifc4_props
    props, _, _ = _run(f, [wall_el])
    qto_rows = [p for p in props if p.group_type == "QTO"]
    assert len(qto_rows) == 3  # Length, Area, Volume


# ===========================================================================
# 3–4. IFC2X3 compatibility
# ===========================================================================

def test_ifc2x3_pset_works(ifc2x3_props):
    f, _, wall_el = ifc2x3_props
    props, _, _ = _run(f, [wall_el])
    pset_rows = [p for p in props if p.group_type == "PSET"]
    assert len(pset_rows) == 1
    assert pset_rows[0].property_name == "Reference"


def test_ifc2x3_qto_works(ifc2x3_props):
    f, _, wall_el = ifc2x3_props
    props, _, _ = _run(f, [wall_el])
    qto_rows = [p for p in props if p.group_type == "QTO"]
    assert len(qto_rows) == 1
    assert qto_rows[0].property_name == "Length"
    assert qto_rows[0].value_number == pytest.approx(3.0)


# ===========================================================================
# 5–10. Core field mapping
# ===========================================================================

def test_element_id_correct(ifc4_props):
    f, _, wall_el = ifc4_props
    props, _, _ = _run(f, [wall_el])
    assert all(p.element_id == wall_el.id for p in props)


def test_group_type_pset(ifc4_props):
    f, _, wall_el = ifc4_props
    props, _, _ = _run(f, [wall_el])
    ref_row = _find(props, property_name="Reference")[0]
    assert ref_row.group_type == "PSET"


def test_group_type_qto(ifc4_props):
    f, _, wall_el = ifc4_props
    props, _, _ = _run(f, [wall_el])
    length_row = _find(props, property_name="Length")[0]
    assert length_row.group_type == "QTO"


def test_group_name_pset(ifc4_props):
    f, _, wall_el = ifc4_props
    props, _, _ = _run(f, [wall_el])
    ref_row = _find(props, property_name="Reference")[0]
    assert ref_row.group_name == "Pset_WallCommon"


def test_group_name_qto(ifc4_props):
    f, _, wall_el = ifc4_props
    props, _, _ = _run(f, [wall_el])
    length_row = _find(props, property_name="Length")[0]
    assert length_row.group_name == "BaseQuantities"


def test_property_name_correct(ifc4_props):
    f, _, wall_el = ifc4_props
    props, _, _ = _run(f, [wall_el])
    names = {p.property_name for p in props}
    assert "Reference" in names
    assert "FireRating" in names
    assert "IsExternal" in names
    assert "ThermalTransmittance" in names
    assert "OptionalValue" in names
    assert "Length" in names
    assert "Area" in names
    assert "Volume" in names


# ===========================================================================
# 11–16. Value typing
# ===========================================================================

def test_text_value_coherent(ifc4_props):
    f, _, wall_el = ifc4_props
    props, _, _ = _run(f, [wall_el])
    ref = _find(props, property_name="Reference")[0]
    assert ref.value_kind == "TEXT"
    assert ref.value_text == "W-REF-01"
    assert ref.value_number is None
    assert ref.value_boolean is None


def test_number_value_coherent(ifc4_props):
    f, _, wall_el = ifc4_props
    props, _, _ = _run(f, [wall_el])
    thermal = _find(props, property_name="ThermalTransmittance")[0]
    assert thermal.value_kind == "NUMBER"
    assert thermal.value_number == pytest.approx(0.35)
    assert thermal.value_text is None
    assert thermal.value_boolean is None


def test_boolean_value_coherent(ifc4_props):
    f, _, wall_el = ifc4_props
    props, _, _ = _run(f, [wall_el])
    ext = _find(props, property_name="IsExternal")[0]
    assert ext.value_kind == "BOOLEAN"
    assert ext.value_boolean is True
    assert ext.value_text is None
    assert ext.value_number is None


def test_null_value_coherent(ifc4_props):
    f, _, wall_el = ifc4_props
    props, _, _ = _run(f, [wall_el])
    opt = _find(props, property_name="OptionalValue")[0]
    assert opt.value_kind == "NULL"
    assert opt.value_text is None
    assert opt.value_number is None
    assert opt.value_boolean is None


def test_ifc_value_type_label(ifc4_props):
    f, _, wall_el = ifc4_props
    props, _, _ = _run(f, [wall_el])
    ref = _find(props, property_name="Reference")[0]
    assert ref.ifc_value_type == "IfcLabel"


def test_ifc_value_type_boolean(ifc4_props):
    f, _, wall_el = ifc4_props
    props, _, _ = _run(f, [wall_el])
    ext = _find(props, property_name="IsExternal")[0]
    assert ext.ifc_value_type == "IfcBoolean"


# ===========================================================================
# 17. QTO ifc_value_type
# ===========================================================================

def test_qto_ifc_value_type(ifc4_props):
    f, _, wall_el = ifc4_props
    props, _, _ = _run(f, [wall_el])
    length_row = _find(props, property_name="Length")[0]
    assert length_row.ifc_value_type == "IfcQuantityLength"
    area_row = _find(props, property_name="Area")[0]
    assert area_row.ifc_value_type == "IfcQuantityArea"
    vol_row = _find(props, property_name="Volume")[0]
    assert vol_row.ifc_value_type == "IfcQuantityVolume"


# ===========================================================================
# 18–20. Units
# ===========================================================================

def test_unit_none(ifc4_props):
    """Properties and quantities without explicit unit → unit = None."""
    f, _, wall_el = ifc4_props
    props, _, _ = _run(f, [wall_el])
    # All properties in the base fixture have no explicit unit
    assert all(p.unit is None for p in props)


def test_si_unit_name_only():
    """IfcSIUnit with no Prefix → unit = 'METRE'."""
    f = ifcopenshell.file(schema="IFC4")
    guid = ifcopenshell.guid
    wall_e = f.create_entity("IfcWall", GlobalId=guid.new())
    si_unit = f.create_entity(
        "IfcSIUnit", UnitType="LENGTHUNIT", Prefix=None, Name="METRE"
    )
    pset = f.create_entity(
        "IfcPropertySet",
        GlobalId=guid.new(),
        Name="PSU",
        HasProperties=[
            f.create_entity(
                "IfcPropertySingleValue",
                Name="Val",
                NominalValue=f.create_entity("IfcLengthMeasure", 1.0),
                Unit=si_unit,
            )
        ],
    )
    f.create_entity(
        "IfcRelDefinesByProperties",
        GlobalId=guid.new(),
        RelatingPropertyDefinition=pset,
        RelatedObjects=[wall_e],
    )
    wall_el = _make_el(db_id=1, ifc_entity_id=wall_e.id())
    props, _, _ = _run(f, [wall_el])
    assert props[0].unit == "METRE"


def test_si_unit_with_prefix():
    """IfcSIUnit with Prefix → unit = 'MILLI METRE'."""
    f = ifcopenshell.file(schema="IFC4")
    guid = ifcopenshell.guid
    wall_e = f.create_entity("IfcWall", GlobalId=guid.new())
    si_unit_mm = f.create_entity(
        "IfcSIUnit", UnitType="LENGTHUNIT", Prefix="MILLI", Name="METRE"
    )
    pset = f.create_entity(
        "IfcPropertySet",
        GlobalId=guid.new(),
        Name="PSU",
        HasProperties=[
            f.create_entity(
                "IfcPropertySingleValue",
                Name="Thick",
                NominalValue=f.create_entity("IfcLengthMeasure", 200.0),
                Unit=si_unit_mm,
            )
        ],
    )
    f.create_entity(
        "IfcRelDefinesByProperties",
        GlobalId=guid.new(),
        RelatingPropertyDefinition=pset,
        RelatedObjects=[wall_e],
    )
    wall_el = _make_el(db_id=1, ifc_entity_id=wall_e.id())
    props, _, _ = _run(f, [wall_el])
    assert props[0].unit == "MILLI METRE"


# ===========================================================================
# 21–22. Relation edge cases
# ===========================================================================

def test_multiple_related_objects():
    """One IfcRelDefinesByProperties with two elements → one row per element."""
    f = ifcopenshell.file(schema="IFC4")
    guid = ifcopenshell.guid

    wall_a = f.create_entity("IfcWall", GlobalId=guid.new(), Name="WA")
    wall_b = f.create_entity("IfcWall", GlobalId=guid.new(), Name="WB")

    pset = f.create_entity(
        "IfcPropertySet",
        GlobalId=guid.new(),
        Name="Pset_WallCommon",
        HasProperties=[
            f.create_entity(
                "IfcPropertySingleValue",
                Name="FireRating",
                NominalValue=f.create_entity("IfcLabel", "2h"),
            )
        ],
    )
    f.create_entity(
        "IfcRelDefinesByProperties",
        GlobalId=guid.new(),
        RelatingPropertyDefinition=pset,
        RelatedObjects=[wall_a, wall_b],
    )

    el_a = _make_el(db_id=1, ifc_entity_id=wall_a.id())
    el_b = _make_el(db_id=2, ifc_entity_id=wall_b.id())
    props, _, _ = _run(f, [el_a, el_b])

    # Two FireRating rows — one per element
    assert len(props) == 2
    el_ids = {p.element_id for p in props}
    assert el_ids == {el_a.id, el_b.id}
    assert all(p.property_name == "FireRating" for p in props)


def test_object_not_in_elements_ignored():
    """IFC entity in RelatedObjects but absent from elements → silently ignored."""
    f = ifcopenshell.file(schema="IFC4")
    guid = ifcopenshell.guid

    wall_a = f.create_entity("IfcWall", GlobalId=guid.new(), Name="WA")
    wall_b = f.create_entity("IfcWall", GlobalId=guid.new(), Name="WB")

    pset = f.create_entity(
        "IfcPropertySet",
        GlobalId=guid.new(),
        Name="PST",
        HasProperties=[
            f.create_entity(
                "IfcPropertySingleValue",
                Name="Prop",
                NominalValue=f.create_entity("IfcLabel", "v"),
            )
        ],
    )
    f.create_entity(
        "IfcRelDefinesByProperties",
        GlobalId=guid.new(),
        RelatingPropertyDefinition=pset,
        RelatedObjects=[wall_a, wall_b],
    )

    # Only wall_a in elements; wall_b absent
    el_a = _make_el(db_id=1, ifc_entity_id=wall_a.id())
    props, _, _ = _run(f, [el_a])

    assert len(props) == 1
    assert props[0].element_id == el_a.id


# ===========================================================================
# 23–25. Ignored definitions
# ===========================================================================

def test_non_pset_qto_definition_ignored():
    """IfcRelDefinesByProperties with unsupported RelatingPropertyDefinition → skipped."""
    f = ifcopenshell.file(schema="IFC4")
    guid = ifcopenshell.guid
    wall_e = f.create_entity("IfcWall", GlobalId=guid.new())

    class _OtherDef:
        def is_a(self, t=None):
            if t is None:
                return "IfcPreDefinedPropertySet"
            return False

        def id(self):
            return 99999

    class _FakeRel:
        def id(self):
            return 1

        RelatingPropertyDefinition = _OtherDef()

        @property
        def RelatedObjects(self):
            return [wall_e]

    class _FileWithOtherDef:
        def by_type(self, ifc_type):
            if ifc_type == "IfcRelDefinesByProperties":
                return [_FakeRel()]
            return f.by_type(ifc_type)

    wall_el = _make_el(db_id=1, ifc_entity_id=wall_e.id())
    props, model, _ = _run(_FileWithOtherDef(), [wall_el])
    assert props == []
    assert model.property_count == 0


def test_unsupported_property_subtype_ignored():
    """IfcPropertyEnumeratedValue in a PSET → skipped, no error."""
    f = ifcopenshell.file(schema="IFC4")
    guid = ifcopenshell.guid
    wall_e = f.create_entity("IfcWall", GlobalId=guid.new())

    enum_prop = f.create_entity(
        "IfcPropertyEnumeratedValue",
        Name="Material",
        EnumerationValues=[f.create_entity("IfcLabel", "Concrete")],
    )
    pset = f.create_entity(
        "IfcPropertySet",
        GlobalId=guid.new(),
        Name="Pset_Test",
        HasProperties=[enum_prop],
    )
    f.create_entity(
        "IfcRelDefinesByProperties",
        GlobalId=guid.new(),
        RelatingPropertyDefinition=pset,
        RelatedObjects=[wall_e],
    )

    wall_el = _make_el(db_id=1, ifc_entity_id=wall_e.id())
    props, model, _ = _run(f, [wall_el])
    assert props == []
    assert model.property_count == 0


def test_complex_quantity_ignored():
    """IfcPhysicalComplexQuantity in a QTO → skipped, no error."""
    f = ifcopenshell.file(schema="IFC4")
    guid = ifcopenshell.guid
    wall_e = f.create_entity("IfcWall", GlobalId=guid.new())

    complex_qty = f.create_entity(
        "IfcPhysicalComplexQuantity",
        Name="ComplexQ",
        HasQuantities=[],
        Discrimination="Disc",
    )
    qto = f.create_entity(
        "IfcElementQuantity",
        GlobalId=guid.new(),
        Name="QTO_Test",
        Quantities=[complex_qty],
    )
    f.create_entity(
        "IfcRelDefinesByProperties",
        GlobalId=guid.new(),
        RelatingPropertyDefinition=qto,
        RelatedObjects=[wall_e],
    )

    wall_el = _make_el(db_id=1, ifc_entity_id=wall_e.id())
    props, model, _ = _run(f, [wall_el])
    assert props == []
    assert model.property_count == 0


# ===========================================================================
# 26–28. Required name validation
# ===========================================================================

def _make_rel_with_pset(f, wall_e, pset_name, prop_name="Prop"):
    """Helper: build IfcPropertySet and rel in file f."""
    pset = f.create_entity(
        "IfcPropertySet",
        GlobalId=ifcopenshell.guid.new(),
        Name=pset_name,
        HasProperties=[
            f.create_entity(
                "IfcPropertySingleValue",
                Name=prop_name,
                NominalValue=f.create_entity("IfcLabel", "v"),
            )
        ],
    )
    f.create_entity(
        "IfcRelDefinesByProperties",
        GlobalId=ifcopenshell.guid.new(),
        RelatingPropertyDefinition=pset,
        RelatedObjects=[wall_e],
    )


def test_blank_group_name_raises():
    """PSET with blank Name → IfcPropertyExtractionError."""
    f = ifcopenshell.file(schema="IFC4")
    guid = ifcopenshell.guid
    wall_e = f.create_entity("IfcWall", GlobalId=guid.new())

    class _BlankNamePset:
        def is_a(self, t=None):
            return (t == "IfcPropertySet") if t else "IfcPropertySet"

        Name = ""
        HasProperties = []

        def id(self):
            return 99999

    class _Rel:
        def id(self):
            return 1

        RelatingPropertyDefinition = _BlankNamePset()

        @property
        def RelatedObjects(self):
            return [wall_e]

    class _File:
        def by_type(self, t):
            if t == "IfcRelDefinesByProperties":
                return [_Rel()]
            return f.by_type(t)

    wall_el = _make_el(db_id=1, ifc_entity_id=wall_e.id())
    with pytest.raises(IfcPropertyExtractionError):
        extract_and_persist_element_properties(
            FakeSession(), FakeModel(), _File(), [wall_el]
        )


def test_none_group_name_raises():
    """PSET with None Name → IfcPropertyExtractionError."""
    f = ifcopenshell.file(schema="IFC4")
    guid = ifcopenshell.guid
    wall_e = f.create_entity("IfcWall", GlobalId=guid.new())

    class _NoneNamePset:
        def is_a(self, t=None):
            return (t == "IfcPropertySet") if t else "IfcPropertySet"

        Name = None
        HasProperties = []

        def id(self):
            return 99999

    class _Rel:
        def id(self):
            return 1

        RelatingPropertyDefinition = _NoneNamePset()

        @property
        def RelatedObjects(self):
            return [wall_e]

    class _File:
        def by_type(self, t):
            if t == "IfcRelDefinesByProperties":
                return [_Rel()]
            return f.by_type(t)

    wall_el = _make_el(db_id=1, ifc_entity_id=wall_e.id())
    with pytest.raises(IfcPropertyExtractionError):
        extract_and_persist_element_properties(
            FakeSession(), FakeModel(), _File(), [wall_el]
        )


def test_blank_property_name_raises():
    """IfcPropertySingleValue with blank Name → IfcPropertyExtractionError."""
    f = ifcopenshell.file(schema="IFC4")
    guid = ifcopenshell.guid
    wall_e = f.create_entity("IfcWall", GlobalId=guid.new())

    blank_prop = f.create_entity(
        "IfcPropertySingleValue",
        Name="   ",
        NominalValue=f.create_entity("IfcLabel", "v"),
    )
    pset = f.create_entity(
        "IfcPropertySet",
        GlobalId=guid.new(),
        Name="Pset_Test",
        HasProperties=[blank_prop],
    )
    f.create_entity(
        "IfcRelDefinesByProperties",
        GlobalId=guid.new(),
        RelatingPropertyDefinition=pset,
        RelatedObjects=[wall_e],
    )

    wall_el = _make_el(db_id=1, ifc_entity_id=wall_e.id())
    with pytest.raises(IfcPropertyExtractionError):
        extract_and_persist_element_properties(
            FakeSession(), FakeModel(), f, [wall_el]
        )


# ===========================================================================
# 29–31. Error propagation
# ===========================================================================

def test_error_message_generic():
    """by_type() crash → IfcPropertyExtractionError with public message."""
    # A valid element is required so the service reaches ifc_file.by_type().
    _dummy = _make_el(db_id=1, ifc_entity_id=1)

    class _BrokenFile:
        def by_type(self, t):
            raise RuntimeError("IfcOpenShell crash")

    with pytest.raises(IfcPropertyExtractionError) as exc_info:
        extract_and_persist_element_properties(
            FakeSession(), FakeModel(), _BrokenFile(), [_dummy]
        )
    assert "No se pudieron extraer las propiedades del archivo IFC." in str(
        exc_info.value
    )


def test_cause_preserved():
    """__cause__ of IfcPropertyExtractionError is the original exception."""
    _dummy = _make_el(db_id=1, ifc_entity_id=1)

    class _BrokenFile:
        def by_type(self, t):
            raise RuntimeError("crash")

    with pytest.raises(IfcPropertyExtractionError) as exc_info:
        extract_and_persist_element_properties(
            FakeSession(), FakeModel(), _BrokenFile(), [_dummy]
        )
    assert exc_info.value.__cause__ is not None


def test_by_type_error_wrapped():
    """OSError from by_type() is preserved as __cause__."""
    _dummy = _make_el(db_id=1, ifc_entity_id=1)

    class _BrokenFile:
        def by_type(self, t):
            raise OSError("IO failure")

    with pytest.raises(IfcPropertyExtractionError) as exc_info:
        extract_and_persist_element_properties(
            FakeSession(), FakeModel(), _BrokenFile(), [_dummy]
        )
    assert isinstance(exc_info.value.__cause__, OSError)


# ===========================================================================
# 32–33. Element validation
# ===========================================================================

def test_element_wrong_model_raises(ifc4_props):
    f, _, _ = ifc4_props
    el = _make_el(db_id=1, ifc_entity_id=100, model_id=999)
    with pytest.raises(IfcPropertyExtractionError):
        extract_and_persist_element_properties(
            FakeSession(), FakeModel(model_id=1), f, [el]
        )


def test_element_no_db_id_raises(ifc4_props):
    f, wall_e, _ = ifc4_props
    el = IfcElement(
        model_id=1,
        ifc_entity_id=wall_e.id(),
        global_id=ifcopenshell.guid.new(),
        ifc_type="IfcWall",
    )
    # el.id is None (not flushed)
    with pytest.raises(IfcPropertyExtractionError):
        extract_and_persist_element_properties(
            FakeSession(), FakeModel(), f, [el]
        )


def test_element_invalid_ifc_entity_id_raises(ifc4_props):
    """IfcElement with ifc_entity_id=0 (non-positive) → IfcPropertyExtractionError."""
    f, _, _ = ifc4_props
    el = _make_el(db_id=1, ifc_entity_id=1)
    el.ifc_entity_id = 0  # invalid — must be > 0
    with pytest.raises(IfcPropertyExtractionError):
        extract_and_persist_element_properties(
            FakeSession(), FakeModel(), f, [el]
        )


def test_complex_entity_nominal_value_raises():
    """NominalValue whose wrappedValue is a complex IFC entity (not a scalar) →
    IfcPropertyExtractionError; no STEP representation stored."""
    f = ifcopenshell.file(schema="IFC4")
    guid = ifcopenshell.guid
    wall_e = f.create_entity("IfcWall", GlobalId=guid.new())

    class _EntityProxy:
        """Mimics an IFC entity reference: has is_a() / id() but no wrappedValue."""

        def is_a(self, t=None):
            return "IfcMaterialReference" if t is None else False

        def id(self):
            return 99999

        # Deliberately no wrappedValue → _classify_nominal_value falls through
        # to the unknown-type branch and must raise ValueError.

    class _ComplexProp:
        def is_a(self, t=None):
            return (t == "IfcPropertySingleValue") if t else "IfcPropertySingleValue"

        Name = "ComplexProp"
        NominalValue = _EntityProxy()
        Unit = None

        def id(self):
            return 88888

    class _ComplexPset:
        def is_a(self, t=None):
            return (t == "IfcPropertySet") if t else "IfcPropertySet"

        Name = "PsetComplex"
        HasProperties = [_ComplexProp()]

        def id(self):
            return 77777

    class _Rel:
        def id(self):
            return 1

        RelatingPropertyDefinition = _ComplexPset()

        @property
        def RelatedObjects(self):
            return [wall_e]

    class _File:
        def by_type(self, t):
            if t == "IfcRelDefinesByProperties":
                return [_Rel()]
            return f.by_type(t)

    wall_el = _make_el(db_id=1, ifc_entity_id=wall_e.id())
    with pytest.raises(IfcPropertyExtractionError):
        extract_and_persist_element_properties(
            FakeSession(), FakeModel(), _File(), [wall_el]
        )


def test_malformed_pset_for_unrelated_objects_ignored():
    """A relation whose ALL RelatedObjects are absent from elements is skipped
    before group_name validation — blank PSET Name must not cause an error."""
    f = ifcopenshell.file(schema="IFC4")
    guid = ifcopenshell.guid

    # wall_absent: in the IFC file but NOT in elements
    wall_absent = f.create_entity("IfcWall", GlobalId=guid.new(), Name="Absent")
    # wall_present: in elements but has no relation pointing to it
    wall_present = f.create_entity("IfcWall", GlobalId=guid.new(), Name="Present")

    class _BlankNamePset:
        def is_a(self, t=None):
            return (t == "IfcPropertySet") if t else "IfcPropertySet"

        Name = ""  # blank — would error if reached
        HasProperties = []

        def id(self):
            return 99999

    class _BadRel:
        def id(self):
            return 1

        RelatingPropertyDefinition = _BlankNamePset()

        @property
        def RelatedObjects(self):
            return [wall_absent]  # only the absent wall

    class _File:
        def by_type(self, t):
            if t == "IfcRelDefinesByProperties":
                return [_BadRel()]
            return f.by_type(t)

    el_present = _make_el(db_id=1, ifc_entity_id=wall_present.id())
    # Only el_present is in elements; wall_absent is not.
    # Bad relation should be skipped entirely — no IfcPropertyExtractionError.
    props, model, _ = _run(_File(), [el_present])
    assert props == []
    assert model.property_count == 0


def test_qto_count_weight_time():
    """IfcQuantityCount, IfcQuantityWeight, IfcQuantityTime → NUMBER rows."""
    f = ifcopenshell.file(schema="IFC4")
    guid = ifcopenshell.guid
    wall_e = f.create_entity("IfcWall", GlobalId=guid.new())

    qto = f.create_entity(
        "IfcElementQuantity",
        GlobalId=guid.new(),
        Name="QTO_Parts",
        Quantities=[
            f.create_entity("IfcQuantityCount", Name="Count", CountValue=3.0),
            f.create_entity("IfcQuantityWeight", Name="Weight", WeightValue=150.5),
            f.create_entity("IfcQuantityTime", Name="InstallTime", TimeValue=8.0),
        ],
    )
    f.create_entity(
        "IfcRelDefinesByProperties",
        GlobalId=guid.new(),
        RelatingPropertyDefinition=qto,
        RelatedObjects=[wall_e],
    )

    wall_el = _make_el(db_id=1, ifc_entity_id=wall_e.id())
    props, _, _ = _run(f, [wall_el])

    by_name = {p.property_name: p for p in props}
    assert by_name["Count"].value_kind == "NUMBER"
    assert by_name["Count"].value_number == pytest.approx(3.0)
    assert by_name["Count"].ifc_value_type == "IfcQuantityCount"

    assert by_name["Weight"].value_kind == "NUMBER"
    assert by_name["Weight"].value_number == pytest.approx(150.5)
    assert by_name["Weight"].ifc_value_type == "IfcQuantityWeight"

    assert by_name["InstallTime"].value_kind == "NUMBER"
    assert by_name["InstallTime"].value_number == pytest.approx(8.0)
    assert by_name["InstallTime"].ifc_value_type == "IfcQuantityTime"


# ===========================================================================
# 34–36. Empty elements
# ===========================================================================

def test_empty_elements_returns_empty(ifc4_props):
    f, _, _ = ifc4_props
    props, _, _ = _run(f, [])
    assert props == []


def test_empty_elements_count_zero(ifc4_props):
    f, _, _ = ifc4_props
    _, model, _ = _run(f, [])
    assert model.property_count == 0


def test_empty_elements_no_flush(ifc4_props):
    f, _, _ = ifc4_props
    db = FakeSession()
    _run(f, [], db=db)
    assert db.flush_count == 0
    assert db.add_all_count == 0


# ===========================================================================
# 37–38. No supported properties
# ===========================================================================

def test_no_supported_props_returns_empty():
    """PSET with only IfcPropertyEnumeratedValue → empty result."""
    f = ifcopenshell.file(schema="IFC4")
    guid = ifcopenshell.guid
    wall_e = f.create_entity("IfcWall", GlobalId=guid.new())
    enum_prop = f.create_entity(
        "IfcPropertyEnumeratedValue",
        Name="Material",
        EnumerationValues=[f.create_entity("IfcLabel", "Concrete")],
    )
    pset = f.create_entity(
        "IfcPropertySet",
        GlobalId=guid.new(),
        Name="Pset_Test",
        HasProperties=[enum_prop],
    )
    f.create_entity(
        "IfcRelDefinesByProperties",
        GlobalId=guid.new(),
        RelatingPropertyDefinition=pset,
        RelatedObjects=[wall_e],
    )
    wall_el = _make_el(db_id=1, ifc_entity_id=wall_e.id())
    props, _, _ = _run(f, [wall_el])
    assert props == []


def test_no_supported_props_no_flush():
    """No supported properties → no flush, no add_all."""
    f = ifcopenshell.file(schema="IFC4")
    guid = ifcopenshell.guid
    wall_e = f.create_entity("IfcWall", GlobalId=guid.new())
    enum_prop = f.create_entity(
        "IfcPropertyEnumeratedValue",
        Name="Mat",
        EnumerationValues=[f.create_entity("IfcLabel", "Steel")],
    )
    pset = f.create_entity(
        "IfcPropertySet",
        GlobalId=guid.new(),
        Name="P",
        HasProperties=[enum_prop],
    )
    f.create_entity(
        "IfcRelDefinesByProperties",
        GlobalId=guid.new(),
        RelatingPropertyDefinition=pset,
        RelatedObjects=[wall_e],
    )
    wall_el = _make_el(db_id=1, ifc_entity_id=wall_e.id())
    db = FakeSession()
    _run(f, [wall_el], db=db)
    assert db.flush_count == 0
    assert db.add_all_count == 0


# ===========================================================================
# 39–40. Flush discipline
# ===========================================================================

def test_success_exactly_one_flush(ifc4_props):
    f, _, wall_el = ifc4_props
    db = FakeSession()
    _run(f, [wall_el], db=db)
    assert db.flush_count == 1


def test_flush_failure_wrapped(ifc4_props):
    f, _, wall_el = ifc4_props
    db = FailingSession(fail_on=1)
    with pytest.raises(IfcPropertyExtractionError):
        extract_and_persist_element_properties(db, FakeModel(), f, [wall_el])


# ===========================================================================
# 41–46. Counter and model state
# ===========================================================================

def test_property_count_correct(ifc4_props):
    f, _, wall_el = ifc4_props
    _, model, _ = _run(f, [wall_el])
    # 5 PSET + 3 QTO = 8
    assert model.property_count == 8


def test_spatial_node_count_not_modified(ifc4_props):
    f, _, wall_el = ifc4_props
    model = FakeModel()
    model.spatial_node_count = 5
    _run(f, [wall_el], model=model)
    assert model.spatial_node_count == 5


def test_element_count_not_modified(ifc4_props):
    f, _, wall_el = ifc4_props
    model = FakeModel()
    model.element_count = 12
    _run(f, [wall_el], model=model)
    assert model.element_count == 12


def test_status_not_modified(ifc4_props):
    f, _, wall_el = ifc4_props
    model = FakeModel()
    model.status = "DONE"
    _run(f, [wall_el], model=model)
    assert model.status == "DONE"


def test_model_state_not_modified(ifc4_props):
    """ifc_schema and error_message must not change."""
    f, _, wall_el = ifc4_props
    model = FakeModel()
    model.ifc_schema = "IFC4"
    model.error_message = "prior"
    _run(f, [wall_el], model=model)
    assert model.ifc_schema == "IFC4"
    assert model.error_message == "prior"


# ===========================================================================
# 47–48. Transaction discipline
# ===========================================================================

def test_no_commit(ifc4_props):
    f, _, wall_el = ifc4_props
    db = FakeSession()
    _run(f, [wall_el], db=db)
    assert db.committed is False


def test_no_rollback(ifc4_props):
    f, _, wall_el = ifc4_props
    db = FakeSession()
    _run(f, [wall_el], db=db)
    assert db.rolled_back is False


# ===========================================================================
# 49. Deterministic order
# ===========================================================================

def test_deterministic_order():
    """Two relations in known rel.id() order → output order matches."""
    f = ifcopenshell.file(schema="IFC4")
    guid = ifcopenshell.guid
    wall_e = f.create_entity("IfcWall", GlobalId=guid.new())

    pset_a = f.create_entity(
        "IfcPropertySet",
        GlobalId=guid.new(),
        Name="PsetA",
        HasProperties=[
            f.create_entity(
                "IfcPropertySingleValue",
                Name="PA",
                NominalValue=f.create_entity("IfcLabel", "a"),
            )
        ],
    )
    pset_b = f.create_entity(
        "IfcPropertySet",
        GlobalId=guid.new(),
        Name="PsetB",
        HasProperties=[
            f.create_entity(
                "IfcPropertySingleValue",
                Name="PB",
                NominalValue=f.create_entity("IfcLabel", "b"),
            )
        ],
    )
    rel_a = f.create_entity(
        "IfcRelDefinesByProperties",
        GlobalId=guid.new(),
        RelatingPropertyDefinition=pset_a,
        RelatedObjects=[wall_e],
    )
    rel_b = f.create_entity(
        "IfcRelDefinesByProperties",
        GlobalId=guid.new(),
        RelatingPropertyDefinition=pset_b,
        RelatedObjects=[wall_e],
    )
    assert rel_a.id() < rel_b.id()

    wall_el = _make_el(db_id=1, ifc_entity_id=wall_e.id())
    props, _, _ = _run(f, [wall_el])
    assert len(props) == 2
    # First relation (PsetA/PA) must come before second (PsetB/PB)
    assert props[0].group_name == "PsetA"
    assert props[1].group_name == "PsetB"


# ===========================================================================
# 50. Exports
# ===========================================================================

def test_exports_from_services():
    from app.services import IfcPropertyExtractionError as E
    from app.services import extract_and_persist_element_properties as fn

    assert E is IfcPropertyExtractionError
    assert callable(fn)
