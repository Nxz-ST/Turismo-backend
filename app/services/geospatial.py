import asyncio
import math
import statistics
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.core.config import Settings


class OptionalGeospatialService:
    """Obtiene señales ambientales complementarias, nunca una prueba absoluta."""

    STAC_URL = "https://stac.dataspace.copernicus.eu/v1/search"
    TOKEN_URL = (
        "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/"
        "protocol/openid-connect/token"
    )
    STATISTICS_URL = "https://sh.dataspace.copernicus.eu/statistics/v1"
    ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"

    _EVALSCRIPT = """
//VERSION=3
function setup() {
  return {
    input: [{bands: ["B02", "B03", "B04", "B08", "B11", "SCL", "dataMask"]}],
    output: [
      {id: "indices", bands: ["ndvi", "ndwi", "ndsi", "bsi"], sampleType: "FLOAT32"},
      {id: "dataMask", bands: 1}
    ]
  };
}
function safeIndex(a, b) {
  return (a + b) === 0 ? 0 : (a - b) / (a + b);
}
function evaluatePixel(s) {
  var cloudOrInvalid = [0, 1, 3, 8, 9, 10].indexOf(s.SCL) >= 0;
  var bsiDen = s.B11 + s.B04 + s.B08 + s.B02;
  var bsi = bsiDen === 0 ? 0 : ((s.B11 + s.B04) - (s.B08 + s.B02)) / bsiDen;
  return {
    indices: [
      safeIndex(s.B08, s.B04),
      safeIndex(s.B03, s.B08),
      safeIndex(s.B03, s.B11),
      bsi
    ],
    dataMask: [s.dataMask && !cloudOrInvalid ? 1 : 0]
  };
}
"""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._access_token: str | None = None

    async def evaluate(
        self,
        *,
        category: str | None,
        latitude: float,
        longitude: float,
        device_altitude: float | None = None,
    ) -> dict[str, Any]:
        sentinel_task = (
            self._sentinel_analysis(latitude, longitude)
            if self._settings.sentinel_enabled
            else self._sentinel_disabled()
        )
        sentinel, terrain = await asyncio.gather(
            sentinel_task,
            self._terrain_profile(latitude, longitude),
        )

        if terrain.get("status") == "available" and device_altitude is not None:
            terrain["device_altitude_m"] = round(device_altitude, 1)
            terrain["difference_m"] = round(
                abs(float(terrain["elevation_m"]) - device_altitude), 1
            )

        coherence = self._environmental_coherence(category, sentinel, terrain)
        available = any(
            item.get("status") == "available" for item in (sentinel, terrain)
        )
        return {
            "status": "available" if available else "unavailable",
            "applicable": available,
            "category": category,
            "sentinel": sentinel,
            "terrain": terrain,
            "coherence": coherence,
            "reason": coherence["explanation"],
            "attribution": [
                "Copernicus Data Space Ecosystem / Sentinel-2 L2A",
                "Copernicus DEM GLO-90 vía Open-Meteo",
            ],
        }

    async def _sentinel_disabled(self) -> dict[str, Any]:
        return {
            "status": "disabled",
            "indices_status": "disabled",
            "reason": "La consulta Sentinel-2 está desactivada por configuración.",
        }

    async def _sentinel_analysis(
        self, latitude: float, longitude: float
    ) -> dict[str, Any]:
        scene = await self._latest_sentinel_scene(latitude, longitude)
        if not (
            self._settings.sentinel_client_id
            and self._settings.sentinel_client_secret
        ):
            return {
                **scene,
                "indices_status": "credentials_required",
                "indices": {},
                "reason": (
                    f"{scene.get('reason', '')} Los índices espectrales requieren "
                    "credenciales OAuth de Copernicus."
                ).strip(),
            }

        indices = await self._spectral_statistics(latitude, longitude)
        return {
            **scene,
            "indices_status": indices.get("status", "unavailable"),
            "indices": indices.get("indices", {}),
            "time_series": indices.get("time_series", []),
            "valid_intervals": indices.get("valid_intervals", 0),
            "indices_reason": indices.get("reason"),
        }

    async def _latest_sentinel_scene(
        self, latitude: float, longitude: float
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        start = now - timedelta(days=self._settings.sentinel_lookback_days)
        delta = self._settings.sentinel_buffer_m / 111_320
        payload = {
            "collections": ["sentinel-2-l2a"],
            "bbox": [
                longitude - delta,
                latitude - delta,
                longitude + delta,
                latitude + delta,
            ],
            "datetime": f"{self._iso(start)}/{self._iso(now)}",
            "query": {"eo:cloud_cover": {"lte": 60}},
            "sortby": [{"field": "properties.datetime", "direction": "desc"}],
            "limit": 10,
        }
        try:
            async with httpx.AsyncClient(timeout=25) as client:
                response = await client.post(self.STAC_URL, json=payload)
            response.raise_for_status()
            features = response.json().get("features") or []
            if not features:
                return {
                    "status": "unavailable",
                    "reason": "No hay escenas utilizables en el periodo configurado.",
                }
            scene = min(
                features,
                key=lambda item: float(
                    (item.get("properties") or {}).get("eo:cloud_cover") or 100
                ),
            )
            properties = scene.get("properties") or {}
            cloud_cover = properties.get("eo:cloud_cover")
            return {
                "status": "available",
                "scene_id": scene.get("id"),
                "acquired_at": properties.get("datetime"),
                "cloud_cover_percent": cloud_cover,
                "resolution_m": properties.get("gsd") or 10,
                "platform": properties.get("platform"),
                "quality": (
                    "good"
                    if cloud_cover is not None and float(cloud_cover) <= 20
                    else "usable"
                ),
                "lookback_days": self._settings.sentinel_lookback_days,
                "buffer_m": self._settings.sentinel_buffer_m,
                "catalog_url": "https://browser.stac.dataspace.copernicus.eu",
                "reason": "Se localizó una escena Sentinel-2 para el área reportada.",
            }
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            return {
                "status": "unavailable",
                "reason": f"No se pudo consultar Copernicus: {type(exc).__name__}",
            }

    async def _spectral_statistics(
        self, latitude: float, longitude: float
    ) -> dict[str, Any]:
        try:
            token = await self._oauth_token()
            now = datetime.now(UTC)
            start = now - timedelta(days=self._settings.sentinel_lookback_days)
            payload = {
                "input": {
                    "bounds": {
                        "bbox": self._bbox(
                            latitude,
                            longitude,
                            self._settings.sentinel_buffer_m,
                        ),
                        "properties": {
                            "crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84"
                        },
                    },
                    "data": [
                        {
                            "type": "sentinel-2-l2a",
                            "dataFilter": {
                                "mosaickingOrder": "leastCC",
                                "maxCloudCoverage": 60,
                            },
                        }
                    ],
                },
                "aggregation": {
                    "timeRange": {"from": self._iso(start), "to": self._iso(now)},
                    "aggregationInterval": {"of": "P30D"},
                    "evalscript": self._EVALSCRIPT,
                    "resx": 10,
                    "resy": 10,
                },
            }
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    self.STATISTICS_URL,
                    headers={"Authorization": f"Bearer {token}"},
                    json=payload,
                )
            response.raise_for_status()
            series = self._parse_statistics(response.json())
            if not series:
                return {
                    "status": "unavailable",
                    "reason": "No hubo píxeles válidos sin nubes en el periodo analizado.",
                }
            recent = series[-3:]
            keys = ("ndvi", "ndwi", "ndsi", "bsi")
            indices = {
                key: round(statistics.median(row[key] for row in recent), 4)
                for key in keys
            }
            return {
                "status": "available",
                "indices": indices,
                "time_series": series,
                "valid_intervals": len(series),
                "aggregation": "median_of_latest_3_valid_30_day_intervals",
                "reason": "Índices calculados excluyendo nubes y píxeles inválidos.",
            }
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            return {
                "status": "unavailable",
                "reason": f"No se pudieron calcular los índices: {type(exc).__name__}",
            }

    async def _oauth_token(self) -> str:
        if self._access_token:
            return self._access_token
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                self.TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._settings.sentinel_client_id,
                    "client_secret": self._settings.sentinel_client_secret,
                },
            )
        response.raise_for_status()
        token = response.json().get("access_token")
        if not token:
            raise ValueError("Copernicus no devolvió access_token")
        self._access_token = str(token)
        return self._access_token

    async def _terrain_profile(
        self, latitude: float, longitude: float
    ) -> dict[str, Any]:
        offset = 100 / 111_320
        lon_scale = max(math.cos(math.radians(latitude)), 0.1)
        lon_offset = offset / lon_scale
        latitudes = [
            latitude,
            latitude + offset,
            latitude,
            latitude - offset,
            latitude,
        ]
        longitudes = [
            longitude,
            longitude,
            longitude + lon_offset,
            longitude,
            longitude - lon_offset,
        ]
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(
                    self.ELEVATION_URL,
                    params={
                        "latitude": ",".join(map(str, latitudes)),
                        "longitude": ",".join(map(str, longitudes)),
                    },
                )
            response.raise_for_status()
            values = [
                float(value) for value in response.json().get("elevation") or []
            ]
            if len(values) != 5:
                raise ValueError("Respuesta incompleta de elevación")
            relief = max(values) - min(values)
            return {
                "status": "available",
                "elevation_m": values[0],
                "local_min_elevation_m": min(values),
                "local_max_elevation_m": max(values),
                "local_relief_m": round(relief, 1),
                "estimated_slope_percent": round(relief / 200 * 100, 1),
                "profile_radius_m": 100,
                "resolution_m": 90,
                "source": "Copernicus DEM GLO-90 / Open-Meteo",
            }
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            return {
                "status": "unavailable",
                "reason": (
                    "No se pudo consultar el modelo de elevación: "
                    f"{type(exc).__name__}"
                ),
            }

    def _environmental_coherence(
        self,
        category: str | None,
        sentinel: dict[str, Any],
        terrain: dict[str, Any],
    ) -> dict[str, Any]:
        indices = sentinel.get("indices") or {}
        ndvi = self._number(indices.get("ndvi"))
        ndwi = self._number(indices.get("ndwi"))
        ndsi = self._number(indices.get("ndsi"))
        bsi = self._number(indices.get("bsi"))
        elevation = self._number(terrain.get("elevation_m"))
        slope = self._number(terrain.get("estimated_slope_percent"))

        signals: list[tuple[str, float, str]] = []
        if category == "bosque" and ndvi is not None:
            signals.append(self._threshold("NDVI", ndvi, 0.45, 0.15, True))
        elif category == "lago" and ndwi is not None:
            signals.append(self._threshold("NDWI", ndwi, 0.15, -0.15, True))
        elif category == "nevado":
            if ndsi is not None:
                signals.append(self._threshold("NDSI", ndsi, 0.25, 0.0, True))
            if elevation is not None:
                signals.append(
                    self._threshold("elevación", elevation, 3500, 2500, True)
                )
        elif category == "desierto" and ndvi is not None:
            signals.append(self._threshold("NDVI bajo", ndvi, 0.20, 0.50, False))
            if bsi is not None:
                signals.append(self._threshold("BSI", bsi, 0.05, -0.15, True))
        elif category == "playa":
            if elevation is not None:
                signals.append(
                    self._threshold(
                        "elevación costera", elevation, 100, 500, False
                    )
                )
            if ndwi is not None:
                signals.append(
                    self._threshold("agua cercana", ndwi, 0.0, -0.25, True)
                )
        elif category in {"montana", "volcan"}:
            if elevation is not None:
                signals.append(
                    self._threshold("elevación", elevation, 1500, 300, True)
                )
            if slope is not None:
                signals.append(self._threshold("pendiente", slope, 12, 3, True))
        elif category == "cascada" and slope is not None:
            signals.append(self._threshold("pendiente", slope, 10, 2, True))

        if not signals:
            return {
                "state": "inconclusive",
                "score": None,
                "coverage": 0.0,
                "signals": [],
                "has_contradiction": False,
                "explanation": "No hay señales suficientes para evaluar coherencia ambiental.",
            }

        score = sum(item[1] for item in signals) / len(signals)
        contradiction = any(item[0] == "contradicts" for item in signals)
        confirmation = any(item[0] == "confirms" for item in signals)
        state = (
            "contradicts"
            if contradiction
            else "confirms"
            if confirmation
            else "inconclusive"
        )
        explanations = {
            "confirms": "Las señales disponibles son coherentes con la categoría propuesta.",
            "contradicts": (
                "Existe una contradicción ambiental; el caso debe revisarse, "
                "pero no se rechaza automáticamente."
            ),
            "inconclusive": "Las señales disponibles no son concluyentes.",
        }
        return {
            "state": state,
            "score": round(score, 4),
            "coverage": round(min(1.0, len(signals) / 2), 4),
            "signals": [
                {"state": state_value, "score": value, "detail": detail}
                for state_value, value, detail in signals
            ],
            "has_contradiction": contradiction,
            "explanation": explanations[state],
        }

    @staticmethod
    def _threshold(
        label: str,
        value: float,
        confirm_at: float,
        contradict_at: float,
        higher_confirms: bool,
    ) -> tuple[str, float, str]:
        if higher_confirms:
            state = (
                "confirms"
                if value >= confirm_at
                else "contradicts"
                if value <= contradict_at
                else "inconclusive"
            )
        else:
            state = (
                "confirms"
                if value <= confirm_at
                else "contradicts"
                if value >= contradict_at
                else "inconclusive"
            )
        score = {
            "confirms": 0.85,
            "inconclusive": 0.50,
            "contradicts": 0.25,
        }[state]
        return state, score, f"{label}: {value:.3f}"

    @staticmethod
    def _parse_statistics(payload: dict[str, Any]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for interval in payload.get("data") or []:
            bands = (
                ((interval.get("outputs") or {}).get("indices") or {}).get(
                    "bands"
                )
                or {}
            )
            row: dict[str, Any] = {
                "from": (interval.get("interval") or {}).get("from"),
                "to": (interval.get("interval") or {}).get("to"),
            }
            valid = True
            for key in ("ndvi", "ndwi", "ndsi", "bsi"):
                stats = (bands.get(key) or {}).get("stats") or {}
                mean = stats.get("mean")
                if mean is None or int(stats.get("sampleCount") or 0) == 0:
                    valid = False
                    break
                row[key] = round(float(mean), 4)
            if valid:
                result.append(row)
        return result

    @staticmethod
    def _bbox(
        latitude: float, longitude: float, radius_m: float
    ) -> list[float]:
        lat_delta = radius_m / 111_320
        lon_delta = radius_m / (
            111_320 * max(math.cos(math.radians(latitude)), 0.1)
        )
        return [
            longitude - lon_delta,
            latitude - lat_delta,
            longitude + lon_delta,
            latitude + lat_delta,
        ]

    @staticmethod
    def _number(value: Any) -> float | None:
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _iso(value: datetime) -> str:
        return value.isoformat().replace("+00:00", "Z")
