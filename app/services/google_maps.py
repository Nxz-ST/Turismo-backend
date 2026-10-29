from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.core.config import Settings
from app.core.errors import ConfigurationError, ExternalServiceError


class GoogleMapsService:
    ALLOWED_TYPES = {
        "restaurant", "lodging", "pharmacy", "gas_station", "atm",
        "travel_agency", "tourist_information_center",
    }
    _photos_unavailable_until: datetime | None = None

    def __init__(self, settings: Settings):
        self._settings = settings

    def _key(self) -> str:
        if not self._settings.google_maps_api_key:
            raise ConfigurationError("Google Maps Platform no esta configurado")
        return self._settings.google_maps_api_key

    @staticmethod
    def _error_message(service: str, response: httpx.Response) -> str:
        try:
            error = response.json().get("error") or {}
            message = error.get("message")
        except (ValueError, AttributeError):
            message = None
        suffix = f": {message}" if message else ""
        return f"{service} respondio {response.status_code}{suffix}"

    async def nearby_services(
        self, *, latitude: float, longitude: float, place_type: str, radius: float
    ) -> list[dict[str, Any]]:
        if place_type not in self.ALLOWED_TYPES:
            raise ValueError("Tipo de servicio no permitido")
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self._key(),
            "X-Goog-FieldMask": (
                "places.id,places.displayName,places.formattedAddress,"
                "places.location,places.rating,places.types,places.photos"
                ",places.nationalPhoneNumber,places.websiteUri,places.googleMapsUri,"
                "places.currentOpeningHours"
            ),
        }
        payload = {
            "includedTypes": [place_type],
            "maxResultCount": 10,
            "locationRestriction": {
                "circle": {
                    "center": {"latitude": latitude, "longitude": longitude},
                    "radius": radius,
                }
            },
        }
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                "https://places.googleapis.com/v1/places:searchNearby",
                headers=headers,
                json=payload,
            )
        if response.is_error:
            raise ExternalServiceError(self._error_message("Google Places", response))
        return response.json().get("places", [])

    async def search_destinations(self, *, query: str) -> list[dict[str, Any]]:
        """Search Peruvian cities and administrative areas for trip planning."""
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self._key(),
            "X-Goog-FieldMask": (
                "places.id,places.displayName,places.formattedAddress,"
                "places.location,places.types"
            ),
        }
        body = {
            "textQuery": f"{query}, Peru",
            "maxResultCount": 8,
            "languageCode": "es",
            "regionCode": "PE",
            "includedType": "locality",
        }
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                "https://places.googleapis.com/v1/places:searchText",
                headers=headers,
                json=body,
            )
        if response.is_error:
            raise ExternalServiceError(
                self._error_message("Google Places", response)
            )
        results: list[dict[str, Any]] = []
        for place in response.json().get("places", []):
            location = place.get("location") or {}
            display_name = place.get("displayName") or {}
            if location.get("latitude") is None or location.get("longitude") is None:
                continue
            results.append(
                {
                    "id": place.get("id"),
                    "name": display_name.get("text") or query,
                    "address": place.get("formattedAddress") or "Perú",
                    "latitude": location["latitude"],
                    "longitude": location["longitude"],
                }
            )
        return results

    async def tourist_coordinate_candidates(
        self,
        *,
        name: str,
        district: str = "",
        province: str = "",
        department: str = "",
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Return geocoding candidates without treating them as corrections.

        Google Places is useful for proposing alternatives, but a result only
        becomes authoritative after an administrator reviews its identity,
        address and intended role (attraction or access point).
        """
        context = ", ".join(
            value.strip()
            for value in (name, district, province, department, "Perú")
            if value and value.strip()
        )
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self._key(),
            "X-Goog-FieldMask": (
                "places.id,places.displayName,places.formattedAddress,"
                "places.location,places.types,places.googleMapsUri"
            ),
        }
        body = {
            "textQuery": context,
            "maxResultCount": min(max(limit, 1), 8),
            "languageCode": "es",
            "regionCode": "PE",
        }
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                "https://places.googleapis.com/v1/places:searchText",
                headers=headers,
                json=body,
            )
        if response.is_error:
            raise ExternalServiceError(
                self._error_message("Google Places", response)
            )

        candidates: list[dict[str, Any]] = []
        for place in response.json().get("places", []):
            location = place.get("location") or {}
            latitude = location.get("latitude")
            longitude = location.get("longitude")
            if latitude is None or longitude is None:
                continue
            display_name = place.get("displayName") or {}
            candidates.append(
                {
                    "name": display_name.get("text") or name,
                    "address": place.get("formattedAddress") or "",
                    "latitude": float(latitude),
                    "longitude": float(longitude),
                    "source": "google_places",
                    "source_reference": place.get("googleMapsUri") or place.get("id"),
                    "types": place.get("types") or [],
                }
            )
        return candidates

    async def route(self, payload: dict[str, float]) -> dict[str, Any]:
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self._key(),
            "X-Goog-FieldMask": (
                "routes.duration,routes.distanceMeters,routes.polyline.encodedPolyline"
            ),
        }
        body = {
            "origin": {
                "location": {
                    "latLng": {
                        "latitude": payload["origin_latitude"],
                        "longitude": payload["origin_longitude"],
                    }
                }
            },
            "destination": {
                "location": {
                    "latLng": {
                        "latitude": payload["destination_latitude"],
                        "longitude": payload["destination_longitude"],
                    }
                }
            },
            "travelMode": {
                "walking": "WALK",
                "bicycling": "BICYCLE",
            }.get(str(payload.get("travel_mode")), "DRIVE"),
        }
        if body["travelMode"] == "DRIVE":
            body["routingPreference"] = "TRAFFIC_AWARE"
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                "https://routes.googleapis.com/directions/v2:computeRoutes",
                headers=headers,
                json=body,
            )
        if response.is_error:
            raise ExternalServiceError(self._error_message("Google Routes", response))
        routes = response.json().get("routes") or []
        if not routes:
            raise ExternalServiceError("Google Routes no encontro una ruta")
        return routes[0]

    async def tourist_photo_reference(
        self, *, name: str, latitude: float, longitude: float
    ) -> str | None:
        photos = await self.tourist_photo_references(
            name=name,
            latitude=latitude,
            longitude=longitude,
            limit=1,
        )
        return photos[0]["name"] if photos else None

    async def tourist_photo_references(
        self,
        *,
        name: str,
        latitude: float,
        longitude: float,
        limit: int = 8,
    ) -> list[dict[str, str]]:
        unavailable_until = type(self)._photos_unavailable_until
        if unavailable_until and datetime.now(timezone.utc) < unavailable_until:
            return []

        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self._key(),
            "X-Goog-FieldMask": "places.photos",
        }
        body = {
            "textQuery": name,
            "maxResultCount": 1,
            "locationBias": {
                "circle": {
                    "center": {"latitude": latitude, "longitude": longitude},
                    "radius": 5000,
                }
            },
        }
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                "https://places.googleapis.com/v1/places:searchText",
                headers=headers,
                json=body,
            )
        if response.is_error:
            if response.status_code in {401, 403}:
                # La foto es un enriquecimiento opcional. Una clave restringida
                # o una API aún no habilitada no debe ocultar datos MINCETUR.
                type(self)._photos_unavailable_until = datetime.now(
                    timezone.utc
                ) + timedelta(minutes=5)
                return []
            raise ExternalServiceError(self._error_message("Google Places", response))
        places = response.json().get("places") or []
        if not places:
            return []
        photos = places[0].get("photos") or []
        results: list[dict[str, str]] = []
        for photo in photos[:limit]:
            if not photo.get("name"):
                continue
            authors = [
                str(author.get("displayName"))
                for author in photo.get("authorAttributions") or []
                if author.get("displayName")
            ]
            results.append(
                {
                    "name": str(photo["name"]),
                    "attribution": ", ".join(authors) or "Google Places",
                }
            )
        return results

    async def photo_bytes(
        self, *, photo_name: str, max_width: int, max_height: int
    ) -> tuple[bytes, str]:
        safe_name = photo_name.strip().lstrip("/")
        if not safe_name.startswith("places/") or "/photos/" not in safe_name:
            raise ValueError("Referencia de fotografia no valida")
        url = f"https://places.googleapis.com/v1/{safe_name}/media"
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(
                url,
                params={
                    "maxWidthPx": max_width,
                    "maxHeightPx": max_height,
                    "key": self._key(),
                },
            )
        if response.is_error:
            raise ExternalServiceError(
                self._error_message("Google Places Photo", response)
            )
        return response.content, response.headers.get("content-type", "image/jpeg")

