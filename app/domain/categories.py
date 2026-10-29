from enum import StrEnum


class TouristCategory(StrEnum):
    BOSQUE = "bosque"
    CASCADA = "cascada"
    DESIERTO = "desierto"
    LAGO = "lago"
    MONTANA = "montana"
    NEVADO = "nevado"
    PLAYA = "playa"
    VOLCAN = "volcan"


CATEGORY_ALIASES = {
    "montaña": TouristCategory.MONTANA,
    "volcán": TouristCategory.VOLCAN,
}


def normalize_category(value: str | None) -> TouristCategory | None:
    if not value:
        return None
    normalized = value.strip().lower()
    try:
        return TouristCategory(normalized)
    except ValueError:
        return CATEGORY_ALIASES.get(normalized)

