from uuid import uuid4

from app.services.auth import AuthenticatedUser


def test_admin_role_comes_from_protected_app_metadata() -> None:
    user = AuthenticatedUser(
        id=uuid4(),
        email="admin@example.com",
        metadata={"role": "user"},
        app_metadata={"role": "admin"},
    )
    assert user.is_admin is True


def test_user_metadata_cannot_grant_admin_access() -> None:
    user = AuthenticatedUser(
        id=uuid4(),
        email="user@example.com",
        metadata={"role": "admin"},
        app_metadata={"role": "user"},
    )
    assert user.is_admin is False
