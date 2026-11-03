from app.api.routes.places import _latest_community_profile


def test_reads_answers_from_compatible_profile_event() -> None:
    result = _latest_community_profile(
        [
            {
                "stage": "human_review",
                "created_at": "2026-11-03T10:00:00Z",
                "metadata": {
                    "event_type": "community_profile",
                    "answers": {"access_type": "walking"},
                },
            }
        ]
    )

    assert result == (
        {"access_type": "walking"},
        "2026-11-03T10:00:00Z",
    )


def test_ignores_non_profile_events() -> None:
    assert _latest_community_profile(
        [{"stage": "decision", "metadata": {"answers": {}}}]
    ) is None
