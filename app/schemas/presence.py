from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class PresenceSampleCreate(BaseModel):
    client_sample_id: UUID
    device_id: UUID
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    altitude: float | None = Field(default=None, ge=-500, le=9000)
    accuracy_m: float = Field(ge=0, le=10_000)
    recorded_at: datetime
    source: Literal["app_open", "app_resume", "map", "route", "capture", "manual"]
    is_mocked: bool | None = None


class PresenceSampleBatch(BaseModel):
    samples: list[PresenceSampleCreate] = Field(min_length=1, max_length=100)


class PresenceSampleResponse(BaseModel):
    id: UUID
    client_sample_id: UUID
    device_id: UUID
    latitude: float
    longitude: float
    altitude: float | None = None
    accuracy_m: float
    recorded_at: datetime
    source: str
    is_mocked: bool | None = None
    expires_at: datetime
    remaining_seconds: int
