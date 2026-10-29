from dataclasses import dataclass
from uuid import UUID

import httpx

from app.core.config import Settings
from app.core.errors import ConfigurationError, ExternalServiceError


@dataclass(frozen=True)
class AuthenticatedUser:
    id: UUID
    email: str | None
    metadata: dict
    app_metadata: dict

    @property
    def is_admin(self) -> bool:
        return self.app_metadata.get("role") == "admin"


class SupabaseAuthService:
    def __init__(self, settings: Settings):
        self._settings = settings

    async def get_user(self, token: str) -> AuthenticatedUser:
        if not self._settings.supabase_url or not self._settings.supabase_publishable_key:
            raise ConfigurationError("Supabase Auth no esta configurado")

        url = f"{self._settings.supabase_url.rstrip('/')}/auth/v1/user"
        headers = {
            "apikey": self._settings.supabase_publishable_key,
            "Authorization": f"Bearer {token}",
        }
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(url, headers=headers)

        if response.status_code in {401, 403}:
            raise PermissionError("Token invalido o expirado")
        if response.is_error:
            raise ExternalServiceError(f"Supabase Auth respondio {response.status_code}")

        payload = response.json()
        return AuthenticatedUser(
            id=UUID(payload["id"]),
            email=payload.get("email"),
            metadata=payload.get("user_metadata") or {},
            app_metadata=payload.get("app_metadata") or {},
        )

