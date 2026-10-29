from typing import Literal

from pydantic import BaseModel, Field


class RouteRequest(BaseModel):
    origin_latitude: float = Field(ge=-90, le=90)
    origin_longitude: float = Field(ge=-180, le=180)
    destination_latitude: float = Field(ge=-90, le=90)
    destination_longitude: float = Field(ge=-180, le=180)
    travel_mode: Literal["driving", "walking", "bicycling"] = "driving"

