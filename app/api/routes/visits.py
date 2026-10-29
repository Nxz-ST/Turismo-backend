from math import asin, cos, radians, sin, sqrt

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import CurrentUser, SettingsDep
from app.core.errors import ConfigurationError, ExternalServiceError
from app.schemas.visit import RouteVisitCreate, RouteVisitResponse
from app.services.storage import R2StorageService
from app.services.supabase import SupabaseRepository


router = APIRouter()


def _distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    d_lat = radians(lat2 - lat1)
    d_lon = radians(lon2 - lon1)
    value = sin(d_lat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(
        d_lon / 2
    ) ** 2
    return 6_371_000 * 2 * asin(sqrt(value))


def _verification_radius(category: str, name: str) -> float:
    text = f"{category} {name}".lower()
    if any(word in text for word in ("nevado", "montaña", "montana", "volcán", "volcan")):
        return 500.0
    if any(word in text for word in ("cascada", "bosque", "lago", "playa", "desierto")):
        return 300.0
    return 180.0


def _with_photo_url(row: dict, storage: R2StorageService) -> dict:
    result = dict(row)
    key = result.get("photo_object_key")
    result["photo_url"] = storage.create_download_url(key) if key else None
    return result


@router.post("", response_model=RouteVisitResponse)
async def create_visit(
    payload: RouteVisitCreate,
    user: CurrentUser,
    settings: SettingsDep,
) -> dict:
    if payload.photo_object_key:
        expected_prefix = f"evidences/{user.id}/"
        if not payload.photo_object_key.startswith(expected_prefix):
            raise HTTPException(status_code=400, detail="La fotografía no pertenece al usuario")

    distance = _distance_m(
        payload.target_latitude,
        payload.target_longitude,
        payload.recorded_latitude,
        payload.recorded_longitude,
    )
    radius = _verification_radius(payload.place_category, payload.place_name)
    # La exactitud forma parte de la decisión: una lectura demasiado imprecisa
    # se conserva en el pasaporte, pero no acredita presencia.
    verified = distance <= radius and payload.gps_accuracy_m <= min(radius, 120)
    moderation = (
        "pending" if payload.photo_object_key or payload.comment.strip() else "not_required"
    )
    data = {
        **payload.model_dump(mode="json"),
        "distance_m": round(distance, 1),
        "verification_radius_m": radius,
        "visit_verified": verified,
        "moderation_status": moderation,
    }
    try:
        row = await SupabaseRepository(settings).create_route_visit(
            user_id=user.id,
            data=data,
        )
        return _with_photo_url(row, R2StorageService(settings))
    except ConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ExternalServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("", response_model=list[RouteVisitResponse])
async def list_visits(
    user: CurrentUser,
    settings: SettingsDep,
    limit: int = Query(default=100, ge=1, le=300),
) -> list[dict]:
    try:
        rows = await SupabaseRepository(settings).list_route_visits(user.id, limit=limit)
        storage = R2StorageService(settings)
        return [_with_photo_url(row, storage) for row in rows]
    except ConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ExternalServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

