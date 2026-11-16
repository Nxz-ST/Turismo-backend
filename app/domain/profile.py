from datetime import UTC, datetime
from typing import Any


PROFILE_FIELDS = (
    "traveler_type",
    "origin_region",
    "origin_country",
    "age_range",
    "interests",
    "hiking_experience",
    "referral_source",
)


def build_profile_row(
    update: dict[str, Any],
    current: dict[str, Any] | None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Combina la actualización con el perfil actual y fecha el consentimiento.

    Las fechas de aceptación las pone el servidor, nunca el cliente. Un cambio
    de versión de términos o del consentimiento de investigación renueva su
    fecha; reenviar el mismo valor la conserva.
    """
    current = current or {}
    moment = (now or datetime.now(UTC)).isoformat()
    # Solo se tocan los campos enviados: aceptar los términos no borra el
    # perfil y editar el perfil no altera el consentimiento.
    row: dict[str, Any] = {
        field: update[field] for field in PROFILE_FIELDS if field in update
    }
    if "interests" in row:
        row["interests"] = list(row["interests"] or [])
    if row.get("traveler_type") == "foreign":
        row["origin_region"] = None
    elif row.get("traveler_type") in {"local", "national"}:
        row["origin_country"] = "Perú"

    version = update.get("accept_terms_version")
    if version and version != current.get("terms_version"):
        row["terms_version"] = version
        row["terms_accepted_at"] = moment

    research = update.get("research_consent")
    if research is not None and bool(research) != bool(current.get("research_consent")):
        row["research_consent"] = bool(research)
        row["research_consent_at"] = moment

    if update.get("complete_onboarding") and not current.get("onboarding_completed_at"):
        row["onboarding_completed_at"] = moment

    row["updated_at"] = moment
    return row
