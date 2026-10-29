from fastapi import APIRouter, HTTPException

from app.api.deps import CurrentUser, SettingsDep
from app.core.errors import ConfigurationError
from app.schemas.upload import PresignedUploadRequest, PresignedUploadResponse
from app.services.storage import R2StorageService


router = APIRouter()


@router.post("/presign", response_model=PresignedUploadResponse)
async def presign_upload(
    payload: PresignedUploadRequest,
    user: CurrentUser,
    settings: SettingsDep,
) -> PresignedUploadResponse:
    storage = R2StorageService(settings)
    object_key = storage.build_object_key(user.id, payload.filename, payload.content_type)
    try:
        upload_url = storage.create_upload_url(object_key, payload.content_type)
    except ConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return PresignedUploadResponse(
        upload_url=upload_url,
        object_key=object_key,
        expires_in=settings.r2_presigned_url_ttl_seconds,
        required_headers={"Content-Type": payload.content_type},
    )

