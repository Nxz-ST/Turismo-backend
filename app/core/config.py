from functools import lru_cache
from typing import Annotated

from pydantic import BeforeValidator, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _split_csv(value: object) -> object:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


CsvList = Annotated[list[str], BeforeValidator(_split_csv)]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: str = "development"
    app_name: str = "RutaAmiga API"
    api_v1_prefix: str = "/api/v1"
    allowed_origins: CsvList = Field(default_factory=lambda: ["http://localhost:3000"])
    max_request_bytes: int = 2_000_000

    supabase_url: str = ""
    supabase_publishable_key: str = ""
    supabase_service_role_key: str = ""

    r2_endpoint_url: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket: str = "ruta-amiga-evidencias"
    r2_presigned_url_ttl_seconds: int = 900

    ai_service_base_url: str = ""
    ai_service_timeout_seconds: int = 180
    google_maps_api_key: str = ""

    process_jobs_inline: bool = True
    sentinel_enabled: bool = False
    sentinel_client_id: str = ""
    sentinel_client_secret: str = ""
    sentinel_lookback_days: int = 180
    sentinel_buffer_m: int = 120
    perusat_enabled: bool = False

    decision_rule_version: str = "multimodal-v1"
    candidate_score_threshold: float = 0.75
    minimum_evidence_coverage: float = 0.70

    @model_validator(mode="after")
    def validate_production_configuration(self) -> "Settings":
        if self.app_env.lower() != "production":
            return self
        required = {
            "SUPABASE_URL": self.supabase_url,
            "SUPABASE_PUBLISHABLE_KEY": self.supabase_publishable_key,
            "SUPABASE_SERVICE_ROLE_KEY": self.supabase_service_role_key,
            "R2_ENDPOINT_URL": self.r2_endpoint_url,
            "R2_ACCESS_KEY_ID": self.r2_access_key_id,
            "R2_SECRET_ACCESS_KEY": self.r2_secret_access_key,
            "GOOGLE_MAPS_API_KEY": self.google_maps_api_key,
        }
        missing = [name for name, value in required.items() if not value.strip()]
        if missing:
            raise ValueError(
                "Faltan secretos obligatorios de producción: " + ", ".join(missing)
            )
        if "*" in self.allowed_origins:
            raise ValueError("ALLOWED_ORIGINS no puede contener * en producción")
        if self.sentinel_enabled and (
            not self.sentinel_client_id or not self.sentinel_client_secret
        ):
            raise ValueError("Sentinel está activo pero sus credenciales están incompletas")
        return self

    @property
    def supabase_rest_url(self) -> str:
        return f"{self.supabase_url.rstrip('/')}/rest/v1"


@lru_cache
def get_settings() -> Settings:
    return Settings()

