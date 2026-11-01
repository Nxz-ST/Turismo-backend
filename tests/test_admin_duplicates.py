from app.api.routes.admin import _community_duplicate_candidates


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
