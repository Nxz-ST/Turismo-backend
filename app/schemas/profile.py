from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


TravelerType = Literal["local", "national", "foreign"]
AgeRange = Literal["18-24", "25-34", "35-44", "45-54", "55-64", "65+"]
Interest = Literal[
    "nature", "adventure", "culture", "beach", "gastronomy", "photography", "relaxation"
]
HikingExperience = Literal["beginner", "intermediate", "advanced"]
ReferralSource = Literal[
    "friends", "social_media", "university", "agency", "search", "other"
]


class UserProfileUpdate(BaseModel):
    """Todos los campos son opcionales: el perfil se puede omitir."""

    traveler_type: TravelerType | None = None
    origin_region: str | None = Field(default=None, max_length=60)
    origin_country: str | None = Field(default=None, max_length=60)
    age_range: AgeRange | None = None
    interests: list[Interest] = Field(default_factory=list, max_length=7)
    hiking_experience: HikingExperience | None = None
    referral_source: ReferralSource | None = None
    # Versión de Términos/Privacidad que el usuario acepta en este envío.
    accept_terms_version: str | None = Field(default=None, max_length=20)
    research_consent: bool | None = None
    complete_onboarding: bool = False

    @field_validator("origin_region", "origin_country")
    @classmethod
    def clean_text(cls, value: str | None) -> str | None:
        value = (value or "").strip()
        return value or None

    @field_validator("interests")
    @classmethod
    def unique_interests(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


class UserProfileResponse(BaseModel):
    exists: bool = True
    traveler_type: TravelerType | None = None
    origin_region: str | None = None
    origin_country: str | None = None
    age_range: AgeRange | None = None
    interests: list[str] = Field(default_factory=list)
    hiking_experience: HikingExperience | None = None
    referral_source: ReferralSource | None = None
    terms_version: str | None = None
    terms_accepted_at: datetime | None = None
    research_consent: bool = False
    research_consent_at: datetime | None = None
    onboarding_completed_at: datetime | None = None
    updated_at: datetime | None = None
