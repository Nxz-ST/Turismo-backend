from datetime import UTC, datetime
from difflib import SequenceMatcher
import math
import unicodedata
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import AdminUser, SettingsDep
from app.core.errors import ConfigurationError, ExternalServiceError, ResourceNotFoundError
from app.core.public_messages import sanitize_evidence_for_public
from app.schemas.coordinate import CoordinateReviewDecision
from app.schemas.review import (
    CommunityPlaceAdminUpdate,
    CommunityPlaceMerge,
    PlaceIssueReportDecision,
    ReviewDecision,
    ReviewResponse,
)
from app.services.google_maps import GoogleMapsService
from app.services.storage import R2StorageService
from app.services.supabase import SupabaseRepository


router = APIRouter()


def _service_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ResourceNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ConfigurationError):
        return HTTPException(status_code=503, detail=str(exc))
    return HTTPException(
        status_code=502,
        detail="El servicio no está disponible por el momento. Inténtalo nuevamente.",
    )


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


def _community_duplicate_candidates(result: dict) -> list[dict]:
    duplicate = result.get("duplicate_result") or {}
    if duplicate.get("status") != "high_match":
        return []
    matches = [
        candidate
        for candidate in duplicate.get("candidates") or []
        if candidate.get("source") == "community" and candidate.get("high_match")
    ]
    return sorted(
        matches,
        key=lambda candidate: float(candidate.get("distance_m") or 999_999),
    )


async def _validated_community_duplicate(
    repository: SupabaseRepository,
    result: dict,
) -> tuple[dict, dict] | None:
    for match in _community_duplicate_candidates(result):
        try:
            canonical = await repository.get_evidence(UUID(str(match.get("id"))))
        except (ValueError, ResourceNotFoundError):
            continue
        if canonical.get("status") in {"candidate", "validated"}:
            return canonical, match
    return None


async def _fresh_validated_community_duplicate(
    repository: SupabaseRepository,
    evidence: dict,
    category: str,
) -> tuple[dict, dict] | None:
    """Revalida duplicados al aprobar para cerrar carreras de procesamiento.

    Un lugar puede publicarse después de que otra evidencia cercana terminó su
    análisis. Por eso el resultado calculado al inicio no siempre contiene al
    lugar canónico que ya existe cuando el revisor toma la decisión.
    """
    nearby = await repository.nearby_community_places(
        float(evidence["latitude"]),
        float(evidence["longitude"]),
        150,
    )
    matches: list[tuple[dict, dict]] = []
    for place in nearby:
        if str(place.get("id")) == str(evidence.get("id")):
            continue
        if (place.get("estado_validacion") or place.get("status")) != "validated":
            continue
        place_category = str(
            place.get("categoria_ia")
            or place.get("categoria")
            or place.get("category")
            or ""
        ).lower()
        if place_category != str(category).lower():
            continue
        try:
            distance = _distance_m(
                float(evidence["latitude"]),
                float(evidence["longitude"]),
                float(place.get("latitud") or place.get("latitude")),
                float(place.get("longitud") or place.get("longitude")),
            )
        except (TypeError, ValueError):
            continue
        similarity = SequenceMatcher(
            None,
            _plain(evidence.get("name")),
            _plain(place.get("nombre") or place.get("name")),
        ).ratio()
        # A menos de 25 m la categoría basta. Entre 25 y 75 m también se exige
        # una coincidencia fuerte de nombre para no fusionar atractivos vecinos.
        if not (distance <= 25 or (distance <= 75 and similarity >= 0.75)):
            continue
        matches.append(
            (
                place,
                {
                    "distance_m": round(distance, 1),
                    "name_similarity": round(similarity, 3),
                },
            )
        )
    return min(matches, key=lambda item: item[1]["distance_m"]) if matches else None


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
        return [sanitize_evidence_for_public(row) for row in rows]
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
        return sanitize_evidence_for_public(row)
    except (ConfigurationError, ExternalServiceError, ResourceNotFoundError) as exc:
        raise _service_error(exc) from exc


@router.get("/reviews/{evidence_id}/dossier")
async def evidence_dossier(
    evidence_id: UUID,
    _: AdminUser,
    settings: SettingsDep,
) -> dict:
    """Expediente estable para impresión, auditoría o exportación a PDF."""
    try:
        repository = SupabaseRepository(settings)
        evidence = await repository.get_evidence(evidence_id)
        results = await repository.latest_results_for([str(evidence_id)])
        events = await repository.processing_events_for([str(evidence_id)])
        result = results.get(str(evidence_id)) or {}
        photo_url = None
        if evidence.get("object_key"):
            photo_url = R2StorageService(settings).create_download_url(
                evidence["object_key"], expires_in=900
            )
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "institutional_notice": (
                "Este expediente organiza evidencia comunitaria y no constituye "
                "un registro oficial ni una declaración de aptitud turística."
            ),
            "evidence": sanitize_evidence_for_public(
                {**evidence, "photo_url": photo_url}
            ),
            "validation": {
                "score": result.get("score"),
                "coverage": result.get("coverage"),
                "category": result.get("category"),
                "reason": result.get("reason"),
                "rule_version": result.get("rule_version"),
                "component_scores": result.get("component_scores") or {},
                "duplicate_result": result.get("duplicate_result") or {},
                "geospatial_result": result.get("geospatial_result") or {},
            },
            "timeline": events.get(str(evidence_id), []),
            "methodology": [
                "Evidencia visual enviada por una persona autenticada.",
                "Coordenadas y precisión registradas al momento del aporte.",
                "Clasificación visual y contraste geoespacial automatizados.",
                "Control de posibles duplicados oficiales y comunitarios.",
                "Decisión final sujeta a revisión humana.",
            ],
        }
    except (ConfigurationError, ExternalServiceError, ResourceNotFoundError) as exc:
        raise _service_error(exc) from exc


@router.get("/pilot/metrics")
async def pilot_metrics(
    _: AdminUser,
    settings: SettingsDep,
) -> dict:
    try:
        inputs = await SupabaseRepository(settings).pilot_metrics_inputs()
        evidences = inputs["evidences"]
        coordinates = inputs["coordinates"]
        community = inputs["community_places"]
        reports = inputs["reports"]
        events = inputs["events"]
        results = inputs["results"]
        contributors = {row.get("user_id") for row in evidences if row.get("user_id")}
        durations = [
            int(row["duration_ms"])
            for row in events
            if row.get("duration_ms") is not None and int(row["duration_ms"]) >= 0
        ]
        profiled = {
            str(row.get("evidence_id"))
            for row in events
            if (row.get("metadata") or {}).get("event_type") == "community_profile"
        }
        latest_results: dict[str, dict] = {}
        for row in results:
            latest_results.setdefault(str(row.get("evidence_id")), row)
        terrain_available = 0
        sentinel_available = 0
        for row in latest_results.values():
            geo = row.get("geospatial_result") or {}
            terrain = geo.get("terrain") or geo.get("sentinel") or {}
            if terrain and not terrain.get("unavailable") and terrain.get("available", True):
                terrain_available += 1
            sentinel = geo.get("sentinel") or {}
            if sentinel and not sentinel.get("unavailable") and sentinel.get("available", True):
                sentinel_available += 1
        return {
            "evidences_total": len(evidences),
            "candidates": sum(row.get("status") == "candidate" for row in evidences),
            "validated": sum(row.get("status") == "validated" for row in evidences),
            "duplicates_avoided": sum(
                row.get("status") == "duplicate" for row in evidences
            ),
            "coordinate_corrections": sum(
                row.get("status") == "applied" for row in coordinates
            ),
            "community_places": sum(
                row.get("publication_status") == "published" for row in community
            ),
            "contributors": len(contributors),
            "open_reports": sum(row.get("status") == "pending" for row in reports),
            "safety_reports": sum(
                row.get("issue_type") == "safety_risk" for row in reports
            ),
            "new_place_contributions": sum(
                row.get("contribution_type") == "new_place" for row in evidences
            ),
            "existing_place_contributions": sum(
                row.get("contribution_type") == "existing_place" for row in evidences
            ),
            "rejected": sum(row.get("status") == "rejected" for row in evidences),
            "needs_review": sum(row.get("status") == "needs_review" for row in evidences),
            "profiled_places": len(profiled),
            "gps_confirmed": sum(
                row.get("presence_status") in {"confirmed", "verified"}
                for row in evidences
            ),
            "avg_processing_seconds": round(sum(durations) / len(durations) / 1000, 1)
            if durations else 0,
            "sentinel_available": sentinel_available,
            "terrain_available": terrain_available,
            "recent_reports": reports[:20],
        }
    except (ConfigurationError, ExternalServiceError) as exc:
        raise _service_error(exc) from exc


@router.get("/community-places")
async def admin_community_places(_: AdminUser, settings: SettingsDep) -> list[dict]:
    try:
        return await SupabaseRepository(settings).list_admin_community_places()
    except (ConfigurationError, ExternalServiceError) as exc:
        raise _service_error(exc) from exc


@router.patch("/community-places/{place_id}")
async def update_admin_community_place(
    place_id: UUID,
    payload: CommunityPlaceAdminUpdate,
    admin: AdminUser,
    settings: SettingsDep,
) -> dict:
    try:
        repository = SupabaseRepository(settings)
        before = await repository.get_community_place(place_id)
        values = payload.model_dump(exclude={"note"}, exclude_none=True)
        if not values:
            raise HTTPException(status_code=422, detail="Indica al menos un cambio para la ficha")
        updated = await repository.update_community_place(place_id, values)
        if before.get("origin_evidence_id"):
            await repository.save_processing_event(
                evidence_id=UUID(str(before["origin_evidence_id"])),
                stage="human_review",
                status="completed",
                title="Ficha comunitaria actualizada",
                detail=payload.note,
                metadata={
                    "event_type": "community_place_admin_update",
                    "reviewer_id": str(admin.id),
                    "changes": values,
                },
            )
        return updated
    except (ConfigurationError, ExternalServiceError, ResourceNotFoundError) as exc:
        raise _service_error(exc) from exc


@router.post("/community-places/{place_id}/merge")
async def merge_admin_community_place(
    place_id: UUID,
    payload: CommunityPlaceMerge,
    admin: AdminUser,
    settings: SettingsDep,
) -> dict:
    try:
        repository = SupabaseRepository(settings)
        source, target = await repository.merge_community_places(
            place_id, payload.target_place_id
        )
        if source.get("origin_evidence_id"):
            await repository.save_processing_event(
                evidence_id=UUID(str(source["origin_evidence_id"])),
                stage="human_review",
                status="completed",
                title="Ficha comunitaria fusionada",
                detail=payload.note,
                metadata={
                    "event_type": "community_place_merge",
                    "reviewer_id": str(admin.id),
                    "source_place_id": str(place_id),
                    "target_place_id": str(payload.target_place_id),
                },
            )
        return {"source": source, "target": target}
    except (ConfigurationError, ExternalServiceError, ResourceNotFoundError) as exc:
        raise _service_error(exc) from exc


@router.patch("/place-reports/{report_id}")
async def decide_place_report(
    report_id: UUID,
    payload: PlaceIssueReportDecision,
    admin: AdminUser,
    settings: SettingsDep,
) -> dict:
    """Registra una decisión humana sin alterar automáticamente la ficha."""
    try:
        return await SupabaseRepository(settings).update_place_issue_report(
            report_id,
            reviewer_id=admin.id,
            status=payload.status,
            note=payload.note,
        )
    except (
        ConfigurationError,
        ExternalServiceError,
        ResourceNotFoundError,
    ) as exc:
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
        if payload.status == "validated":
            latest = await repository.latest_results_for([str(evidence_id)])
            latest_result = latest.get(str(evidence_id)) or {}
            duplicate_result = latest_result.get("duplicate_result") or {}
            if duplicate_result.get("status") == "category_conflict":
                expected = duplicate_result.get("expected_category") or "registrada"
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"No se puede validar: el lugar está registrado como {expected} "
                        "y la fotografía corresponde a otra categoría. Solicita una "
                        "nueva fotografía del atractivo."
                    ),
                )
            duplicate = await _validated_community_duplicate(
                repository,
                latest_result,
            )
            if duplicate is not None:
                canonical, match = duplicate
                community_place = await repository.promote_community_place(canonical)
                canonical_id = str(community_place["id"])
                canonical_name = str(
                    canonical.get("name") or "el descubrimiento comunitario existente"
                )
                reason = (
                    f"Aporte consolidado con {canonical_name}. RutaAmiga detectó "
                    f"la misma categoría a {float(match.get('distance_m') or 0):.0f} m; "
                    "no se creó una segunda ficha pública."
                )
                await repository.update_evidence(
                    evidence_id,
                    {
                        "target_place_snapshot": {
                            "community_evidence_id": canonical_id,
                            "nombre": canonical_name,
                            "categoria": canonical.get("predicted_category"),
                            "latitud": canonical.get("latitude"),
                            "longitud": canonical.get("longitude"),
                            "distance_m": match.get("distance_m"),
                            "linked_automatically": True,
                        }
                    },
                )
                await repository.link_evidence_to_community_place(
                    evidence_id,
                    canonical_id,
                )
                return await repository.save_manual_review(
                    evidence_id=evidence_id,
                    reviewer_id=admin.id,
                    status="duplicate",
                    category=category,
                    reason=reason,
                )
            fresh_duplicate = await _fresh_validated_community_duplicate(
                repository,
                evidence,
                str(category),
            )
            if fresh_duplicate is not None:
                canonical, match = fresh_duplicate
                canonical_id = str(canonical["id"])
                canonical_name = str(
                    canonical.get("nombre")
                    or canonical.get("name")
                    or "el descubrimiento comunitario existente"
                )
                reason = (
                    f"Aporte consolidado con {canonical_name}. Al momento de "
                    f"aprobar ya existía una ficha de la misma categoría a "
                    f"{float(match['distance_m']):.0f} m; no se creó un duplicado."
                )
                await repository.update_evidence(
                    evidence_id,
                    {
                        "target_place_snapshot": {
                            "community_evidence_id": canonical_id,
                            "nombre": canonical_name,
                            "categoria": category,
                            "latitud": canonical.get("latitud")
                            or canonical.get("latitude"),
                            "longitud": canonical.get("longitud")
                            or canonical.get("longitude"),
                            "distance_m": match["distance_m"],
                            "linked_automatically": True,
                            "rechecked_at_review": True,
                        }
                    },
                )
                await repository.link_evidence_to_community_place(
                    evidence_id,
                    canonical_id,
                )
                return await repository.save_manual_review(
                    evidence_id=evidence_id,
                    reviewer_id=admin.id,
                    status="duplicate",
                    category=category,
                    reason=reason,
                )
        reviewed = await repository.save_manual_review(
            evidence_id=evidence_id,
            reviewer_id=admin.id,
            status=payload.status,
            category=category,
            reason=payload.reason,
        )
        if payload.status == "validated":
            refreshed = await repository.get_evidence(evidence_id)
            if refreshed.get("contribution_type") == "new_place":
                await repository.promote_community_place(refreshed)
            elif refreshed.get("target_community_place_id"):
                await repository.link_evidence_to_community_place(
                    evidence_id,
                    refreshed["target_community_place_id"],
                )
        return reviewed
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
