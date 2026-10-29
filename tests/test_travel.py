from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.api.routes.travel import get_travel_state, save_travel_state
from app.core.config import Settings
from app.schemas.travel import TravelStateUpdate
from app.services.auth import AuthenticatedUser
from app.services.supabase import SupabaseRepository


def _user() -> AuthenticatedUser:
    return AuthenticatedUser(
        id=uuid4(),
        email="traveler@example.com",
        metadata={},
        app_metadata={"role": "user"},
    )


def test_travel_state_rejects_invalid_version() -> None:
    with pytest.raises(ValidationError):
        TravelStateUpdate(version=0)


def test_travel_state_limits_favorites() -> None:
    with pytest.raises(ValidationError):
        TravelStateUpdate(favorites=[{"id": index} for index in range(501)])


def test_travel_state_limits_saved_routes() -> None:
    with pytest.raises(ValidationError):
        TravelStateUpdate(saved_routes=[{"id": index} for index in range(51)])


@pytest.mark.asyncio
async def test_empty_remote_state_has_safe_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    async def empty_state(self: SupabaseRepository, user_id: object) -> None:
        return None

    monkeypatch.setattr(SupabaseRepository, "get_travel_state", empty_state)
    result = await get_travel_state(_user(), Settings(_env_file=None))

    assert result["favorites"] == []
    assert result["trip"] == []
    assert result["reviews"] == {}


@pytest.mark.asyncio
async def test_save_state_is_scoped_to_authenticated_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def save_state(
        self: SupabaseRepository,
        user_id: object,
        data: dict,
    ) -> dict:
        captured["user_id"] = user_id
        captured["data"] = data
        return {**data, "updated_at": None}

    monkeypatch.setattr(SupabaseRepository, "upsert_travel_state", save_state)
    user = _user()
    payload = TravelStateUpdate(
        favorites=[{"id": "playa-tuquillo"}],
        trip=[{"id": "playa-tuquillo"}],
        reviews={"playa-tuquillo": [{"rating": 5}]},
    )

    result = await save_travel_state(payload, user, Settings(_env_file=None))

    assert captured["user_id"] == user.id
    assert result["favorites"][0]["id"] == "playa-tuquillo"
