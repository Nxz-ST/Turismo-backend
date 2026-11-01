from app.api.routes.evidences import _profile_description
from app.schemas.evidence import EvidenceProfileAnswers


def test_profile_description_uses_only_controlled_answers() -> None:
    description = _profile_description(
        {"name": "Laguna de prueba"},
        EvidenceProfileAnswers(
            access_type="walking",
            cost_type="free",
            access_difficulty="moderate",
            place_state="open",
            activities=["photography", "nature"],
            services=["parking"],
            risks=["low_signal"],
        ),
    )

    assert "Laguna de prueba" in description
    assert "a pie" in description
    assert "fotografía" in description
    assert "baja cobertura móvil" in description
    assert "sujetos a confirmación" in description
