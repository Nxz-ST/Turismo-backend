import mimetypes
from pathlib import Path
from uuid import UUID, uuid4

import boto3
from botocore.config import Config

from app.core.config import Settings
from app.core.errors import ConfigurationError


class R2StorageService:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._client = None

    def _get_client(self):
        if not all(
            [
                self._settings.r2_endpoint_url,
                self._settings.r2_access_key_id,
                self._settings.r2_secret_access_key,
            ]
        ):
            raise ConfigurationError("Cloudflare R2 no esta configurado")
        if self._client is None:
            self._client = boto3.client(
                "s3",
                endpoint_url=self._settings.r2_endpoint_url,
                aws_access_key_id=self._settings.r2_access_key_id,
                aws_secret_access_key=self._settings.r2_secret_access_key,
                region_name="auto",
                config=Config(signature_version="s3v4"),
            )
        return self._client

    def build_object_key(self, user_id: UUID, filename: str, content_type: str) -> str:
        extension = Path(filename).suffix.lower()
        if not extension:
            extension = mimetypes.guess_extension(content_type) or ".jpg"
        return f"evidences/{user_id}/{uuid4()}{extension}"

    def create_upload_url(self, object_key: str, content_type: str) -> str:
        return self._get_client().generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self._settings.r2_bucket,
                "Key": object_key,
                "ContentType": content_type,
            },
            ExpiresIn=self._settings.r2_presigned_url_ttl_seconds,
        )

    def create_download_url(self, object_key: str, expires_in: int = 300) -> str:
        return self._get_client().generate_presigned_url(
            "get_object",
            Params={"Bucket": self._settings.r2_bucket, "Key": object_key},
            ExpiresIn=expires_in,
        )

