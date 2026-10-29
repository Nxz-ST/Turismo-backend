from fastapi import APIRouter, HTTPException, Query

from app.api.deps import CurrentUser
from app.core.errors import ExternalServiceError
from app.services.weather import WeatherService


router = APIRouter()


@router.get("/forecast")
async def forecast(
    _: CurrentUser,
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(ge=-180, le=180),
) -> dict:
    try:
        return await WeatherService().forecast(
            latitude=latitude, longitude=longitude
        )
    except ExternalServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
