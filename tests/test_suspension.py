from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api import deps
from app.core.config import Settings
from app.core.errors import ExternalServiceError
from app.domain.suspension import SUSPENDED_CODE, is_active, suspended_detail, suspension_until
from app.services.auth import AuthenticatedUser

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


def test_permanent_suspension_is_always_active() -> None:
    assert is_active({"reason": "spam", "suspended_until": None}, NOW)


def test_temporary_suspension_expires() -> None:
    future = (NOW + timedelta(days=1)).isoformat()
    past = (NOW - timedelta(seconds=1)).isoformat()
    assert is_active({"suspended_until": future}, NOW)
    assert not is_active({"suspended_until": past}, NOW)
    assert not is_active(None, NOW)


def test_suspension_until_from_days() -> None:
    assert suspension_until(None, NOW) is None
    assert suspension_until(7, NOW) == NOW + timedelta(days=7)


def test_detail_carries_code_and_reason_for_the_app() -> None:
    detail = suspended_detail({"reason": "Contenido sexual", "suspended_until": None})
    assert detail["code"] == SUSPENDED_CODE
    assert detail["reason"] == "Contenido sexual"
    assert detail["suspended_until"] is None


def _user(admin: bool = False) -> AuthenticatedUser:
    return AuthenticatedUser(
        id=uuid4(),
        email="u@example.com",
        metadata={},
        app_metadata={"role": "admin"} if admin else {},
    )


@pytest.fixture
def patch_auth(monkeypatch):
    deps.clear_suspension_cache()

    def install(user: AuthenticatedUser, suspension=None, error: bool = False):
        class FakeAuth:
            def __init__(self, _settings):
                pass

            async def get_user(self, _token):
                return user

        class FakeRepo:
            def __init__(self, _settings):
                pass

            async def get_account_suspension(self, _user_id):
                if error:
                    raise ExternalServiceError("tabla inexistente")
                return suspension

        monkeypatch.setattr(deps, "SupabaseAuthService", FakeAuth)
        monkeypatch.setattr(deps, "SupabaseRepository", FakeRepo)

    yield install
    deps.clear_suspension_cache()


@pytest.mark.asyncio
async def test_suspended_user_gets_403_with_reason(patch_auth) -> None:
    patch_auth(_user(), {"reason": "Desnudos", "suspended_until": None})
    with pytest.raises(HTTPException) as exc:
        await deps.current_user(Settings(), authorization="Bearer t")
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == SUSPENDED_CODE
    assert exc.value.detail["reason"] == "Desnudos"


@pytest.mark.asyncio
async def test_expired_suspension_lets_user_in(patch_auth) -> None:
    user = _user()
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    patch_auth(user, {"reason": "spam", "suspended_until": past})
    assert await deps.current_user(Settings(), authorization="Bearer t") is user


@pytest.mark.asyncio
async def test_lookup_failure_does_not_block(patch_auth) -> None:
    user = _user()
    patch_auth(user, error=True)
    assert await deps.current_user(Settings(), authorization="Bearer t") is user


@pytest.mark.asyncio
async def test_admins_are_never_blocked(patch_auth) -> None:
    admin = _user(admin=True)
    patch_auth(admin, {"reason": "x", "suspended_until": None})
    assert await deps.current_user(Settings(), authorization="Bearer t") is admin
