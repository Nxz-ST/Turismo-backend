from app.api.routes.itineraries import (
    _decode_polyline,
    _distance_km,
    _fits_duration,
    _official,
    _route,
)


def test_decodes_google_route_polyline() -> None:
    points = _decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@")
    assert points == [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]


def test_distance_is_zero_for_same_coordinate() -> None:
    assert _distance_km(-12.0, -77.0, -12.0, -77.0) == 0


def test_route_orders_stops_and_estimates_duration() -> None:
    stops = [
        {"name": "Primero", "latitude": -12.01, "longitude": -77.0},
        {"name": "Segundo", "latitude": -12.02, "longitude": -77.0},
    ]
    result = _route(
        title="Ruta",
        subtitle="Prueba",
        kind="nearby",
        origin=(-12.0, -77.0),
        stops=stops,
    )
    assert [stop["order"] for stop in result["stops"]] == [1, 2]
    assert result["distance_km"] > 0
    assert result["duration_minutes"] >= 90


def test_walking_route_is_slower_than_driving() -> None:
    stop = {"name": "Destino", "latitude": -12.03, "longitude": -77.0}
    driving = _route(
        title="Ruta",
        subtitle="",
        kind="test",
        origin=(-12.0, -77.0),
        stops=[dict(stop)],
        travel_mode="driving",
    )
    walking = _route(
        title="Ruta",
        subtitle="",
        kind="test",
        origin=(-12.0, -77.0),
        stops=[dict(stop)],
        travel_mode="walking",
    )
    assert walking["duration_minutes"] > driving["duration_minutes"]
    assert walking["travel_mode"] == "walking"


def test_duration_filter_limits_number_of_stops() -> None:
    stops = [
        {"name": f"Parada {index}", "latitude": -12.0 - index * 0.02, "longitude": -77.0}
        for index in range(1, 8)
    ]
    short = _fits_duration(
        origin=(-12.0, -77.0),
        stops=stops,
        duration_minutes=120,
        travel_mode="driving",
    )
    long = _fits_duration(
        origin=(-12.0, -77.0),
        stops=stops,
        duration_minutes=600,
        travel_mode="driving",
    )
    assert len(short) < len(long)


def test_two_hour_plan_never_forces_a_snow_peak() -> None:
    stops = [
        {
            "id": "nevado",
            "name": "Nevado de prueba",
            "category": "Sitio natural",
            "latitude": -9.44,
            "longitude": -77.30,
            "altitude_m": 5700,
        },
        {
            "id": "museo",
            "name": "Museo local",
            "category": "Manifestación cultural",
            "latitude": -9.53,
            "longitude": -77.52,
            "altitude_m": 3050,
        },
    ]
    selected = _fits_duration(
        origin=(-9.53, -77.52),
        stops=stops,
        duration_minutes=120,
        travel_mode="driving",
    )
    assert [stop["id"] for stop in selected] == ["museo"]


def test_full_day_snow_peak_has_conservative_activity_time() -> None:
    stop = {
        "id": "nevado",
        "name": "Nevado de prueba",
        "category": "Sitio natural",
        "latitude": -9.44,
        "longitude": -77.30,
        "altitude_m": 5700,
    }
    selected = _fits_duration(
        origin=(-9.53, -77.52),
        stops=[stop],
        duration_minutes=600,
        travel_mode="driving",
    )
    assert len(selected) == 1
    result = _route(
        title="Alta montaña",
        subtitle="",
        kind="adventure",
        origin=(-9.53, -77.52),
        stops=selected,
    )
    assert result["activity_minutes"] == 480
    assert result["requires_special_planning"] is True
    assert result["stops"][0]["difficulty_source"] == "rutaamiga_conservative_estimate"


def test_official_place_exposes_information_provenance() -> None:
    place = _official(
        {
            "id": 10,
            "codigo": 10,
            "nombre": "Museo de prueba",
            "latitud": -9.5,
            "longitud": -77.5,
            "altitud": 3050,
            "horario_visita": "09:00 a 17:00",
        }
    )

    assert place["provenance"]["identity"] == "official_tourism_record"
    assert place["provenance"]["coordinates"] == "official_reported"
    assert place["provenance"]["visit_information"] == "official_record"


def test_official_place_uses_approved_access_for_navigation() -> None:
    place = _official(
        {
            "id": 20,
            "codigo": 20,
            "nombre": "Nevado de prueba",
            "latitud": -9.4,
            "longitud": -77.3,
            "altitud": 5500,
            "coordinate_quality": "reported",
            "access_latitud": -9.45,
            "access_longitud": -77.35,
            "access_notes": "Inicio del sendero confirmado",
            "access_source": "manual_admin_review",
        }
    )

    assert place["latitude"] == -9.45
    assert place["longitude"] == -77.35
    assert place["attraction_latitude"] == -9.4
    assert place["attraction_longitude"] == -77.3
    assert place["navigation_coordinate_role"] == "access_point"
    assert place["coordinate_quality"] == "verified_access"
    assert place["provenance"]["coordinates"] == "verified_access_point"
