import pytest
from pydantic import ValidationError

from app.api.routes.admin import _score_coordinate_candidate
from app.schemas.coordinate import CoordinateReviewDecision


def test_coordinate_approval_requires_complete_candidate() -> None:
    with pytest.raises(ValidationError):
        CoordinateReviewDecision(
            action="approve_coordinate",
            note="Fuente comprobada",
        )


def test_reject_does_not_require_candidate() -> None:
    payload = CoordinateReviewDecision(
        action="reject",
        note="No corresponde al atractivo",
    )
    assert payload.latitude is None
    assert payload.longitude is None


def test_candidate_score_rewards_name_and_administrative_context() -> None:
    place = {
        "nombre": "Playa Tuquillo",
        "distrito": "Huarmey",
        "provincia": "Huarmey",
        "departamento": "Áncash",
    }
    matching = {
        "name": "Playa Tuquillo",
        "address": "Huarmey, Áncash, Perú",
    }
    unrelated = {
        "name": "Restaurante Tuquillo",
        "address": "Lima, Perú",
    }

    assert _score_coordinate_candidate(place, matching) > _score_coordinate_candidate(
        place, unrelated
    )
    assert _score_coordinate_candidate(place, matching) <= 0.85
