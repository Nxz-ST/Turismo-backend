from typing import Literal

from pydantic import BaseModel, Field, model_validator


class CoordinateReviewDecision(BaseModel):
    action: Literal["approve_coordinate", "approve_access", "reject"]
    note: str = Field(min_length=3, max_length=1000)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    candidate_name: str | None = Field(default=None, max_length=200)
    candidate_address: str | None = Field(default=None, max_length=500)
    source: str | None = Field(default=None, max_length=80)
    source_reference: str | None = Field(default=None, max_length=1000)
    confidence: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def validate_candidate(self) -> "CoordinateReviewDecision":
        if self.action != "reject" and (
            self.latitude is None or self.longitude is None
        ):
            raise ValueError("Una aprobación requiere latitud y longitud")
        return self
