from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, Iterable, List, Mapping

REFERENCE_DATE = date(2026, 10, 23)
BASELINE_HARVEST_DAY = 75
HARVEST_MATURITY_THRESHOLD = 0.92

SensorState = Dict[str, float | int | str]
ActuatorState = Dict[str, float | int | bool | str]
CropState = Dict[str, float | int]

BASELINE_SENSOR: SensorState = {
    "scenario_seed": "cloudy-winter-low-light",
    "twin_day": 34,
    "crop_stage": "flowering_delayed_fruit_set",
    "growth_index": 0.42,
    "dli_mol_m2_day": 11.2,
    "substrate_moisture_percent": 31,
    "humidity_percent": 82,
    "temperature_c": 24.8,
    "co2_ppm": 420,
    "disease_risk": "high",
}

BLUEPRINTS: Dict[str, Dict[str, object]] = {
    "baseline": {
        "name": "Baseline",
        "summary": "Current operation projected from today's sensor state.",
        "operator_intent": "Observe the current synthetic farm state without forcing a recovery recipe.",
        "control_focus": "LED 40% / 12h, minimal irrigation, low airflow, ambient CO₂.",
        "tradeoff": "Lowest intervention, but low DLI and moisture keep disease risk high and delay shipment.",
        "sensor": BASELINE_SENSOR,
        "actuator": {
            "led_intensity_percent": 40,
            "photoperiod_hours": 12,
            "water_valve_open": False,
            "irrigation_pulses_per_day": 1,
            "fan_duty_percent": 20,
            "co2_ppm": 420,
        },
        "expected_ship": "2027-01-06",
        "yield_score": 72,
        "opex_delta_percent": 0,
    },
    "plan-a-low-cost": {
        "name": "Plan A",
        "summary": "Recover growth while limiting electricity and water cost.",
        "operator_intent": "Moderate correction for a cost-sensitive operator who still wants visible recovery.",
        "control_focus": "Small LED/photoperiod increase, irrigation normalization, light airflow, modest CO₂.",
        "tradeoff": "Cheaper than aggressive forcing, but humidity and maturity improve more slowly.",
        "sensor": {
            "scenario_seed": "omniops-plan-a-low-cost",
            "twin_day": 34,
            "crop_stage": "stable_low_cost_recovery",
            "growth_index": 0.51,
            "dli_mol_m2_day": 13.5,
            "substrate_moisture_percent": 42,
            "humidity_percent": 72,
            "temperature_c": 23.2,
            "co2_ppm": 500,
            "disease_risk": "controlled",
        },
        "actuator": {
            "led_intensity_percent": 55,
            "photoperiod_hours": 13,
            "water_valve_open": True,
            "irrigation_pulses_per_day": 3,
            "fan_duty_percent": 35,
            "co2_ppm": 500,
        },
        "expected_ship": "2027-01-01",
        "yield_score": 79,
        "opex_delta_percent": -6,
    },
    "plan-b-early-shipment": {
        "name": "Plan B",
        "summary": "Push DLI and CO₂ for earlier harvest, accepting higher OpEx.",
        "operator_intent": "Force the crop toward the earliest viable shipment date.",
        "control_focus": "High LED + long photoperiod, stronger CO₂ enrichment, balanced irrigation and fan.",
        "tradeoff": "Best shipment acceleration and yield score, but highest electricity/CO₂ load.",
        "sensor": {
            "scenario_seed": "omniops-plan-b-early-shipment",
            "twin_day": 34,
            "crop_stage": "fruiting_early_harvest",
            "growth_index": 0.61,
            "dli_mol_m2_day": 17.8,
            "substrate_moisture_percent": 48,
            "humidity_percent": 68,
            "temperature_c": 23.6,
            "co2_ppm": 650,
            "disease_risk": "controlled",
        },
        "actuator": {
            "led_intensity_percent": 80,
            "photoperiod_hours": 16,
            "water_valve_open": True,
            "irrigation_pulses_per_day": 3,
            "fan_duty_percent": 55,
            "co2_ppm": 650,
        },
        "expected_ship": "2026-12-22",
        "yield_score": 87,
        "opex_delta_percent": 18,
    },
    "plan-c-disease-safe": {
        "name": "Plan C",
        "summary": "Prioritize humidity and airflow safety margin.",
        "operator_intent": "Protect the crop when disease pressure is the evaluator's main concern.",
        "control_focus": "High airflow, safe humidity band, enough LED/DLI to keep fruit development moving.",
        "tradeoff": "Lower disease risk than Plan B, but shipment is less aggressive and fan cost rises.",
        "sensor": {
            "scenario_seed": "omniops-plan-c-disease-safe",
            "twin_day": 34,
            "crop_stage": "disease_safe_fruiting",
            "growth_index": 0.56,
            "dli_mol_m2_day": 15.4,
            "substrate_moisture_percent": 45,
            "humidity_percent": 62,
            "temperature_c": 22.8,
            "co2_ppm": 580,
            "disease_risk": "low",
        },
        "actuator": {
            "led_intensity_percent": 70,
            "photoperiod_hours": 15,
            "water_valve_open": True,
            "irrigation_pulses_per_day": 4,
            "fan_duty_percent": 70,
            "co2_ppm": 580,
        },
        "expected_ship": "2026-12-28",
        "yield_score": 83,
        "opex_delta_percent": 9,
    },
}


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def risk_pressure(label: str) -> float:
    return {"high": 0.70, "controlled": 0.42, "low": 0.24}.get(label, 0.42)


def risk_label(pressure: float) -> str:
    if pressure >= 0.66:
        return "high"
    if pressure >= 0.38:
        return "controlled"
    return "low"


def sensor_from_actuator(actuator: Mapping[str, object], base_sensor: Mapping[str, object] | None = None) -> SensorState:
    """Generate a plausible synthetic sensor state from operator actuator setpoints.

    The POC has no physical sensors, so actuator changes are translated into a
    deterministic greenhouse response model.  Baseline actuator values map back
    to the baseline sensor state; deviations then move DLI, moisture, humidity,
    temperature, CO₂ and disease pressure in the expected direction.
    """

    base = BASELINE_SENSOR if base_sensor is None else base_sensor
    led = float(actuator["led_intensity_percent"])
    photoperiod = float(actuator["photoperiod_hours"])
    pulses = float(actuator["irrigation_pulses_per_day"])
    fan = float(actuator["fan_duty_percent"])
    co2_target = float(actuator["co2_ppm"])
    water_open = bool(actuator.get("water_valve_open", False))

    dli = clamp(float(base["dli_mol_m2_day"]) + (led - 40.0) * 0.105 + (photoperiod - 12.0) * 0.75, 7.5, 23.5)
    moisture = clamp(
        float(base["substrate_moisture_percent"]) + (pulses - 1.0) * 4.5 + (2.5 if water_open else 0.0),
        24.0,
        65.0,
    )
    humidity = clamp(
        float(base["humidity_percent"]) + (pulses - 1.0) * 1.8 - (fan - 20.0) * 0.32 - (led - 40.0) * 0.035,
        48.0,
        90.0,
    )
    temperature = clamp(
        float(base["temperature_c"]) + (led - 40.0) * 0.025 + (photoperiod - 12.0) * 0.05 - (fan - 20.0) * 0.018,
        18.0,
        29.0,
    )
    co2 = clamp(co2_target, 380.0, 900.0)
    moisture_stress = max(0.0, 38.0 - moisture) * 0.010 + max(0.0, moisture - 58.0) * 0.006
    disease_pressure = clamp(
        0.70
        + (humidity - 82.0) * 0.018
        + moisture_stress
        - (fan - 20.0) * 0.0040
        - (dli - 11.2) * 0.0060,
        0.12,
        0.84,
    )
    growth_index = clamp(
        0.42
        + (dli - 11.2) * 0.018
        + (moisture - 31.0) * 0.0035
        + max(0.0, co2 - 420.0) * 0.00010
        - max(0.0, disease_pressure - 0.42) * 0.08
        + max(0.0, 0.42 - disease_pressure) * 0.04,
        0.28,
        0.78,
    )
    if growth_index >= 0.60 and disease_pressure <= 0.38:
        crop_stage = "operator_balanced_fruiting"
    elif dli >= 17.0:
        crop_stage = "operator_early_harvest_push"
    elif disease_pressure <= 0.38:
        crop_stage = "operator_disease_safe_projection"
    elif moisture < 38.0:
        crop_stage = "operator_dry_stress_projection"
    else:
        crop_stage = "operator_controlled_projection"

    return {
        "scenario_seed": "manual-actuator-control",
        "twin_day": int(base.get("twin_day", 34)),
        "crop_stage": crop_stage,
        "growth_index": round(growth_index, 3),
        "dli_mol_m2_day": round(dli, 1),
        "substrate_moisture_percent": int(round(moisture)),
        "humidity_percent": int(round(humidity)),
        "temperature_c": round(temperature, 1),
        "co2_ppm": int(round(co2)),
        "disease_risk": risk_label(disease_pressure),
    }


def crop_state_from_sensor(sensor: Mapping[str, object]) -> CropState:
    growth = float(sensor.get("growth_index", 0.42))
    risk = risk_pressure(str(sensor.get("disease_risk", "controlled")))
    twin_day = int(sensor.get("twin_day", 34))
    fruit_maturity = clamp(0.18 + growth * 0.62 + max(0, twin_day - 34) * 0.006, 0.12, 0.88)
    return {
        "day": twin_day,
        "vegetativeGrowth": round(clamp(0.52 + growth * 0.38, 0.0, 1.0), 3),
        "flowering": round(clamp(0.45 + growth * 0.46, 0.0, 1.0), 3),
        "fruitSet": round(clamp(0.25 + growth * 0.58, 0.0, 1.0), 3),
        "fruitMaturity": round(fruit_maturity, 3),
        "diseasePressure": round(risk, 3),
        "estimatedYield": round(clamp(58 + growth * 42 - risk * 12, 0, 100), 1),
    }


def sensor_band_score(value: float, optimal_min: float, optimal_max: float, hard_min: float, hard_max: float) -> float:
    if optimal_min <= value <= optimal_max:
        return 1.0
    if value < optimal_min:
        return clamp((value - hard_min) / max(0.001, optimal_min - hard_min), 0.0, 1.0)
    return clamp((hard_max - value) / max(0.001, hard_max - optimal_max), 0.0, 1.0)


def main_limiting_factor(sensor: Mapping[str, object]) -> str:
    dli = float(sensor["dli_mol_m2_day"])
    moisture = float(sensor["substrate_moisture_percent"])
    humidity = float(sensor["humidity_percent"])
    temperature = float(sensor["temperature_c"])
    co2 = float(sensor["co2_ppm"])
    factors = [
        ((16.0 - dli) / 6.0, "Low DLI limits photosynthesis and fruit maturity"),
        ((38.0 - moisture) / 18.0, "Low substrate moisture slows fruit set"),
        ((humidity - 76.0) / 14.0, "High humidity increases disease pressure"),
        ((21.0 - temperature) / 4.0, "Low temperature slows vegetative growth"),
        ((temperature - 25.0) / 4.0, "High temperature increases stress"),
        ((550.0 - co2) / 250.0, "Low CO2 limits assimilation"),
    ]
    severity, label = max(factors, key=lambda item: item[0])
    if severity <= 0:
        return "No severe limiter; maintain current climate balance"
    return label


def growth_kpi(sensor: Mapping[str, object], crop: Mapping[str, object], expected_ship: str) -> Dict[str, object]:
    dli_score = sensor_band_score(float(sensor["dli_mol_m2_day"]), 16.0, 20.0, 8.0, 24.0)
    moisture_score = sensor_band_score(float(sensor["substrate_moisture_percent"]), 42.0, 55.0, 24.0, 65.0)
    humidity_score = sensor_band_score(float(sensor["humidity_percent"]), 60.0, 72.0, 48.0, 90.0)
    temp_score = sensor_band_score(float(sensor["temperature_c"]), 21.5, 24.5, 17.0, 29.0)
    co2_score = sensor_band_score(float(sensor["co2_ppm"]), 550.0, 750.0, 380.0, 900.0)
    environment_score = dli_score * 0.28 + moisture_score * 0.22 + humidity_score * 0.20 + temp_score * 0.15 + co2_score * 0.15
    crop_score = (
        float(crop["vegetativeGrowth"]) * 0.18
        + float(crop["flowering"]) * 0.14
        + float(crop["fruitSet"]) * 0.18
        + float(crop["fruitMaturity"]) * 0.28
        + (1.0 - float(crop["diseasePressure"])) * 0.22
    )
    return {
        "healthScore": int(round(clamp((environment_score * 0.44 + crop_score * 0.56) * 100.0, 0.0, 100.0))),
        "stage": sensor["crop_stage"],
        "fruitMaturityPercent": int(round(float(crop["fruitMaturity"]) * 100.0)),
        "harvestReadinessPercent": int(round(clamp(float(crop["fruitMaturity"]) * 0.62 + float(crop["estimatedYield"]) / 100.0 * 0.22 + (1.0 - float(crop["diseasePressure"])) * 0.16, 0.0, 1.0) * 100.0)),
        "expectedShip": expected_ship,
        "diseaseRisk": sensor["disease_risk"],
        "mainLimitingFactor": main_limiting_factor(sensor),
        "confidence": "model-estimated",
        "basis": "synthetic sensor history + deterministic crop-state model",
    }


def vision_assessment_from_state(
    sensor: Mapping[str, object],
    crop: Mapping[str, object],
    *,
    camera_path: str,
    capture_path: str,
    observed_at: str,
) -> Dict[str, object]:
    """Return a POC phenotype assessment for a virtual crop-camera capture.

    This deliberately does not claim real-world measurement.  It is a
    foundation-model adapter shape with a deterministic local estimator so the
    Omniverse demo can show the intended camera -> vision -> growth-status
    workflow before a real model/provider is plugged in.
    """

    maturity = int(round(float(crop["fruitMaturity"]) * 100.0))
    fruit_set = int(round(float(crop["fruitSet"]) * 100.0))
    canopy = int(round(float(crop["vegetativeGrowth"]) * 100.0))
    disease_pressure = float(crop["diseasePressure"])
    disease_risk = risk_label(disease_pressure)
    health = int(
        round(
            clamp(
                (
                    float(crop["vegetativeGrowth"]) * 0.25
                    + float(crop["fruitSet"]) * 0.20
                    + float(crop["fruitMaturity"]) * 0.25
                    + (1.0 - disease_pressure) * 0.30
                )
                * 100.0,
                0.0,
                100.0,
            )
        )
    )
    readiness = int(
        round(
            clamp(
                float(crop["fruitMaturity"]) * 0.70
                + float(crop["estimatedYield"]) / 100.0 * 0.20
                + (1.0 - disease_pressure) * 0.10,
                0.0,
                1.0,
            )
            * 100.0
        )
    )
    growth_progress = int(
        round(
            clamp(
                float(crop["vegetativeGrowth"]) * 0.20
                + float(crop["flowering"]) * 0.20
                + float(crop["fruitSet"]) * 0.25
                + float(crop["fruitMaturity"]) * 0.35,
                0.0,
                1.0,
            )
            * 100.0
        )
    )
    if maturity >= 75:
        stage = "red-fruit maturity visible"
    elif fruit_set >= 55:
        stage = "fruit-set developing"
    elif canopy >= 60:
        stage = "flowering / canopy build"
    else:
        stage = "vegetative recovery"

    return {
        "source": "virtual-camera-observed",
        "provider": "foundation-model-adapter/mock",
        "confidence": "poc-heuristic",
        "basis": "virtual crop camera capture + deterministic phenotype estimator",
        "cameraPath": camera_path,
        "capturePath": capture_path,
        "observedAt": observed_at,
        "phenotypeStage": stage,
        "healthScore": health,
        "growthProgressPercent": growth_progress,
        "fruitMaturityPercent": maturity,
        "fruitSetPercent": fruit_set,
        "canopyVigorPercent": canopy,
        "harvestReadinessPercent": readiness,
        "diseaseRisk": disease_risk,
        "traits": [
            f"Whole-cycle growth progress estimate: {growth_progress}%",
            f"Fruit maturity visible estimate: {maturity}%",
            f"Fruit-set density estimate: {fruit_set}%",
            f"Canopy vigor estimate: {canopy}%",
            f"Disease pressure visual proxy: {int(round(disease_pressure * 100.0))}%",
        ],
        "recommendation": (
            "Use this as a virtual phenotyping check only; replace provider with real camera/foundation model for production."
        ),
        "sensorContext": {
            "dliMolM2Day": sensor.get("dli_mol_m2_day"),
            "humidityPercent": sensor.get("humidity_percent"),
            "temperatureC": sensor.get("temperature_c"),
            "co2Ppm": sensor.get("co2_ppm"),
        },
    }


def blueprint_score(blueprint_id: str) -> Dict[str, object]:
    bp = BLUEPRINTS[blueprint_id]
    sensor = bp["sensor"]  # type: ignore[index]
    crop = crop_state_from_sensor(sensor)  # type: ignore[arg-type]
    expected_ship = str(bp["expected_ship"])
    baseline_date = date.fromisoformat(str(BLUEPRINTS["baseline"]["expected_ship"]))
    candidate_date = date.fromisoformat(expected_ship)
    days_earlier = max(0, (baseline_date - candidate_date).days)
    opex = float(bp["opex_delta_percent"])
    disease = str(sensor["disease_risk"])  # type: ignore[index]
    disease_penalty = {"high": 18.0, "controlled": 3.0, "low": 0.0}.get(disease, 8.0)
    score = float(bp["yield_score"]) + days_earlier * 0.8 + max(0.0, -opex) * 0.2 - max(0.0, opex) * 0.25 - disease_penalty
    return {
        "blueprintId": blueprint_id,
        "name": bp["name"],
        "summary": bp["summary"],
        "operatorIntent": bp["operator_intent"],
        "controlFocus": bp["control_focus"],
        "tradeoff": bp["tradeoff"],
        "score": round(clamp(score, 0.0, 100.0), 1),
        "daysEarlier": days_earlier,
        "yieldScore": bp["yield_score"],
        "opexDeltaPercent": bp["opex_delta_percent"],
        "diseaseRisk": disease,
        "kpi": growth_kpi(sensor, crop, expected_ship),  # type: ignore[arg-type]
    }


def ranked_blueprints() -> List[Dict[str, object]]:
    return sorted((blueprint_score(k) for k in BLUEPRINTS if k != "baseline"), key=lambda x: float(x["score"]), reverse=True)


def _manual_expected_ship(sensor: Mapping[str, object], crop: Mapping[str, object]) -> str:
    maturity_gap = max(0.0, HARVEST_MATURITY_THRESHOLD - float(crop["fruitMaturity"]))
    disease_penalty_days = float(crop["diseasePressure"]) * 8.0
    harvest_day = clamp(
        int(sensor["twin_day"]) + maturity_gap / 0.010 + disease_penalty_days,
        int(sensor["twin_day"]) + 7,
        90,
    )
    return (REFERENCE_DATE + timedelta(days=int(round(harvest_day)))).isoformat()


def state_for_manual_actuator(actuator: Mapping[str, object]) -> Dict[str, object]:
    """Return a local preview state for manual actuator controls."""

    normalized_actuator = {
        "led_intensity_percent": int(round(float(actuator.get("led_intensity_percent", 40)))),
        "photoperiod_hours": int(round(float(actuator.get("photoperiod_hours", 12)))),
        "water_valve_open": bool(actuator.get("water_valve_open", False)),
        "irrigation_pulses_per_day": int(round(float(actuator.get("irrigation_pulses_per_day", 1)))),
        "fan_duty_percent": int(round(float(actuator.get("fan_duty_percent", 20)))),
        "co2_ppm": int(round(float(actuator.get("co2_ppm", 420)))),
    }
    sensor = sensor_from_actuator(normalized_actuator)
    crop = crop_state_from_sensor(sensor)
    expected_ship = _manual_expected_ship(sensor, crop)
    return {
        "blueprintId": "manual-actuator-preview",
        "name": "Manual Actuator Preview",
        "summary": "Local projection from the current slider setpoints before/after applying them to the USD twin.",
        "sensor": sensor,
        "actuator": normalized_actuator,
        "crop": crop,
        "kpi": growth_kpi(sensor, crop, expected_ship),
        "ranked": ranked_blueprints(),
        "timeline": project_days(sensor, normalized_actuator, range(0, 22, 3)),
    }


def project_days(sensor: Mapping[str, object], actuator: Mapping[str, object], days: Iterable[int]) -> List[Dict[str, object]]:
    rows = []
    base_growth = float(sensor["growth_index"])
    led_gain = max(0.0, float(actuator["led_intensity_percent"]) - 40.0) / 1000.0
    co2_gain = max(0.0, float(actuator["co2_ppm"]) - 420.0) / 6000.0
    fan_gain = max(0.0, float(actuator["fan_duty_percent"]) - 20.0) / 1200.0
    disease_base = risk_pressure(str(sensor["disease_risk"]))
    for offset in days:
        projected = deepcopy(dict(sensor))
        projected["twin_day"] = int(sensor["twin_day"]) + offset
        projected["growth_index"] = round(clamp(base_growth + offset * (0.006 + led_gain + co2_gain), 0.0, 1.0), 3)
        pressure = clamp(disease_base - offset * fan_gain, 0.12, 0.82)
        projected["disease_risk"] = risk_label(pressure)
        crop = crop_state_from_sensor(projected)
        crop["diseasePressure"] = round(pressure, 3)
        rows.append({"day": projected["twin_day"], "sensor": projected, "crop": crop})
    return rows


def state_for_blueprint(blueprint_id: str) -> Dict[str, object]:
    bp = BLUEPRINTS[blueprint_id]
    sensor = deepcopy(bp["sensor"])  # type: ignore[arg-type]
    actuator = deepcopy(bp["actuator"])  # type: ignore[arg-type]
    crop = crop_state_from_sensor(sensor)
    return {
        "blueprintId": blueprint_id,
        "name": bp["name"],
        "summary": bp["summary"],
        "sensor": sensor,
        "actuator": actuator,
        "crop": crop,
        "kpi": growth_kpi(sensor, crop, str(bp["expected_ship"])),
        "ranked": ranked_blueprints(),
        "timeline": project_days(sensor, actuator, range(0, 22, 3)),
    }
