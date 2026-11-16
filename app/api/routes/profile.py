from fastapi import APIRouter, HTTPException

from app.api.deps import CurrentUser, SettingsDep
from app.core.errors import ConfigurationError, ExternalServiceError
from app.domain.profile import build_profile_row
from app.schemas.profile import UserProfileResponse, UserProfileUpdate
from app.services.supabase import SupabaseRepository


router = APIRouter()


@router.get("", response_model=UserProfileResponse)
async def get_profile(user: CurrentUser, settings: SettingsDep) -> dict:
    try:
        row = await SupabaseRepository(settings).get_user_profile(user.id)
        return {**row, "exists": True} if row else {"exists": False}
    except ConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ExternalServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.put("", response_model=UserProfileResponse)
async def save_profile(
    payload: UserProfileUpdate,
    user: CurrentUser,
    settings: SettingsDep,
) -> dict:
    try:
        repository = SupabaseRepository(settings)
        current = await repository.get_user_profile(user.id)
        row = build_profile_row(
            payload.model_dump(mode="json", exclude_unset=True), current
        )
        saved = await repository.upsert_user_profile(user_id=user.id, data=row)
        return {**saved, "exists": True}
    except ConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ExternalServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
