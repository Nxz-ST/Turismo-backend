from datetime import UTC, datetime, timedelta

from app.domain.trust import build_trust_passport


def test_counts_unique_people_instead_of_submissions() -> None:
    now = datetime.now(UTC).isoformat()
    passport = build_trust_passport(
        source="community",
        place_id="place-1",
        visits=[
            {
                "user_id": "user-a",
                "visit_verified": True,
                "captured_at": now,
                "place_condition": "good",
                "access_condition": "open",
            },
            {
                "user_id": "user-a",
                "visit_verified": True,
                "captured_at": now,
                "place_condition": "good",
                "access_condition": "open",
            },
            {
                "user_id": "user-b",
                "visit_verified": True,
                "captured_at": now,
                "place_condition": "regular",
                "access_condition": "open",
            },
        ],
        evidences=[
            {"user_id": "user-a", "status": "validated", "updated_at": now},
            {"user_id": "user-c", "status": "duplicate", "updated_at": now},
        ],
    )

    assert passport["verified_visitors"] == 2
    assert passport["approved_contributors"] == 2
    assert passport["independent_supporters"] == 3
    assert passport["trust_level"] == "community_corroborated"
    assert passport["place_condition"] == "good"
    assert passport["access_condition"] == "open"


def test_ignores_unverified_visits_and_rejected_evidence() -> None:
    passport = build_trust_passport(
        source="community",
        place_id="place-2",
        visits=[
            {
                "user_id": "user-a",
                "visit_verified": False,
                "captured_at": datetime.now(UTC).isoformat(),
            }
        ],
        evidences=[
            {
                "user_id": "user-b",
                "status": "rejected",
                "updated_at": datetime.now(UTC).isoformat(),
            }
        ],
    )

    assert passport["independent_supporters"] == 0
    assert passport["freshness"] == "unverified"
    assert passport["trust_level"] == "community_initial"


def test_marks_old_information_as_outdated() -> None:
    old = (datetime.now(UTC) - timedelta(days=200)).isoformat()
    passport = build_trust_passport(
        source="official",
        place_id="12",
        visits=[],
        evidences=[{"user_id": "user-a", "status": "validated", "updated_at": old}],
    )

    assert passport["trust_level"] == "official_registry"
    assert passport["freshness"] == "outdated"
