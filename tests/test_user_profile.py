from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.domain.profile import build_profile_row
from app.schemas.profile import UserProfileUpdate


NOW = datetime(2026, 11, 13, 15, 0, tzinfo=UTC)


def _update(**values) -> dict:
    return UserProfileUpdate(**values).model_dump(mode="json", exclude_unset=True)


def test_accepting_terms_sets_server_timestamp_without_touching_profile() -> None:
    row = build_profile_row(
        _update(accept_terms_version="1.0", research_consent=True), None, now=NOW
    )

    assert row["terms_version"] == "1.0"
    assert row["terms_accepted_at"] == NOW.isoformat()
    assert row["research_consent"] is True
    assert row["research_consent_at"] == NOW.isoformat()
    assert "traveler_type" not in row
    assert "interests" not in row


def test_resending_same_consent_keeps_original_dates() -> None:
    current = {"terms_version": "1.0", "research_consent": True}
    row = build_profile_row(
        _update(accept_terms_version="1.0", research_consent=True), current, now=NOW
    )

    assert "terms_accepted_at" not in row
    assert "research_consent_at" not in row


def test_withdrawing_research_consent_is_dated() -> None:
    row = build_profile_row(
        _update(research_consent=False), {"research_consent": True}, now=NOW
    )

    assert row["research_consent"] is False
    assert row["research_consent_at"] == NOW.isoformat()


def test_profile_update_normalizes_origin_and_completes_onboarding_once() -> None:
    row = build_profile_row(
        _update(
            traveler_type="national",
            origin_region=" Áncash ",
            origin_country="Chile",
            interests=["nature", "nature", "adventure"],
            complete_onboarding=True,
        ),
        None,
        now=NOW,
    )

    assert row["origin_region"] == "Áncash"
    assert row["origin_country"] == "Perú"
    assert row["interests"] == ["nature", "adventure"]
    assert row["onboarding_completed_at"] == NOW.isoformat()

    again = build_profile_row(
        _update(complete_onboarding=True),
        {"onboarding_completed_at": NOW.isoformat()},
        now=NOW,
    )
    assert "onboarding_completed_at" not in again


def test_foreign_traveler_drops_peruvian_region() -> None:
    row = build_profile_row(
        _update(traveler_type="foreign", origin_country="Chile", origin_region="Lima"),
        None,
        now=NOW,
    )

    assert row["origin_region"] is None
    assert row["origin_country"] == "Chile"


@pytest.mark.parametrize(
    "values",
    [
        {"age_range": "17"},
        {"interests": ["shopping"]},
        {"traveler_type": "tourist"},
        {"hiking_experience": "expert"},
    ],
)
def test_rejects_values_outside_the_declared_options(values: dict) -> None:
    with pytest.raises(ValidationError):
        UserProfileUpdate(**values)
