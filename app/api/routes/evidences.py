import math
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status

from app.api.deps import CurrentUser, SettingsDep
from app.core.errors import ConfigurationError, ExternalServiceError, ResourceNotFoundError
from app.schemas.evidence import EvidenceCreate, EvidenceResponse, ProcessResponse
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
            if payload.target_place_id is None:
                raise HTTPException(
                    status_code=422,
                    detail="Selecciona el lugar existente al que pertenece la evidencia",
                )
            place = await repository.get_tourist_place(payload.target_place_id)
            place_latitude = float(place["latitud"])
            place_longitude = float(place["longitud"])
            data["target_place_snapshot"] = {
                "id": place.get("id"),
                "codigo": place.get("codigo"),
                "nombre": place.get("nombre"),
                "categoria": place.get("categoria_texto"),
                "departamento": place.get("departamento"),
                "provincia": place.get("provincia"),
                "distrito": place.get("distrito"),
                "latitud": place_latitude,
                "longitud": place_longitude,
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
        elif payload.target_place_id is not None:
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
        for row in rows:
            object_key = row.pop("object_key", None)
            if object_key:
                row["foto_url"] = storage.create_download_url(object_key, expires_in=900)
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

