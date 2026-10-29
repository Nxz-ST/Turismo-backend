from collections import Counter

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import CurrentUser, SettingsDep
from app.core.errors import ConfigurationError, ExternalServiceError
from app.services.supabase import SupabaseRepository


router = APIRouter()


def _condition_summary(rows: list[dict]) -> dict:
    place_counts = Counter(
        row["place_condition"] for row in rows if row.get("place_condition")
    )
    access_counts = Counter(
        row["access_condition"] for row in rows if row.get("access_condition")
    )
    return {
        "place_condition": place_counts.most_common(1)[0][0] if place_counts else None,
        "access_condition": access_counts.most_common(1)[0][0] if access_counts else None,
        "verified_reports": len(rows),
        "last_reported_at": rows[0].get("captured_at") if rows else None,
        "source": "verified_route_visits",
        "window_days": 30,
    }


@router.get("/nearby")
async def nearby_places(
    _: CurrentUser,
    settings: SettingsDep,
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(ge=-180, le=180),
    radius: float = Query(default=10_000, gt=0, le=100_000),
) -> list[dict]:
    try:
        return await SupabaseRepository(settings).nearby_places(latitude, longitude, radius)
    except ConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ExternalServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/{place_id}/conditions")
async def place_conditions(
    place_id: str,
    _: CurrentUser,
    settings: SettingsDep,
) -> dict:
    try:
        rows = await SupabaseRepository(settings).recent_verified_place_conditions(
            place_id
        )
        return _condition_summary(rows)
    except ConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ExternalServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

