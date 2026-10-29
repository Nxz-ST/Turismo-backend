import math
import unicodedata
from time import perf_counter
from datetime import UTC, datetime
from uuid import UUID

from app.core.config import Settings
from app.core.errors import ConfigurationError, ExternalServiceError
from app.domain.decision import (
    EvidenceStatus,
    build_multimodal_decision,
    decide_from_existing_model,
)
from app.services.ai import ExistingAiService
from app.services.geospatial import OptionalGeospatialService
from app.services.storage import R2StorageService
from app.services.supabase import SupabaseRepository


class ValidationWorkflow:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._repository = SupabaseRepository(settings)
        self._storage = R2StorageService(settings)
        self._ai = ExistingAiService(settings)
        self._geospatial = OptionalGeospatialService(settings)

    async def process(self, evidence_id: UUID, job_id: UUID) -> None:
        try:
            evidence = await self._repository.get_evidence(evidence_id)
            await self._repository.update_job(
                job_id,
                {"status": "processing_ai", "started_at": datetime.now(UTC).isoformat()},
            )
            await self._repository.update_evidence(
                evidence_id, {"status": EvidenceStatus.PROCESSING_AI.value}
            )
            await self._repository.save_processing_event(
                evidence_id=evidence_id,
                stage="visual_ai",
                status="processing",
                title="Analisis visual iniciado",
                detail="El motor multimodal esta evaluando la fotografia.",
            )

            image_url = self._storage.create_download_url(evidence["object_key"])
            source = "existing_multimodal_model"
            ai_started = perf_counter()
            try:
                model_result = await self._ai.predict(
                    image_url=image_url,
                    filename=evidence["original_filename"],
                    content_type=evidence["mime_type"],
                    latitude=evidence["latitude"],
                    longitude=evidence["longitude"],
                    altitude=evidence.get("altitude") or 0,
                )
                model_decision = decide_from_existing_model(model_result)
                await self._repository.save_processing_event(
                    evidence_id=evidence_id,
                    stage="visual_ai",
                    status="completed",
                    title="Analisis visual completado",
                    detail=(
                        f"Categoria {model_decision.category or 'no concluyente'}; "
                        f"confianza {model_decision.confidence:.0%}."
                    ),
                    duration_ms=int((perf_counter() - ai_started) * 1000),
                    metadata={
                        "category": model_decision.category,
                        "confidence": model_decision.confidence,
                        "model_version": model_result.get("model_version"),
                    },
                )
                await self._repository.update_job(job_id, {"status": "processing_gis"})
                await self._repository.update_evidence(
                    evidence_id, {"status": EvidenceStatus.PROCESSING_GIS.value}
                )
                await self._repository.save_processing_event(
                    evidence_id=evidence_id,
                    stage="geospatial",
                    status="processing",
                    title="Validacion geoespacial iniciada",
                    detail="Consultando MINCETUR, duplicidad, Sentinel y relieve.",
                )
                geo_started = perf_counter()
                geospatial = await self._geospatial.evaluate(
                    category=model_decision.category,
                    latitude=evidence["latitude"],
                    longitude=evidence["longitude"],
                    device_altitude=evidence.get("altitude"),
                )
                duplicate_result = await self._duplicate_context(
                    evidence, model_decision.category
                )
                if (
                    evidence.get("contribution_type") == "existing_place"
                    and evidence.get("target_place_id") is not None
                ):
                    duplicate_result["status"] = "linked_target"
                    duplicate_result["target_place_id"] = evidence["target_place_id"]
                    duplicate_result["target_distance_m"] = evidence.get(
                        "target_distance_m"
                    )
                    duplicate_result["note"] = (
                        "La coincidencia es esperada: el usuario vinculó la "
                        "evidencia a un lugar existente."
                    )
                await self._repository.save_processing_event(
                    evidence_id=evidence_id,
                    stage="geospatial",
                    status="completed",
                    title="Validacion geoespacial completada",
                    detail=str(
                        (geospatial.get("coherence") or {}).get("explanation")
                        or "Senales geograficas registradas."
                    ),
                    duration_ms=int((perf_counter() - geo_started) * 1000),
                    metadata={
                        "coherence": (geospatial.get("coherence") or {}).get("state"),
                        "duplicate_status": duplicate_result.get("status"),
                    },
                )
                decision = build_multimodal_decision(
                    model=model_decision,
                    evidence=evidence,
                    geospatial=geospatial,
                    duplicate_result=duplicate_result,
                    candidate_threshold=self._settings.candidate_score_threshold,
                    minimum_coverage=self._settings.minimum_evidence_coverage,
                    minimum_visual_confidence=(
                        self._settings.minimum_visual_confidence
                    ),
                    rule_version=self._settings.decision_rule_version,
                )
                source = self._settings.decision_rule_version
                decision_data = {
                    "status": decision.status.value,
                    "category": decision.category,
                    "confidence": decision.confidence,
                    "score": decision.score,
                    "coverage": decision.coverage,
                    "reason": decision.reason,
                    "geospatial_result": geospatial,
                    "components": decision.components,
                    "duplicate_result": duplicate_result,
                    "duplicate_status": decision.duplicate_status,
                    "rule_version": decision.rule_version,
                }
            except (ConfigurationError, ExternalServiceError) as exc:
                await self._repository.save_processing_event(
                    evidence_id=evidence_id,
                    stage="visual_ai",
                    status="failed",
                    title="Analisis visual no disponible",
                    detail=str(exc)[:500],
                    duration_ms=int((perf_counter() - ai_started) * 1000),
                )
                source = "ai_unavailable"
                model_result = {"error": str(exc)[:500]}
                geospatial = await self._geospatial.evaluate(
                    category=None,
                    latitude=evidence["latitude"],
                    longitude=evidence["longitude"],
                    device_altitude=evidence.get("altitude"),
                )
                decision_data = {
                    "status": EvidenceStatus.NEEDS_REVIEW.value,
                    "category": None,
                    "confidence": 0.0,
                    "score": 0.0,
                    "coverage": 0.0,
                    "reason": (
                        "El análisis automático no estuvo disponible. "
                        "La evidencia fue conservada para revisión humana."
                    ),
                    "geospatial_result": geospatial,
                    "components": {},
                    "duplicate_result": {"status": "not_evaluated"},
                    "duplicate_status": "not_evaluated",
                    "rule_version": self._settings.decision_rule_version,
                }
            if self._settings.sentinel_enabled:
                await self._repository.save_satellite_observation(
                    evidence_id=evidence_id,
                    geospatial_result=decision_data["geospatial_result"],
                )
            await self._repository.save_validation_result(
                evidence_id=evidence_id,
                model_result=model_result,
                decision=decision_data,
                source=source,
            )
            await self._repository.update_evidence(
                evidence_id,
                {
                    "status": decision_data["status"],
                    "predicted_category": decision_data["category"],
                    "confidence": decision_data["confidence"],
                    "score": decision_data["score"],
                    "evidence_coverage": decision_data["coverage"],
                    "duplicate_status": decision_data["duplicate_status"],
                    "decision_reason": decision_data["reason"],
                },
            )
            await self._repository.save_processing_event(
                evidence_id=evidence_id,
                stage="decision",
                status="completed",
                title="Resultado preliminar generado",
                detail=decision_data["reason"],
                metadata={
                    "status": decision_data["status"],
                    "score": decision_data["score"],
                    "coverage": decision_data["coverage"],
                    "rule_version": decision_data["rule_version"],
                },
            )
            await self._repository.update_job(
                job_id,
                {"status": "completed", "completed_at": datetime.now(UTC).isoformat()},
            )
        except Exception as exc:
            try:
                await self._repository.save_processing_event(
                    evidence_id=evidence_id,
                    stage="decision",
                    status="failed",
                    title="No se pudo completar el procesamiento",
                    detail=str(exc)[:500],
                )
            except Exception:
                pass
            await self._repository.update_evidence(
                evidence_id,
                {"status": EvidenceStatus.FAILED.value, "decision_reason": str(exc)[:500]},
            )
            await self._repository.update_job(
                job_id,
                {
                    "status": "failed",
                    "error": str(exc)[:1000],
                    "completed_at": datetime.now(UTC).isoformat(),
                },
            )

    async def _duplicate_context(
        self, evidence: dict, predicted_category: str | None
    ) -> dict:
        """La duplicidad es una salida separada; una falla no bloquea el score."""
        official: list[dict] = []
        community: list[dict] = []
        errors: list[str] = []
        try:
            official = await self._repository.nearby_places(
                evidence["latitude"], evidence["longitude"], 500
            )
        except (ConfigurationError, ExternalServiceError) as exc:
            errors.append(f"mincetur: {type(exc).__name__}")
        try:
            community = await self._repository.nearby_community_places(
                evidence["latitude"], evidence["longitude"], 150
            )
            community = [
                row for row in community if str(row.get("id")) != str(evidence["id"])
            ]
        except (ConfigurationError, ExternalServiceError) as exc:
            errors.append(f"comunidad: {type(exc).__name__}")

        candidates = [
            self._duplicate_candidate(evidence, row, predicted_category, "mincetur")
            for row in official
        ] + [
            self._duplicate_candidate(evidence, row, predicted_category, "community")
            for row in community
        ]
        candidates = [item for item in candidates if item is not None]
        high_matches = [item for item in candidates if item["high_match"]]

        if high_matches:
            status = "high_match"
        elif candidates or official or community:
            status = "nearby_match"
        elif errors and not official and not community:
            status = "not_evaluated"
        else:
            status = "no_match"
        return {
            "status": status,
            "official_matches": len(official),
            "community_matches": len(community),
            "candidates": sorted(
                candidates,
                key=lambda item: item.get("distance_m") or 999_999,
            )[:10],
            "errors": errors,
            "note": "La coincidencia indica posible duplicidad, no validez del lugar.",
        }

    @classmethod
    def _duplicate_candidate(
        cls,
        evidence: dict,
        row: dict,
        predicted_category: str | None,
        source: str,
    ) -> dict | None:
        latitude = cls._first_number(row, "latitud", "latitude")
        longitude = cls._first_number(row, "longitud", "longitude")
        if latitude is None or longitude is None:
            return None
        distance = cls._distance_m(
            float(evidence["latitude"]),
            float(evidence["longitude"]),
            latitude,
            longitude,
        )
        name = str(row.get("nombre") or row.get("name") or "")
        similarity = cls._name_similarity(str(evidence.get("name") or ""), name)
        row_category = str(
            row.get("categoria_ia")
            or row.get("categoria")
            or row.get("categoria_texto")
            or ""
        ).lower()
        category_match = bool(
            predicted_category and row_category and predicted_category in row_category
        )
        return {
            "id": row.get("id"),
            "name": name,
            "source": source,
            "distance_m": round(distance, 1),
            "name_similarity": round(similarity, 3),
            "category_match": category_match,
            "high_match": distance <= 75 and (similarity >= 0.60 or category_match),
        }

    @staticmethod
    def _first_number(row: dict, *keys: str) -> float | None:
        for key in keys:
            try:
                value = row.get(key)
                if value is not None:
                    return float(value)
            except (TypeError, ValueError):
                continue
        return None

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

    @staticmethod
    def _name_similarity(left: str, right: str) -> float:
        def tokens(value: str) -> set[str]:
            normalized = unicodedata.normalize("NFKD", value.lower())
            ascii_value = "".join(
                char for char in normalized if not unicodedata.combining(char)
            )
            return {part for part in ascii_value.split() if len(part) > 2}

        left_tokens, right_tokens = tokens(left), tokens(right)
        if not left_tokens or not right_tokens:
            return 0.0
        return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)

