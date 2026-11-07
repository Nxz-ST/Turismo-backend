from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ReviewDecision(BaseModel):
    status: Literal["validated", "rejected", "needs_review"]
    category: Literal[
        "bosque",
        "cascada",
        "desierto",
        "lago",
        "montana",
        "nevado",
        "playa",
        "volcan",
    ] | None = None
    reason: str = Field(min_length=3, max_length=1000)


class ReviewResponse(BaseModel):
    id: UUID
    status: str
    predicted_category: str | None = None
    decision_reason: str | None = None


class PlaceIssueReportDecision(BaseModel):
    status: Literal["reviewed", "resolved", "dismissed"]
    note: str = Field(min_length=3, max_length=500)


class CommunityPlaceAdminUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=140)
    description: str | None = Field(default=None, max_length=2000)
    category: Literal[
        "bosque", "cascada", "desierto", "lago", "montana", "nevado",
        "playa", "volcan",
    ] | None = None
    publication_status: Literal["published", "under_review", "hidden"] | None = None
    note: str = Field(min_length=3, max_length=500)


class CommunityPlaceMerge(BaseModel):
    target_place_id: UUID
    note: str = Field(min_length=3, max_length=500)
