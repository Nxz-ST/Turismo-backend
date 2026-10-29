import pytest
from pydantic import ValidationError

from app.schemas.review import ReviewDecision


def test_review_accepts_supported_category() -> None:
    review = ReviewDecision(
        status="validated",
        category="cascada",
        reason="La evidencia y la ubicación son coherentes.",
    )
    assert review.status == "validated"


def test_review_rejects_unknown_category() -> None:
    with pytest.raises(ValidationError):
        ReviewDecision(
            status="validated",
            category="ciudad",
            reason="Categoría fuera del modelo.",
        )
