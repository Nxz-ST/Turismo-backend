from app.services.workflow import _automatic_official_match


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
