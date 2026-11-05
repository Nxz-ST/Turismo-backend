import pytest

from app.api.routes.admin import (
    _community_duplicate_candidates,
    _fresh_validated_community_duplicate,
)


def test_only_high_community_matches_are_consolidation_candidates() -> None:
    candidates = _community_duplicate_candidates(
        {
            "duplicate_result": {
                "status": "high_match",
                "candidates": [
                    {
                        "id": "far",
                        "source": "community",
                        "high_match": False,
                        "distance_m": 2,
                    },
                    {
                        "id": "official",
                        "source": "mincetur",
                        "high_match": True,
                        "distance_m": 1,
                    },
                    {
                        "id": "near",
                        "source": "community",
                        "high_match": True,
                        "distance_m": 4,
                    },
                ],
            }
        }
    )

    assert [candidate["id"] for candidate in candidates] == ["near"]


def test_nearby_match_is_not_automatically_consolidated() -> None:
    assert (
        _community_duplicate_candidates(
            {"duplicate_result": {"status": "nearby_match", "candidates": []}}
        )
        == []
    )


@pytest.mark.asyncio
async def test_review_rechecks_places_published_after_processing() -> None:
    class Repository:
        async def nearby_community_places(self, *_args):
            return [
                {
                    "id": "canonical-place",
                    "nombre": "Cascada La Grande",
                    "categoria_ia": "cascada",
                    "estado_validacion": "validated",
                    "latitud": -11.8700384,
                    "longitud": -76.4010961,
                }
            ]

    duplicate = await _fresh_validated_community_duplicate(
        Repository(),
        {
            "id": "later-evidence",
            "name": "cascada la grande",
            "latitude": -11.8700358,
            "longitude": -76.4010954,
        },
        "cascada",
    )

    assert duplicate is not None
    assert duplicate[0]["id"] == "canonical-place"
    assert duplicate[1]["distance_m"] < 1


@pytest.mark.asyncio
async def test_review_does_not_merge_a_different_nearby_category() -> None:
    class Repository:
        async def nearby_community_places(self, *_args):
            return [
                {
                    "id": "nearby-lake",
                    "nombre": "Laguna La Grande",
                    "categoria_ia": "lago",
                    "estado_validacion": "validated",
                    "latitud": -11.8700384,
                    "longitud": -76.4010961,
                }
            ]

    duplicate = await _fresh_validated_community_duplicate(
        Repository(),
        {
            "id": "waterfall-evidence",
            "name": "Cascada La Grande",
            "latitude": -11.8700358,
            "longitude": -76.4010954,
        },
        "cascada",
    )

    assert duplicate is None
