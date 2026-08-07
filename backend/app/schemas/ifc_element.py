from typing import Optional

from pydantic import BaseModel, ConfigDict


class IfcSpatialNodeSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ifc_entity_id: int
    global_id: str
    ifc_type: str
    name: Optional[str]
    description: Optional[str]
    long_name: Optional[str]
    elevation: Optional[float]


class IfcElementPropertyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    group_type: str
    group_name: str
    property_name: str
    value_kind: str
    ifc_value_type: Optional[str]
    value_text: Optional[str]
    value_number: Optional[float]
    value_boolean: Optional[bool]
    unit: Optional[str]


class IfcElementDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ifc_entity_id: int
    global_id: str
    ifc_type: str
    name: Optional[str]
    description: Optional[str]
    object_type: Optional[str]
    tag: Optional[str]
    predefined_type: Optional[str]
    type_global_id: Optional[str]
    type_ifc_type: Optional[str]
    type_name: Optional[str]
    direct_spatial: Optional[IfcSpatialNodeSummary]
    resolved_storey: Optional[IfcSpatialNodeSummary]
    properties: list[IfcElementPropertyResponse]
