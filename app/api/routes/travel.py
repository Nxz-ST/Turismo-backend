from fastapi import APIRouter, HTTPException

from app.api.deps import CurrentUser, SettingsDep
from app.core.errors import ConfigurationError, ExternalServiceError
from app.schemas.travel import TravelStateResponse, TravelStateUpdate
from app.services.supabase import SupabaseRepository


router = APIRouter()


@router.get("/state", response_model=TravelStateResponse)
async def get_travel_state(user: CurrentUser, settings: SettingsDep) -> dict:
    try:
        row = await SupabaseRepository(settings).get_travel_state(user.id)
        return row or {
            "favorites": [],
            "trip": [],
            "reviews": {},
            "saved_routes": [],
            "version": 1,
            "updated_at": None,
        }
    except ConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ExternalServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.put("/state", response_model=TravelStateResponse)
async def save_travel_state(
    payload: TravelStateUpdate,
    user: CurrentUser,
    settings: SettingsDep,
) -> dict:
    try:
        return await SupabaseRepository(settings).upsert_travel_state(
            user_id=user.id,
            data=payload.model_dump(mode="json"),
        )
    except ConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ExternalServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

