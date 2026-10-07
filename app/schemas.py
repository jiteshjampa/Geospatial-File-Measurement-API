from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class FileSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    feature_count: int
    crs: str
    status: str
    created_at: datetime


class FeatureMeasurement(BaseModel):
    feature_index: int
    geometry_type: str
    geometry: dict[str, Any] | None
    geometry_crs: str
    properties: dict[str, Any]
    area_m2: float | None
    length_m: float | None
    measurement_status: str
    message: str | None


class MeasurementsResponse(BaseModel):
    file_id: str
    filename: str
    crs: str
    feature_count: int
    area_unit: str = "square meters"
    length_unit: str = "meters"
    features: list[FeatureMeasurement]


class FeaturePage(BaseModel):
    file_id: str
    total: int
    offset: int
    limit: int
    features: list[FeatureMeasurement]
