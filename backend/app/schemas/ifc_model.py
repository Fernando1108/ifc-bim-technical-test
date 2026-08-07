from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class IfcModelResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    original_filename: str
    file_size_bytes: int
    sha256: str
    status: str
    ifc_schema: Optional[str]
    error_message: Optional[str]
    created_at: datetime
    processing_started_at: Optional[datetime]
    processed_at: Optional[datetime]
