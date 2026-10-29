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
