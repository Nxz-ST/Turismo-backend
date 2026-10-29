from datetime import UTC, datetime, timedelta
import math
from typing import Any
from uuid import UUID

import httpx

from app.core.config import Settings
from app.core.errors import ConfigurationError, ExternalServiceError, ResourceNotFoundError


class SupabaseRepository:
    def __init__(self, settings: Settings):
        self._settings = settings

    @property
    def _headers(self) -> dict[str, str]:
        key = self._settings.supabase_service_role_key
        if not self._settings.supabase_url or not key:
            raise ConfigurationError("Supabase Database no esta configurado")
        return {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        request_headers = {**self._headers, **kwargs.pop("headers", {})}
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.request(
                method,
                f"{self._settings.supabase_rest_url}/{path.lstrip('/')}",
                headers=request_headers,
                **kwargs,
            )
        if response.is_error:
            raise ExternalServiceError(
                f"Supabase respondio {response.status_code}: {response.text[:300]}"
            )
        return response

    async def create_evidence(self, *, user_id: UUID, data: dict[str, Any]) -> dict[str, Any]:
        payload = {**data, "user_id": str(user_id), "status": "pending"}
        response = await self._request(
            "POST",
            "evidences",
            params={"on_conflict": "user_id,client_evidence_id"},
            headers={**self._headers, "Prefer": "resolution=merge-duplicates,return=representation"},
            json=payload,
        )
        return response.json()[0]

    async def get_tourist_place(self, place_id: int) -> dict[str, Any]:
        response = await self._request(
            "GET",
            "lugares_turisticos",
            params={"id": f"eq.{place_id}", "limit": "1"},
        )
        rows = response.json()
        if not rows:
            raise ResourceNotFoundError("El lugar turístico seleccionado no existe")
        return rows[0]

    async def create_route_visit(
        self, *, user_id: UUID, data: dict[str, Any]
    ) -> dict[str, Any]:
        response = await self._request(
            "POST",
            "route_visits",
            params={"on_conflict": "user_id,client_visit_id"},
            headers={
                **self._headers,
                "Prefer": "resolution=merge-duplicates,return=representation",
            },
            json={**data, "user_id": str(user_id)},
        )
        return response.json()[0]

    async def list_route_visits(
        self, user_id: UUID, *, limit: int = 100
    ) -> list[dict[str, Any]]:
        response = await self._request(
            "GET",
            "route_visits",
            params={
                "user_id": f"eq.{user_id}",
                "order": "captured_at.desc",
                "limit": str(limit),
            },
        )
        return response.json()

    async def recent_verified_place_conditions(
        self, place_id: str, *, days: int = 30, limit: int = 40
    ) -> list[dict[str, Any]]:
        cutoff = datetime.now(UTC) - timedelta(days=days)
        response = await self._request(
            "GET",
            "route_visits",
            params={
                "place_id": f"eq.{place_id}",
                "visit_verified": "eq.true",
                "captured_at": f"gte.{cutoff.isoformat()}",
                "or": "(place_condition.not.is.null,access_condition.not.is.null)",
                "select": "place_condition,access_condition,captured_at",
                "order": "captured_at.desc",
                "limit": str(limit),
            },
        )
        return response.json()

    async def get_travel_state(self, user_id: UUID) -> dict[str, Any] | None:
        response = await self._request(
            "GET",
            "user_travel_state",
            params={"user_id": f"eq.{user_id}", "limit": "1"},
        )
        rows = response.json()
        return rows[0] if rows else None

    async def upsert_travel_state(
        self, *, user_id: UUID, data: dict[str, Any]
    ) -> dict[str, Any]:
        response = await self._request(
            "POST",
            "user_travel_state",
            params={"on_conflict": "user_id"},
            headers={
                **self._headers,
                "Prefer": "resolution=merge-duplicates,return=representation",
            },
            json={**data, "user_id": str(user_id), "updated_at": datetime.now(UTC).isoformat()},
        )
        return response.json()[0]

    async def save_presence_samples(
        self, *, user_id: UUID, samples: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        payload = [{**sample, "user_id": str(user_id)} for sample in samples]
        response = await self._request(
            "POST",
            "presence_samples",
            params={"on_conflict": "user_id,client_sample_id"},
            headers={
                **self._headers,
                "Prefer": "resolution=merge-duplicates,return=representation",
            },
            json=payload,
        )
        return response.json()

    async def list_recent_presence_samples(
        self, user_id: UUID, *, hours: int = 24, limit: int = 100
    ) -> list[dict[str, Any]]:
        cutoff = datetime.now(UTC) - timedelta(hours=hours)
        response = await self._request(
            "GET",
            "presence_samples",
            params={
                "user_id": f"eq.{user_id}",
                "recorded_at": f"gte.{cutoff.isoformat()}",
                "order": "recorded_at.desc",
                "limit": str(limit),
            },
        )
        return response.json()

    async def get_presence_sample(
        self, sample_id: UUID, user_id: UUID
    ) -> dict[str, Any]:
        response = await self._request(
            "GET",
            "presence_samples",
            params={"id": f"eq.{sample_id}", "user_id": f"eq.{user_id}", "limit": "1"},
        )
        rows = response.json()
        if not rows:
            raise ResourceNotFoundError("La muestra de presencia no pertenece al usuario o ya no existe")
        return rows[0]

    async def delete_expired_presence_samples(
        self, user_id: UUID, *, retention_hours: int = 72
    ) -> None:
        cutoff = datetime.now(UTC) - timedelta(hours=retention_hours)
        await self._request(
            "DELETE",
            "presence_samples",
            params={
                "user_id": f"eq.{user_id}",
                "recorded_at": f"lt.{cutoff.isoformat()}",
            },
        )

    async def create_presence_attestation(
        self,
        *,
        evidence_id: UUID,
        user_id: UUID,
        latitude: float,
        longitude: float,
        preferred_sample_id: UUID | None = None,
    ) -> dict[str, Any]:
        samples = await self.list_recent_presence_samples(user_id, hours=24, limit=100)
        evaluated: list[dict[str, Any]] = []
        for sample in samples:
            distance = self._distance_m(
                latitude,
                longitude,
                float(sample["latitude"]),
                float(sample["longitude"]),
            )
            evaluated.append({**sample, "distance_m": distance})

        nearby = [
            row
            for row in evaluated
            if row["distance_m"] <= 200
            and float(row.get("accuracy_m") or 10_000) <= 250
            and row.get("is_mocked") is not True
        ]
        precise = [
            row
            for row in nearby
            if row["distance_m"] <= 150 and float(row.get("accuracy_m") or 10_000) <= 100
        ]
        capture_samples = [row for row in precise if row.get("source") == "capture"]
        if capture_samples or len(precise) >= 2:
            status = "confirmed"
            reason = "El dispositivo registro presencia precisa cerca del atractivo durante las ultimas 24 horas."
        elif nearby:
            status = "partial"
            reason = "Existe una muestra reciente cercana, pero su cantidad o precision es limitada."
        elif samples:
            status = "not_confirmed"
            reason = "No se encontraron muestras recientes suficientemente cercanas al atractivo."
        else:
            status = "unavailable"
            reason = "No hay muestras GPS disponibles dentro de la ventana movil de 24 horas."

        valid = precise or nearby
        latest = max(valid, key=lambda row: row["recorded_at"]) if valid else None
        accuracies = sorted(float(row["accuracy_m"]) for row in valid)
        median_accuracy = (
            accuracies[len(accuracies) // 2] if accuracies else None
        )
        expires_at = None
        if latest:
            recorded = datetime.fromisoformat(
                str(latest["recorded_at"]).replace("Z", "+00:00")
            )
            expires_at = (recorded.astimezone(UTC) + timedelta(hours=24)).isoformat()
        attestation = {
            "status": status,
            "reason": reason,
            "radius_m": 200,
            "samples_count": len(valid),
            "precise_samples_count": len(precise),
            "minimum_distance_m": round(min((row["distance_m"] for row in valid), default=0), 1)
            if valid
            else None,
            "median_accuracy_m": round(median_accuracy, 1) if median_accuracy is not None else None,
            "first_seen_at": min((row["recorded_at"] for row in valid), default=None),
            "last_seen_at": latest.get("recorded_at") if latest else None,
            "expires_at": expires_at,
            "mocked_samples_excluded": sum(row.get("is_mocked") is True for row in evaluated),
            "note": "Confirma presencia aproximada del dispositivo, no la autoria ni el instante exacto de la fotografia.",
        }
        response = await self._request(
            "PATCH",
            "evidences",
            params={"id": f"eq.{evidence_id}", "user_id": f"eq.{user_id}"},
            headers={**self._headers, "Prefer": "return=representation"},
            json={
                "presence_status": status,
                "presence_expires_at": expires_at,
                "presence_attestation": attestation,
            },
        )
        rows = response.json()
        if not rows:
            raise ResourceNotFoundError("Evidencia no encontrada")
        return rows[0]

    @staticmethod
    def _distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        radius = 6_371_000
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        value = (
            math.sin(dphi / 2) ** 2
            + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
        )
        return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))

    async def get_evidence(self, evidence_id: UUID, user_id: UUID | None = None) -> dict[str, Any]:
        params: dict[str, str] = {"id": f"eq.{evidence_id}", "limit": "1"}
        if user_id:
            params["user_id"] = f"eq.{user_id}"
        response = await self._request("GET", "evidences", params=params)
        rows = response.json()
        if not rows:
            raise ResourceNotFoundError("Evidencia no encontrada")
        return rows[0]

    async def list_evidences(self, user_id: UUID, limit: int = 50) -> list[dict[str, Any]]:
        response = await self._request(
            "GET",
            "evidences",
            params={
                "user_id": f"eq.{user_id}",
                "order": "created_at.desc",
                "limit": str(limit),
            },
        )
        return response.json()

    async def list_review_queue(
        self,
        *,
        statuses: list[str] | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        params = {
            "order": "created_at.desc",
            "limit": str(limit),
        }
        if statuses:
            params["status"] = f"in.({','.join(statuses)})"
        response = await self._request(
            "GET",
            "evidences",
            params=params,
        )
        return response.json()

    async def list_coordinate_reviews(
        self,
        *,
        statuses: list[str] | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        params = {
            "order": "created_at.desc",
            "limit": str(limit),
        }
        if statuses:
            params["status"] = f"in.({','.join(statuses)})"
        response = await self._request(
            "GET",
            "place_coordinate_reviews",
            params=params,
        )
        reviews = response.json()
        place_ids = sorted({str(row["place_id"]) for row in reviews})
        if not place_ids:
            return []
        places_response = await self._request(
            "GET",
            "lugares_turisticos",
            params={
                "id": f"in.({','.join(place_ids)})",
                "select": (
                    "id,codigo,nombre,departamento,provincia,distrito,latitud,"
                    "longitud,coordinate_quality,coordinate_source,access_latitud,"
                    "access_longitud,access_notes,access_source"
                ),
            },
        )
        places = {str(row["id"]): row for row in places_response.json()}
        return [
            {**review, "place": places.get(str(review["place_id"]), {})}
            for review in reviews
        ]

    async def get_coordinate_review(self, review_id: UUID) -> dict[str, Any]:
        response = await self._request(
            "GET",
            "place_coordinate_reviews",
            params={"id": f"eq.{review_id}", "limit": "1"},
        )
        rows = response.json()
        if not rows:
            raise ResourceNotFoundError("Revisión de coordenadas no encontrada")
        return rows[0]

    async def save_coordinate_candidate(
        self,
        *,
        review_id: UUID,
        review_type: str,
        latitude: float,
        longitude: float,
        name: str | None,
        address: str | None,
        source: str,
        source_reference: str | None,
        confidence: float | None,
    ) -> dict[str, Any]:
        review = await self.get_coordinate_review(review_id)
        distance_m = self._distance_m(
            float(review["original_latitude"]),
            float(review["original_longitude"]),
            latitude,
            longitude,
        )
        response = await self._request(
            "PATCH",
            "place_coordinate_reviews",
            params={"id": f"eq.{review_id}"},
            headers={**self._headers, "Prefer": "return=representation"},
            json={
                "review_type": review_type,
                "status": "candidate",
                "candidate_latitude": latitude,
                "candidate_longitude": longitude,
                "candidate_name": name,
                "candidate_address": address,
                "candidate_source": source,
                "candidate_reference": source_reference,
                "candidate_distance_m": round(distance_m, 1),
                "confidence": confidence,
            },
        )
        rows = response.json()
        if not rows:
            raise ResourceNotFoundError("Revisión de coordenadas no encontrada")
        return rows[0]

    async def reject_coordinate_review(
        self,
        *,
        review_id: UUID,
        reviewer_id: UUID,
        note: str,
    ) -> dict[str, Any]:
        response = await self._request(
            "PATCH",
            "place_coordinate_reviews",
            params={"id": f"eq.{review_id}"},
            headers={**self._headers, "Prefer": "return=representation"},
            json={
                "status": "rejected",
                "reviewed_by": str(reviewer_id),
                "review_note": note,
                "reviewed_at": datetime.now(UTC).isoformat(),
            },
        )
        rows = response.json()
        if not rows:
            raise ResourceNotFoundError("Revisión de coordenadas no encontrada")
        return rows[0]

    async def apply_coordinate_review(
        self,
        *,
        review_id: UUID,
        reviewer_id: UUID,
        note: str,
    ) -> dict[str, Any]:
        response = await self._request(
            "POST",
            "rpc/apply_place_coordinate_review",
            json={
                "p_review_id": str(review_id),
                "p_reviewer_id": str(reviewer_id),
                "p_note": note,
            },
        )
        payload = response.json()
        return payload[0] if isinstance(payload, list) and payload else payload

    async def latest_results_for(
        self, evidence_ids: list[str]
    ) -> dict[str, dict[str, Any]]:
        if not evidence_ids:
            return {}
        response = await self._request(
            "GET",
            "validation_results",
            params={
                "evidence_id": f"in.({','.join(evidence_ids)})",
                "select": (
                    "evidence_id,geospatial_result,source,created_at,score,coverage,"
                    "component_scores,duplicate_result,rule_version,reason"
                ),
                "order": "created_at.desc",
            },
        )
        latest: dict[str, dict[str, Any]] = {}
        for row in response.json():
            evidence_id = str(row["evidence_id"])
            current = latest.get(evidence_id)
            if current is None or (
                not current.get("geospatial_result") and row.get("geospatial_result")
            ):
                latest[evidence_id] = row
        return latest

    async def update_evidence(self, evidence_id: UUID, values: dict[str, Any]) -> dict[str, Any]:
        response = await self._request(
            "PATCH",
            "evidences",
            params={"id": f"eq.{evidence_id}"},
            headers={**self._headers, "Prefer": "return=representation"},
            json=values,
        )
        rows = response.json()
        if not rows:
            raise ResourceNotFoundError("Evidencia no encontrada")
        return rows[0]

    async def create_job(self, evidence_id: UUID) -> dict[str, Any]:
        response = await self._request(
            "POST",
            "validation_jobs",
            headers={**self._headers, "Prefer": "return=representation"},
            json={"evidence_id": str(evidence_id), "status": "pending"},
        )
        return response.json()[0]

    async def save_processing_event(
        self,
        *,
        evidence_id: UUID,
        stage: str,
        status: str,
        title: str,
        detail: str = "",
        duration_ms: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        try:
            await self._request(
                "POST",
                "processing_events",
                json={
                    "evidence_id": str(evidence_id),
                    "stage": stage,
                    "status": status,
                    "title": title,
                    "detail": detail,
                    "duration_ms": duration_ms,
                    "metadata": metadata or {},
                },
            )
        except ExternalServiceError as exc:
            if "processing_events" not in str(exc):
                raise

    async def processing_events_for(
        self, evidence_ids: list[str]
    ) -> dict[str, list[dict[str, Any]]]:
        if not evidence_ids:
            return {}
        try:
            response = await self._request(
                "GET",
                "processing_events",
                params={
                    "evidence_id": f"in.({','.join(evidence_ids)})",
                    "order": "created_at.asc",
                },
            )
        except ExternalServiceError as exc:
            if "processing_events" in str(exc):
                return {}
            raise
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in response.json():
            grouped.setdefault(str(row["evidence_id"]), []).append(row)
        return grouped

    async def update_job(self, job_id: UUID, values: dict[str, Any]) -> None:
        await self._request(
            "PATCH",
            "validation_jobs",
            params={"id": f"eq.{job_id}"},
            json=values,
        )

    async def save_validation_result(
        self,
        *,
        evidence_id: UUID,
        model_result: dict[str, Any],
        decision: dict[str, Any],
        source: str = "existing_multimodal_model",
    ) -> None:
        await self._request(
            "POST",
            "validation_results",
            json={
                "evidence_id": str(evidence_id),
                "source": source,
                "model_version": str(model_result.get("model_version") or "unknown"),
                "raw_result": model_result,
                "status": decision["status"],
                "category": decision.get("category"),
                "confidence": decision.get("confidence"),
                "score": decision.get("score"),
                "coverage": decision.get("coverage"),
                "reason": decision.get("reason"),
                "geospatial_result": decision.get("geospatial_result") or {},
                "component_scores": decision.get("components") or {},
                "duplicate_result": decision.get("duplicate_result") or {},
                "rule_version": decision.get("rule_version") or "legacy",
            },
        )

    async def save_manual_review(
        self,
        *,
        evidence_id: UUID,
        reviewer_id: UUID,
        status: str,
        category: str | None,
        reason: str,
    ) -> dict[str, Any]:
        await self._request(
            "POST",
            "validation_results",
            json={
                "evidence_id": str(evidence_id),
                "source": "manual_review",
                "model_version": "human-v1",
                "status": status,
                "category": category,
                "reason": reason,
                "raw_result": {
                    "reviewer_id": str(reviewer_id),
                    "reviewed_manually": True,
                },
            },
        )
        await self.save_processing_event(
            evidence_id=evidence_id,
            stage="human_review",
            status="completed",
            title="Revision humana completada",
            detail=reason,
            metadata={"reviewer_id": str(reviewer_id), "decision": status},
        )
        values: dict[str, Any] = {
            "status": status,
            "decision_reason": reason,
        }
        if category is not None:
            values["predicted_category"] = category
        return await self.update_evidence(evidence_id, values)

    async def save_satellite_observation(
        self,
        *,
        evidence_id: UUID,
        geospatial_result: dict[str, Any],
    ) -> None:
        sentinel = geospatial_result.get("sentinel") or {}
        status = (
            "available" if sentinel.get("status") == "available" else "unavailable"
        )
        await self._request(
            "POST",
            "satellite_requests",
            json={
                "evidence_id": str(evidence_id),
                "provider": "sentinel_2",
                "status": status,
                "completed_at": datetime.now(UTC).isoformat(),
                "acquisition_date": sentinel.get("acquired_at"),
                "cloud_coverage": sentinel.get("cloud_cover_percent"),
                "spatial_resolution_m": sentinel.get("resolution_m"),
                "result": geospatial_result,
            },
        )

    async def nearby_places(self, latitude: float, longitude: float, radius: float) -> list[dict]:
        response = await self._request(
            "POST",
            "rpc/obtener_lugares_cercanos",
            json={
                "lat_usuario": latitude,
                "lng_usuario": longitude,
                "radio_metros": radius,
            },
        )
        rpc_rows = response.json()
        if len(rpc_rows) >= 8:
            return rpc_rows

        # Compatibilidad con la función geoespacial heredada: algunas versiones
        # confunden el parámetro `radio_metros` con la columna homónima y solo
        # devuelven dos o tres filas. El catálogo actual es pequeño (530 filas),
        # por lo que un respaldo calculado en el backend evita rutas incompletas
        # hasta aplicar la migración que corrige la RPC.
        catalog_response = await self._request(
            "GET",
            "lugares_turisticos",
            params={"select": "*", "limit": 1000},
        )
        nearby = [
            row
            for row in catalog_response.json()
            if row.get("latitud") is not None
            and row.get("longitud") is not None
            and self._distance_m(
                latitude,
                longitude,
                float(row["latitud"]),
                float(row["longitud"]),
            )
            <= radius
        ]
        nearby.sort(
            key=lambda row: self._distance_m(
                latitude,
                longitude,
                float(row["latitud"]),
                float(row["longitud"]),
            )
        )
        return nearby if len(nearby) > len(rpc_rows) else rpc_rows

    async def nearby_reported_places(
        self, latitude: float, longitude: float, radius: float
    ) -> list[dict[str, Any]]:
        params = {
            "lat_usuario": latitude,
            "lng_usuario": longitude,
            "radio_metros": radius,
        }
        legacy = await self._request(
            "POST",
            "rpc/obtener_reportes_cercanos",
            json=params,
        )
        current = await self._request(
            "POST",
            "rpc/obtener_evidencias_cercanas",
            json=params,
        )
        return [*legacy.json(), *current.json()]

    async def nearby_community_places(
        self, latitude: float, longitude: float, radius: float
    ) -> list[dict[str, Any]]:
        response = await self._request(
            "POST",
            "rpc/obtener_evidencias_cercanas",
            json={
                "lat_usuario": latitude,
                "lng_usuario": longitude,
                "radio_metros": radius,
            },
        )
        return response.json()

