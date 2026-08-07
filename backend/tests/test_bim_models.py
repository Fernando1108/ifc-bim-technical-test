"""
SQLAlchemy metadata tests for BIM relational model.

No database connection required — validates ORM table definitions only.
"""
import sqlalchemy as sa

from app.models.spatial_node import SpatialNode
from app.models.element import IfcElement
from app.models.element_property import ElementProperty
import app.models as models_pkg

_SN = SpatialNode.__table__
_EL = IfcElement.__table__
_EP = ElementProperty.__table__


# ===========================================================================
# Helpers
# ===========================================================================

def _col(table, name: str) -> sa.Column:
    return table.c[name]


def _constraint_names(table) -> set:
    return {c.name for c in table.constraints}


def _index_names(table) -> set:
    return {idx.name for idx in table.indexes}


def _fk_for_col(table, col_name: str):
    fks = list(_col(table, col_name).foreign_keys)
    assert len(fks) == 1, f"Expected 1 FK on {col_name}, got {len(fks)}"
    return fks[0]


# ===========================================================================
# SPATIAL NODES — table name
# ===========================================================================

def test_spatial_nodes_tablename():
    assert SpatialNode.__tablename__ == "spatial_nodes"


# ---------------------------------------------------------------------------
# SPATIAL NODES — column set
# ---------------------------------------------------------------------------

def test_spatial_nodes_column_set():
    expected = {
        "id",
        "model_id",
        "ifc_entity_id",
        "global_id",
        "ifc_type",
        "name",
        "description",
        "long_name",
        "elevation",
        "parent_id",
        "created_at",
    }
    assert set(_SN.c.keys()) == expected


# ---------------------------------------------------------------------------
# SPATIAL NODES — primary key
# ---------------------------------------------------------------------------

def test_spatial_nodes_pk():
    assert _col(_SN, "id").primary_key is True


# ---------------------------------------------------------------------------
# SPATIAL NODES — nullability
# ---------------------------------------------------------------------------

def test_spatial_nodes_model_id_not_nullable():
    assert _col(_SN, "model_id").nullable is False


def test_spatial_nodes_ifc_entity_id_not_nullable():
    assert _col(_SN, "ifc_entity_id").nullable is False


def test_spatial_nodes_global_id_not_nullable():
    assert _col(_SN, "global_id").nullable is False


def test_spatial_nodes_ifc_type_not_nullable():
    assert _col(_SN, "ifc_type").nullable is False


def test_spatial_nodes_created_at_not_nullable():
    assert _col(_SN, "created_at").nullable is False


def test_spatial_nodes_name_nullable():
    assert _col(_SN, "name").nullable is True


def test_spatial_nodes_description_nullable():
    assert _col(_SN, "description").nullable is True


def test_spatial_nodes_long_name_nullable():
    assert _col(_SN, "long_name").nullable is True


def test_spatial_nodes_elevation_nullable():
    assert _col(_SN, "elevation").nullable is True


def test_spatial_nodes_parent_id_nullable():
    assert _col(_SN, "parent_id").nullable is True


# ---------------------------------------------------------------------------
# SPATIAL NODES — FK model_id → ifc_models CASCADE
# ---------------------------------------------------------------------------

def test_spatial_nodes_model_fk_references_ifc_models():
    fk = _fk_for_col(_SN, "model_id")
    assert fk.column.table.name == "ifc_models"
    assert fk.column.name == "id"


def test_spatial_nodes_model_fk_ondelete_cascade():
    fk = _fk_for_col(_SN, "model_id")
    assert fk.ondelete.upper() == "CASCADE"


# ---------------------------------------------------------------------------
# SPATIAL NODES — FK parent_id → spatial_nodes CASCADE
# ---------------------------------------------------------------------------

def test_spatial_nodes_parent_fk_references_self():
    fk = _fk_for_col(_SN, "parent_id")
    assert fk.column.table.name == "spatial_nodes"
    assert fk.column.name == "id"


def test_spatial_nodes_parent_fk_ondelete_cascade():
    fk = _fk_for_col(_SN, "parent_id")
    assert fk.ondelete.upper() == "CASCADE"


# ---------------------------------------------------------------------------
# SPATIAL NODES — unique constraints
# ---------------------------------------------------------------------------

def test_spatial_nodes_unique_model_entity():
    assert "uq_spatial_nodes_model_entity" in _constraint_names(_SN)


def test_spatial_nodes_unique_model_global_id():
    assert "uq_spatial_nodes_model_global_id" in _constraint_names(_SN)


# ---------------------------------------------------------------------------
# SPATIAL NODES — CHECK constraints
# ---------------------------------------------------------------------------

def test_spatial_nodes_check_entity_positive():
    assert "ck_spatial_nodes_ifc_entity_id_positive" in _constraint_names(_SN)


# ---------------------------------------------------------------------------
# SPATIAL NODES — indexes
# ---------------------------------------------------------------------------

def test_spatial_nodes_index_model_id():
    assert "ix_spatial_nodes_model_id" in _index_names(_SN)


def test_spatial_nodes_index_parent_id():
    assert "ix_spatial_nodes_parent_id" in _index_names(_SN)


def test_spatial_nodes_index_model_ifc_type():
    assert "ix_spatial_nodes_model_ifc_type" in _index_names(_SN)


# ===========================================================================
# ELEMENTS — table name
# ===========================================================================

def test_elements_tablename():
    assert IfcElement.__tablename__ == "elements"


# ---------------------------------------------------------------------------
# ELEMENTS — column set
# ---------------------------------------------------------------------------

def test_elements_column_set():
    expected = {
        "id",
        "model_id",
        "ifc_entity_id",
        "global_id",
        "ifc_type",
        "name",
        "description",
        "object_type",
        "tag",
        "predefined_type",
        "type_global_id",
        "type_ifc_type",
        "type_name",
        "direct_spatial_node_id",
        "resolved_storey_id",
        "parent_element_id",
        "created_at",
    }
    assert set(_EL.c.keys()) == expected


# ---------------------------------------------------------------------------
# ELEMENTS — primary key
# ---------------------------------------------------------------------------

def test_elements_pk():
    assert _col(_EL, "id").primary_key is True


# ---------------------------------------------------------------------------
# ELEMENTS — required columns
# ---------------------------------------------------------------------------

def test_elements_model_id_not_nullable():
    assert _col(_EL, "model_id").nullable is False


def test_elements_ifc_entity_id_not_nullable():
    assert _col(_EL, "ifc_entity_id").nullable is False


def test_elements_global_id_not_nullable():
    assert _col(_EL, "global_id").nullable is False


def test_elements_ifc_type_not_nullable():
    assert _col(_EL, "ifc_type").nullable is False


def test_elements_created_at_not_nullable():
    assert _col(_EL, "created_at").nullable is False


# ---------------------------------------------------------------------------
# ELEMENTS — optional columns
# ---------------------------------------------------------------------------

def test_elements_name_nullable():
    assert _col(_EL, "name").nullable is True


def test_elements_description_nullable():
    assert _col(_EL, "description").nullable is True


def test_elements_object_type_nullable():
    assert _col(_EL, "object_type").nullable is True


def test_elements_tag_nullable():
    assert _col(_EL, "tag").nullable is True


def test_elements_predefined_type_nullable():
    assert _col(_EL, "predefined_type").nullable is True


def test_elements_type_global_id_nullable():
    assert _col(_EL, "type_global_id").nullable is True


def test_elements_type_ifc_type_nullable():
    assert _col(_EL, "type_ifc_type").nullable is True


def test_elements_type_name_nullable():
    assert _col(_EL, "type_name").nullable is True


def test_elements_direct_spatial_node_id_nullable():
    assert _col(_EL, "direct_spatial_node_id").nullable is True


def test_elements_resolved_storey_id_nullable():
    assert _col(_EL, "resolved_storey_id").nullable is True


def test_elements_parent_element_id_nullable():
    assert _col(_EL, "parent_element_id").nullable is True


# ---------------------------------------------------------------------------
# ELEMENTS — FK model_id CASCADE
# ---------------------------------------------------------------------------

def test_elements_model_fk_references_ifc_models():
    fk = _fk_for_col(_EL, "model_id")
    assert fk.column.table.name == "ifc_models"
    assert fk.column.name == "id"


def test_elements_model_fk_ondelete_cascade():
    fk = _fk_for_col(_EL, "model_id")
    assert fk.ondelete.upper() == "CASCADE"


# ---------------------------------------------------------------------------
# ELEMENTS — FK direct_spatial_node_id SET NULL
# ---------------------------------------------------------------------------

def test_elements_direct_spatial_node_fk_references_spatial_nodes():
    fk = _fk_for_col(_EL, "direct_spatial_node_id")
    assert fk.column.table.name == "spatial_nodes"
    assert fk.column.name == "id"


def test_elements_direct_spatial_node_fk_ondelete_set_null():
    fk = _fk_for_col(_EL, "direct_spatial_node_id")
    assert fk.ondelete.upper() == "SET NULL"


# ---------------------------------------------------------------------------
# ELEMENTS — FK resolved_storey_id SET NULL
# ---------------------------------------------------------------------------

def test_elements_resolved_storey_fk_references_spatial_nodes():
    fk = _fk_for_col(_EL, "resolved_storey_id")
    assert fk.column.table.name == "spatial_nodes"
    assert fk.column.name == "id"


def test_elements_resolved_storey_fk_ondelete_set_null():
    fk = _fk_for_col(_EL, "resolved_storey_id")
    assert fk.ondelete.upper() == "SET NULL"


# ---------------------------------------------------------------------------
# ELEMENTS — FK parent_element_id SET NULL (self-ref)
# ---------------------------------------------------------------------------

def test_elements_parent_element_fk_references_self():
    fk = _fk_for_col(_EL, "parent_element_id")
    assert fk.column.table.name == "elements"
    assert fk.column.name == "id"


def test_elements_parent_element_fk_ondelete_set_null():
    fk = _fk_for_col(_EL, "parent_element_id")
    assert fk.ondelete.upper() == "SET NULL"


# ---------------------------------------------------------------------------
# ELEMENTS — unique constraints
# ---------------------------------------------------------------------------

def test_elements_unique_model_entity():
    assert "uq_elements_model_entity" in _constraint_names(_EL)


def test_elements_unique_model_global_id():
    assert "uq_elements_model_global_id" in _constraint_names(_EL)


# ---------------------------------------------------------------------------
# ELEMENTS — CHECK constraints
# ---------------------------------------------------------------------------

def test_elements_check_entity_positive():
    assert "ck_elements_ifc_entity_id_positive" in _constraint_names(_EL)


# ---------------------------------------------------------------------------
# ELEMENTS — indexes
# ---------------------------------------------------------------------------

def test_elements_index_model_id():
    assert "ix_elements_model_id" in _index_names(_EL)


def test_elements_index_direct_spatial_node_id():
    assert "ix_elements_direct_spatial_node_id" in _index_names(_EL)


def test_elements_index_resolved_storey_id():
    assert "ix_elements_resolved_storey_id" in _index_names(_EL)


def test_elements_index_parent_element_id():
    assert "ix_elements_parent_element_id" in _index_names(_EL)


def test_elements_index_model_ifc_type():
    assert "ix_elements_model_ifc_type" in _index_names(_EL)


# ===========================================================================
# ELEMENT PROPERTIES — table name
# ===========================================================================

def test_element_properties_tablename():
    assert ElementProperty.__tablename__ == "element_properties"


# ---------------------------------------------------------------------------
# ELEMENT PROPERTIES — column set
# ---------------------------------------------------------------------------

def test_element_properties_column_set():
    expected = {
        "id",
        "element_id",
        "group_type",
        "group_name",
        "property_name",
        "value_kind",
        "ifc_value_type",
        "value_text",
        "value_number",
        "value_boolean",
        "unit",
        "created_at",
    }
    assert set(_EP.c.keys()) == expected


# ---------------------------------------------------------------------------
# ELEMENT PROPERTIES — FK element_id CASCADE
# ---------------------------------------------------------------------------

def test_element_properties_element_fk_references_elements():
    fk = _fk_for_col(_EP, "element_id")
    assert fk.column.table.name == "elements"
    assert fk.column.name == "id"


def test_element_properties_element_fk_ondelete_cascade():
    fk = _fk_for_col(_EP, "element_id")
    assert fk.ondelete.upper() == "CASCADE"


# ---------------------------------------------------------------------------
# ELEMENT PROPERTIES — required columns
# ---------------------------------------------------------------------------

def test_element_properties_element_id_not_nullable():
    assert _col(_EP, "element_id").nullable is False


def test_element_properties_group_type_not_nullable():
    assert _col(_EP, "group_type").nullable is False


def test_element_properties_group_name_not_nullable():
    assert _col(_EP, "group_name").nullable is False


def test_element_properties_property_name_not_nullable():
    assert _col(_EP, "property_name").nullable is False


def test_element_properties_value_kind_not_nullable():
    assert _col(_EP, "value_kind").nullable is False


# ---------------------------------------------------------------------------
# ELEMENT PROPERTIES — typed value columns optional
# ---------------------------------------------------------------------------

def test_element_properties_ifc_value_type_nullable():
    assert _col(_EP, "ifc_value_type").nullable is True


def test_element_properties_value_text_nullable():
    assert _col(_EP, "value_text").nullable is True


def test_element_properties_value_number_nullable():
    assert _col(_EP, "value_number").nullable is True


def test_element_properties_value_boolean_nullable():
    assert _col(_EP, "value_boolean").nullable is True


def test_element_properties_unit_nullable():
    assert _col(_EP, "unit").nullable is True


# ---------------------------------------------------------------------------
# ELEMENT PROPERTIES — CHECK constraints
# ---------------------------------------------------------------------------

def test_element_properties_check_group_type():
    assert "ck_element_properties_group_type" in _constraint_names(_EP)


def test_element_properties_check_value_kind():
    assert "ck_element_properties_value_kind" in _constraint_names(_EP)


def test_element_properties_check_typed_value():
    assert "ck_element_properties_typed_value" in _constraint_names(_EP)


# ---------------------------------------------------------------------------
# ELEMENT PROPERTIES — indexes
# ---------------------------------------------------------------------------

def test_element_properties_index_element_id():
    assert "ix_element_properties_element_id" in _index_names(_EP)


def test_element_properties_index_property_name():
    assert "ix_element_properties_property_name" in _index_names(_EP)


def test_element_properties_index_group():
    assert "ix_element_properties_group" in _index_names(_EP)


# ===========================================================================
# MODELS EXPORT — app.models exports all BIM classes
# ===========================================================================

def test_models_export_spatial_node():
    from app.models import SpatialNode as _SN_cls
    assert _SN_cls is SpatialNode


def test_models_export_ifc_element():
    from app.models import IfcElement as _EL_cls
    assert _EL_cls is IfcElement


def test_models_export_element_property():
    from app.models import ElementProperty as _EP_cls
    assert _EP_cls is ElementProperty


def test_models_all_contains_spatial_node():
    assert "SpatialNode" in models_pkg.__all__


def test_models_all_contains_ifc_element():
    assert "IfcElement" in models_pkg.__all__


def test_models_all_contains_element_property():
    assert "ElementProperty" in models_pkg.__all__
