from difflib import SequenceMatcher
import math
import unicodedata
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import AdminUser, SettingsDep
from app.core.errors import ConfigurationError, ExternalServiceError, ResourceNotFoundError
from app.schemas.coordinate import CoordinateReviewDecision
from app.schemas.review import ReviewDecision, ReviewResponse
from app.services.google_maps import GoogleMapsService
from app.services.storage import R2StorageService
from app.services.supabase import SupabaseRepository


router = APIRouter()


def _service_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ResourceNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ConfigurationError):
        return HTTPException(status_code=503, detail=str(exc))
    return HTTPException(status_code=502, detail=str(exc))


def _plain(value: object) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "").lower())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    value = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def _score_coordinate_candidate(place: dict, candidate: dict) -> float:
    name_score = SequenceMatcher(
        None,
        _plain(place.get("nombre")),
        _plain(candidate.get("name")),
    ).ratio()
    address = _plain(candidate.get("address"))
    contexts = [
        _plain(place.get(field))
        for field in ("distrito", "provincia", "departamento")
        if place.get(field)
    ]
    context_score = (
        sum(context in address for context in contexts) / len(contexts)
        if contexts
        else 0
    )
    # Es una prioridad de revisión, no una aprobación automática. Google puede
    # representar la cima, la entrada o un negocio con nombre parecido.
    return round(min(0.85, name_score * 0.7 + context_score * 0.15), 3)


@router.get("/reviews")
async def review_queue(
    _: AdminUser,
    settings: SettingsDep,
    limit: int = Query(default=50, ge=1, le=100),
) -> list[dict]:
    try:
        rows = await SupabaseRepository(settings).list_review_queue(
            limit=limit,
        )
        results = await SupabaseRepository(settings).latest_results_for(
            [str(row["id"]) for row in rows]
        )
        events = await SupabaseRepository(settings).processing_events_for(
            [str(row["id"]) for row in rows]
        )
        storage = R2StorageService(settings)
        for row in rows:
            result = results.get(str(row["id"])) or {}
            row["geospatial_result"] = result.get("geospatial_result") or {}
            row["validation_details"] = result
            row["processing_events"] = events.get(str(row["id"]), [])
            if row.get("object_key"):
                row["photo_url"] = storage.create_download_url(row["object_key"], expires_in=900)
        return rows
    except (ConfigurationError, ExternalServiceError) as exc:
        raise _service_error(exc) from exc


@router.get("/reviews/{evidence_id}")
async def review_detail(
    evidence_id: UUID,
    _: AdminUser,
    settings: SettingsDep,
) -> dict:
    try:
        row = await SupabaseRepository(settings).get_evidence(evidence_id)
        results = await SupabaseRepository(settings).latest_results_for(
            [str(evidence_id)]
        )
        events = await SupabaseRepository(settings).processing_events_for(
            [str(evidence_id)]
        )
        row["geospatial_result"] = (
            results.get(str(evidence_id), {}).get("geospatial_result") or {}
        )
        row["validation_details"] = results.get(str(evidence_id), {})
        row["processing_events"] = events.get(str(evidence_id), [])
        if row.get("object_key"):
            row["photo_url"] = R2StorageService(settings).create_download_url(
                row["object_key"], expires_in=900
            )
        return row
    except (ConfigurationError, ExternalServiceError, ResourceNotFoundError) as exc:
        raise _service_error(exc) from exc


@router.patch("/reviews/{evidence_id}", response_model=ReviewResponse)
async def decide_review(
    evidence_id: UUID,
    payload: ReviewDecision,
    admin: AdminUser,
    settings: SettingsDep,
) -> dict:
    try:
        repository = SupabaseRepository(settings)
        evidence = await repository.get_evidence(evidence_id)
        category = payload.category or evidence.get("predicted_category")
        if payload.status == "validated" and not category:
            raise HTTPException(
                status_code=422,
                detail="Selecciona una categoria antes de validar",
            )
        return await repository.save_manual_review(
            evidence_id=evidence_id,
            reviewer_id=admin.id,
            status=payload.status,
            category=category,
            reason=payload.reason,
        )
    except HTTPException:
        raise
    except (ConfigurationError, ExternalServiceError, ResourceNotFoundError) as exc:
        raise _service_error(exc) from exc


@router.get("/coordinate-reviews")
async def coordinate_review_queue(
    _: AdminUser,
    settings: SettingsDep,
    limit: int = Query(default=100, ge=1, le=200),
) -> list[dict]:
    try:
        return await SupabaseRepository(settings).list_coordinate_reviews(
            statuses=["flagged", "candidate"],
            limit=limit,
        )
    except (ConfigurationError, ExternalServiceError) as exc:
        raise _service_error(exc) from exc


@router.get("/coordinate-reviews/{review_id}/suggestions")
async def coordinate_review_suggestions(
    review_id: UUID,
    _: AdminUser,
    settings: SettingsDep,
) -> list[dict]:
    try:
        repository = SupabaseRepository(settings)
        review = await repository.get_coordinate_review(review_id)
        place = await repository.get_tourist_place(int(review["place_id"]))
        candidates = await GoogleMapsService(settings).tourist_coordinate_candidates(
            name=str(place.get("nombre") or "Atractivo turístico"),
            district=str(place.get("distrito") or ""),
            province=str(place.get("provincia") or ""),
            department=str(place.get("departamento") or ""),
        )
        for candidate in candidates:
            candidate["distance_from_reported_m"] = round(
                _distance_m(
                    float(review["original_latitude"]),
                    float(review["original_longitude"]),
                    float(candidate["latitude"]),
                    float(candidate["longitude"]),
                ),
                1,
            )
            candidate["confidence"] = _score_coordinate_candidate(
                place, candidate
            )
            candidate["confidence_kind"] = "review_priority_only"
        candidates.sort(key=lambda item: item["confidence"], reverse=True)
        return candidates
    except (ConfigurationError, ExternalServiceError, ResourceNotFoundError) as exc:
        raise _service_error(exc) from exc


@router.patch("/coordinate-reviews/{review_id}")
async def decide_coordinate_review(
    review_id: UUID,
    payload: CoordinateReviewDecision,
    admin: AdminUser,
    settings: SettingsDep,
) -> dict:
    try:
        repository = SupabaseRepository(settings)
        await repository.get_coordinate_review(review_id)
        if payload.action == "reject":
            return await repository.reject_coordinate_review(
                review_id=review_id,
                reviewer_id=admin.id,
                note=payload.note,
            )

        await repository.save_coordinate_candidate(
            review_id=review_id,
            review_type=(
                "access" if payload.action == "approve_access" else "coordinate"
            ),
            latitude=float(payload.latitude),
            longitude=float(payload.longitude),
            name=payload.candidate_name,
            address=payload.candidate_address,
            source=payload.source or "manual_admin_review",
            source_reference=payload.source_reference,
            confidence=payload.confidence,
        )
        return await repository.apply_coordinate_review(
            review_id=review_id,
            reviewer_id=admin.id,
            note=payload.note,
        )
    except (ConfigurationError, ExternalServiceError, ResourceNotFoundError) as exc:
        raise _service_error(exc) from exc
