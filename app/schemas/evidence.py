from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class EvidenceCreate(BaseModel):
    client_evidence_id: UUID
    object_key: str = Field(min_length=1, max_length=500)
    original_filename: str = Field(min_length=1, max_length=180)
    mime_type: str = Field(pattern=r"^image/(jpeg|png|webp)$")
    name: str = Field(min_length=1, max_length=180)
    description: str = Field(default="", max_length=2000)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    altitude: float | None = Field(default=None, ge=-500, le=9000)
    gps_accuracy_m: float | None = Field(default=None, ge=0, le=10_000)
    capture_source: str = Field(default="unknown", pattern=r"^(camera|gallery|unknown)$")
    captured_at: datetime | None = None
    content_hash: str | None = Field(default=None, max_length=128)
    presence_sample_id: UUID | None = None
    contribution_type: Literal["new_place", "existing_place"] = "new_place"
    target_place_id: int | None = Field(default=None, ge=1)


class EvidenceResponse(BaseModel):
    id: UUID
    client_evidence_id: UUID
    user_id: UUID
    name: str
    description: str
    object_key: str
    mime_type: str
    latitude: float
    longitude: float
    altitude: float | None
    gps_accuracy_m: float | None = None
    capture_source: str = "unknown"
    status: str
    predicted_category: str | None = None
    confidence: float | None = None
    score: float | None = None
    evidence_coverage: float | None = None
    duplicate_status: str | None = None
    presence_sample_id: UUID | None = None
    presence_status: str = "unavailable"
    presence_expires_at: datetime | None = None
    presence_attestation: dict = Field(default_factory=dict)
    contribution_type: Literal["new_place", "existing_place"] = "new_place"
    target_place_id: int | None = None
    target_place_snapshot: dict = Field(default_factory=dict)
    target_distance_m: float | None = None
    decision_reason: str | None = None
    photo_url: str | None = None
    geospatial_result: dict = Field(default_factory=dict)
    validation_details: dict = Field(default_factory=dict)
    processing_events: list[dict] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ProcessResponse(BaseModel):
    evidence_id: UUID
    job_id: UUID
    status: str

