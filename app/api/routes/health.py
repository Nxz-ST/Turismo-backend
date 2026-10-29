from fastapi import APIRouter

from app.core.config import get_settings
from app.schemas.common import HealthResponse


router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(status="ok", service=settings.app_name, version="0.1.0")

