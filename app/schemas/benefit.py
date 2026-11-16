from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


PlaceSource = Literal["official", "community"]
RedemptionStatus = Literal["requested", "confirmed", "redeemed", "cancelled", "expired"]


class BenefitClaimRequest(BaseModel):
    place_source: PlaceSource
    place_id: str = Field(min_length=1, max_length=100)
    place_name: str = Field(min_length=1, max_length=180)


class BenefitTransitionRequest(BaseModel):
    status: RedemptionStatus
    note: str | None = Field(default=None, max_length=500)


class AgencyMemberRequest(BaseModel):
    user_id: UUID
    member_role: Literal["owner", "staff"] = "staff"


class AgencyAccountRequest(BaseModel):
    email: str = Field(min_length=5, max_length=200)
    password: str = Field(min_length=8, max_length=100)
    member_role: Literal["owner", "staff"] = "staff"
