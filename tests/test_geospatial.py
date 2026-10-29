from app.core.config import Settings
from app.services.geospatial import OptionalGeospatialService


def test_parse_sentinel_statistics_ignores_empty_intervals() -> None:
    payload = {
        "data": [
            {
                "interval": {"from": "2026-01-01", "to": "2026-02-01"},
                "outputs": {
                    "indices": {
                        "bands": {
                            key: {"stats": {"mean": value, "sampleCount": 12}}
                            for key, value in {
                                "ndvi": 0.7,
                                "ndwi": -0.2,
                                "ndsi": -0.1,
                                "bsi": 0.05,
                            }.items()
                        }
                    }
                },
            },
            {
                "interval": {"from": "2026-02-01", "to": "2026-03-01"},
                "outputs": {"indices": {"bands": {}}},
            },
        ]
    }
    rows = OptionalGeospatialService._parse_statistics(payload)
    assert len(rows) == 1
    assert rows[0]["ndvi"] == 0.7


def test_parse_sentinel_statistics_ignores_non_finite_intervals() -> None:
    payload = {
        "data": [
            {
                "interval": {"from": "2026-01-01", "to": "2026-02-01"},
                "outputs": {
                    "indices": {
                        "bands": {
                            key: {
                                "stats": {
                                    "mean": float("nan") if key == "ndvi" else 0.1,
                                    "sampleCount": 12,
                                }
                            }
                            for key in ("ndvi", "ndwi", "ndsi", "bsi")
                        }
                    }
                },
            }
        ]
    }
    assert OptionalGeospatialService._parse_statistics(payload) == []


def test_non_finite_environmental_number_is_unavailable() -> None:
    assert OptionalGeospatialService._number(float("nan")) is None
    assert OptionalGeospatialService._number(float("inf")) is None


def test_forest_coherence_uses_ndvi() -> None:
    service = OptionalGeospatialService(Settings())
    result = service._environmental_coherence(
        "bosque",
        {"indices": {"ndvi": 0.63}},
        {"status": "available", "elevation_m": 500},
    )
    assert result["state"] == "confirms"
    assert result["has_contradiction"] is False


def test_water_contradiction_is_exposed_for_human_review() -> None:
    service = OptionalGeospatialService(Settings())
    result = service._environmental_coherence(
        "lago",
        {"indices": {"ndwi": -0.4}},
        {"status": "available", "elevation_m": 500},
    )
    assert result["state"] == "contradicts"
    assert result["has_contradiction"] is True
