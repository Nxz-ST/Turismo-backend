from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class TravelStateUpdate(BaseModel):
    favorites: list[dict[str, Any]] = Field(default_factory=list, max_length=500)
    trip: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    reviews: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    saved_routes: list[dict[str, Any]] = Field(default_factory=list, max_length=50)
    version: int = Field(default=1, ge=1)

    @field_validator("favorites", "trip", "saved_routes")
    @classmethod
    def limit_serialized_places(cls, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for place in value:
            if len(str(place)) > 20_000:
                raise ValueError("Un lugar contiene demasiada información")
        return value

    @field_validator("reviews")
    @classmethod
    def limit_reviews(
        cls, value: dict[str, list[dict[str, Any]]]
    ) -> dict[str, list[dict[str, Any]]]:
        if len(value) > 500:
            raise ValueError("Hay demasiados lugares con reseñas")
        if sum(len(items) for items in value.values()) > 5_000:
            raise ValueError("Hay demasiadas reseñas")
        return value


class TravelStateResponse(TravelStateUpdate):
    updated_at: datetime | None = None

