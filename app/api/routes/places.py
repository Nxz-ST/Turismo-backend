from collections import Counter

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import CurrentUser, SettingsDep
from app.core.errors import ConfigurationError, ExternalServiceError
from app.core.errors import ResourceNotFoundError
from app.domain.trust import build_trust_passport
from app.schemas.place import CommunityPlaceResponse, TrustPassportResponse
from app.services.storage import R2StorageService
from app.services.supabase import SupabaseRepository


router = APIRouter()


def _latest_community_profile(events: list[dict]) -> tuple[dict, str | None] | None:
    for event in reversed(events):
        metadata = event.get("metadata") or {}
        is_profile = (
            event.get("stage") == "community_profile"
            or metadata.get("event_type") == "community_profile"
        )
        answers = metadata.get("answers")
        if is_profile and isinstance(answers, dict):
            return answers, event.get("created_at")
    return None


async def _trust_passport(
    repository: SupabaseRepository,
    *,
    source: Literal["official", "community"],
    place_id: str,
) -> dict:
    visits, evidences = await repository.trust_passport_inputs(
        source=source,
        place_id=place_id,
    )
    return build_trust_passport(
        source=source,
        place_id=place_id,
        visits=visits,
        evidences=evidences,
    )


def _community_public_row(row: dict, storage: R2StorageService) -> dict:
    raw_description = str(
        row.get("descripcion") or row.get("description") or ""
    ).strip()
    description = (
        raw_description
        if raw_description.startswith("Información comunitaria verificada para ")
        else (
            "La evidencia visual y la ubicación fueron corroboradas. "
            "La información de visita todavía se está completando."
        )
    )
    result = {
        **row,
        "nombre": row.get("nombre") or row.get("name"),
        "descripcion": description,
        "categoria_ia": row.get("categoria_ia") or row.get("category"),
        "latitud": row.get("latitud") or row.get("latitude"),
        "longitud": row.get("longitud") or row.get("longitude"),
        "altitud": row.get("altitud") or row.get("altitude"),
        "estado_validacion": "validated",
    }
    object_key = result.pop("object_key", None) or result.pop(
        "primary_photo_object_key", None
    )
    result["foto_url"] = (
        storage.create_download_url(object_key, expires_in=900)
        if object_key
        else None
    )
    result.setdefault("photos", [])
    result.setdefault("community_updates", [])
    return result


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


@router.get("/community/nearby", response_model=list[CommunityPlaceResponse])
async def nearby_community_places(
    _: CurrentUser,
    settings: SettingsDep,
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(ge=-180, le=180),
    radius: float = Query(default=10_000, gt=0, le=100_000),
) -> list[dict]:
    try:
        repository = SupabaseRepository(settings)
        rows = await repository.nearby_canonical_community_places(
            latitude,
            longitude,
            radius,
        )
        storage = R2StorageService(settings)
        enriched = []
        for row in rows:
            public = _community_public_row(row, storage)
            public["trust"] = await _trust_passport(
                repository,
                source="community",
                place_id=str(public["id"]),
            )
            enriched.append(public)
        return enriched
    except ConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ExternalServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/community/{place_id}", response_model=CommunityPlaceResponse)
async def community_place_detail(
    place_id: UUID,
    _: CurrentUser,
    settings: SettingsDep,
) -> dict:
    try:
        repository = SupabaseRepository(settings)
        row = await repository.get_community_place(place_id)
        public = _community_public_row(row, R2StorageService(settings))
        evidence_rows = await repository.community_place_evidences(place_id)
        events_by_evidence = await repository.processing_events_for(
            [str(evidence["id"]) for evidence in evidence_rows]
        )
        storage = R2StorageService(settings)
        photos: list[str] = []
        updates: list[dict] = []
        for evidence in evidence_rows:
            object_key = evidence.get("object_key")
            if object_key:
                url = storage.create_download_url(str(object_key), expires_in=900)
                if url not in photos:
                    photos.append(url)
            description = str(evidence.get("description") or "").strip()
            if description.startswith("Información comunitaria verificada para "):
                profile = _latest_community_profile(
                    events_by_evidence.get(str(evidence["id"]), [])
                )
                updates.append(
                    {
                        "description": description,
                        "reported_at": (
                            profile[1] if profile else evidence.get("updated_at")
                        ),
                        "answers": profile[0] if profile else None,
                    }
                )
        public["photos"] = photos
        public["community_updates"] = updates[:10]
        if updates:
            public["descripcion"] = updates[0]["description"]
        public["trust"] = await _trust_passport(
            repository,
            source="community",
            place_id=str(place_id),
        )
        return public
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ExternalServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get(
    "/{source}/{place_id}/trust",
    response_model=TrustPassportResponse,
)
async def place_trust_passport(
    source: Literal["official", "community"],
    place_id: str,
    _: CurrentUser,
    settings: SettingsDep,
) -> dict:
    try:
        repository = SupabaseRepository(settings)
        if source == "official":
            try:
                await repository.get_tourist_place(int(place_id))
            except ValueError as exc:
                raise HTTPException(
                    status_code=422,
                    detail="El identificador oficial no es válido",
                ) from exc
        else:
            await repository.get_community_place(place_id)
        return await _trust_passport(
            repository,
            source=source,
            place_id=place_id,
        )
    except HTTPException:
        raise
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
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

