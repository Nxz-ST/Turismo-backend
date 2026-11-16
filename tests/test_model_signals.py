import pytest

from app.domain.model_signals import summarize_model_signals


def test_nevado_case_exposes_real_classifier_confidence_and_gemma_label() -> None:
    # Caso real: Nevado Huaytapallana (CASO_DUDOSO por Gemma = montaña).
    signals = summarize_model_signals(
        {
            "estado": "CASO_DUDOSO",
            "clasificacion_modelo": "nevado",
            "confianza_modelo": "99.99",
            "clase_embeddings": "nevado",
            "similitud_visual": "95.24",
            "motivo_decision": "Gemma y los clasificadores visuales no coinciden.",
            "gemma": {"clase": "montaña", "disponible": True, "descripcion": "Paisaje montañoso nevado"},
            "fusion": {"senales": ["nevado", "nevado", "montana"], "conflicto_gemma": True},
        }
    )

    assert signals is not None
    assert signals["classifier"]["category"] == "nevado"
    assert signals["classifier"]["confidence"] == pytest.approx(0.9999)
    assert signals["embeddings"]["category"] == "nevado"
    assert signals["gemma"]["category"] == "montana"
    assert signals["majority_category"] == "nevado"
    assert signals["agreement"] == 2
    assert signals["gemma_conflict"] is True
    assert signals["state"] == "CASO_DUDOSO"


def test_three_way_disagreement_has_no_majority() -> None:
    # Caso real: Bosque Berlin (volcán / lago / bosque).
    signals = summarize_model_signals(
        {
            "clasificacion_modelo": "volcan",
            "confianza_modelo": 45.56,
            "clase_embeddings": "lago",
            "gemma": {"clase": "bosque"},
        }
    )

    assert signals is not None
    assert signals["majority_category"] is None
    assert signals["agreement"] == 1
    assert signals["classifier"]["confidence"] == pytest.approx(0.4556)


def test_manual_review_rows_without_model_data_return_none() -> None:
    assert summarize_model_signals({"reviewer_id": "x", "reviewed_manually": True}) is None
    assert summarize_model_signals(None) is None


def test_unavailable_gemma_is_not_counted_and_bad_numbers_are_ignored() -> None:
    signals = summarize_model_signals(
        {
            "clasificacion_modelo": "lago",
            "confianza_modelo": "n/a",
            "gemma": {"clase": "bosque", "disponible": False},
        }
    )

    assert signals is not None
    assert signals["gemma"]["category"] is None
    assert signals["classifier"]["confidence"] is None
    assert signals["signals_available"] == 1
