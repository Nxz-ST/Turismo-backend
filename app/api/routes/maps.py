from fastapi import APIRouter, HTTPException, Query, Response

from app.api.deps import CurrentUser, SettingsDep
from app.core.errors import ConfigurationError, ExternalServiceError
from app.schemas.maps import RouteRequest
from app.services.google_maps import GoogleMapsService
from app.services.storage import R2StorageService
from app.services.supabase import SupabaseRepository


router = APIRouter()


@router.get("/destinations/search")
async def search_destinations(
    _: CurrentUser,
    settings: SettingsDep,
    query: str = Query(min_length=2, max_length=120),
) -> list[dict]:
    try:
        return await GoogleMapsService(settings).search_destinations(query=query)
    except ConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ExternalServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/services/nearby")
async def nearby_services(
    _: CurrentUser,
    settings: SettingsDep,
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(ge=-180, le=180),
    place_type: str = Query(alias="type"),
    radius: float = Query(default=3_000, gt=0, le=50_000),
) -> list[dict]:
    try:
        return await GoogleMapsService(settings).nearby_services(
            latitude=latitude,
            longitude=longitude,
            place_type=place_type,
            radius=radius,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ExternalServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/routes")
async def compute_route(
    payload: RouteRequest,
    _: CurrentUser,
    settings: SettingsDep,
) -> dict:
    try:
        return await GoogleMapsService(settings).route(payload.model_dump())
    except ConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ExternalServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/photos/tourist")
async def tourist_photo_reference(
    _: CurrentUser,
    settings: SettingsDep,
    name: str = Query(min_length=1, max_length=180),
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(ge=-180, le=180),
) -> dict[str, str | None]:
    try:
        photo_name = await GoogleMapsService(settings).tourist_photo_reference(
            name=name,
            latitude=latitude,
            longitude=longitude,
        )
        return {"photo_name": photo_name}
    except ConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ExternalServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/photos/media")
async def photo_media(
    _: CurrentUser,
    settings: SettingsDep,
    name: str = Query(min_length=1, max_length=500),
    max_width: int = Query(default=800, ge=64, le=1600),
    max_height: int = Query(default=600, ge=64, le=1600),
) -> Response:
    try:
        content, content_type = await GoogleMapsService(settings).photo_bytes(
            photo_name=name,
            max_width=max_width,
            max_height=max_height,
        )
        return Response(
            content=content,
            media_type=content_type,
            headers={"Cache-Control": "private, max-age=3600"},
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ExternalServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/photos/gallery")
async def tourist_photo_gallery(
    _: CurrentUser,
    settings: SettingsDep,
    name: str = Query(min_length=1, max_length=180),
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(ge=-180, le=180),
    limit: int = Query(default=10, ge=1, le=16),
) -> list[dict[str, str]]:
    """Return lightweight gallery metadata; clients request image bytes lazily."""
    items: list[dict[str, str]] = []

    try:
        google_photos = await GoogleMapsService(settings).tourist_photo_references(
            name=name,
            latitude=latitude,
            longitude=longitude,
            # Reservamos espacio para aportes validados de la comunidad.
            limit=min(limit, 6),
        )
        items.extend(
            {
                "id": photo["name"],
                "source": "google",
                "attribution": photo["attribution"],
                "photo_name": photo["name"],
            }
            for photo in google_photos
        )
    except (ConfigurationError, ExternalServiceError):
        # La galería es enriquecimiento opcional: conservamos las fotos
        # comunitarias aunque Google no esté disponible temporalmente.
        pass

    if len(items) < limit:
        try:
            nearby = await SupabaseRepository(settings).nearby_community_places(
                latitude,
                longitude,
                350,
            )
            storage = R2StorageService(settings)
            seen_keys: set[str] = set()
            for row in nearby:
                if len(items) >= limit:
                    break
                status = row.get("estado_validacion") or row.get("status")
                object_key = str(row.get("object_key") or "").strip()
                if status not in {
                    "validated",
                    "approved",
                    "validated_satellite",
                } or not object_key or object_key in seen_keys:
                    continue
                seen_keys.add(object_key)
                items.append(
                    {
                        "id": str(row.get("id") or object_key),
                        "source": "community",
                        "attribution": "Comunidad RutaAmiga",
                        "url": storage.create_download_url(object_key, expires_in=3600),
                    }
                )
        except (ConfigurationError, ExternalServiceError):
            pass

    return items

