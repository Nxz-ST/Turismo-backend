import asyncio
from math import asin, cos, radians, sin, sqrt
from typing import Literal

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, SettingsDep
from app.core.errors import ConfigurationError, ExternalServiceError
from app.services.google_maps import GoogleMapsService
from app.services.supabase import SupabaseRepository


router = APIRouter()

_VERIFIED_COORDINATE_CORRECTIONS = {
    11506: (-9.439077, -77.302956, 5721.0),
    11531: (-9.525, -77.385, 5434.0),
}


def _decode_polyline(encoded: str) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    index = latitude = longitude = 0
    while index < len(encoded):
        deltas: list[int] = []
        for _ in range(2):
            result = shift = 0
            while True:
                value = ord(encoded[index]) - 63
                index += 1
                result |= (value & 0x1F) << shift
                shift += 5
                if value < 0x20:
                    break
            deltas.append(~(result >> 1) if result & 1 else result >> 1)
        latitude += deltas[0]
        longitude += deltas[1]
        points.append((latitude / 1e5, longitude / 1e5))
    return points


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    d_lat = radians(lat2 - lat1)
    d_lon = radians(lon2 - lon1)
    a = sin(d_lat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(
        d_lon / 2
    ) ** 2
    return 6371 * 2 * asin(sqrt(a))


def _official(row: dict) -> dict:
    code = int(row.get("codigo") or 0)
    correction = _VERIFIED_COORDINATE_CORRECTIONS.get(code)
    attraction_latitude = (
        correction[0] if correction else float(row.get("latitud") or 0)
    )
    attraction_longitude = (
        correction[1] if correction else float(row.get("longitud") or 0)
    )
    altitude = correction[2] if correction else float(row.get("altitud") or 0)
    access_latitude = row.get("access_latitud")
    access_longitude = row.get("access_longitud")
    has_access = access_latitude is not None and access_longitude is not None
    latitude = float(access_latitude) if has_access else attraction_latitude
    longitude = float(access_longitude) if has_access else attraction_longitude
    stored_quality = str(row.get("coordinate_quality") or "reported")
    coordinate_quality = (
        "verified_access"
        if has_access
        else "verified_correction"
        if correction
        else stored_quality
    )
    has_visit_information = any(
        row.get(field)
        for field in (
            "tipo_ingreso",
            "tarifa_adulto",
            "tarifa_nino",
            "tarifa_extranjero",
            "epoca_visita",
            "horario_visita",
            "recomendaciones_visita",
        )
    )
    return {
        "id": f"official-{row.get('id')}",
        "name": row.get("nombre") or "Atractivo turístico",
        "description": row.get("descripcion") or "",
        "latitude": latitude,
        "longitude": longitude,
        "attraction_latitude": attraction_latitude,
        "attraction_longitude": attraction_longitude,
        "navigation_coordinate_role": "access_point" if has_access else "attraction",
        "access_notes": row.get("access_notes") or "",
        "category": row.get("categoria_texto") or "Atractivo natural",
        "source": "official",
        "validation_status": "official",
        "district": row.get("distrito") or "",
        "province": row.get("provincia") or "",
        "department": row.get("departamento") or "",
        "altitude_m": altitude,
        "entry_type": row.get("tipo_ingreso") or "",
        "adult_fee": row.get("tarifa_adulto") or "",
        "child_fee": row.get("tarifa_nino") or "",
        "foreigner_fee": row.get("tarifa_extranjero") or "",
        "visit_season": row.get("epoca_visita") or "",
        "visit_hours": row.get("horario_visita") or "",
        "visit_recommendations": row.get("recomendaciones_visita") or "",
        "activities": row.get("actividades") or "",
        "coordinate_quality": coordinate_quality,
        "provenance": {
            "identity": "official_tourism_record",
            "coordinates": (
                "verified_access_point"
                if has_access
                else "verified_correction"
                if correction or stored_quality == "verified_correction"
                else "referential_duplicate_cluster"
                if stored_quality == "approximate_cluster"
                else "official_reported"
            ),
            "coordinate_source": row.get("coordinate_source") or "mincetur_reported",
            "access_source": row.get("access_source") if has_access else None,
            "altitude": "official_record" if altitude > 0 else "not_available",
            "visit_information": (
                "official_record" if has_visit_information else "not_available"
            ),
        },
    }


def _community(row: dict) -> dict:
    return {
        "id": f"community-{row.get('id')}",
        "name": row.get("nombre") or "Descubrimiento de la comunidad",
        "description": row.get("descripcion") or "",
        "latitude": float(row.get("latitud") or 0),
        "longitude": float(row.get("longitud") or 0),
        "category": row.get("categoria_ia") or "Por determinar",
        "source": "community",
        "validation_status": row.get("estado_validacion") or "candidate",
        "district": "",
        "province": "",
        "altitude_m": float(row.get("altitud") or 0),
        "coordinate_quality": row.get("coordinate_quality") or "reported",
        "provenance": {
            "identity": "validated_community_contribution",
            "coordinates": "validated_community_contribution",
            "altitude": (
                "community_reported" if float(row.get("altitud") or 0) > 0
                else "not_available"
            ),
            "visit_information": "not_available",
        },
    }


def _activity_profile(stop: dict) -> dict:
    """Conservative planning profile; these are product estimates, not trail facts."""
    text = f"{stop.get('name', '')} {stop.get('category', '')}".lower()
    altitude = float(stop.get("altitude_m") or 0)

    if "nevado" in text or "glaciar" in text:
        return {
            "activity_minutes": 480,
            "minimum_budget_minutes": 600,
            "difficulty": "exigente",
            "activity_type": "alta montaña",
            "access_note": (
                "Estimación referencial: requiere aproximación, aclimatación y "
                "evaluación con guía local; puede necesitar más de un día."
            ),
            "adventure_score": 5,
        }
    if any(word in text for word in ("volcán", "volcan", "montaña", "montana")):
        return {
            "activity_minutes": 300,
            "minimum_budget_minutes": 420,
            "difficulty": "alta",
            "activity_type": "montaña",
            "access_note": "Considera aproximación, desnivel, clima y retorno con luz.",
            "adventure_score": 4,
        }
    if any(word in text for word in ("cascada", "catarata")):
        return {
            "activity_minutes": 120,
            "minimum_budget_minutes": 180,
            "difficulty": "moderada",
            "activity_type": "sendero natural",
            "access_note": "Incluye aproximación peatonal y tiempo de visita.",
            "adventure_score": 3,
        }
    if any(word in text for word in ("laguna", "lago")):
        minutes = 180 if altitude >= 3800 else 120
        return {
            "activity_minutes": minutes,
            "minimum_budget_minutes": minutes + 60,
            "difficulty": "moderada" if altitude >= 3800 else "media",
            "activity_type": "paisaje y caminata",
            "access_note": "El tiempo puede aumentar por altura y tramo peatonal.",
            "adventure_score": 3,
        }
    if "playa" in text:
        return {
            "activity_minutes": 150,
            "minimum_budget_minutes": 210,
            "difficulty": "fácil",
            "activity_type": "visita recreativa",
            "access_note": "Tiempo sugerido para recorrido y permanencia.",
            "adventure_score": 1,
        }
    if any(word in text for word in ("bosque", "desierto", "cañón", "canon")):
        return {
            "activity_minutes": 150,
            "minimum_budget_minutes": 240,
            "difficulty": "media",
            "activity_type": "exploración natural",
            "access_note": "Incluye recorrido interno y margen de retorno.",
            "adventure_score": 2,
        }
    return {
        "activity_minutes": 60,
        "minimum_budget_minutes": 90,
        "difficulty": "fácil",
        "activity_type": "visita turística",
        "access_note": "Duración referencial; confirma horarios y acceso local.",
        "adventure_score": 0,
    }


def _prepare_stop(stop: dict) -> dict:
    prepared = dict(stop)
    prepared.update(_activity_profile(prepared))
    prepared["difficulty_source"] = "rutaamiga_conservative_estimate"
    prepared["activity_duration_source"] = "rutaamiga_conservative_estimate"
    return prepared


def _mark_coordinate_quality(stops: list[dict]) -> list[dict]:
    counts: dict[tuple[float, float], int] = {}
    for stop in stops:
        key = (round(stop["latitude"], 4), round(stop["longitude"], 4))
        counts[key] = counts.get(key, 0) + 1
    checked: list[dict] = []
    for stop in stops:
        item = dict(stop)
        key = (round(item["latitude"], 4), round(item["longitude"], 4))
        if (
            counts[key] >= 3
            and item.get("coordinate_quality")
            not in {"verified_correction", "verified_access"}
        ):
            item["coordinate_quality"] = "approximate_cluster"
        checked.append(item)
    return checked


def _route(
    *,
    title: str,
    subtitle: str,
    kind: str,
    origin: tuple[float, float],
    stops: list[dict],
    travel_mode: str = "driving",
) -> dict:
    total = 0.0
    travel_minutes = 0
    activity_minutes = 0
    previous = origin
    speed_kmh = {"walking": 4.5}.get(travel_mode, 30.0)
    for index, stop in enumerate(stops, start=1):
        stop.update(_activity_profile(stop))
        stop["difficulty_source"] = "rutaamiga_conservative_estimate"
        stop["activity_duration_source"] = "rutaamiga_conservative_estimate"
        leg = _distance_km(
            previous[0], previous[1], stop["latitude"], stop["longitude"]
        )
        stop["order"] = index
        stop["distance_from_previous_km"] = round(leg, 1)
        total += leg
        travel_minutes += round((leg / speed_kmh) * 60)
        activity_minutes += int(stop["activity_minutes"])
        previous = (stop["latitude"], stop["longitude"])
    minutes = travel_minutes + activity_minutes
    demanding = any(stop.get("difficulty") in {"alta", "exigente"} for stop in stops)
    return {
        "id": kind,
        "title": title,
        "subtitle": subtitle,
        "kind": kind,
        "distance_km": round(total, 1),
        "duration_minutes": max(minutes, 45),
        "travel_minutes": travel_minutes,
        "activity_minutes": activity_minutes,
        "estimate_kind": "conservative_activity_profile",
        "data_sources": [
            {
                "field": "places",
                "source": "official_and_validated_community_records",
            },
            {
                "field": "difficulty_and_activity_time",
                "source": "rutaamiga_conservative_estimate",
            },
            {
                "field": "initial_distance",
                "source": "geographic_estimate",
            },
        ],
        "requires_special_planning": demanding,
        "stops": stops,
        "navigation_mode": "preview",
        "travel_mode": travel_mode,
    }


def _fits_duration(
    *,
    origin: tuple[float, float],
    stops: list[dict],
    duration_minutes: int,
    travel_mode: str,
) -> list[dict]:
    selected: list[dict] = []
    for stop in stops:
        prepared = _prepare_stop(stop)
        if prepared["minimum_budget_minutes"] > duration_minutes:
            continue
        # Las actividades de alta montaña se planifican solas; no se mezclan
        # automáticamente con varias paradas urbanas o naturales.
        if prepared["activity_type"] == "alta montaña" and selected:
            continue
        if selected and any(
            item.get("activity_type") == "alta montaña" for item in selected
        ):
            break
        candidate = [*selected, prepared]
        preview = _route(
            title="",
            subtitle="",
            kind="preview",
            origin=origin,
            stops=candidate,
            travel_mode=travel_mode,
        )
        if preview["duration_minutes"] <= duration_minutes:
            selected = candidate
        if len(selected) >= 7:
            break
    return selected


@router.get("/suggestions")
async def suggested_itineraries(
    _: CurrentUser,
    settings: SettingsDep,
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(ge=-180, le=180),
    radius: float = Query(default=30_000, gt=0, le=100_000),
    duration_minutes: int = Query(default=300, ge=60, le=1_440),
    experience: Literal["mixed", "official", "nature", "discoveries"] = "mixed",
    travel_mode: Literal["driving", "walking"] = "driving",
    intent: Literal["nearby", "corridor", "day", "discoveries"] = "nearby",
    destination_latitude: float | None = Query(default=None, ge=-90, le=90),
    destination_longitude: float | None = Query(default=None, ge=-180, le=180),
    destination_name: str | None = Query(default=None, max_length=120),
    max_detour_minutes: int = Query(default=20, ge=5, le=60),
) -> list[dict]:
    repository = SupabaseRepository(settings)
    planning_radius = min(
        radius,
        15_000 if duration_minutes <= 120 else 40_000 if duration_minutes < 600 else 100_000,
    )
    search_centers = [(latitude, longitude)]
    if (
        intent == "corridor"
        and destination_latitude is not None
        and destination_longitude is not None
    ):
        # Sample the origin-destination corridor. The radius is intentionally
        # conservative so suggestions remain worthwhile detours.
        segments = 6
        try:
            road_route = await GoogleMapsService(settings).route(
                {
                    "origin_latitude": latitude,
                    "origin_longitude": longitude,
                    "destination_latitude": destination_latitude,
                    "destination_longitude": destination_longitude,
                    "travel_mode": travel_mode,
                }
            )
            road_points = _decode_polyline(
                road_route.get("polyline", {}).get("encodedPolyline", "")
            )
        except (ConfigurationError, ExternalServiceError, ValueError, IndexError):
            road_points = []
        if road_points:
            search_centers = [
                road_points[round(index * (len(road_points) - 1) / segments)]
                for index in range(1, segments + 1)
            ]
        else:
            search_centers = [
                (
                    latitude
                    + (destination_latitude - latitude) * index / segments,
                    longitude
                    + (destination_longitude - longitude) * index / segments,
                )
                for index in range(1, segments + 1)
            ]
        speed_kmh = 30 if travel_mode == "driving" else 4.5
        planning_radius = min(
            30_000,
            max(3_000, speed_kmh * max_detour_minutes * 1000 / 60 / 2),
        )

    official_batches, community_batches = await asyncio.gather(
        asyncio.gather(
            *[
                repository.nearby_places(lat, lon, planning_radius)
                for lat, lon in search_centers
            ]
        ),
        asyncio.gather(
            *[
                repository.nearby_community_places(lat, lon, planning_radius)
                for lat, lon in search_centers
            ]
        ),
    )
    official_rows = list(
        {
            str(row.get("id")): row
            for batch in official_batches
            for row in batch
        }.values()
    )
    community_rows = list(
        {
            str(row.get("id")): row
            for batch in community_batches
            for row in batch
            if (row.get("estado_validacion") or row.get("status"))
            in {"validated", "approved", "validated_satellite"}
        }.values()
    )
    official = [_official(row) for row in official_rows]
    community = [_community(row) for row in community_rows]
    all_stops = _mark_coordinate_quality([*official, *community])
    official = [stop for stop in all_stops if stop["source"] == "official"]
    community = [stop for stop in all_stops if stop["source"] == "community"]
    # Un punto administrativo o repetido puede mostrarse como referencia, pero
    # nunca debe convertirse automáticamente en una instrucción de navegación.
    safe_stops = [
        stop
        for stop in all_stops
        if stop.get("coordinate_quality") != "approximate_cluster"
    ]
    safe_official = [stop for stop in safe_stops if stop["source"] == "official"]
    safe_community = [stop for stop in safe_stops if stop["source"] == "community"]
    all_stops.sort(
        key=lambda stop: _distance_km(
            latitude, longitude, stop["latitude"], stop["longitude"]
        )
    )
    routes: list[dict] = []
    province = next(
        (stop["province"] for stop in official if stop.get("province")),
        "tu destino",
    ).title()
    duration_label = (
        "en 2 horas" if duration_minutes <= 120
        else "en un día" if duration_minutes >= 600
        else "en medio día"
    )
    natural_words = {
        "bosque", "cascada", "desierto", "lago", "montaña", "montana",
        "nevado", "playa", "volcán", "volcan", "natural",
    }
    if intent == "corridor":
        preferred = safe_stops
        title = f"Paradas rumbo a {destination_name or 'tu destino'}"
        subtitle = f"Lugares verificados con desvíos de hasta {max_detour_minutes} min"
    elif experience == "official":
        preferred = safe_official
        title = "Ruta de atractivos oficiales"
        subtitle = "Lugares registrados en la fuente turística oficial"
    elif experience == "discoveries":
        preferred = [*safe_community, *safe_official]
        title = "Ruta de descubrimientos"
        subtitle = "Nuevos lugares validados combinados con atractivos oficiales"
    elif experience == "nature":
        preferred = [
            stop for stop in safe_stops
            if any(word in stop["category"].lower() for word in natural_words)
        ] or safe_stops
        title = "Ruta de naturaleza"
        subtitle = "Paisajes y atractivos naturales cercanos"
    else:
        preferred = safe_stops
        beach_count = sum(
            "playa" in f"{stop['name']} {stop['category']}".lower()
            for stop in preferred
        )
        if beach_count >= 2:
            title = f"Circuito de playas de {province}"
            subtitle = f"Una selección lista para conocer {province} {duration_label}"
        else:
            title = f"Conoce {province} {duration_label}"
            subtitle = "Atractivos cercanos ordenados para aprovechar mejor tu visita"

    origin = (latitude, longitude)
    seen_routes: set[tuple[str, ...]] = set()

    def add_route(*, candidates: list[dict], route_title: str,
                  route_subtitle: str, kind: str) -> None:
        if len(routes) >= 3:
            return
        selected = _fits_duration(
            origin=origin,
            stops=candidates,
            duration_minutes=duration_minutes,
            travel_mode=travel_mode,
        )
        # Una sola visita es un destino, no un circuito. Las recomendaciones
        # automáticas de esta pantalla siempre deben conectar al menos dos
        # lugares distintos.
        # El orden no convierte al mismo grupo de paradas en otra alternativa.
        # Así evitamos mostrar A-B y B-A como dos recomendaciones distintas.
        signature = tuple(sorted(str(stop.get("id")) for stop in selected))
        if len(selected) < 2 or signature in seen_routes:
            return
        seen_routes.add(signature)
        routes.append(
            _route(
                title=route_title,
                subtitle=route_subtitle,
                kind=kind,
                origin=origin,
                stops=selected,
                travel_mode=travel_mode,
            )
        )

    # Primera alternativa: la más cercana que sí cabe en el tiempo real de la
    # actividad. Una visita de dos horas ya no fuerza un nevado en la lista.
    add_route(
        candidates=preferred,
        route_title=title,
        route_subtitle=subtitle,
        kind=f"planned-{intent}-{experience}-{duration_minutes}-{travel_mode}",
    )

    # Segunda alternativa: accesos más simples y actividades cortas. El orden
    # mezcla esfuerzo y distancia, por eso no replica la selección anterior.
    accessible = sorted(
        preferred,
        key=lambda stop: (
            _activity_profile(stop)["minimum_budget_minutes"],
            _distance_km(latitude, longitude, stop["latitude"], stop["longitude"]),
        ),
    )
    add_route(
        candidates=accessible,
        route_title="Ruta tranquila y accesible",
        route_subtitle="Paradas compatibles con tu tiempo y menor exigencia física",
        kind=f"accessible-{intent}-{duration_minutes}-{travel_mode}",
    )

    # Tercera alternativa: naturaleza/aventura. Solo aparece si el presupuesto
    # permite la actividad; un nevado requiere como mínimo un día completo.
    adventure = sorted(
        preferred,
        key=lambda stop: (
            -int(_activity_profile(stop)["adventure_score"]),
            _distance_km(latitude, longitude, stop["latitude"], stop["longitude"]),
        ),
    )
    add_route(
        candidates=adventure,
        route_title="Paisajes y aventura",
        route_subtitle="Prioriza experiencias naturales con tiempo de actividad realista",
        kind=f"adventure-{intent}-{duration_minutes}-{travel_mode}",
    )
    if safe_community and experience != "discoveries":
        discovery = [dict(stop) for stop in safe_community[:2]]
        discovery.extend(
            dict(stop)
            for stop in safe_official
            if stop["id"] not in {item["id"] for item in discovery}
        )
        add_route(
            candidates=discovery,
            route_title="Ruta de descubrimientos",
            route_subtitle="Descubrimientos validados combinados con lugares oficiales",
            kind=f"discoveries-{duration_minutes}-{travel_mode}",
        )

    # Completa hasta tres alternativas con subconjuntos reales. Esto evita
    # repetir el mismo circuito con otro título y también evita presentar una
    # visita individual como si fuera una ruta. Con A, B y C pueden existir,
    # por ejemplo, A-B, A-C y B-C, siempre que cada par quepa en el tiempo.
    if len(routes) < 3:
        prepared_stops = [_prepare_stop(stop) for stop in preferred]
        eligible = [
            stop
            for stop in prepared_stops
            if stop["minimum_budget_minutes"] <= duration_minutes
            and stop["activity_type"] != "alta montaña"
        ]
        for first_index, first in enumerate(eligible):
            for second in eligible[first_index + 1:]:
                if len(routes) >= 3:
                    break
                names = f"{first.get('name')} y {second.get('name')}"
                add_route(
                    candidates=[first, second],
                    route_title=f"Recorrido por {names}",
                    route_subtitle="Dos paradas compatibles para explorar sin apurar el viaje",
                    kind=(
                        f"pair-{first.get('id')}-{second.get('id')}-"
                        f"{duration_minutes}-{travel_mode}"
                    ),
                )
            if len(routes) >= 3:
                break
    return routes
