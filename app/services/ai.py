from typing import Any

import httpx

from app.core.config import Settings
from app.core.errors import ConfigurationError, ExternalServiceError


class ExistingAiService:
    """Adaptador del /predict existente; el servicio de IA no se modifica."""

    def __init__(self, settings: Settings):
        self._settings = settings

    async def predict(
        self,
        *,
        image_url: str,
        filename: str,
        content_type: str,
        latitude: float,
        longitude: float,
        altitude: float,
    ) -> dict[str, Any]:
        if not self._settings.ai_service_base_url:
            raise ConfigurationError("El Motor de IA no esta configurado")

        timeout = httpx.Timeout(self._settings.ai_service_timeout_seconds)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                image_response = await client.get(image_url)
                if image_response.is_error:
                    raise ExternalServiceError("No se pudo descargar la evidencia desde R2")

                response = await client.post(
                    f"{self._settings.ai_service_base_url.rstrip('/')}/predict",
                    files={"file": (filename, image_response.content, content_type)},
                    data={
                        "lat": str(latitude),
                        "lon": str(longitude),
                        "alt": str(altitude),
                    },
                )
        except httpx.TimeoutException as exc:
            raise ExternalServiceError(
                "El Motor de IA excedio el tiempo maximo de procesamiento"
            ) from exc
        except httpx.HTTPError as exc:
            raise ExternalServiceError(
                f"No se pudo comunicar con el Motor de IA: {type(exc).__name__}"
            ) from exc

        if response.is_error:
            raise ExternalServiceError(
                f"Motor de IA respondio {response.status_code}: {response.text[:300]}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise ExternalServiceError("El Motor de IA devolvio una respuesta no JSON") from exc

