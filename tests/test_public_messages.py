from app.core.public_messages import (
    public_decision_reason,
    sanitize_evidence_for_public,
)


def test_hides_database_details_from_decision_reason() -> None:
    reason = 'Supabase respondio 400: {"code":"23514","details":"Failing row"}'

    public = public_decision_reason(reason)

    assert public is not None
    assert "Supabase" not in public
    assert "23514" not in public


def test_preserves_explanatory_decision_reason() -> None:
    reason = "La fotografía necesita revisión humana."

    assert public_decision_reason(reason) == reason


def test_hides_internal_processing_event_detail() -> None:
    evidence = {
        "decision_reason": "Supabase respondió 400: SQLSTATE 23514",
        "processing_events": [
            {"stage": "decision", "detail": "Failing row from PostgREST"}
        ],
    }

    sanitized = sanitize_evidence_for_public(evidence)

    assert "Supabase" not in sanitized["decision_reason"]
    assert "PostgREST" not in sanitized["processing_events"][0]["detail"]
