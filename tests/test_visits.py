from app.api.routes.visits import _distance_m, _verification_radius


def test_visit_distance_is_zero_at_same_location() -> None:
    assert _distance_m(-9.5278, -77.5278, -9.5278, -77.5278) == 0


def test_natural_places_receive_contextual_arrival_radius() -> None:
    assert _verification_radius("Sitio natural", "Nevado Vallunaraju") == 500
    assert _verification_radius("Playa", "Tuquillo") == 300
    assert _verification_radius("Museo", "Museo regional") == 180

