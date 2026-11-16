import pytest

from app.services.workflow import (
    ValidationWorkflow,
    _automatic_community_match,
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


def _beach_repository(name: str, category: str = "playa"):
    class Repository:
        async def nearby_places(self, *_args):
            return []

        async def nearby_community_places(self, *_args):
            return [
                {
                    "id": "13062b5b-20fc-4af0-b0a4-553ae8284f49",
                    "nombre": name,
                    "latitud": -12.317277,
                    "longitud": -76.835859,
                    "categoria_ia": category,
                    "estado_validacion": "validated",
                }
            ]

    workflow = object.__new__(ValidationWorkflow)
    workflow._repository = Repository()
    return workflow


SECOND_BEACH = {
    "id": "second-evidence",
    "name": "Playa el silencio",
    "latitude": -12.316448,
    "longitude": -76.836422,
    "contribution_type": "new_place",
}


@pytest.mark.asyncio
async def test_same_beach_at_110_meters_becomes_contribution() -> None:
    workflow = _beach_repository("Playa el silencio")

    result = await workflow._duplicate_context(SECOND_BEACH, "playa")
    match = _automatic_community_match(SECOND_BEACH, result)

    assert result["status"] == "high_match"
    assert match is not None
    assert match["id"] == "13062b5b-20fc-4af0-b0a4-553ae8284f49"
    assert 100 < match["distance_m"] < 120


@pytest.mark.asyncio
async def test_different_beach_name_at_110_meters_stays_new_place() -> None:
    workflow = _beach_repository("Playa Las Gaviotas")

    result = await workflow._duplicate_context(SECOND_BEACH, "playa")

    assert result["status"] == "nearby_match"
    assert _automatic_community_match(SECOND_BEACH, result) is None


@pytest.mark.asyncio
async def test_same_name_other_category_is_not_linked_automatically() -> None:
    workflow = _beach_repository("Playa el silencio", category="lago")

    result = await workflow._duplicate_context(SECOND_BEACH, "playa")

    assert _automatic_community_match(SECOND_BEACH, result) is None


def test_existing_place_contribution_is_not_relinked() -> None:
    evidence = {**SECOND_BEACH, "contribution_type": "existing_place"}
    result = {
        "status": "high_match",
        "candidates": [
            {
                "id": "place",
                "source": "community",
                "high_match": True,
                "category_match": True,
                "distance_m": 10,
            }
        ],
    }

    assert _automatic_community_match(evidence, result) is None
