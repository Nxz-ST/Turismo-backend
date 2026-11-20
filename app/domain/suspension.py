"""Reglas del bloqueo de cuentas (Términos y condiciones, sección 4)."""

from datetime import UTC, datetime, timedelta
from typing import Any

SUSPENDED_CODE = "account_suspended"


def _parse(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def is_active(row: dict[str, Any] | None, now: datetime | None = None) -> bool:
    """Un bloqueo sigue vigente si no tiene fecha de fin o aún no llega."""
    if not row:
        return False
    until = _parse(row.get("suspended_until"))
    return until is None or until > (now or datetime.now(UTC))


def suspension_until(days: int | None, now: datetime | None = None) -> datetime | None:
    if days is None:
        return None
    return (now or datetime.now(UTC)) + timedelta(days=days)


def suspended_detail(row: dict[str, Any]) -> dict[str, Any]:
    """Cuerpo del 403 que la app usa para mostrar la pantalla de bloqueo."""
    until = _parse(row.get("suspended_until"))
    return {
        "code": SUSPENDED_CODE,
        "message": "Tu cuenta está bloqueada por incumplir los Términos y condiciones.",
        "reason": row.get("reason"),
        "suspended_until": until.isoformat() if until else None,
    }
