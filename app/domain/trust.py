from collections import Counter
from datetime import UTC, datetime
from typing import Any, Literal


PlaceSource = Literal["official", "community"]


def build_trust_passport(
    *,
    source: PlaceSource,
    place_id: str,
    visits: list[dict[str, Any]],
    evidences: list[dict[str, Any]],
) -> dict[str, Any]:
    verified_visits = [row for row in visits if row.get("visit_verified") is True]
    approved_evidences = [
        row
        for row in evidences
        if str(row.get("status") or "") in {"validated", "duplicate"}
    ]
    visitor_ids = {
        str(row["user_id"])
        for row in verified_visits
        if row.get("user_id") is not None
    }
    contributor_ids = {
        str(row["user_id"])
        for row in approved_evidences
        if row.get("user_id") is not None
    }
    supporters = visitor_ids | contributor_ids
    observed_at = [
        parsed
        for parsed in (
            _datetime(row.get("captured_at") or row.get("updated_at"))
            for row in [*verified_visits, *approved_evidences]
        )
        if parsed is not None
    ]
    last_verified = max(observed_at) if observed_at else None
    place_condition = _majority(verified_visits, "place_condition")
    access_condition = _majority(verified_visits, "access_condition")
    return {
        "place_id": place_id,
        "source": source,
        "trust_level": _trust_level(source, len(supporters)),
        "verified_visitors": len(visitor_ids),
        "approved_contributors": len(contributor_ids),
        "independent_supporters": len(supporters),
        "last_verified_at": last_verified,
        "freshness": _freshness(last_verified),
        "place_condition": place_condition,
        "access_condition": access_condition,
        "method": "unique_verified_people_v1",
    }


def _trust_level(source: PlaceSource, supporters: int) -> str:
    if source == "official":
        return "official_registry"
    if supporters >= 5:
        return "community_established"
    if supporters >= 2:
        return "community_corroborated"
    return "community_initial"


def _freshness(value: datetime | None) -> str:
    if value is None:
        return "unverified"
    days = (datetime.now(UTC) - value).days
    if days <= 30:
        return "recent"
    if days <= 180:
        return "current"
    return "outdated"


def _majority(rows: list[dict[str, Any]], key: str) -> str | None:
    counts = Counter(str(row[key]) for row in rows if row.get(key))
    return counts.most_common(1)[0][0] if counts else None


def _datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
