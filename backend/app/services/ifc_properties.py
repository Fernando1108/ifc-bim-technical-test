"""
IFC element properties (PropertySets and Quantities) extraction service.

Extracts IfcPropertySingleValue from IfcPropertySet and simple quantities
from IfcElementQuantity, linked via IfcRelDefinesByProperties.

Unsupported property/quantity subtypes are silently skipped.
Does NOT commit or rollback — transaction control belongs to the caller.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.element import IfcElement
from app.models.element_property import ElementProperty
from app.models.ifc_model import IfcModel

_ERR_MSG = "No se pudieron extraer las propiedades del archivo IFC."

# Supported IfcElementQuantity subtypes and the attribute holding the scalar value.
_QTO_VALUE_ATTR: dict[str, str] = {
    "IfcQuantityLength": "LengthValue",
    "IfcQuantityArea": "AreaValue",
    "IfcQuantityVolume": "VolumeValue",
    "IfcQuantityCount": "CountValue",
    "IfcQuantityWeight": "WeightValue",
    "IfcQuantityTime": "TimeValue",
}


class IfcPropertyExtractionError(Exception):
    """Raised when properties cannot be extracted or persisted."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _required_str(value, context: str) -> str:
    """Return str(value) or raise ValueError if None/blank."""
    if value is None:
        raise ValueError(f"{context} is None")
    s = str(value)
    if not s.strip():
        raise ValueError(f"{context} is blank")
    return s


def _resolve_unit(unit_entity) -> str | None:
    """Return a deterministic string representation of an explicit IFC unit.

    None → None.
    IfcSIUnit → "PREFIX NAME" (with prefix) or "NAME" (no prefix).
    IfcMonetaryUnit → Currency string.
    Other supported/unsupported → unit_entity.is_a().

    Unexpected errors propagate to the global guard.
    """
    if unit_entity is None:
        return None
    ifc_type = unit_entity.is_a()
    if ifc_type == "IfcSIUnit":
        prefix = getattr(unit_entity, "Prefix", None)
        name = getattr(unit_entity, "Name", None)
        name_str = str(name) if name is not None else ""
        if prefix is not None:
            return f"{prefix} {name_str}".strip()
        return name_str or None
    if ifc_type == "IfcMonetaryUnit":
        currency = getattr(unit_entity, "Currency", None)
        return str(currency) if currency is not None else None
    return ifc_type


def _get_ifc_value_type(nominal_value) -> str | None:
    """Return nominal_value.is_a() or None when not available.

    AttributeError → None (attribute absent from schema).
    Unexpected errors propagate.
    """
    try:
        return nominal_value.is_a()
    except AttributeError:
        return None


def _classify_nominal_value(
    nominal_value,
) -> tuple[str, str | None, float | None, bool | None, str | None]:
    """Classify an IfcPropertySingleValue.NominalValue.

    Returns (value_kind, value_text, value_number, value_boolean, ifc_value_type).

    None NominalValue → NULL.
    Extracts .wrappedValue when present (only AttributeError → use nominal_value itself).
    bool  → BOOLEAN
    int / float (not bool) → NUMBER (stored as float)
    str   → TEXT
    other → TEXT via str() fallback
    """
    if nominal_value is None:
        return "NULL", None, None, None, None

    ifc_value_type = _get_ifc_value_type(nominal_value)

    try:
        val = nominal_value.wrappedValue
    except AttributeError:
        val = nominal_value

    if isinstance(val, bool):
        return "BOOLEAN", None, None, val, ifc_value_type
    if isinstance(val, (int, float)):
        return "NUMBER", None, float(val), None, ifc_value_type
    if isinstance(val, str):
        return "TEXT", val, None, None, ifc_value_type
    # Unknown type: not a safe scalar (may be a complex IFC entity/reference).
    # Refuse to serialize — raise so the global guard wraps this as
    # IfcPropertyExtractionError and preserves __cause__.
    raise ValueError(
        f"NominalValue has unsupported wrappedValue type: {type(val).__name__}"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_and_persist_element_properties(
    db: Session,
    model: IfcModel,
    ifc_file,
    elements: list[IfcElement],
) -> list[ElementProperty]:
    """
    Extract and persist ElementProperty rows for all given elements.

    Processes IfcRelDefinesByProperties in rel.id() order (deterministic).
    Extracts:
    - IfcPropertySingleValue from IfcPropertySet  (group_type = PSET)
    - Simple quantities from IfcElementQuantity   (group_type = QTO)

    Unsupported property / quantity subtypes are silently skipped.
    One db.flush() call issued when properties exist; none otherwise.

    Transaction control is the caller's responsibility.
    Never calls db.commit() or db.rollback().

    Args:
        db:       SQLAlchemy session.
        model:    IfcModel being processed (property_count updated).
        ifc_file: Open ifcopenshell file object.
        elements: IfcElement list from extract_and_persist_elements.
                  Must all belong to model.id with DB ids assigned.

    Returns:
        Persisted ElementProperty list (empty when none found).

    Raises:
        IfcPropertyExtractionError: wraps any unexpected error during
            validation, extraction, or persistence.
    """
    try:
        # ------------------------------------------------------------------
        # 0. Validate elements
        # ------------------------------------------------------------------
        for el in elements:
            if el.model_id != model.id:
                raise ValueError("IfcElement belongs to a different model")
            if el.id is None:
                raise ValueError(
                    "IfcElement has no DB id — flush elements first"
                )
            if (
                not isinstance(el.ifc_entity_id, int)
                or isinstance(el.ifc_entity_id, bool)
                or el.ifc_entity_id <= 0
            ):
                raise ValueError(
                    "IfcElement.ifc_entity_id must be a positive integer"
                )

        # ------------------------------------------------------------------
        # 1. Build mapping: ifc_entity_id → IfcElement  (O(1) lookups)
        # ------------------------------------------------------------------
        el_by_eid: dict[int, IfcElement] = {el.ifc_entity_id: el for el in elements}

        if not el_by_eid:
            model.property_count = 0
            return []

        # ------------------------------------------------------------------
        # 2. Single pass over IfcRelDefinesByProperties (sorted by rel.id())
        # ------------------------------------------------------------------
        properties: list[ElementProperty] = []

        for rel in sorted(
            ifc_file.by_type("IfcRelDefinesByProperties"),
            key=lambda r: r.id(),
        ):
            # 1. Collect relevant elements first, sorted for determinism.
            #    Relations whose RelatedObjects are entirely absent from elements
            #    are skipped before any prop_def inspection or name validation.
            related_elements: list[IfcElement] = []
            for obj in sorted(rel.RelatedObjects, key=lambda o: o.id()):
                el = el_by_eid.get(obj.id())
                if el is not None:
                    related_elements.append(el)

            if not related_elements:
                continue

            # 2. Determine group_type; skip unsupported definitions
            prop_def = rel.RelatingPropertyDefinition
            if prop_def.is_a("IfcPropertySet"):
                group_type = "PSET"
            elif prop_def.is_a("IfcElementQuantity"):
                group_type = "QTO"
            else:
                continue

            group_name = _required_str(
                getattr(prop_def, "Name", None), "group_name"
            )

            # ---------------------------------------------------------------
            # PSET — extract IfcPropertySingleValue only
            # ---------------------------------------------------------------
            if group_type == "PSET":
                has_props = getattr(prop_def, "HasProperties", None) or []
                for prop in sorted(has_props, key=lambda p: p.id()):
                    if not prop.is_a("IfcPropertySingleValue"):
                        continue  # silently skip unsupported subtypes

                    property_name = _required_str(
                        getattr(prop, "Name", None), "property_name"
                    )
                    nominal = getattr(prop, "NominalValue", None)
                    kind, vt, vn, vb, ivt = _classify_nominal_value(nominal)

                    unit_str = _resolve_unit(getattr(prop, "Unit", None))

                    for el in related_elements:
                        properties.append(
                            ElementProperty(
                                element_id=el.id,
                                group_type="PSET",
                                group_name=group_name,
                                property_name=property_name,
                                value_kind=kind,
                                ifc_value_type=ivt,
                                value_text=vt,
                                value_number=vn,
                                value_boolean=vb,
                                unit=unit_str,
                            )
                        )

            # ---------------------------------------------------------------
            # QTO — extract supported simple quantities only
            # ---------------------------------------------------------------
            else:
                quantities = getattr(prop_def, "Quantities", None) or []
                for qty in sorted(quantities, key=lambda q: q.id()):
                    qty_type = qty.is_a()
                    value_attr = _QTO_VALUE_ATTR.get(qty_type)
                    if value_attr is None:
                        continue  # silently skip unsupported subtypes

                    property_name = _required_str(
                        getattr(qty, "Name", None), "property_name"
                    )
                    raw_val = getattr(qty, value_attr)
                    value_number = float(raw_val)

                    unit_str = _resolve_unit(getattr(qty, "Unit", None))

                    for el in related_elements:
                        properties.append(
                            ElementProperty(
                                element_id=el.id,
                                group_type="QTO",
                                group_name=group_name,
                                property_name=property_name,
                                value_kind="NUMBER",
                                ifc_value_type=qty_type,
                                value_text=None,
                                value_number=value_number,
                                value_boolean=None,
                                unit=unit_str,
                            )
                        )

        # ------------------------------------------------------------------
        # 3. Persist — exactly one flush when rows exist
        # ------------------------------------------------------------------
        if not properties:
            model.property_count = 0
            return []

        db.add_all(properties)
        db.flush()
        model.property_count = len(properties)
        return properties

    except IfcPropertyExtractionError:
        raise
    except Exception as exc:
        raise IfcPropertyExtractionError(_ERR_MSG) from exc
