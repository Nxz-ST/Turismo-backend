from pydantic import BaseModel, Field, field_validator


ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024


class PresignedUploadRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=180)
    content_type: str
    size_bytes: int = Field(gt=0, le=MAX_IMAGE_BYTES)

    @field_validator("content_type")
    @classmethod
    def validate_content_type(cls, value: str) -> str:
        normalized = value.lower().strip()
        if normalized not in ALLOWED_IMAGE_TYPES:
            raise ValueError("Solo se permiten imagenes JPEG, PNG o WebP")
        return normalized


class PresignedUploadResponse(BaseModel):
    upload_url: str
    object_key: str
    expires_in: int
    required_headers: dict[str, str]

