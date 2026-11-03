from typing import Any


_INTERNAL_MARKERS = (
    "supabase respondio",
    "supabase respondió",
    "failing row",
    "sqlstate",
    "postgrest",
    "traceback",
    "stack trace",
    "exception",
    '"code":"23',
    '"details":',
)


def contains_internal_detail(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return bool(text) and any(marker in text for marker in _INTERNAL_MARKERS)


def public_processing_failure() -> str:
    return (
        "No pudimos completar el análisis automático. Tu aporte está seguro y "
        "quedó disponible para reintento o revisión."
    )


def public_decision_reason(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if contains_internal_detail(text):
        return public_processing_failure()
    return text


def sanitize_evidence_for_public(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    result["decision_reason"] = public_decision_reason(
        result.get("decision_reason")
    )
    events = []
    for raw_event in result.get("processing_events") or []:
        event = dict(raw_event)
        if contains_internal_detail(event.get("detail")):
            event["detail"] = public_processing_failure()
        events.append(event)
    if "processing_events" in result:
        result["processing_events"] = events
    return result
