from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class TrustPassportResponse(BaseModel):
    place_id: str
    source: Literal["official", "community"]
    trust_level: str
    verified_visitors: int
    approved_contributors: int
    independent_supporters: int
    last_verified_at: datetime | None = None
    freshness: str
    place_condition: str | None = None
    access_condition: str | None = None
    method: str


class CommunityPlaceResponse(BaseModel):
    id: UUID
    nombre: str
    descripcion: str
    categoria_ia: str
    latitud: float
    longitud: float
    altitud: float | None = None
    estado_validacion: str = "validated"
    foto_url: str | None = None
    photos: list[str] = Field(default_factory=list)
    community_updates: list[dict] = Field(default_factory=list)
    origin_evidence_id: UUID
    created_at: datetime
    updated_at: datetime
    trust: TrustPassportResponse | None = None


class PlaceIssueReportCreate(BaseModel):
    place_name: str = Field(default="", max_length=180)
    issue_type: Literal[
        "access_closed",
        "safety_risk",
        "wrong_location",
        "outdated_info",
    ]
    details: str = Field(default="", max_length=500)
    observed_at: datetime | None = None
