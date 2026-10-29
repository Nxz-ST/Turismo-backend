from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from app.core.config import Settings, get_settings
from app.core.errors import ConfigurationError, ExternalServiceError
from app.services.auth import AuthenticatedUser, SupabaseAuthService


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
        return await SupabaseAuthService(settings).get_user(token)
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except (ConfigurationError, ExternalServiceError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


CurrentUser = Annotated[AuthenticatedUser, Depends(current_user)]


async def admin_user(user: CurrentUser) -> AuthenticatedUser:
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requiere el rol de administrador",
        )
    return user


AdminUser = Annotated[AuthenticatedUser, Depends(admin_user)]

