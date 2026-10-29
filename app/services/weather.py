from typing import Any

import httpx

from app.core.errors import ExternalServiceError


class WeatherService:
    async def forecast(self, *, latitude: float, longitude: float) -> dict[str, Any]:
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "current": (
                "temperature_2m,apparent_temperature,precipitation,"
                "weather_code,wind_speed_10m,is_day"
            ),
            "daily": (
                "weather_code,temperature_2m_max,temperature_2m_min,"
                "precipitation_probability_max,sunrise,sunset"
            ),
            "timezone": "auto",
            "forecast_days": 3,
        }
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                "https://api.open-meteo.com/v1/forecast", params=params
            )
        if response.is_error:
            raise ExternalServiceError(
                f"Open-Meteo respondio {response.status_code}"
            )
        payload = response.json()
        return {
            "current": payload.get("current") or {},
            "daily": payload.get("daily") or {},
            "timezone": payload.get("timezone"),
            "source": "Open-Meteo",
        }
