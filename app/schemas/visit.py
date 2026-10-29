from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class RouteVisitCreate(BaseModel):
    client_visit_id: UUID
    route_id: str = Field(min_length=1, max_length=240)
    place_id: str = Field(min_length=1, max_length=240)
    place_name: str = Field(min_length=1, max_length=240)
    place_category: str = Field(default="", max_length=240)
    place_region: str = Field(default="", max_length=240)
    place_source: Literal["official", "community"]
    target_latitude: float = Field(ge=-90, le=90)
    target_longitude: float = Field(ge=-180, le=180)
    recorded_latitude: float = Field(ge=-90, le=90)
    recorded_longitude: float = Field(ge=-180, le=180)
    gps_accuracy_m: float = Field(ge=0, le=10_000)
    rating: int | None = Field(default=None, ge=1, le=5)
    comment: str = Field(default="", max_length=1200)
    place_condition: Literal["good", "regular", "poor"] | None = None
    access_condition: Literal["open", "difficult", "blocked"] | None = None
    photo_object_key: str | None = Field(default=None, max_length=500)
    captured_at: datetime


class RouteVisitResponse(BaseModel):
    id: UUID
    client_visit_id: UUID
    route_id: str
    place_id: str
    place_name: str
    place_category: str
    place_region: str
    place_source: str
    distance_m: float
    verification_radius_m: float
    gps_accuracy_m: float
    visit_verified: bool
    rating: int | None = None
    comment: str
    place_condition: str | None = None
    access_condition: str | None = None
    photo_object_key: str | None = None
    photo_url: str | None = None
    moderation_status: str
    captured_at: datetime
    created_at: datetime

