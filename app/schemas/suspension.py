from pydantic import BaseModel, Field, field_validator


class SuspensionRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=300)
    # Nulo = bloqueo definitivo.
    days: int | None = Field(default=None, ge=1, le=365)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("Escribe el motivo del bloqueo")
        return value
