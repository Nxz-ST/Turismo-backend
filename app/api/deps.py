import logging
import time
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status

from app.core.config import Settings, get_settings
from app.core.errors import ConfigurationError, ExternalServiceError
from app.domain.suspension import is_active, suspended_detail
from app.services.auth import AuthenticatedUser, SupabaseAuthService
from app.services.supabase import SupabaseRepository

logger = logging.getLogger(__name__)

# Evita consultar la tabla de bloqueos en cada petición del mismo usuario.
_SUSPENSION_TTL_SECONDS = 60.0
_suspension_cache: dict[UUID, tuple[float, dict[str, Any] | None]] = {}


def clear_suspension_cache(user_id: UUID | None = None) -> None:
    if user_id is None:
        _suspension_cache.clear()
    else:
        _suspension_cache.pop(user_id, None)


async def _active_suspension(settings: Settings, user_id: UUID) -> dict[str, Any] | None:
    cached = _suspension_cache.get(user_id)
    if cached and cached[0] > time.monotonic():
        row = cached[1]
    else:
        try:
            row = await SupabaseRepository(settings).get_account_suspension(user_id)
        except (ConfigurationError, ExternalServiceError) as exc:
            # Si la tabla aún no existe o Supabase falla, no se bloquea a nadie.
            logger.warning("No se pudo consultar el bloqueo de %s: %s", user_id, exc)
            return None
        _suspension_cache[user_id] = (time.monotonic() + _SUSPENSION_TTL_SECONDS, row)
    return row if is_active(row) else None


SettingsDep = Annotated[Settings, Depends(get_settings)]


async def current_user(
    settings: SettingsDep,
    authorization: Annotated[str | None, Header()] = None,
) -> AuthenticatedUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Se requiere un token Bearer",
        )
    token = authorization.split(" ", 1)[1].strip()
    try:
        user = await SupabaseAuthService(settings).get_user(token)
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except (ConfigurationError, ExternalServiceError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not user.is_admin:
        suspension = await _active_suspension(settings, user.id)
        if suspension:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=suspended_detail(suspension),
            )
    return user


CurrentUser = Annotated[AuthenticatedUser, Depends(current_user)]


async def admin_user(user: CurrentUser) -> AuthenticatedUser:
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requiere el rol de administrador",
        )
    return user


AdminUser = Annotated[AuthenticatedUser, Depends(admin_user)]

