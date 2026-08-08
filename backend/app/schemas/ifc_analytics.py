from typing import Optional

from pydantic import BaseModel


class IfcAnalyticsTypeCount(BaseModel):
    ifc_type: str
    count: int


class IfcAnalyticsStoreyCount(BaseModel):
    global_id: str
    name: Optional[str]
    elevation: Optional[float]
    count: int


class IfcModelAnalyticsResponse(BaseModel):
    total_elements: int
    total_spatial_nodes: int
    total_properties: int
    by_ifc_type: list[IfcAnalyticsTypeCount]
    by_storey: list[IfcAnalyticsStoreyCount]
    without_storey_count: int


class IfcAnalyticsElementStorey(BaseModel):
    global_id: str
    name: Optional[str]
    elevation: Optional[float]


class IfcAnalyticsElementItem(BaseModel):
    ifc_entity_id: int
    global_id: str
    ifc_type: str
    name: Optional[str]
    object_type: Optional[str]
    tag: Optional[str]
    predefined_type: Optional[str]
    type_ifc_type: Optional[str]
    type_name: Optional[str]
    storey: Optional[IfcAnalyticsElementStorey]


class IfcAnalyticsElementPage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[IfcAnalyticsElementItem]
