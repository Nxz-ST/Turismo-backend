from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from app.domain.categories import normalize_category


class EvidenceStatus(StrEnum):
    PENDING = "pending"
    PROCESSING_AI = "processing_ai"
    PROCESSING_GIS = "processing_gis"
    CANDIDATE = "candidate"
    NEEDS_REVIEW = "needs_review"
    DUPLICATE = "duplicate"
    REJECTED = "rejected"
    VALIDATED = "validated"
    FAILED = "failed"


@dataclass(frozen=True)
class PreliminaryDecision:
    status: EvidenceStatus
    category: str | None
    confidence: float
    score: float
    reason: str


@dataclass(frozen=True)
class ScoreComponent:
    score: float
    weight: float
    coverage: float
    explanation: str


@dataclass(frozen=True)
class MultimodalDecision:
    status: EvidenceStatus
    category: str | None
    confidence: float
    score: float
    coverage: float
    reason: str
    duplicate_status: str
    rule_version: str
    components: dict[str, dict[str, Any]]
    has_environmental_contradiction: bool

    def as_payload(self) -> dict[str, Any]:
        return asdict(self)


def _ratio(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number / 100 if number > 1 else number))


def decide_from_existing_model(result: dict[str, Any]) -> PreliminaryDecision:
    """Mapea el contrato actual del modelo sin modificarlo ni recalcular su score."""
    model_state = str(result.get("estado") or "CASO_DUDOSO").upper()
    raw_category = (
        result.get("clase_final_gis")
        or result.get("clasificacion_modelo")
        or result.get("mejor_clase_visual")
    )
    category = normalize_category(str(raw_category) if raw_category else None)
    confidence = _ratio(result.get("confianza_modelo") or result.get("confianza"))
    score = _ratio(result.get("score_total"))
    reason = str(result.get("motivo_decision") or "Sin motivo registrado")

    states = {
        "LUGAR_REGISTRADO": EvidenceStatus.DUPLICATE,
        "POSIBLE_NUEVO_ATRACTIVO": EvidenceStatus.CANDIDATE,
        "POSIBLE_NUEVO_LUGAR": EvidenceStatus.CANDIDATE,
        "CASO_DUDOSO": EvidenceStatus.NEEDS_REVIEW,
        "IMAGEN_NO_VALIDA": EvidenceStatus.REJECTED,
        "NO_TURISTICO": EvidenceStatus.REJECTED,
    }

    return PreliminaryDecision(
        status=states.get(model_state, EvidenceStatus.NEEDS_REVIEW),
        category=category.value if category else None,
        confidence=confidence,
        score=score,
        reason=reason,
    )


def build_multimodal_decision(
    *,
    model: PreliminaryDecision,
    evidence: dict[str, Any],
    geospatial: dict[str, Any],
    duplicate_result: dict[str, Any] | None = None,
    candidate_threshold: float = 0.75,
    minimum_coverage: float = 0.70,
    minimum_visual_confidence: float = 0.65,
    rule_version: str = "multimodal-v1",
) -> MultimodalDecision:
    """Combina evidencia sin convertir Sentinel o MINCETUR en rechazo automático."""
    capture = _capture_component(evidence)
    visual_is_conclusive = model.status not in {
        EvidenceStatus.REJECTED,
        EvidenceStatus.NEEDS_REVIEW,
    }
    visual_available = (
        visual_is_conclusive and model.category is not None and model.confidence > 0
    )
    visual = ScoreComponent(
        score=model.confidence if visual_available else 0.0,
        weight=0.45,
        coverage=1.0 if visual_available else 0.0,
        explanation=(
            f"Modelo visual: {model.category} con {model.confidence:.0%} de confianza."
            if visual_available
            else (
                "La clasificación visual fue descartada porque el motor marcó "
                "la imagen como inválida o no concluyente."
                if model.category is not None
                else "El modelo visual no produjo una categoría utilizable."
            )
        ),
    )
    coherence = geospatial.get("coherence") or {}
    geo_score = coherence.get("score")
    geo_coverage = _ratio(coherence.get("coverage"))
    geographic = ScoreComponent(
        score=_ratio(geo_score) if geo_score is not None else 0.0,
        weight=0.35,
        coverage=geo_coverage,
        explanation=str(
            coherence.get("explanation")
            or "No se obtuvieron señales ambientales concluyentes."
        ),
    )
    components = {
        "visual": visual,
        "capture": capture,
        "geospatial": geographic,
    }
    available_weight = sum(
        component.weight * component.coverage for component in components.values()
    )
    weighted_value = sum(
        component.score * component.weight * component.coverage
        for component in components.values()
    )
    score = weighted_value / available_weight if available_weight else 0.0
    coverage = min(1.0, available_weight)

    duplicate = duplicate_result or {}
    duplicate_status = str(duplicate.get("status") or "not_evaluated")
    contradiction = bool(coherence.get("has_contradiction"))
    is_existing_place = (
        evidence.get("contribution_type") == "existing_place"
        and evidence.get("target_place_id") is not None
    )

    if model.status == EvidenceStatus.REJECTED:
        status = EvidenceStatus.REJECTED
        outcome = "El motor visual marcó la imagen como no turística o no válida."
    elif model.status == EvidenceStatus.NEEDS_REVIEW:
        status = EvidenceStatus.NEEDS_REVIEW
        outcome = "El motor visual consideró la imagen ambigua; se requiere revisión humana."
    elif model.confidence < minimum_visual_confidence:
        status = EvidenceStatus.NEEDS_REVIEW
        outcome = (
            "La confianza visual está por debajo del umbral requerido; "
            "se necesita revisión humana."
        )
    elif duplicate_status == "high_match" and not is_existing_place:
        status = EvidenceStatus.DUPLICATE
        outcome = "Se detectó una coincidencia geográfica alta; requiere verificación de duplicidad."
    elif contradiction:
        status = EvidenceStatus.NEEDS_REVIEW
        outcome = "Hay una contradicción ambiental y el caso se deriva a revisión humana."
    elif score >= candidate_threshold and coverage >= minimum_coverage:
        status = EvidenceStatus.CANDIDATE
        outcome = (
            "La evidencia es apta para complementar el lugar existente."
            if is_existing_place
            else "La evidencia alcanza el umbral heurístico para candidato fuerte."
        )
    elif coverage < minimum_coverage:
        status = EvidenceStatus.NEEDS_REVIEW
        outcome = "La cobertura de fuentes es insuficiente; se requiere revisión o evidencia adicional."
    else:
        status = EvidenceStatus.NEEDS_REVIEW
        outcome = "El puntaje preliminar requiere revisión humana."

    reason = (
        f"{outcome} Plausibilidad {score:.0%}; cobertura {coverage:.0%}. "
        "Sentinel actúa solo como confirmación de coherencia."
    )

    # Una categoría conflictiva o inválida solo permanece en raw_result para
    # auditoría. No debe publicarse en la evidencia como si fuera una predicción
    # confiable (por ejemplo, mostrar "lago" en un CASO_DUDOSO).
    published_category = model.category
    published_confidence = model.confidence
    published_score = round(score, 4)
    if model.status in {EvidenceStatus.REJECTED, EvidenceStatus.NEEDS_REVIEW}:
        published_category = None
        published_confidence = 0.0
    if model.status == EvidenceStatus.REJECTED:
        published_score = 0.0

    return MultimodalDecision(
        status=status,
        category=published_category,
        confidence=published_confidence,
        score=published_score,
        coverage=round(coverage, 4),
        reason=reason,
        duplicate_status=duplicate_status,
        rule_version=rule_version,
        components={name: asdict(value) for name, value in components.items()},
        has_environmental_contradiction=contradiction,
    )


def _capture_component(evidence: dict[str, Any]) -> ScoreComponent:
    score = 0.15  # coordenadas ya validadas por el esquema de entrada
    coverage = 0.15
    details = ["coordenadas válidas"]

    accuracy = _optional_float(evidence.get("gps_accuracy_m"))
    if accuracy is not None:
        coverage += 0.20
        if accuracy <= 30:
            score += 0.20
            details.append(f"GPS preciso ({accuracy:.0f} m)")
        elif accuracy <= 100:
            score += 0.12
            details.append(f"GPS utilizable ({accuracy:.0f} m)")
        else:
            score += 0.04
            details.append(f"GPS impreciso ({accuracy:.0f} m)")

    source = str(evidence.get("capture_source") or "unknown")
    if source != "unknown":
        coverage += 0.15
        score += 0.15 if source == "camera" else 0.04
        details.append("captura desde cámara" if source == "camera" else "imagen de galería")

    captured_at = _datetime(evidence.get("captured_at"))
    if captured_at is not None:
        coverage += 0.10
        age = max(0.0, (datetime.now(UTC) - captured_at).total_seconds())
        if age <= 86_400:
            score += 0.10
            details.append("captura reciente")
        elif age <= 604_800:
            score += 0.05
            details.append("captura de menos de siete días")
        else:
            score += 0.02
            details.append("captura antigua")

    if evidence.get("content_hash"):
        coverage += 0.10
        score += 0.10
        details.append("hash registrado")

    presence = str(evidence.get("presence_status") or "unavailable")
    if presence != "unavailable":
        coverage += 0.30
        if presence == "confirmed":
            score += 0.30
            details.append("presencia reciente confirmada")
        elif presence == "partial":
            score += 0.15
            details.append("presencia reciente parcial")
        else:
            details.append("presencia reciente no confirmada")

    return ScoreComponent(
        score=round(min(1.0, score), 4),
        weight=0.20,
        coverage=round(min(1.0, coverage), 4),
        explanation="Confiabilidad de captura: " + ", ".join(details) + ".",
    )


def _datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _optional_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None

