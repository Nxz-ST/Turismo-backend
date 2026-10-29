import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_production_rejects_missing_secrets() -> None:
    with pytest.raises(ValidationError):
        Settings(app_env="production", _env_file=None)


def test_production_rejects_wildcard_cors() -> None:
    with pytest.raises(ValidationError):
        Settings(
            app_env="production",
            allowed_origins=["*"],
            supabase_url="https://example.supabase.co",
            supabase_publishable_key="publishable",
            supabase_service_role_key="service",
            r2_endpoint_url="https://r2.example.com",
            r2_access_key_id="key",
            r2_secret_access_key="secret",
            google_maps_api_key="google",
            _env_file=None,
        )
