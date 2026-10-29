import pytest

from app.domain.decision import (
    EvidenceStatus,
    build_multimodal_decision,
    decide_from_existing_model,
)


@pytest.mark.parametrize(
    ("model_state", "expected"),
    [
        ("POSIBLE_NUEVO_ATRACTIVO", EvidenceStatus.CANDIDATE),
        ("POSIBLE_NUEVO_LUGAR", EvidenceStatus.CANDIDATE),
        ("LUGAR_REGISTRADO", EvidenceStatus.DUPLICATE),
        ("CASO_DUDOSO", EvidenceStatus.NEEDS_REVIEW),
        ("IMAGEN_NO_VALIDA", EvidenceStatus.REJECTED),
        ("NO_TURISTICO", EvidenceStatus.REJECTED),
    ],
)
def test_existing_model_states_are_preserved(model_state: str, expected: EvidenceStatus) -> None:
    decision = decide_from_existing_model(
        {
            "estado": model_state,
            "clase_final_gis": "montaña",
            "confianza_modelo": 86,
            "score_total": 0.81,
            "motivo_decision": "Prueba",
        }
    )
    assert decision.status == expected
    assert decision.category == "montana"
    assert decision.confidence == pytest.approx(0.86)
    assert decision.score == pytest.approx(0.81)


def test_unknown_model_state_requires_review() -> None:
    decision = decide_from_existing_model({"estado": "NUEVO_ESTADO"})
    assert decision.status == EvidenceStatus.NEEDS_REVIEW


def test_confidence_is_clamped() -> None:
    decision = decide_from_existing_model(
        {"estado": "CASO_DUDOSO", "confianza_modelo": 120, "score_total": -10}
    )
    assert decision.confidence == 1
    assert decision.score == 0


def test_multimodal_candidate_requires_score_and_coverage() -> None:
    model = decide_from_existing_model(
        {
            "estado": "POSIBLE_NUEVO_ATRACTIVO",
            "clasificacion_modelo": "bosque",
            "confianza_modelo": 92,
        }
    )
    decision = build_multimodal_decision(
        model=model,
        evidence={
            "latitude": -12.0,
            "longitude": -77.0,
            "gps_accuracy_m": 8,
            "capture_source": "camera",
            "captured_at": "2099-01-01T00:00:00Z",
            "content_hash": "abc",
            "presence_status": "confirmed",
        },
        geospatial={
            "coherence": {
                "score": 0.85,
                "coverage": 1.0,
                "has_contradiction": False,
                "explanation": "Coherente",
            }
        },
        duplicate_result={"status": "no_match"},
    )
    assert decision.status == EvidenceStatus.CANDIDATE
    assert decision.score >= 0.75
    assert decision.coverage == pytest.approx(1.0)


def test_sentinel_contradiction_never_auto_rejects() -> None:
    model = decide_from_existing_model(
        {
            "clasificacion_modelo": "lago",
            "confianza_modelo": 95,
        }
    )
    decision = build_multimodal_decision(
        model=model,
        evidence={
            "latitude": -12.0,
            "longitude": -77.0,
            "gps_accuracy_m": 5,
            "capture_source": "camera",
            "captured_at": "2099-01-01T00:00:00Z",
            "content_hash": "abc",
        },
        geospatial={
            "coherence": {
                "score": 0.25,
                "coverage": 1.0,
                "has_contradiction": True,
                "explanation": "Contradicción",
            }
        },
        duplicate_result={"status": "no_match"},
    )
    assert decision.status == EvidenceStatus.NEEDS_REVIEW
    assert decision.status != EvidenceStatus.REJECTED


def test_duplicate_is_separate_from_plausibility_score() -> None:
    model = decide_from_existing_model(
        {
            "estado": "POSIBLE_NUEVO_ATRACTIVO",
            "clasificacion_modelo": "playa",
            "confianza_modelo": 90,
        }
    )
    decision = build_multimodal_decision(
        model=model,
        evidence={"latitude": -12.0, "longitude": -77.0},
        geospatial={
            "coherence": {
                "score": 0.85,
                "coverage": 1.0,
                "has_contradiction": False,
            }
        },
        duplicate_result={"status": "high_match"},
    )
    assert decision.status == EvidenceStatus.DUPLICATE
    assert decision.score > 0


def test_existing_place_contribution_is_not_rejected_as_duplicate() -> None:
    model = decide_from_existing_model(
        {
            "estado": "POSIBLE_NUEVO_ATRACTIVO",
            "clasificacion_modelo": "playa",
            "confianza_modelo": 90,
        }
    )
    decision = build_multimodal_decision(
        model=model,
        evidence={
            "latitude": -10.0,
            "longitude": -78.1,
            "contribution_type": "existing_place",
            "target_place_id": 42,
        },
        geospatial={
            "coherence": {
                "score": 0.9,
                "coverage": 1.0,
                "has_contradiction": False,
            }
        },
        duplicate_result={"status": "high_match"},
        candidate_threshold=0.5,
        minimum_coverage=0.5,
    )
    assert decision.status == EvidenceStatus.CANDIDATE


def test_invalid_model_result_is_rejected_even_with_strong_signals() -> None:
    model = decide_from_existing_model(
        {
            "estado": "IMAGEN_NO_VALIDA",
            "clasificacion_modelo": "nevado",
            "confianza_modelo": 99,
        }
    )
    decision = build_multimodal_decision(
        model=model,
        evidence={"latitude": -12.0, "longitude": -77.0},
        geospatial={
            "coherence": {
                "score": 0.9,
                "coverage": 1.0,
                "has_contradiction": False,
            }
        },
        duplicate_result={"status": "no_match"},
    )
    assert decision.status == EvidenceStatus.REJECTED
    assert decision.category is None
    assert decision.confidence == 0
    assert decision.score == 0


def test_doubtful_model_result_requires_review() -> None:
    model = decide_from_existing_model(
        {
            "estado": "CASO_DUDOSO",
            "clasificacion_modelo": "bosque",
            "confianza_modelo": 95,
        }
    )
    decision = build_multimodal_decision(
        model=model,
        evidence={"latitude": -12.0, "longitude": -77.0},
        geospatial={"coherence": {"score": 0.9, "coverage": 1.0}},
        duplicate_result={"status": "no_match"},
    )
    assert decision.status == EvidenceStatus.NEEDS_REVIEW
    assert decision.category is None
    assert decision.confidence == 0


def test_doubtful_conflicting_category_is_kept_only_in_raw_model_result() -> None:
    raw_result = {
        "estado": "CASO_DUDOSO",
        "clasificacion_modelo": "lago",
        "confianza_modelo": 99.7,
        "fusion": {
            "clase_final": "lago",
            "conflicto_gemma": True,
            "senales": ["lago", "lago", "bosque"],
        },
        "gemma": {
            "clase": "bosque",
            "validacion": "TURISTICO",
            "tipo_contenido": "captura_directa",
        },
    }
    model = decide_from_existing_model(raw_result)
    decision = build_multimodal_decision(
        model=model,
        evidence={"latitude": -11.989, "longitude": -76.836},
        geospatial={
            "coherence": {
                "score": 0.25,
                "coverage": 0.5,
                "has_contradiction": True,
            }
        },
        duplicate_result={"status": "no_match"},
    )

    assert model.category == "lago"
    assert decision.status == EvidenceStatus.NEEDS_REVIEW
    assert decision.category is None
    assert decision.confidence == 0


def test_low_visual_confidence_requires_review() -> None:
    model = decide_from_existing_model(
        {
            "estado": "POSIBLE_NUEVO_ATRACTIVO",
            "clasificacion_modelo": "nevado",
            "confianza_modelo": 54,
        }
    )
    decision = build_multimodal_decision(
        model=model,
        evidence={"latitude": -12.0, "longitude": -77.0},
        geospatial={"coherence": {"score": 0.9, "coverage": 1.0}},
        duplicate_result={"status": "no_match"},
    )
    assert decision.status == EvidenceStatus.NEEDS_REVIEW

