from pydantic import ValidationError
import pytest

from app.api.routes.places import _condition_summary
from app.schemas.visit import RouteVisitCreate


def test_condition_summary_uses_verified_majority() -> None:
    summary = _condition_summary(
        [
            {
                "place_condition": "good",
                "access_condition": "open",
                "captured_at": "2026-10-28T12:00:00Z",
            },
            {
                "place_condition": "good",
                "access_condition": "difficult",
                "captured_at": "2026-10-27T12:00:00Z",
            },
            {
                "place_condition": "regular",
                "access_condition": "open",
                "captured_at": "2026-10-26T12:00:00Z",
            },
        ]
    )

    assert summary["place_condition"] == "good"
    assert summary["access_condition"] == "open"
    assert summary["verified_reports"] == 3
    assert summary["source"] == "verified_route_visits"


def test_visit_rejects_unknown_condition() -> None:
    with pytest.raises(ValidationError):
        RouteVisitCreate(
            client_visit_id="48dcfd70-e5a7-4ae1-90a4-57fa1e35a778",
            route_id="route",
            place_id="official-1",
            place_name="Lugar",
            place_source="official",
            target_latitude=-10,
            target_longitude=-78,
            recorded_latitude=-10,
            recorded_longitude=-78,
            gps_accuracy_m=5,
            captured_at="2026-10-28T12:00:00Z",
            place_condition="perfect",
        )
