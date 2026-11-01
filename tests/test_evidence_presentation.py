from app.api.routes.evidences import _with_public_community_description


def test_short_public_description_uses_verified_community_fallback() -> None:
    presented = _with_public_community_description(
        {"descripcion": "laguna", "categoria_ia": "lago"}
    )

    assert presented["descripcion_usuario"] == "laguna"
    assert "validado como lago" in presented["descripcion"]


def test_free_text_is_not_published_even_when_it_is_long() -> None:
    description = "Laguna tranquila con acceso por un sendero local."

    presented = _with_public_community_description(
        {"descripcion": description, "categoria_ia": "lago"}
    )

    assert presented["descripcion"] != description
    assert presented["descripcion_usuario"] == description


def test_generated_questionnaire_description_is_preserved() -> None:
    description = (
        "Información comunitaria verificada para Laguna Azul. "
        "El acceso reportado es a pie."
    )

    presented = _with_public_community_description(
        {"descripcion": description, "categoria_ia": "lago"}
    )

    assert presented["descripcion"] == description
    assert "descripcion_usuario" not in presented
