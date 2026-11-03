import pytest

from app.services.workflow import (
    ValidationWorkflow,
    _automatic_official_match,
    _persisted_duplicate_status,
)


def test_new_duplicate_states_remain_compatible_with_legacy_constraint() -> None:
    assert _persisted_duplicate_status("category_conflict") == "high_match"
    assert _persisted_duplicate_status("linked_target") == "high_match"
    assert _persisted_duplicate_status("no_match") == "no_match"


def test_new_contribution_uses_nearest_strong_official_match() -> None:
    match = _automatic_official_match(
        {"contribution_type": "new_place"},
        {
            "status": "high_match",
            "candidates": [
                {
                    "id": 8,
                    "source": "mincetur",
                    "distance_m": 60,
                    "high_match": True,
                },
                {
                    "id": 9,
                    "source": "mincetur",
                    "distance_m": 15,
                    "high_match": True,
                },
            ],
        },
    )

    assert match is not None
    assert match["id"] == 9


def test_community_match_stays_for_human_consolidation() -> None:
    match = _automatic_official_match(
        {"contribution_type": "new_place"},
        {
            "status": "high_match",
            "candidates": [
                {
                    "id": "community-id",
                    "source": "community",
                    "distance_m": 10,
                    "high_match": True,
                }
            ],
        },
    )

    assert match is None


@pytest.mark.asyncio
async def test_validated_nearby_place_with_other_category_is_conflict() -> None:
    class Repository:
        async def nearby_places(self, *_args):
            return []

        async def nearby_community_places(self, *_args):
            return [
                {
                    "id": "3eb59196-9987-4691-8e9b-c3637266a65e",
                    "nombre": "Laguna Azul",
                    "latitud": -11.98903,
                    "longitud": -76.83690,
                    "categoria_ia": "lago",
                    "estado_validacion": "validated",
                }
            ]

    workflow = object.__new__(ValidationWorkflow)
    workflow._repository = Repository()

    result = await workflow._duplicate_context(
        {
            "id": "new-evidence",
            "name": "Laguna Azul",
            "latitude": -11.98903,
            "longitude": -76.83690,
        },
        "bosque",
    )

    assert result["status"] == "category_conflict"
    assert result["expected_category"] == "lago"
    assert result["observed_category"] == "bosque"
