from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.review import CommunityPlaceAdminUpdate, CommunityPlaceMerge


def test_community_admin_update_requires_a_meaningful_audit_note() -> None:
    with pytest.raises(ValidationError):
        CommunityPlaceAdminUpdate(name="Cascada Arampampa", note="no")


def test_community_admin_update_accepts_thesis_workflow_fields() -> None:
    payload = CommunityPlaceAdminUpdate(
        name="Cascada Arampampa",
        description="Ficha consolidada después de revisión humana.",
        category="cascada",
        publication_status="published",
        note="Contraste realizado con las evidencias disponibles.",
    )

    assert payload.category == "cascada"
    assert payload.publication_status == "published"


def test_community_merge_requires_a_target_and_note() -> None:
    target = uuid4()
    payload = CommunityPlaceMerge(
        target_place_id=target,
        note="Duplicado corroborado por cercanía y categoría.",
    )

    assert payload.target_place_id == target
