from fastapi import APIRouter

from app.api.routes import admin, evidences, health, itineraries, maps, places, presence, travel, uploads, visits, weather


api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(uploads.router, prefix="/uploads", tags=["uploads"])
api_router.include_router(evidences.router, prefix="/evidences", tags=["evidences"])
api_router.include_router(places.router, prefix="/places", tags=["places"])
api_router.include_router(maps.router, prefix="/maps", tags=["maps"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
api_router.include_router(itineraries.router, prefix="/itineraries", tags=["itineraries"])
api_router.include_router(presence.router, prefix="/presence", tags=["presence"])
api_router.include_router(visits.router, prefix="/visits", tags=["visits"])
api_router.include_router(weather.router, prefix="/weather", tags=["weather"])
api_router.include_router(travel.router, prefix="/me/travel", tags=["travel"])

