from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import CurrentUser, SettingsDep
from app.core.errors import ConfigurationError, ExternalServiceError
from app.schemas.presence import PresenceSampleBatch, PresenceSampleResponse
from app.services.supabase import SupabaseRepository


router = APIRouter()


def _service_error(exc: Exception) -> HTTPException:
    code = 503 if isinstance(exc, ConfigurationError) else 502
    return HTTPException(status_code=code, detail=str(exc))


def _with_expiry(row: dict) -> dict:
    recorded = datetime.fromisoformat(str(row["recorded_at"]).replace("Z", "+00:00"))
    expires = recorded.astimezone(UTC) + timedelta(hours=24)
    return {
        **row,
        "expires_at": expires,
        "remaining_seconds": max(0, int((expires - datetime.now(UTC)).total_seconds())),
    }


@router.post("/samples", response_model=list[PresenceSampleResponse], status_code=status.HTTP_201_CREATED)
async def save_samples(
    payload: PresenceSampleBatch,
    user: CurrentUser,
    settings: SettingsDep,
) -> list[dict]:
    now = datetime.now(UTC)
    for sample in payload.samples:
        recorded = sample.recorded_at
        if recorded.tzinfo is None:
            recorded = recorded.replace(tzinfo=UTC)
        if recorded > now + timedelta(minutes=5):
            raise HTTPException(status_code=422, detail="La muestra GPS tiene una fecha futura")
        if recorded < now - timedelta(hours=72):
            raise HTTPException(status_code=422, detail="La muestra GPS es demasiado antigua")
    try:
        repository = SupabaseRepository(settings)
        rows = await repository.save_presence_samples(
            user_id=user.id,
            samples=[sample.model_dump(mode="json") for sample in payload.samples],
        )
        await repository.delete_expired_presence_samples(user.id, retention_hours=72)
        return [_with_expiry(row) for row in rows]
    except (ConfigurationError, ExternalServiceError) as exc:
        raise _service_error(exc) from exc


@router.get("/recent", response_model=list[PresenceSampleResponse])
async def recent_samples(
    user: CurrentUser,
    settings: SettingsDep,
    limit: int = Query(default=30, ge=1, le=100),
) -> list[dict]:
    try:
        rows = await SupabaseRepository(settings).list_recent_presence_samples(
            user.id, hours=24, limit=limit
        )
        return [_with_expiry(row) for row in rows]
    except (ConfigurationError, ExternalServiceError) as exc:
        raise _service_error(exc) from exc
