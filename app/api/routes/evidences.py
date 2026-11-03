import math
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status

from app.api.deps import CurrentUser, SettingsDep
from app.core.errors import ConfigurationError, ExternalServiceError, ResourceNotFoundError
from app.schemas.evidence import (
    EvidenceCreate,
    EvidenceProfileAnswers,
    EvidenceProfileResponse,
    EvidenceResponse,
    ProcessResponse,
)
from app.services.supabase import SupabaseRepository
from app.services.storage import R2StorageService
from app.services.workflow import ValidationWorkflow


router = APIRouter()


def _with_photo_url(row: dict, storage: R2StorageService) -> dict:
    result = dict(row)
    object_key = result.get("object_key")
    if object_key:
        result["photo_url"] = storage.create_download_url(object_key, expires_in=900)
    return result


def _with_public_community_description(row: dict) -> dict:
    result = dict(row)
    description = str(result.get("descripcion") or "").strip()
    generated_profile = description.startswith(
        "Información comunitaria verificada para "
    )
    if not generated_profile:
        category = str(result.get("categoria_ia") or "atractivo turístico")
        result["descripcion"] = (
            f"Descubrimiento de la comunidad validado como {category}. "
            "La información detallada todavía está en verificación."
        )
        result["descripcion_usuario"] = description
    return result


def _handle_service_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ResourceNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ConfigurationError):
        return HTTPException(status_code=503, detail=str(exc))
    return HTTPException(status_code=502, detail=str(exc))


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


_PROFILE_LABELS = {
    "access_type": {
        "walking": "a pie",
        "vehicle": "en vehículo",
        "public_transport": "en transporte público",
        "mixed": "mediante acceso mixto",
    },
    "cost_type": {"free": "gratuito", "paid": "con ingreso pagado"},
    "access_difficulty": {
        "easy": "de dificultad fácil",
        "moderate": "de dificultad moderada",
        "difficult": "de acceso difícil",
    },
    "place_state": {
        "open": "se encontró abierto",
        "restricted": "presentó acceso restringido",
        "closed": "se encontró cerrado",
    },
    "activities": {
        "photography": "fotografía",
        "walking": "caminata",
        "swimming": "baño",
        "nature": "observación de naturaleza",
        "culture": "actividades culturales",
        "adventure": "aventura",
        "relaxation": "descanso",
    },
    "services": {
        "restrooms": "baños",
        "parking": "estacionamiento",
        "food": "alimentación",
        "guide": "guía",
        "signage": "señalización",
    },
    "risks": {
        "difficult_access": "acceso complicado",
        "slippery_surface": "superficie resbaladiza",
        "strong_current": "corriente fuerte",
        "steep_drop": "desnivel pronunciado",
        "low_signal": "baja cobertura móvil",
    },
}


def _answer_labels(group: str, values: list[str]) -> list[str]:
    labels = _PROFILE_LABELS[group]
    return [labels[value] for value in dict.fromkeys(values) if value in labels]


def _profile_description(evidence: dict, answers: EvidenceProfileAnswers) -> str:
    data = answers.model_dump(mode="json")
    name = str(evidence.get("name") or "Este lugar").strip()
    parts: list[str] = []
    access = _PROFILE_LABELS["access_type"].get(data["access_type"])
    difficulty = _PROFILE_LABELS["access_difficulty"].get(
        data["access_difficulty"]
    )
    cost = _PROFILE_LABELS["cost_type"].get(data["cost_type"])
    state = _PROFILE_LABELS["place_state"].get(data["place_state"])
    if access:
        parts.append(f"El acceso reportado es {access}")
    if difficulty:
        parts.append(difficulty)
    if cost:
        parts.append(f"el ingreso fue indicado como {cost}")
    if state:
        parts.append(state)
    activities = _answer_labels("activities", data["activities"])
    services = _answer_labels("services", data["services"])
    risks = _answer_labels("risks", data["risks"])
    sentences = [f"Información comunitaria verificada para {name}."]
    if parts:
        sentences.append("; ".join(parts).capitalize() + ".")
    if activities:
        sentences.append(f"Actividades observadas: {', '.join(activities)}.")
    if services:
        sentences.append(f"Servicios observados: {', '.join(services)}.")
    if risks:
        sentences.append(f"Precauciones reportadas: {', '.join(risks)}.")
    sentences.append("Datos aportados por la comunidad y sujetos a confirmación.")
    return " ".join(sentences)


@router.post("", response_model=EvidenceResponse, status_code=status.HTTP_201_CREATED)
async def create_evidence(
    payload: EvidenceCreate,
    user: CurrentUser,
    settings: SettingsDep,
) -> dict:
    expected_prefix = f"evidences/{user.id}/"
    if not payload.object_key.startswith(expected_prefix):
        raise HTTPException(status_code=400, detail="La imagen no pertenece al usuario autenticado")
    try:
        repository = SupabaseRepository(settings)
        data = payload.model_dump(mode="json")
        if payload.contribution_type == "existing_place":
            if (payload.target_place_id is None) == (
                payload.target_community_place_id is None
            ):
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "Selecciona un único lugar oficial o comunitario al que "
                        "pertenece la evidencia"
                    ),
                )
            if payload.target_community_place_id is not None:
                place = await repository.get_community_place(
                    payload.target_community_place_id
                )
                data["community_place_id"] = str(payload.target_community_place_id)
                snapshot_category = place.get("category")
            else:
                place = await repository.get_tourist_place(payload.target_place_id)
                snapshot_category = place.get("categoria_texto")
            place_latitude = float(place.get("latitud") or place["latitude"])
            place_longitude = float(place.get("longitud") or place["longitude"])
            data["target_place_snapshot"] = {
                "id": place.get("id"),
                "codigo": place.get("codigo"),
                "nombre": place.get("nombre") or place.get("name"),
                "categoria": snapshot_category,
                "departamento": place.get("departamento"),
                "provincia": place.get("provincia"),
                "distrito": place.get("distrito"),
                "latitud": place_latitude,
                "longitud": place_longitude,
                "source": (
                    "community"
                    if payload.target_community_place_id is not None
                    else "official"
                ),
            }
            data["target_distance_m"] = round(
                _distance_m(
                    payload.latitude,
                    payload.longitude,
                    place_latitude,
                    place_longitude,
                ),
                1,
            )
        elif (
            payload.target_place_id is not None
            or payload.target_community_place_id is not None
        ):
            raise HTTPException(
                status_code=422,
                detail="Un descubrimiento nuevo no debe incluir un lugar existente",
            )
        if payload.presence_sample_id is not None:
            await repository.get_presence_sample(payload.presence_sample_id, user.id)
        evidence = await repository.create_evidence(
            user_id=user.id,
            data=data,
        )
        evidence = await repository.create_presence_attestation(
            evidence_id=UUID(str(evidence["id"])),
            user_id=user.id,
            latitude=payload.latitude,
            longitude=payload.longitude,
            preferred_sample_id=payload.presence_sample_id,
        )
        await repository.save_processing_event(
            evidence_id=UUID(str(evidence["id"])),
            stage="received",
            status="completed",
            title="Evidencia recibida",
            detail="Fotografia, metadatos y referencia de ubicacion almacenados.",
        )
        evidence["processing_events"] = []
        return evidence
    except HTTPException:
        raise
    except (ConfigurationError, ExternalServiceError, ResourceNotFoundError) as exc:
        raise _handle_service_error(exc) from exc


@router.get("", response_model=list[EvidenceResponse])
async def list_evidences(
    user: CurrentUser,
    settings: SettingsDep,
    limit: int = Query(default=50, ge=1, le=100),
) -> list[dict]:
    try:
        rows = await SupabaseRepository(settings).list_evidences(user.id, limit)
        results = await SupabaseRepository(settings).latest_results_for(
            [str(row["id"]) for row in rows]
        )
        events = await SupabaseRepository(settings).processing_events_for(
            [str(row["id"]) for row in rows]
        )
        storage = R2StorageService(settings)
        enriched = []
        for row in rows:
            result = results.get(str(row["id"])) or {}
            row["geospatial_result"] = result.get("geospatial_result") or {}
            row["validation_details"] = result
            row["processing_events"] = events.get(str(row["id"]), [])
            enriched.append(_with_photo_url(row, storage))
        return enriched
    except (ConfigurationError, ExternalServiceError) as exc:
        raise _handle_service_error(exc) from exc


@router.get("/nearby")
async def nearby_reported_places(
    _: CurrentUser,
    settings: SettingsDep,
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(ge=-180, le=180),
    radius: float = Query(default=10_000, gt=0, le=100_000),
) -> list[dict]:
    try:
        rows = await SupabaseRepository(settings).nearby_reported_places(
            latitude,
            longitude,
            radius,
        )
        storage = R2StorageService(settings)
        for index, raw_row in enumerate(rows):
            row = _with_public_community_description(raw_row)
            object_key = row.pop("object_key", None)
            if object_key:
                row["foto_url"] = storage.create_download_url(object_key, expires_in=900)
            rows[index] = row
        return rows
    except (ConfigurationError, ExternalServiceError) as exc:
        raise _handle_service_error(exc) from exc


@router.get("/{evidence_id}", response_model=EvidenceResponse)
async def get_evidence(
    evidence_id: UUID,
    user: CurrentUser,
    settings: SettingsDep,
) -> dict:
    try:
        row = await SupabaseRepository(settings).get_evidence(evidence_id, user.id)
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
        return _with_photo_url(row, R2StorageService(settings))
    except (ConfigurationError, ExternalServiceError, ResourceNotFoundError) as exc:
        raise _handle_service_error(exc) from exc


@router.post(
    "/{evidence_id}/profile",
    response_model=EvidenceProfileResponse,
)
async def complete_evidence_profile(
    evidence_id: UUID,
    payload: EvidenceProfileAnswers,
    user: CurrentUser,
    settings: SettingsDep,
) -> dict:
    repository = SupabaseRepository(settings)
    try:
        evidence = await repository.get_evidence(evidence_id, user.id)
        if evidence.get("status") not in {"candidate", "validated"}:
            raise HTTPException(
                status_code=409,
                detail=(
                    "El cuestionario estará disponible cuando la evidencia "
                    "supere la validación automática."
                ),
            )
        answers = payload.model_dump(mode="json")
        description = _profile_description(evidence, payload)
        await repository.update_evidence(
            evidence_id,
            {"description": description},
        )
        await repository.save_processing_event(
            evidence_id=evidence_id,
            stage="community_profile",
            status="completed",
            title="Información comunitaria completada",
            detail="El usuario respondió el cuestionario estructurado del lugar.",
            metadata={
                "contribution_type": evidence.get("contribution_type"),
                "answers": answers,
                "generated_description": description,
            },
        )
        return {
            "evidence_id": evidence_id,
            "contribution_type": evidence.get("contribution_type") or "new_place",
            "description": description,
            "answers": answers,
        }
    except HTTPException:
        raise
    except (ConfigurationError, ExternalServiceError, ResourceNotFoundError) as exc:
        raise _handle_service_error(exc) from exc


@router.post("/{evidence_id}/process", response_model=ProcessResponse, status_code=202)
async def process_evidence(
    evidence_id: UUID,
    background_tasks: BackgroundTasks,
    user: CurrentUser,
    settings: SettingsDep,
) -> ProcessResponse:
    repository = SupabaseRepository(settings)
    try:
        evidence = await repository.get_evidence(evidence_id, user.id)
        if evidence["status"] in {"processing_ai", "processing_gis"}:
            raise HTTPException(status_code=409, detail="La evidencia ya se esta procesando")
        job = await repository.create_job(evidence_id)
        await repository.save_processing_event(
            evidence_id=evidence_id,
            stage="queued",
            status="pending",
            title="Validacion en cola",
            detail="El procesamiento se ejecutara en segundo plano.",
        )
    except HTTPException:
        raise
    except (ConfigurationError, ExternalServiceError, ResourceNotFoundError) as exc:
        raise _handle_service_error(exc) from exc

    if settings.process_jobs_inline:
        background_tasks.add_task(
            ValidationWorkflow(settings).process,
            evidence_id,
            UUID(job["id"]),
        )
    return ProcessResponse(
        evidence_id=evidence_id,
        job_id=UUID(job["id"]),
        status="pending",
    )

