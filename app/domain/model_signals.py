"""Resumen de lectura de las señales del motor visual para el panel.

No interviene en la decisión: solo expone lo que el motor ya calculó
(clasificador, embeddings y Gemma) para que un caso "no concluyente" muestre
qué dijo cada señal en lugar de aparecer como "Sin señal".
"""

from collections import Counter
from typing import Any

from app.domain.categories import normalize_category


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return max(0.0, min(1.0, number / 100 if number > 1 else number))


def _category(value: Any) -> str | None:
    category = normalize_category(str(value)) if value else None
    return category.value if category else None


def summarize_model_signals(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    """Devuelve las señales del motor o None si el resultado no las contiene."""
    if not isinstance(raw, dict):
        return None
    gemma = raw.get("gemma") if isinstance(raw.get("gemma"), dict) else {}
    fusion = raw.get("fusion") if isinstance(raw.get("fusion"), dict) else {}
    classifier = _category(raw.get("clasificacion_modelo"))
    embeddings = _category(raw.get("clase_embeddings"))
    gemma_category = _category(gemma.get("clase")) if gemma.get("disponible", True) else None
    if not (classifier or embeddings or gemma_category):
        return None

    votes = Counter(
        category for category in (classifier, embeddings, gemma_category) if category
    )
    majority, majority_votes = votes.most_common(1)[0] if votes else (None, 0)
    return {
        "state": str(raw.get("estado") or "") or None,
        "reason": str(raw.get("motivo_decision") or "") or None,
        "classifier": {
            "category": classifier,
            "confidence": _number(raw.get("confianza_modelo")),
        },
        "embeddings": {
            "category": embeddings,
            "similarity": _number(raw.get("similitud_visual")),
        },
        "gemma": {
            "category": gemma_category,
            "description": str(gemma.get("descripcion") or "")[:400] or None,
        },
        "majority_category": majority if majority_votes >= 2 else None,
        "agreement": majority_votes,
        "signals_available": sum(votes.values()),
        "gemma_conflict": bool(fusion.get("conflicto_gemma")),
    }
