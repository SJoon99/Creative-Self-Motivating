"""SmartFarm Gemma/RAG adapter and blueprint candidate helpers.

This module is deliberately free of Omniverse imports so the planning contract
can be tested outside Kit.  TwinX RAG has two supported contracts:

* ``/blueprints/generate``: state-aware Blueprint A/B/C generation from the
  current Baseline Twin snapshot.
* ``/recommend``: legacy date/stage-based setpoint recommendation.  The local
  twin can still convert those setpoints into fallback actuator candidates.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import urllib.error
import urllib.request
from typing import Any, Callable, Mapping

DEFAULT_REFERENCE_DATE = dt.date(2026, 10, 23)
DEFAULT_TIMEOUT_SECONDS = 30.0
UI_TEXT_CONTRACT = (
    "Return every human-facing label, summary, rationale, intent, tradeoff, and evidence summary in concise "
    "English ASCII only. Do not use Korean or other non-ASCII glyphs because the Omniverse demo UI renders "
    "unsupported glyphs as question marks."
)


class RagAdapterError(RuntimeError):
    """Raised when the external RAG service cannot return usable advice."""

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def is_blueprint_generation_unsupported(exc: RagAdapterError) -> bool:
    """Return true only for legacy deployments without the new endpoint."""
    return exc.status_code in {404, 405, 501}


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    return int(round(_as_float(value, float(default))))


def _bounded_int(value: Any, default: int, minimum: float, maximum: float) -> int:
    return _as_int(_clamp(_as_float(value, default), minimum, maximum), default)


def _date_from_any(value: Any, default: dt.date = DEFAULT_REFERENCE_DATE) -> dt.date:
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str) and value:
        try:
            return dt.date.fromisoformat(value[:10])
        except ValueError:
            return default
    return default


def _ui_safe_text(value: Any, fallback: str) -> str:
    """Return text that can be rendered by the current Omniverse UI font.

    The TwinX Gemma/RAG endpoint can legitimately answer in Korean, but the
    Kit UI used for this demo renders unsupported glyphs as ``?``.  For the
    operator dashboard, prefer an English fallback over showing unreadable
    question-mark strings.
    """

    text = str(value or "").strip()
    if not text:
        return fallback
    text = text.replace("CO₂", "CO2").replace("°", " deg ")
    try:
        text.encode("ascii")
    except UnicodeEncodeError:
        return fallback
    if text.count("?") >= 2:
        return fallback
    return " ".join(text.split())


def _setpoint_target(setpoints: Mapping[str, Any], key: str, default: float) -> float:
    raw = setpoints.get(key) or {}
    if isinstance(raw, Mapping):
        return _as_float(raw.get("target", raw.get("min", default)), default)
    return _as_float(raw, default)


def _setpoint_range(setpoints: Mapping[str, Any], key: str, default_min: float, default_max: float) -> dict[str, float]:
    raw = setpoints.get(key) or {}
    if not isinstance(raw, Mapping):
        target = _as_float(raw, (default_min + default_max) / 2.0)
        return {"min": default_min, "max": default_max, "target": target}
    target = _as_float(raw.get("target"), (default_min + default_max) / 2.0)
    return {
        "min": _as_float(raw.get("min"), default_min),
        "max": _as_float(raw.get("max"), default_max),
        "target": target,
    }


def build_state_snapshot(
    sensor_state: Mapping[str, Any],
    crop_state: Mapping[str, Any],
    actuator_state: Mapping[str, Any],
    *,
    growth_kpi: Mapping[str, Any] | None = None,
    vision_assessment: Mapping[str, Any] | None = None,
    goal: str = "balanced",
    constraints: Mapping[str, Any] | None = None,
    reference_date: Any = DEFAULT_REFERENCE_DATE,
) -> dict[str, Any]:
    """Create the single state object used for RAG-backed blueprint planning."""
    ref_date = _date_from_any(reference_date)
    current_day = _as_int(crop_state.get("day", sensor_state.get("twin_day", 34)), 34)
    planting_date = ref_date - dt.timedelta(days=max(0, current_day))
    return {
        "facilityId": "smartfarm-spark-a7ce",
        "goal": goal or "balanced",
        "referenceDate": ref_date.isoformat(),
        "plantingDate": planting_date.isoformat(),
        "currentDay": current_day,
        "sensorState": dict(sensor_state),
        "cropState": dict(crop_state),
        "actuatorState": dict(actuator_state),
        "growthKpi": dict(growth_kpi or {}),
        "visionAssessment": dict(vision_assessment or {}),
        "constraints": dict(constraints or {"maxOpexIncreasePct": 18, "diseaseRiskMax": "controlled"}),
    }


def normalize_rag_recommendation(payload: Mapping[str, Any] | list[Mapping[str, Any]]) -> dict[str, Any]:
    """Normalize TwinX RAG `/recommend` output into the app's advice schema."""
    if isinstance(payload, list):
        if not payload:
            raise RagAdapterError("RAG recommendation list is empty")
        payload = payload[0]
    if not isinstance(payload, Mapping):
        raise RagAdapterError("RAG recommendation payload is not an object")

    setpoints = payload.get("setpoints") or {}
    if not isinstance(setpoints, Mapping):
        raise RagAdapterError("RAG recommendation missing setpoints object")

    supplemental = setpoints.get("supplemental_light") or {}
    nutrient = setpoints.get("nutrient") or {}
    recommended = {
        "temperatureDayC": _setpoint_range(setpoints, "temp_day_c", 18.0, 23.0),
        "temperatureNightC": _setpoint_range(setpoints, "temp_night_c", 7.0, 12.0),
        "humidityPct": _setpoint_range(setpoints, "humidity_pct", 60.0, 72.0),
        "co2Ppm": _setpoint_range(setpoints, "co2_ppm", 900.0, 1500.0),
        "supplementalLight": {
            "on": bool(supplemental.get("on", False)) if isinstance(supplemental, Mapping) else False,
            "hoursPerDay": _as_float(supplemental.get("hours_per_day", 0) if isinstance(supplemental, Mapping) else 0, 0.0),
            "note": str(supplemental.get("note", "")) if isinstance(supplemental, Mapping) else "",
        },
        "nutrient": {
            "ecDsM": _as_float(nutrient.get("ec_ds_m", 1.0) if isinstance(nutrient, Mapping) else 1.0, 1.0),
            "ph": _as_float(nutrient.get("ph", 6.2) if isinstance(nutrient, Mapping) else 6.2, 6.2),
            "note": str(nutrient.get("note", "")) if isinstance(nutrient, Mapping) else "",
        },
    }
    raw_sources = list(payload.get("sources") or [])
    evidence = [
        {"source": str(source), "summary": str(source), "kind": "rag-source"}
        for source in raw_sources
    ]
    return {
        "provider": "twinx-gemma-rag",
        "model": payload.get("model", "gemma4"),
        "date": payload.get("date"),
        "plantingDate": payload.get("planting_date"),
        "daysAfterPlanting": payload.get("days_after_planting"),
        "growthStage": payload.get("growth_stage"),
        "seasonalAdjustment": payload.get("seasonal_adjustment"),
        "recommendedSetpoints": recommended,
        "evidence": evidence,
        "explanation": payload.get("explanation", ""),
        "raw": dict(payload),
    }


def _normalize_recommended_setpoints(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        return {}
    if any(key in raw for key in ("temperatureDayC", "humidityPct", "co2Ppm", "supplementalLight")):
        return dict(raw)
    if any(key in raw for key in ("temp_day_c", "humidity_pct", "co2_ppm", "supplemental_light")):
        return normalize_rag_recommendation({"setpoints": raw}).get("recommendedSetpoints", {})
    return dict(raw)


def _evidence_items(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        raw = [] if raw is None else [raw]
    evidence: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, Mapping):
            summary = item.get("summary") or item.get("text") or item.get("source") or str(item)
            evidence.append({
                "source": item.get("source", "TwinX RAG"),
                "page": item.get("page"),
                "summary": summary,
                "similarity": item.get("similarity"),
            })
        else:
            evidence.append({"source": str(item), "summary": str(item)})
    return evidence


def _target_value(raw: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in raw and raw[key] is not None:
            return raw[key]
    return default


def _normalize_actuator_targets(raw: Mapping[str, Any], snapshot: Mapping[str, Any] | None = None) -> dict[str, Any]:
    base = _actuator_base(snapshot or {})
    return {
        "led_intensity_percent": _bounded_int(
            _target_value(raw, "ledIntensityPercent", "led_intensity_percent", "led", default=base["led_intensity_percent"]),
            base["led_intensity_percent"],
            0,
            100,
        ),
        "photoperiod_hours": _bounded_int(
            _target_value(raw, "photoperiodHours", "photoperiod_hours", "photoperiod", default=base["photoperiod_hours"]),
            base["photoperiod_hours"],
            8,
            18,
        ),
        "water_valve_open": bool(
            _target_value(raw, "waterValveOpen", "water_valve_open", "waterValve", default=base["water_valve_open"])
        ),
        "irrigation_pulses_per_day": _bounded_int(
            _target_value(
                raw,
                "irrigationPulsesPerDay",
                "irrigation_pulses_per_day",
                "irrigation",
                default=base["irrigation_pulses_per_day"],
            ),
            base["irrigation_pulses_per_day"],
            0,
            8,
        ),
        "fan_duty_percent": _bounded_int(
            _target_value(raw, "fanDutyPercent", "fan_duty_percent", "fan", default=base["fan_duty_percent"]),
            base["fan_duty_percent"],
            0,
            100,
        ),
        "co2_ppm": _bounded_int(
            _target_value(raw, "co2Ppm", "co2_ppm", "co2", default=base["co2_ppm"]),
            base["co2_ppm"],
            380,
            900,
        ),
    }




PLAN_LABELS = ("Plan A", "Plan B", "Plan C")
PLAN_SLOT_IDS = ("blueprint-a", "blueprint-b", "blueprint-c")


def _plan_label(index: int, candidate_id: str = "", raw_label: str = "") -> str:
    normalized_id = candidate_id.lower().replace("_", "-").strip()
    if normalized_id in {"plan-a", "blueprint-a"} or normalized_id.endswith("-a"):
        return "Plan A"
    if normalized_id in {"plan-b", "blueprint-b"} or normalized_id.endswith("-b"):
        return "Plan B"
    if normalized_id in {"plan-c", "blueprint-c"} or normalized_id.endswith("-c"):
        return "Plan C"

    normalized_label = " ".join(str(raw_label).lower().replace("-", " ").split())
    if normalized_label in {"plan a", "blueprint a"} or normalized_label.startswith("plan a "):
        return "Plan A"
    if normalized_label in {"plan b", "blueprint b"} or normalized_label.startswith("plan b "):
        return "Plan B"
    if normalized_label in {"plan c", "blueprint c"} or normalized_label.startswith("plan c "):
        return "Plan C"
    return PLAN_LABELS[min(index, len(PLAN_LABELS) - 1)]


def _default_blueprint_id(index: int) -> str:
    if 0 <= index < len(PLAN_SLOT_IDS):
        return PLAN_SLOT_IDS[index]
    suffix = chr(ord("a") + max(0, min(index, 25)))
    return f"blueprint-{suffix}"

def _blueprint_label(index: int) -> str:
    return chr(ord("A") + index) if 0 <= index < 26 else str(index + 1)


def assign_rotating_plan_slots(candidates: list[dict[str, Any]], rotation: int = 0) -> list[dict[str, Any]]:
    """Assign neutral Plan A/B/C display slots to scored candidates.

    Plan letters are presentation slots, not fixed agronomic strategies.  The
    highest/middle/lowest scoring generated candidates rotate through A/B/C on
    successive runs while preserving the real Twin simulation score and original
    source candidate metadata for audit.
    """

    if not candidates:
        return []

    slot_count = min(len(PLAN_SLOT_IDS), len(candidates))
    if slot_count <= 0:
        return list(candidates)

    try:
        offset = int(rotation) % slot_count
    except (TypeError, ValueError):
        offset = 0

    def score_value(item: Mapping[str, Any]) -> float:
        try:
            return float(item.get("score", 0.0))
        except (TypeError, ValueError):
            return 0.0

    copied = [dict(item) for item in candidates[:slot_count]]
    ranked = sorted(enumerate(copied), key=lambda pair: (-score_value(pair[1]), pair[0]))
    assigned: list[dict[str, Any]] = []
    for rank_index, (_original_index, candidate) in enumerate(ranked):
        slot_index = (rank_index + offset) % slot_count
        slot_id = _default_blueprint_id(slot_index)
        slot_label = PLAN_LABELS[slot_index]
        source_id = candidate.get("sourceCandidateId") or candidate.get("blueprintId") or candidate.get("id")
        source_name = candidate.get("sourceCandidateName") or candidate.get("name") or candidate.get("label")
        candidate["sourceCandidateId"] = source_id
        candidate["sourceCandidateName"] = source_name
        candidate["sourceScoreRank"] = rank_index + 1
        candidate["displaySlotRotation"] = offset
        candidate["id"] = slot_id
        candidate["blueprintId"] = slot_id
        candidate["name"] = slot_label
        candidate["label"] = slot_label
        candidate["slotAssignmentPolicy"] = "rotating_score_slot"
        assigned.append(candidate)

    slot_order = {slot_id: index for index, slot_id in enumerate(PLAN_SLOT_IDS)}
    assigned.sort(key=lambda item: slot_order.get(str(item.get("id")), len(slot_order)))
    return assigned + [dict(item) for item in candidates[slot_count:]]


def candidate_needs_quality_repair(
    candidate: Mapping[str, Any],
    *,
    min_score: float = 20.0,
    max_horizon_days: int | None = None,
    disease_pressure_limit: float | None = None,
) -> bool:
    """Return true when a generated candidate is not viable enough to demo.

    This is a transparent Twin quality gate, not a score override.  The caller
    can use it to decide whether to run a one-pass repaired actuator recipe and
    re-score that repaired candidate through the same Twin simulation.
    """

    score = _as_float(candidate.get("score"), 0.0)
    if score < float(min_score):
        return True

    predicted = candidate.get("predicted")
    predicted = predicted if isinstance(predicted, Mapping) else {}
    if str(predicted.get("diseaseRisk") or "").lower() == "high":
        return True

    simulation = candidate.get("simulation")
    simulation = simulation if isinstance(simulation, Mapping) else {}
    harvest_day = simulation.get("harvestDay")
    horizon = simulation.get("maxHorizonDays", max_horizon_days)
    if harvest_day is not None and horizon is not None:
        try:
            if int(round(float(harvest_day))) >= int(round(float(horizon))):
                return True
        except (TypeError, ValueError):
            pass

    final_crop = simulation.get("finalCropState")
    final_crop = final_crop if isinstance(final_crop, Mapping) else {}
    if disease_pressure_limit is not None and "diseasePressure" in final_crop:
        if _as_float(final_crop.get("diseasePressure"), 0.0) > float(disease_pressure_limit):
            return True

    return False


def _control_focus(actuator: Mapping[str, Any]) -> str:
    return (
        f"LED {actuator['led_intensity_percent']}% / {actuator['photoperiod_hours']}h, "
        f"irrigation {actuator['irrigation_pulses_per_day']}/day, "
        f"fan {actuator['fan_duty_percent']}%, CO2 {actuator['co2_ppm']} ppm"
    )


def normalize_blueprint_generation(payload: Mapping[str, Any], snapshot: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Normalize TwinX ``/blueprints/generate`` output for local twin simulation."""
    if not isinstance(payload, Mapping):
        raise RagAdapterError("Blueprint generation payload is not an object")

    raw_candidates = payload.get("candidates") or payload.get("blueprints") or payload.get("plans") or []
    if not isinstance(raw_candidates, list) or not raw_candidates:
        raise RagAdapterError("Blueprint generation payload missing candidates")

    provider = payload.get("provider", "twinx-gemma-rag")
    evidence = _evidence_items(payload.get("evidence") or payload.get("sources"))
    objective = payload.get("objective") or (snapshot or {}).get("goal", "earliest_viable_shipment")
    warnings = list(payload.get("warnings") or [])

    candidates: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_candidates):
        if not isinstance(raw, Mapping):
            raise RagAdapterError(f"Blueprint candidate {index + 1} is not an object")
        raw_label = str(raw.get("label") or raw.get("name") or f"Blueprint {_blueprint_label(index)}")
        candidate_id = str(raw.get("id") or _default_blueprint_id(index))
        label = _plan_label(index, candidate_id, raw_label)
        actuator_raw = raw.get("actuatorTargets") or raw.get("actuatorTarget") or raw.get("actuatorState") or {}
        if not isinstance(actuator_raw, Mapping):
            raise RagAdapterError(f"Blueprint candidate {label} missing actuator targets")
        actuator = _normalize_actuator_targets(actuator_raw, snapshot)
        item_evidence = _evidence_items(raw.get("evidence")) or evidence
        default_rationale = (
            f"{label}: Gemma/RAG candidate with LED {actuator['led_intensity_percent']}%, "
            f"{actuator['photoperiod_hours']}h photoperiod, irrigation {actuator['irrigation_pulses_per_day']}/day, "
            f"fan {actuator['fan_duty_percent']}%, CO2 {actuator['co2_ppm']} ppm. Twin simulation will score "
            "shipment timing, yield, OpEx, and disease risk."
        )
        default_tagline = f"{label}: state-aware Gemma/RAG generated blueprint."
        default_intent = (
            f"{label}: close the current sensor/crop gap with a simulated actuator recipe before applying it."
        )
        default_tradeoff = "Twin simulation validates the balance between earlier shipment, yield, OpEx, and disease risk."
        rationale = _ui_safe_text(raw.get("rationale") or raw.get("reason") or raw.get("summary"), default_rationale)
        candidates.append({
            "id": candidate_id,
            "kind": raw.get("kind", "gemma_rag_generated"),
            "provider": provider,
            "name": label,
            "label": label,
            "tagline": _ui_safe_text(raw.get("tagline") or raw.get("summary"), default_tagline),
            "operatorIntent": _ui_safe_text(raw.get("operatorIntent") or raw.get("intent") or rationale, default_intent),
            "tradeoff": _ui_safe_text(raw.get("tradeoff") or raw.get("riskNotes"), default_tradeoff),
            "rationale": rationale,
            "controlFocus": _ui_safe_text(raw.get("controlFocus"), _control_focus(actuator)),
            "actuatorState": actuator,
            "expectedSensorShift": raw.get("expectedSensorShift", {}),
            "ragEvidence": item_evidence,
            "generationWarning": raw.get("generationWarning"),
        })

    recommended = payload.get("recommendedCandidateId") or payload.get("recommendedBlueprintId")
    setpoints = _normalize_recommended_setpoints(payload.get("recommendedSetpoints") or payload.get("setpoints"))
    rag_advice = {
        "provider": provider,
        "model": payload.get("model", "gemma4"),
        "objective": objective,
        "growthStage": payload.get("growthStage") or payload.get("growth_stage"),
        "recommendedSetpoints": setpoints,
        "evidence": evidence,
        "explanation": payload.get("explanation") or payload.get("baselineSummary") or "",
        "baselineSummary": payload.get("baselineSummary") or "",
        "generationMode": payload.get("generationMode", "gemma_json"),
        "warnings": warnings,
        "blueprintCandidates": candidates,
        "recommendedCandidateId": recommended,
    }
    return {
        "provider": provider,
        "model": rag_advice["model"],
        "objective": objective,
        "baselineSummary": rag_advice["baselineSummary"],
        "ragAdvice": rag_advice,
        "gapAnalysis": payload.get("gapAnalysis"),
        "candidates": candidates,
        "recommendedCandidateId": recommended,
        "generationMode": rag_advice["generationMode"],
        "warnings": warnings,
    }


class SmartFarmRagClient:
    """Small urllib client for the TwinX rag-strawberry API."""

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        opener: Callable[..., Any] | None = None,
    ):
        self.base_url = (base_url or "").rstrip("/")
        self.token = token or ""
        self.timeout = timeout
        self._opener = opener or urllib.request.urlopen
        self.last_request_trace: dict[str, Any] = {}

    @classmethod
    def from_env(cls) -> "SmartFarmRagClient":
        token = os.getenv("SMARTFARM_RAG_TOKEN", "")
        token_file = os.getenv("SMARTFARM_RAG_TOKEN_FILE", "")
        if not token and token_file:
            try:
                with open(token_file, encoding="utf-8") as f:
                    token = f.read().strip()
            except OSError:
                token = ""
        timeout = _as_float(os.getenv("SMARTFARM_RAG_TIMEOUT", DEFAULT_TIMEOUT_SECONDS), DEFAULT_TIMEOUT_SECONDS)
        return cls(os.getenv("SMARTFARM_RAG_BASE_URL", ""), token, timeout=timeout)

    @property
    def enabled(self) -> bool:
        return bool(self.base_url)

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/healthz")

    def recommend(self, snapshot: Mapping[str, Any], *, no_llm: bool = False) -> dict[str, Any]:
        if not self.enabled:
            raise RagAdapterError("SMARTFARM_RAG_BASE_URL is not configured")
        body = {
            "planting_date": snapshot["plantingDate"],
            "date": snapshot["referenceDate"],
            "no_llm": bool(no_llm),
            "responseLanguage": "en-US",
            "uiTextContract": UI_TEXT_CONTRACT,
        }
        return normalize_rag_recommendation(self._request("POST", "/recommend", body))

    def generate_blueprints(
        self,
        snapshot: Mapping[str, Any],
        *,
        candidate_count: int = 3,
        no_llm: bool = False,
    ) -> dict[str, Any]:
        """Request state-aware Blueprint candidates from TwinX Gemma/RAG."""
        if not self.enabled:
            raise RagAdapterError("SMARTFARM_RAG_BASE_URL is not configured")
        body = {
            "facilityId": snapshot.get("facilityId", "smartfarm-spark-a7ce"),
            "objective": snapshot.get("goal", "earliest_viable_shipment"),
            "responseLanguage": "en-US",
            "uiTextContract": UI_TEXT_CONTRACT,
            "candidateCount": int(candidate_count),
            "referenceDate": snapshot.get("referenceDate"),
            "plantingDate": snapshot.get("plantingDate"),
            "currentDay": snapshot.get("currentDay"),
            "constraints": snapshot.get("constraints", {}),
            "baseline": {
                "sensorState": snapshot.get("sensorState", {}),
                "cropState": snapshot.get("cropState", {}),
                "actuatorState": snapshot.get("actuatorState", {}),
                "growthKpi": snapshot.get("growthKpi", {}),
                "visionAssessment": snapshot.get("visionAssessment", {}),
            },
            "no_llm": bool(no_llm),
        }
        return normalize_blueprint_generation(self._request("POST", "/blueprints/generate", body), snapshot)

    def _request(self, method: str, path: str, body: Mapping[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Accept", "application/json")
        if body is not None:
            req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        self.last_request_trace = {
            "method": method,
            "path": path,
            "url": url,
            "sentAt": dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "timeoutSeconds": self.timeout,
            "authConfigured": bool(self.token),
            "bodySummary": self._body_summary(body or {}),
        }
        try:
            with self._opener(req, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
                status = getattr(response, "status", None)
                if status is None and hasattr(response, "getcode"):
                    status = response.getcode()
                self.last_request_trace.update({
                    "ok": True,
                    "statusCode": status,
                    "receivedAt": dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
                    "responseKeys": sorted(payload.keys()) if isinstance(payload, Mapping) else [],
                })
                return payload
        except urllib.error.HTTPError as exc:
            self.last_request_trace.update({
                "ok": False,
                "statusCode": exc.code,
                "error": f"HTTP Error {exc.code}: {exc.reason}",
                "receivedAt": dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
            })
            raise RagAdapterError(f"RAG request failed: HTTP Error {exc.code}: {exc.reason}", status_code=exc.code) from exc
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            self.last_request_trace.update({
                "ok": False,
                "error": str(exc),
                "receivedAt": dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
            })
            raise RagAdapterError(f"RAG request failed: {exc}") from exc

    def _body_summary(self, body: Mapping[str, Any]) -> dict[str, Any]:
        baseline = body.get("baseline") if isinstance(body.get("baseline"), Mapping) else {}
        baseline_sensor = baseline.get("sensorState") if isinstance(baseline.get("sensorState"), Mapping) else {}
        baseline_vision = baseline.get("visionAssessment") if isinstance(baseline.get("visionAssessment"), Mapping) else {}
        return {
            "keys": sorted(body.keys()),
            "objective": body.get("objective"),
            "candidateCount": body.get("candidateCount"),
            "currentDay": body.get("currentDay") or baseline_sensor.get("twin_day"),
            "plantingDate": body.get("planting_date") or body.get("plantingDate"),
            "date": body.get("date") or body.get("referenceDate"),
            "noLlm": body.get("no_llm"),
            "responseLanguage": body.get("responseLanguage"),
            "hasVisionAssessment": bool(baseline_vision),
            "sensor": {
                key: baseline_sensor.get(key)
                for key in ("dli_mol_m2_day", "humidity_percent", "substrate_moisture_percent", "temperature_c", "co2_ppm")
                if key in baseline_sensor
            },
        }


def analyze_gap(snapshot: Mapping[str, Any], rag_advice: Mapping[str, Any]) -> dict[str, Any]:
    """Compare current farm state with RAG setpoints and rank corrections."""
    sensor = snapshot.get("sensorState") or {}
    crop = snapshot.get("cropState") or {}
    sp = rag_advice.get("recommendedSetpoints") or {}
    humidity = sp.get("humidityPct") or {"target": 66.0}
    temp_day = sp.get("temperatureDayC") or {"target": 22.0}
    co2 = sp.get("co2Ppm") or {"target": 900.0}
    light = sp.get("supplementalLight") or {}

    # Convert RAG light-hours guidance into the Twin's DLI-oriented sensor axis.
    light_hours = _as_float(light.get("hoursPerDay"), 0.0)
    target_dli = _clamp(14.0 + light_hours * 0.75, 14.0, 20.0)
    target_moisture = 46.0

    comparisons = [
        {
            "key": "dliMolM2Day",
            "label": "DLI",
            "current": _as_float(sensor.get("dli_mol_m2_day"), 0.0),
            "target": target_dli,
            "unit": "mol/m²/day",
            "weight": 1.20,
            "correction": "increase LED intensity/photoperiod",
        },
        {
            "key": "humidityPct",
            "label": "Humidity",
            "current": _as_float(sensor.get("humidity_percent"), 0.0),
            "target": _as_float(humidity.get("target"), 66.0),
            "unit": "%RH",
            "weight": 1.10,
            "correction": "increase airflow and avoid excess irrigation",
        },
        {
            "key": "co2Ppm",
            "label": "CO2",
            "current": _as_float(sensor.get("co2_ppm"), 0.0),
            "target": min(_as_float(co2.get("target"), 900.0), 900.0),
            "unit": "ppm",
            "weight": 0.95,
            "correction": "raise CO2 enrichment setpoint",
        },
        {
            "key": "substrateMoisturePct",
            "label": "Substrate moisture",
            "current": _as_float(sensor.get("substrate_moisture_percent"), 0.0),
            "target": target_moisture,
            "unit": "%",
            "weight": 0.85,
            "correction": "normalize irrigation pulses",
        },
        {
            "key": "temperatureC",
            "label": "Temperature",
            "current": _as_float(sensor.get("temperature_c"), 0.0),
            "target": _as_float(temp_day.get("target"), 22.0),
            "unit": "deg C",
            "weight": 0.65,
            "correction": "balance LED heat with ventilation",
        },
    ]

    normalized_denominators = {
        "dliMolM2Day": 8.0,
        "humidityPct": 20.0,
        "co2Ppm": 520.0,
        "substrateMoisturePct": 28.0,
        "temperatureC": 7.0,
    }
    deviations = []
    total = 0.0
    for item in comparisons:
        delta = item["target"] - item["current"]
        if item["key"] == "humidityPct":
            # For humidity, positive problem means current is too high.
            problem_delta = item["current"] - item["target"]
        else:
            problem_delta = delta
        severity = _clamp(abs(problem_delta) / normalized_denominators[item["key"]], 0.0, 1.0) * item["weight"]
        total += severity
        deviations.append({
            **{k: v for k, v in item.items() if k not in {"weight"}},
            "delta": round(delta, 2),
            "severity": round(_clamp(severity, 0.0, 1.0), 3),
            "direction": "raise" if delta > 0 else ("lower" if delta < 0 else "hold"),
        })

    maturity = _as_float(crop.get("fruitMaturity"), 0.0)
    disease = _as_float(crop.get("diseasePressure"), 0.0)
    if disease >= 0.62:
        deviations.append({
            "key": "diseasePressure",
            "label": "Disease pressure",
            "current": disease,
            "target": 0.42,
            "unit": "risk",
            "delta": round(0.42 - disease, 2),
            "severity": 0.95,
            "direction": "lower",
            "correction": "prioritize humidity reduction and airflow safety margin",
        })
        total += 0.95
    if maturity < 0.55:
        deviations.append({
            "key": "fruitMaturity",
            "label": "Fruit maturity",
            "current": maturity,
            "target": 0.72,
            "unit": "ratio",
            "delta": round(0.72 - maturity, 2),
            "severity": 0.72,
            "direction": "raise",
            "correction": "increase photosynthesis support while keeping disease risk controlled",
        })
        total += 0.72

    ranked = sorted(deviations, key=lambda item: item["severity"], reverse=True)
    return {
        "provider": rag_advice.get("provider", "twinx-gemma-rag"),
        "growthStage": rag_advice.get("growthStage"),
        "deviationScore": round(_clamp(total / 5.0, 0.0, 1.0) * 100.0, 1),
        "limitingFactors": [f"{d['label']}: {d['correction']}" for d in ranked[:4]],
        "deviations": ranked,
        "requiredCorrections": [d["correction"] for d in ranked[:4]],
    }


def _actuator_base(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    actuator = snapshot.get("actuatorState") or {}
    return {
        "led_intensity_percent": _as_int(actuator.get("led_intensity_percent"), 40),
        "photoperiod_hours": _as_int(actuator.get("photoperiod_hours"), 12),
        "water_valve_open": bool(actuator.get("water_valve_open", False)),
        "irrigation_pulses_per_day": _as_int(actuator.get("irrigation_pulses_per_day"), 1),
        "fan_duty_percent": _as_int(actuator.get("fan_duty_percent"), 20),
        "co2_ppm": _as_int(actuator.get("co2_ppm"), 420),
    }


def _candidate_recipe(
    base: Mapping[str, Any],
    *,
    led: float,
    photoperiod: float,
    irrigation: float,
    fan: float,
    co2: float,
) -> dict[str, Any]:
    pulses = int(_clamp(round(irrigation), 0, 8))
    return {
        "led_intensity_percent": int(_clamp(round(led), 0, 100)),
        "photoperiod_hours": int(_clamp(round(photoperiod), 8, 18)),
        "water_valve_open": pulses > 0 or bool(base.get("water_valve_open", False)),
        "irrigation_pulses_per_day": pulses,
        "fan_duty_percent": int(_clamp(round(fan), 0, 100)),
        "co2_ppm": int(_clamp(round(co2), 380, 900)),
    }


def generate_blueprint_candidates(
    snapshot: Mapping[str, Any],
    rag_advice: Mapping[str, Any],
    gap_analysis: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Generate SmartFarm candidate blueprints from state + RAG advice + gaps."""
    sensor = snapshot.get("sensorState") or {}
    sp = rag_advice.get("recommendedSetpoints") or {}
    base = _actuator_base(snapshot)
    humidity_target = _as_float((sp.get("humidityPct") or {}).get("target"), 66.0)
    co2_target = min(_as_float((sp.get("co2Ppm") or {}).get("target"), 900.0), 900.0)
    light_hours = _as_float((sp.get("supplementalLight") or {}).get("hoursPerDay"), 0.0)
    dli_target = _clamp(14.0 + light_hours * 0.75, 14.0, 20.0)
    dli_gap = max(0.0, dli_target - _as_float(sensor.get("dli_mol_m2_day"), 11.0))
    humidity_excess = max(0.0, _as_float(sensor.get("humidity_percent"), 72.0) - humidity_target)
    moisture_gap = max(0.0, 46.0 - _as_float(sensor.get("substrate_moisture_percent"), 42.0))
    co2_gap = max(0.0, co2_target - _as_float(sensor.get("co2_ppm"), 420.0))
    temp_excess = max(0.0, _as_float(sensor.get("temperature_c"), 23.0) - _as_float((sp.get("temperatureDayC") or {}).get("target"), 22.0))

    evidence = list(rag_advice.get("evidence") or [])[:5]
    stage = _ui_safe_text(rag_advice.get("growthStage"), "current growth stage")
    top_factors = list(gap_analysis.get("limitingFactors") or [])[:3]
    reason = _ui_safe_text("; ".join(str(factor) for factor in top_factors), "RAG setpoint gap correction")

    raw = [
        {
            "id": "blueprint-a",
            "kind": "gemma_rag_early_shipment",
            "name": "Plan A",
            "tagline": "Use RAG setpoint upper bands to accelerate fruit maturity.",
            "operatorIntent": "Prioritize earlier harvest by correcting DLI and CO2 deficits first.",
            "tradeoff": "Fastest maturity push, but highest LED/CO2 operating load.",
            "recipe": _candidate_recipe(
                base,
                led=max(72, base["led_intensity_percent"] + dli_gap * 4.6),
                photoperiod=max(15, base["photoperiod_hours"] + dli_gap * 0.44),
                irrigation=max(3, base["irrigation_pulses_per_day"] + moisture_gap / 12.0),
                fan=max(48, base["fan_duty_percent"] + humidity_excess * 0.75),
                co2=max(740, min(900, co2_target + co2_gap * 0.18)),
            ),
        },
        {
            "id": "blueprint-b",
            "kind": "gemma_rag_balanced",
            "name": "Plan B",
            "tagline": "Correct current sensor gaps toward RAG setpoints without over-forcing.",
            "operatorIntent": f"Bring the current {stage} twin back into the literature-backed setpoint envelope.",
            "tradeoff": "Balanced actuator movement; moderate cost and moderate disease-risk reduction.",
            "recipe": _candidate_recipe(
                base,
                led=max(base["led_intensity_percent"], 48 + dli_gap * 3.2),
                photoperiod=max(base["photoperiod_hours"], 12 + dli_gap * 0.36),
                irrigation=max(base["irrigation_pulses_per_day"], 2 + moisture_gap / 9.0),
                fan=max(base["fan_duty_percent"], 32 + humidity_excess * 0.82 + temp_excess * 2.0),
                co2=max(base["co2_ppm"], min(760, co2_target)),
            ),
        },
        {
            "id": "blueprint-c",
            "kind": "gemma_rag_disease_safe",
            "name": "Plan C",
            "tagline": "Use RAG humidity band as the primary safety constraint.",
            "operatorIntent": "Reduce disease pressure before chasing shipment acceleration.",
            "tradeoff": "Higher airflow energy; protects crop health when humidity/disease gaps dominate.",
            "recipe": _candidate_recipe(
                base,
                led=max(62, base["led_intensity_percent"] + dli_gap * 2.8),
                photoperiod=max(14, base["photoperiod_hours"] + dli_gap * 0.30),
                irrigation=max(2, min(4, base["irrigation_pulses_per_day"] + moisture_gap / 14.0)),
                fan=max(66, base["fan_duty_percent"] + humidity_excess * 1.25 + temp_excess * 2.6),
                co2=max(620, min(820, co2_target)),
            ),
        },
    ]

    candidates = []
    for item in raw:
        actuator = item.pop("recipe")
        candidates.append({
            **item,
            "provider": "twinx-gemma-rag",
            "ragAdvice": rag_advice,
            "gapAnalysis": gap_analysis,
            "ragEvidence": evidence,
            "rationale": f"{item['name']}: {reason}.",
            "controlFocus": (
                f"LED {actuator['led_intensity_percent']}% / {actuator['photoperiod_hours']}h, "
                f"irrigation {actuator['irrigation_pulses_per_day']}/day, "
                f"fan {actuator['fan_duty_percent']}%, CO2 {actuator['co2_ppm']} ppm"
            ),
            "actuatorState": actuator,
            "expectedSensorShift": {
                "dliMolM2Day": round(dli_gap, 1),
                "humidityPct": round(-humidity_excess, 1),
                "co2Ppm": int(round(co2_gap)),
                "substrateMoisturePct": round(moisture_gap, 1),
            },
        })
    return candidates
