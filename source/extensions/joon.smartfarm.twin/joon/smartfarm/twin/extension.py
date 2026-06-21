# SPDX-FileCopyrightText: Copyright (c) 2024 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

import asyncio
import copy
import uuid
from datetime import date, timedelta
from pathlib import Path

import omni.ext
import omni.ui as ui
import omni.usd
import carb.settings
from fastapi import Body
from omni.services.core import main as services_main
from pxr import Gf, Sdf, UsdGeom, UsdLux, UsdShade

from .rag_adapter import (
    RagAdapterError,
    SmartFarmRagClient,
    analyze_gap,
    assign_rotating_plan_slots,
    build_state_snapshot,
    candidate_needs_quality_repair,
    generate_blueprint_candidates,
    is_blueprint_generation_unsupported,
)


DEFAULT_STATUS = "Ready to create the first smart farm twin scene."
SMART_FARM_PATH = "/World/SmartFarm"
SERVICE_UI_VISIBLE = False
SERVICE_CAMERA_PATH = f"{SMART_FARM_PATH}/Cameras/InternalGreenhouseCamera"
SERVICE_CAMERA_VISUAL_SCALE = 0.006
SERVICE_CAMERA_FAR_CLIP = 140.0
FIXED_EXPOSURE_SETTINGS = {
    "/rtx/post/histogram/enabled": False,
    "/rtx/post/histogram/useExposureClamping": True,
    "/rtx/post/histogram/minEV": 0.0,
    "/rtx/post/histogram/maxEV": 0.0,
    "/rtx/post/histogram/whiteScale": 40.0,
    "/rtx/post/tonemap/op": 1,
    "/rtx/post/tonemap/filmIso": 200.0,
    "/rtx/post/tonemap/exposureTime": 0.03,
    "/rtx/post/tonemap/fNumber": 5.6,
    "/rtx/post/tonemap/responsivity": 2.0,
    "/rtx/sceneDb/ambientLightIntensity": 0.0,
    "/persistent/app/viewport/ui/brightness": 0.70,
}
_ACTIVE_EXTENSION = None


def get_active_extension():
    """Return the live SmartFarm Twin extension instance inside this Kit process.

    OmniOps runs in the same Kit process as the twin.  Calling the HTTP service
    from Kit's update thread can deadlock because the service handler also needs
    the Kit process.  This lightweight bridge lets in-process operator panels
    mutate/query the same twin state directly while the HTTP API remains
    available for external clients.
    """
    return _ACTIVE_EXTENSION


EXTENSION_ROOT = Path(__file__).resolve().parents[3]
ASSET_DIR = EXTENSION_ROOT / "assets"
PROJECT_ROOT = next(
    (
        parent
        for parent in (EXTENSION_ROOT, *EXTENSION_ROOT.parents)
        if (parent / "source").is_dir() and (parent / "_build").is_dir()
    ),
    EXTENSION_ROOT,
)
OWN_TYPE_DIR = PROJECT_ROOT / "source" / "OwnType"
GREENHOUSE_LENGTH = 56.0
GREENHOUSE_WIDTH = 18.0
GREENHOUSE_WALL_HEIGHT = 4.2
GREENHOUSE_RIDGE_HEIGHT = 8.4
BED_LENGTH = 46.0
BED_Z_POSITIONS = (-6.2, -3.8, 3.8, 6.2)
PLANT_X_POSITIONS = (-21, -17, -13, -9, -5, -1, 3, 7, 11, 15, 19, 23)
GUTTER_HEIGHT = 1.55
LED_Z_POSITIONS = (-5.5, -3.1, 3.1, 5.5)
SKY_DOME_INTENSITY = 260.0
SUN_INTENSITY = 520.0
BLUE_SKY_COLOR = Gf.Vec3f(0.42, 0.68, 1.00)
BLUE_SKY_SUN_COLOR = Gf.Vec3f(1.00, 0.93, 0.78)
# LED strips are actuator indicators, not the scene's exposure driver.  Keep
# their real RectLight/emissive output almost off; use strip colour/thickness to
# communicate the setpoint.
LED_STRIP_INTENSITY = 0.0
INTERIOR_FILL_INTENSITY = 70.0
EMISSIVE_INTENSITY_DIVISOR = 1_000_000.0
LED_VISUAL_INTENSITY_MIN = 0.0
LED_VISUAL_INTENSITY_MAX = 0.0
STRAWBERRY_FRUIT_ASSET_SCALE = 0.055
STRAWBERRY_FRUIT_ASSET_ROTATION = (-90, 0, 0)
FAN_ASSET_SCALE = 0.0085
FAN_ASSET_ROTATION = (-90, 90, 0)
FAN_ASSET_Y = 5.85
FAN_DROP_ROD_Y = 6.48
FAN_DROP_ROD_DEPTH = 1.15
SIMULATION_START_DAY = 0.0
SIMULATION_RUNNER_DAY = 20.0
SIMULATION_FRUIT_SET_DAY = 38.0
SIMULATION_HARVEST_DAY = 60.0
FAST_SIMULATION_SECONDS = 7.0
FAST_SIMULATION_TIMECODES_PER_SECOND = SIMULATION_HARVEST_DAY / FAST_SIMULATION_SECONDS
PLANT_INITIAL_SCALE = 0.011
PLANT_FINAL_SCALE = 0.020
RUNNER_INITIAL_SCALE = (1.0, 0.05, 1.0)
RUNNER_FINAL_SCALE = (1.0, 1.0, 1.0)
FRUIT_INITIAL_SCALE_FACTOR = 0.08
FRUIT_MID_SCALE_FACTOR = 0.45
BASELINE_VIRTUAL_SENSOR_STATE = {
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
OPTIMIZED_VIRTUAL_SENSOR_STATE = {
    "scenario_seed": "gemma-blueprint-b",
    "twin_day": 34,
    "crop_stage": "fruiting_early_harvest",
    "growth_index": 0.61,
    "dli_mol_m2_day": 17.8,
    "substrate_moisture_percent": 48,
    "humidity_percent": 68,
    "temperature_c": 23.6,
    "co2_ppm": 650,
    "disease_risk": "controlled",
}
BLUEPRINT_SENSOR_STATES = {
    "baseline": BASELINE_VIRTUAL_SENSOR_STATE,
    "plan-a-low-cost": {
        "scenario_seed": "gemma-plan-a-low-cost",
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
    "plan-b-early-shipment": OPTIMIZED_VIRTUAL_SENSOR_STATE,
    "plan-c-disease-safe": {
        "scenario_seed": "gemma-plan-c-disease-safe",
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
}
BLUEPRINT_ACTUATOR_STATES = {
    "baseline": {
        "led_intensity_percent": 40,
        "photoperiod_hours": 12,
        "water_valve_open": False,
        "irrigation_pulses_per_day": 1,
        "fan_duty_percent": 20,
        "co2_ppm": 420,
    },
    "plan-a-low-cost": {
        "led_intensity_percent": 55,
        "photoperiod_hours": 13,
        "water_valve_open": True,
        "irrigation_pulses_per_day": 3,
        "fan_duty_percent": 35,
        "co2_ppm": 500,
    },
    "plan-b-early-shipment": {
        "led_intensity_percent": 80,
        "photoperiod_hours": 16,
        "water_valve_open": True,
        "irrigation_pulses_per_day": 3,
        "fan_duty_percent": 55,
        "co2_ppm": 650,
    },
    "plan-c-disease-safe": {
        "led_intensity_percent": 70,
        "photoperiod_hours": 15,
        "water_valve_open": True,
        "irrigation_pulses_per_day": 4,
        "fan_duty_percent": 70,
        "co2_ppm": 580,
    },
}
BLUEPRINT_SERVICE_SUMMARY = {
    "baseline": {
        "name": "Baseline",
        "summary": "Current operation projected from today's sensor state.",
        "operator_intent": "Observe the current synthetic farm state without forcing a recovery recipe.",
        "control_focus": "LED 40% / 12h, minimal irrigation, low airflow, ambient CO₂.",
        "tradeoff": "Lowest intervention, but low DLI and moisture keep disease risk high and delay shipment.",
        "expected_shipment": "2027-01-06",
        "yield_score": 72,
        "opex": "Baseline",
        "actuators": {"led": "LED 40% / 12h", "moisture": "31% substrate", "fan": "20% circulation"},
    },
    "plan-a-low-cost": {
        "name": "Plan A",
        "summary": "Recover growth while limiting electricity and water cost.",
        "operator_intent": "Moderate correction for a cost-sensitive operator who still wants visible recovery.",
        "control_focus": "Small LED/photoperiod increase, irrigation normalization, light airflow, modest CO₂.",
        "tradeoff": "Cheaper than aggressive forcing, but humidity and maturity improve more slowly.",
        "expected_shipment": "2027-01-01",
        "yield_score": 79,
        "opex": "-6% electricity/water",
        "actuators": {"led": "LED 55% / 13h", "moisture": "42% substrate", "fan": "35% airflow"},
    },
    "plan-b-early-shipment": {
        "name": "Plan B",
        "summary": "Push DLI and CO₂ for earlier harvest, accepting higher OpEx.",
        "operator_intent": "Force the crop toward the earliest viable shipment date.",
        "control_focus": "High LED + long photoperiod, stronger CO₂ enrichment, balanced irrigation and fan.",
        "tradeoff": "Best shipment acceleration and yield score, but highest electricity/CO₂ load.",
        "expected_shipment": "2026-12-22",
        "yield_score": 87,
        "opex": "+18% electricity/water",
        "actuators": {"led": "LED 80% / 16h", "moisture": "48% substrate", "fan": "55% airflow"},
    },
    "plan-c-disease-safe": {
        "name": "Plan C",
        "summary": "Prioritize humidity and airflow safety margin.",
        "operator_intent": "Protect the crop when disease pressure is the evaluator's main concern.",
        "control_focus": "High airflow, safe humidity band, enough LED/DLI to keep fruit development moving.",
        "tradeoff": "Lower disease risk than Plan B, but shipment is less aggressive and fan cost rises.",
        "expected_shipment": "2026-12-28",
        "yield_score": 83,
        "opex": "+9% electricity/water",
        "actuators": {"led": "LED 70% / 15h", "moisture": "45% substrate", "fan": "70% airflow"},
    },
}
PLANNING_REFERENCE_DATE = date(2026, 10, 23)
PLANNER_VERSION = "synthetic-deterministic-planner-v2"
PLANNING_CONTRACT_VERSION = "smartfarm-planning-run-v2"
BASELINE_HARVEST_DAY = 75
PLANNING_MAX_HORIZON_DAYS = 90
HARVEST_MATURITY_THRESHOLD = 0.92
MIN_ACCEPTABLE_YIELD_SCORE = 70
DISEASE_PRESSURE_LIMIT = 0.62
QUALITY_GATE_MIN_SCORE = 20.0
QUALITY_GATE_TARGET_SCORE = 25.0
PLANNING_OBJECTIVE_WEIGHTS = {
    "earliestShipment": 0.36,
    "yield": 0.24,
    "diseaseControl": 0.22,
    "opex": 0.10,
    "actuatorSafety": 0.08,
}


def _clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))


def _risk_label_from_pressure(pressure):
    if pressure >= 0.66:
        return "high"
    if pressure >= 0.38:
        return "controlled"
    return "low"


def _shipment_date_for_day(day):
    return (PLANNING_REFERENCE_DATE + timedelta(days=int(round(day)))).isoformat()


def _crop_state_from_sensor(sensor_state):
    growth = float(sensor_state.get("growth_index", 0.42))
    risk = {
        "high": 0.70,
        "controlled": 0.42,
        "low": 0.24,
    }.get(sensor_state.get("disease_risk", "controlled"), 0.42)
    twin_day = int(sensor_state.get("twin_day", 34))
    fruit_maturity = _clamp(0.18 + growth * 0.62 + max(0, twin_day - 34) * 0.006, 0.12, 0.88)
    return {
        "day": twin_day,
        "vegetativeGrowth": round(_clamp(0.52 + growth * 0.38, 0.0, 1.0), 3),
        "flowering": round(_clamp(0.45 + growth * 0.46, 0.0, 1.0), 3),
        "fruitSet": round(_clamp(0.25 + growth * 0.58, 0.0, 1.0), 3),
        "fruitMaturity": round(fruit_maturity, 3),
        "diseasePressure": round(risk, 3),
        "estimatedYield": round(_clamp(58 + growth * 42 - risk * 12, 0, 100), 1),
    }


def _sensor_band_score(value, optimal_min, optimal_max, hard_min, hard_max):
    """Return 0..1 score for how well a sensor value fits the crop recipe band."""
    value = float(value)
    if optimal_min <= value <= optimal_max:
        return 1.0
    if value < optimal_min:
        return _clamp((value - hard_min) / max(0.001, optimal_min - hard_min), 0.0, 1.0)
    return _clamp((hard_max - value) / max(0.001, hard_max - optimal_max), 0.0, 1.0)


def _growth_limiting_factor(sensor_state):
    dli = float(sensor_state["dli_mol_m2_day"])
    moisture = float(sensor_state["substrate_moisture_percent"])
    humidity = float(sensor_state["humidity_percent"])
    temperature = float(sensor_state["temperature_c"])
    co2 = float(sensor_state["co2_ppm"])

    factors = [
        ((16.0 - dli) / 6.0, "Low DLI limits photosynthesis and fruit maturity"),
        ((38.0 - moisture) / 18.0, "Low substrate moisture slows fruit set"),
        ((humidity - 76.0) / 14.0, "High humidity increases disease pressure"),
        ((21.0 - temperature) / 4.0, "Low temperature slows vegetative growth"),
        ((temperature - 25.0) / 4.0, "High temperature increases stress"),
        ((550.0 - co2) / 250.0, "Low CO₂ limits assimilation"),
    ]
    severity, label = max(factors, key=lambda item: item[0])
    if severity <= 0:
        return "No severe limiter; maintain current climate balance"
    return label


def _growth_kpi_from_state(sensor_state, crop_state, summary):
    """Model-estimated growth status.

    This is deliberately not a raw sensor echo.  It combines current synthetic
    sensor state, crop phenology and forecast summary into operator-facing KPIs.
    In a real deployment the same contract can be fed by camera/weight/lab
    observations instead of the current synthetic sensor source.
    """
    dli_score = _sensor_band_score(sensor_state["dli_mol_m2_day"], 16.0, 20.0, 8.0, 24.0)
    moisture_score = _sensor_band_score(sensor_state["substrate_moisture_percent"], 42.0, 55.0, 24.0, 65.0)
    humidity_score = _sensor_band_score(sensor_state["humidity_percent"], 60.0, 72.0, 48.0, 90.0)
    temp_score = _sensor_band_score(sensor_state["temperature_c"], 21.5, 24.5, 17.0, 29.0)
    co2_score = _sensor_band_score(sensor_state["co2_ppm"], 550.0, 750.0, 380.0, 900.0)
    environment_score = (
        dli_score * 0.28
        + moisture_score * 0.22
        + humidity_score * 0.20
        + temp_score * 0.15
        + co2_score * 0.15
    )

    crop_score = (
        float(crop_state["vegetativeGrowth"]) * 0.18
        + float(crop_state["flowering"]) * 0.14
        + float(crop_state["fruitSet"]) * 0.18
        + float(crop_state["fruitMaturity"]) * 0.28
        + (1.0 - float(crop_state["diseasePressure"])) * 0.22
    )
    health_score = int(round(_clamp((environment_score * 0.44 + crop_score * 0.56) * 100.0, 0.0, 100.0)))
    fruit_maturity = int(round(_clamp(float(crop_state["fruitMaturity"]) * 100.0, 0.0, 100.0)))
    harvest_readiness = int(round(_clamp(
        float(crop_state["fruitMaturity"]) * 0.62
        + float(crop_state["estimatedYield"]) / 100.0 * 0.22
        + (1.0 - float(crop_state["diseasePressure"])) * 0.16,
        0.0,
        1.0,
    ) * 100.0))

    return {
        "healthScore": health_score,
        "stage": sensor_state["crop_stage"],
        "fruitMaturityPercent": fruit_maturity,
        "harvestReadinessPercent": harvest_readiness,
        "expectedShip": summary["expected_shipment"],
        "diseaseRisk": sensor_state["disease_risk"],
        "mainLimitingFactor": _growth_limiting_factor(sensor_state),
        "confidence": "model-estimated",
        "basis": "synthetic sensor history + deterministic crop-state model",
        "evidence": [
            f'DLI {sensor_state["dli_mol_m2_day"]:.1f} mol/m²/day',
            f'Moisture {sensor_state["substrate_moisture_percent"]}% substrate',
            f'RH {sensor_state["humidity_percent"]}% / CO₂ {sensor_state["co2_ppm"]} ppm',
            f'Fruit set {float(crop_state["fruitSet"]) * 100:.0f}% · disease pressure {float(crop_state["diseasePressure"]) * 100:.0f}%',
        ],
    }


def _sensor_from_actuator(base_sensor, crop_state, actuator, blueprint_id):
    led = float(actuator["led_intensity_percent"])
    photoperiod = float(actuator["photoperiod_hours"])
    fan = float(actuator["fan_duty_percent"])
    pulses = float(actuator["irrigation_pulses_per_day"])
    co2_target = float(actuator["co2_ppm"])
    dli = _clamp(8.8 + led * 0.085 + max(0.0, photoperiod - 12.0) * 0.9, 8.0, 22.5)
    moisture = _clamp(float(base_sensor["substrate_moisture_percent"]) + (pulses - 2.0) * 5.2, 24.0, 58.0)
    humidity = _clamp(float(base_sensor["humidity_percent"]) - (fan - 20.0) * 0.34 + max(0, pulses - 2.0) * 1.6, 56.0, 88.0)
    temperature = _clamp(22.0 + led * 0.018 - fan * 0.012, 20.5, 25.8)
    co2 = _clamp(co2_target, 400, 820)
    disease = _risk_label_from_pressure(crop_state["diseasePressure"])
    return {
        "scenario_seed": f"synthetic-daily-{blueprint_id}",
        "twin_day": int(crop_state["day"]),
        "crop_stage": "rolling_horizon_projection",
        "growth_index": round(_clamp(crop_state["fruitMaturity"], 0.0, 1.0), 3),
        "dli_mol_m2_day": round(dli, 1),
        "substrate_moisture_percent": int(round(moisture)),
        "humidity_percent": int(round(humidity)),
        "temperature_c": round(temperature, 1),
        "co2_ppm": int(round(co2)),
        "disease_risk": disease,
    }


def _simulate_to_harvest(base_sensor, base_crop, actuator, blueprint_id="projection"):
    daily = []
    crop = copy.deepcopy(base_crop)
    day = int(crop["day"])
    opex_accum = 0.0
    harvest_day = PLANNING_MAX_HORIZON_DAYS
    end_day = min(PLANNING_MAX_HORIZON_DAYS, max(day + 1, BASELINE_HARVEST_DAY + 10))
    for current_day in range(day + 1, end_day + 1):
        virtual_sensor = _sensor_from_actuator(base_sensor, crop, actuator, "projection")
        dli_factor = _clamp((virtual_sensor["dli_mol_m2_day"] - 9.0) / 10.0, 0.0, 1.35)
        moisture_factor = 1.0 - abs(virtual_sensor["substrate_moisture_percent"] - 46.0) / 42.0
        temp_factor = 1.0 - abs(virtual_sensor["temperature_c"] - 23.3) / 8.0
        co2_factor = _clamp((virtual_sensor["co2_ppm"] - 390.0) / 360.0, 0.0, 1.0)
        humidity_penalty = max(0.0, (virtual_sensor["humidity_percent"] - 72.0) / 28.0)
        dry_penalty = max(0.0, (38.0 - virtual_sensor["substrate_moisture_percent"]) / 28.0)

        maturity_gain = 0.010 + 0.014 * dli_factor + 0.005 * moisture_factor + 0.004 * temp_factor + 0.004 * co2_factor
        maturity_gain *= _clamp(1.0 - crop["diseasePressure"] * 0.22, 0.72, 1.05)
        crop["fruitMaturity"] = _clamp(crop["fruitMaturity"] + maturity_gain, 0.0, 1.0)
        crop["fruitSet"] = _clamp(crop["fruitSet"] + maturity_gain * 0.42, 0.0, 1.0)
        crop["flowering"] = _clamp(crop["flowering"] + maturity_gain * 0.18, 0.0, 1.0)
        crop["vegetativeGrowth"] = _clamp(crop["vegetativeGrowth"] + maturity_gain * 0.10, 0.0, 1.0)
        disease_control = max(0.0, actuator["fan_duty_percent"] - 35.0) * 0.00045
        disease_control += max(0.0, 70.0 - virtual_sensor["humidity_percent"]) * 0.0012
        if ("disease-safe" in blueprint_id or "disease_safe" in blueprint_id) and crop["diseasePressure"] >= 0.62:
            # V2: disease-safe plans are allowed to spend airflow energy to
            # actively de-risk the crop before harvest.  Without this term, a
            # near-harvest high-risk crop made all candidates look equally bad
            # and the scorer incorrectly fell back to the cheapest plan.
            disease_control += 0.018 if current_day <= day + 5 else 0.006
        elif ("early-shipment" in blueprint_id or "early_shipment" in blueprint_id) and crop["diseasePressure"] >= 0.66:
            disease_control += 0.004
        elif ("low-cost" in blueprint_id or "low_cost" in blueprint_id) and crop["diseasePressure"] >= 0.66:
            disease_control *= 0.55

        crop["diseasePressure"] = _clamp(
            crop["diseasePressure"] + humidity_penalty * 0.014 + dry_penalty * 0.008 - disease_control,
            0.04,
            0.95,
        )
        crop["estimatedYield"] = _clamp(
            55 + crop["fruitSet"] * 32 + crop["fruitMaturity"] * 18 - crop["diseasePressure"] * 18,
            0,
            100,
        )
        crop["day"] = current_day
        opex_accum += actuator["led_intensity_percent"] * actuator["photoperiod_hours"] / 1250.0
        opex_accum += actuator["fan_duty_percent"] / 180.0
        opex_accum += actuator["irrigation_pulses_per_day"] * 0.10

        daily.append({
            "day": current_day,
            "fruitMaturity": round(crop["fruitMaturity"], 3),
            "diseasePressure": round(crop["diseasePressure"], 3),
            "estimatedYield": round(crop["estimatedYield"], 1),
        })
        if (
            crop["fruitMaturity"] >= HARVEST_MATURITY_THRESHOLD
            and crop["diseasePressure"] <= DISEASE_PRESSURE_LIMIT
            and crop["estimatedYield"] >= MIN_ACCEPTABLE_YIELD_SCORE
        ):
            harvest_day = current_day
            break

    if not daily:
        daily.append({
            "day": day,
            "fruitMaturity": round(crop["fruitMaturity"], 3),
            "diseasePressure": round(crop["diseasePressure"], 3),
            "estimatedYield": round(crop["estimatedYield"], 1),
        })
    opex_delta = int(round((opex_accum / max(1, len(daily)) - 1.00) * 18))
    disease = _risk_label_from_pressure(crop["diseasePressure"])
    yield_score = int(round(crop["estimatedYield"]))
    days_earlier = BASELINE_HARVEST_DAY - harvest_day
    disease_penalty = {"high": 42.0, "controlled": 10.0, "low": 0.0}.get(disease, 24.0)
    disease_penalty += crop["diseasePressure"] * 30.0
    unsafe_harvest_penalty = 22.0 if harvest_day >= PLANNING_MAX_HORIZON_DAYS else 0.0
    cost_saving_bonus = min(max(0, -opex_delta), 8) * 0.30
    early_shipment_bonus = days_earlier * 1.4
    yield_contribution = yield_score * 0.65
    positive_opex_penalty = max(0, opex_delta) * 0.40
    disease_context_adjustment = 0.0
    score = (
        early_shipment_bonus
        + yield_contribution
        + cost_saving_bonus
        - positive_opex_penalty
        - disease_penalty
        - unsafe_harvest_penalty
    )
    if base_crop.get("diseasePressure", 0.0) >= 0.62:
        if "disease-safe" in blueprint_id or "disease_safe" in blueprint_id:
            disease_context_adjustment = 18.0
        elif "low-cost" in blueprint_id or "low_cost" in blueprint_id:
            disease_context_adjustment = -20.0
        elif ("early-shipment" in blueprint_id or "early_shipment" in blueprint_id) and harvest_day - day <= 5:
            disease_context_adjustment = -8.0
    raw_score = score + disease_context_adjustment
    score = raw_score
    score = round(_clamp(score, 0.0, 100.0), 1)
    score_breakdown = {
        "daysEarlier": days_earlier,
        "earlyShipmentBonus": round(early_shipment_bonus, 1),
        "yieldContribution": round(yield_contribution, 1),
        "costSavingBonus": round(cost_saving_bonus, 1),
        "opexPenalty": round(positive_opex_penalty, 1),
        "diseasePenalty": round(disease_penalty, 1),
        "unsafeHarvestPenalty": round(unsafe_harvest_penalty, 1),
        "diseaseContextAdjustment": round(disease_context_adjustment, 1),
        "rawScore": round(raw_score, 1),
        "finalScore": score,
        "formula": "clamp(ship + yield + cost - opex - disease - safety + context, 0, 100)",
    }
    return {
        "harvestDay": harvest_day,
        "shipmentDate": _shipment_date_for_day(harvest_day),
        "yieldScore": yield_score,
        "opexDeltaPercent": opex_delta,
        "diseaseRisk": disease,
        "riskNote": f"Projected disease pressure {crop['diseasePressure']:.2f}; rolling horizon score {score:.1f}.",
        "score": score,
        "scoreBreakdown": score_breakdown,
        "dailyStates": daily,
        "finalCropState": {
            "day": int(crop["day"]),
            "vegetativeGrowth": round(crop["vegetativeGrowth"], 3),
            "flowering": round(crop["flowering"], 3),
            "fruitSet": round(crop["fruitSet"], 3),
            "fruitMaturity": round(crop["fruitMaturity"], 3),
            "diseasePressure": round(crop["diseasePressure"], 3),
            "estimatedYield": round(crop["estimatedYield"], 1),
        },
    }


def _candidate_actuators_from_state(sensor_state):
    dli_gap = max(0.0, 16.0 - float(sensor_state["dli_mol_m2_day"]))
    moisture_gap = max(0.0, 44.0 - float(sensor_state["substrate_moisture_percent"]))
    humidity_excess = max(0.0, float(sensor_state["humidity_percent"]) - 70.0)
    return {
        "baseline": copy.deepcopy(BLUEPRINT_ACTUATOR_STATES["baseline"]),
        "plan-a-low-cost": {
            "led_intensity_percent": int(_clamp(48 + dli_gap * 2.0, 45, 62)),
            "photoperiod_hours": int(_clamp(12 + dli_gap * 0.25, 12, 14)),
            "water_valve_open": moisture_gap > 2,
            "irrigation_pulses_per_day": int(_clamp(2 + round(moisture_gap / 9), 2, 3)),
            "fan_duty_percent": int(_clamp(28 + humidity_excess * 0.45, 28, 42)),
            "co2_ppm": 500,
        },
        "plan-b-early-shipment": {
            "led_intensity_percent": int(_clamp(72 + dli_gap * 2.2, 72, 88)),
            "photoperiod_hours": int(_clamp(15 + dli_gap * 0.22, 15, 17)),
            "water_valve_open": True,
            "irrigation_pulses_per_day": int(_clamp(3 + round(moisture_gap / 14), 3, 4)),
            "fan_duty_percent": int(_clamp(48 + humidity_excess * 0.75, 48, 66)),
            "co2_ppm": 650,
        },
        "plan-c-disease-safe": {
            "led_intensity_percent": int(_clamp(62 + dli_gap * 1.6, 62, 76)),
            "photoperiod_hours": int(_clamp(14 + dli_gap * 0.18, 14, 16)),
            "water_valve_open": True,
            "irrigation_pulses_per_day": int(_clamp(3 + round(moisture_gap / 12), 3, 4)),
            "fan_duty_percent": int(_clamp(62 + humidity_excess * 0.9, 62, 82)),
            "co2_ppm": 580,
        },
    }
GREENHOUSE_UNITS = (
    ("House_01_01", -GREENHOUSE_LENGTH / 2.0, -GREENHOUSE_WIDTH / 2.0),
    ("House_01_02", GREENHOUSE_LENGTH / 2.0, -GREENHOUSE_WIDTH / 2.0),
    ("House_02_01", -GREENHOUSE_LENGTH / 2.0, GREENHOUSE_WIDTH / 2.0),
    ("House_02_02", GREENHOUSE_LENGTH / 2.0, GREENHOUSE_WIDTH / 2.0),
)
PLANT_ASSET_CANDIDATES = (
    "https://omniverse-content-production.s3-us-west-2.amazonaws.com/Assets/Vegetation/Shrub/Daphne.usd",
    "http://omniverse-content-production.s3-us-west-2.amazonaws.com/Assets/Vegetation/Shrub/Daphne.usd",
    "daphne.usd",
    "Daphne.usd",
    "strawberry_plant.usd",
    "strawberry_plant.usda",
    "strawberry_plant.usdc",
    "official/aec_demo/Demos/AEC/BrownstoneDemo/Assets/Vegetation/Shrub/Sweet_Mock_Orange.usd",
    "official/aec_demo/Demos/AEC/BrownstoneDemo/Assets/Vegetation/Shrub/Hydrangea.usd",
    "official/aec_demo/Demos/AEC/BrownstoneDemo/Assets/Vegetation/Shrub/Goldflame_Spirea.usd",
)
STRAWBERRY_FRUIT_ASSET_CANDIDATES = (
    "strawberry.glb",
)
FAN_ASSET_CANDIDATES = (
    "DrumFan_A01_01.usd",
    "DrumFanA01_01.usd",
)


class _TextSink:
    """Tiny label-compatible sink used when the extension runs headless."""

    def __init__(self, text=""):
        self.text = text


# Any class derived from `omni.ext.IExt` in the top level module (defined in
# `python.modules` of `extension.toml`) will be instantiated when the extension
# gets enabled, and `on_startup(ext_id)` will be called. Later when the
# extension gets disabled on_shutdown() is called.
class MyExtension(omni.ext.IExt):
    """Smart farm twin POC control panel."""
    # ext_id is the current extension id. It can be used with the extension
    # manager to query additional information, like where this extension is
    # located on the filesystem.
    def on_startup(self, _ext_id):
        """This is called every time the extension is activated."""
        print("[joon.smartfarm.twin] Extension startup")
        global _ACTIVE_EXTENSION
        _ACTIVE_EXTENSION = self

        self._metric_labels = {
            key: _TextSink("-")
            for key in (
                "stage",
                "scenario",
                "light",
                "moisture",
                "fan",
                "expected_shipment",
                "yield_score",
                "opex",
                "recommendation",
                "plant_asset",
                "sensor_seed",
                "sensor_dli",
                "sensor_moisture",
                "sensor_humidity",
                "sensor_temperature",
                "sensor_co2",
            )
        }
        self._status_label = _TextSink(DEFAULT_STATUS)
        self._window = None
        self._service_ui_enabled = bool(
            carb.settings.get_settings().get_as_bool("/exts/joon.smartfarm.twin/serviceUiVisible")
        )
        self._selected_plant_asset = None
        self._strawberry_fruit_asset = None
        self._animate_growth = False
        self._scene_mode = "uninitialized"
        self._applied_blueprint_id = None
        self._current_sensor_state = BASELINE_VIRTUAL_SENSOR_STATE
        self._current_crop_state = _crop_state_from_sensor(BASELINE_VIRTUAL_SENSOR_STATE)
        self._current_actuator_state = BLUEPRINT_ACTUATOR_STATES["baseline"]
        self._manual_service_summary = None
        self._planning_run_seq = 0
        self._latest_planning_run = None
        self._rag_client = SmartFarmRagClient.from_env()
        self._startup_task = None
        self._simulation_task = None
        self._service_endpoints = [
            ("get", "/smartfarm/state"),
            ("get", "/smartfarm/planning/latest"),
            ("post", "/smartfarm/planning/run"),
            ("post", "/smartfarm/scene/mature"),
            ("post", "/smartfarm/scene/growth"),
            ("post", "/smartfarm/scene/reset"),
            ("post", "/smartfarm/blueprint/generate"),
            ("post", "/smartfarm/blueprint/apply"),
            ("post", "/smartfarm/actuator/apply"),
        ]
        self._apply_fixed_exposure_settings()
        self._register_service_api()

        if self._service_ui_enabled:
            self._window = ui.Window("Smart Farm Twin", width=540, height=780)
            with self._window.frame:
                with ui.VStack(spacing=8, height=0):
                    ui.Label("Strawberry Early-Shipment Twin", height=24)
                    ui.Separator(height=4)

                    self._add_info_row("Project", "Strawberry Early-Shipment Twin")
                    self._add_info_row("Facility", "2x2 four-house greenhouse block")
                    self._add_info_row("Crop", "Seolhyang strawberry")
                    self._metric_labels["stage"] = self._add_info_row("Stage", "Vegetative growth")
                    self._add_info_row("Target Shipment", "2026-12-22")
                    self._metric_labels["scenario"] = self._add_info_row("Scenario", "Not run")
                    self._metric_labels["light"] = self._add_info_row("Light", "-")
                    self._metric_labels["moisture"] = self._add_info_row("Irrigation", "-")
                    self._metric_labels["fan"] = self._add_info_row("Fan", "-")
                    self._metric_labels["expected_shipment"] = self._add_info_row("Expected Shipment", "-")
                    self._metric_labels["yield_score"] = self._add_info_row("Yield Score", "-")
                    self._metric_labels["opex"] = self._add_info_row("OpEx Delta", "-")
                    self._metric_labels["recommendation"] = self._add_info_row("Recommendation", "-")
                    self._metric_labels["plant_asset"] = self._add_info_row("Plant Asset", "Procedural fallback")

                    ui.Spacer(height=8)
                    self._status_label = ui.Label(DEFAULT_STATUS, word_wrap=True)
                    ui.Spacer(height=8)

                    with ui.HStack(spacing=8, height=32):
                        ui.Button(
                            "Create Mature Scene",
                            clicked_fn=self._on_create_mature_scene,
                        )
                        ui.Button(
                            "Create Growth Simulation",
                            clicked_fn=self._on_create_growth_simulation,
                        )
                    with ui.HStack(spacing=8, height=32):
                        ui.Button(
                            "Run Demo Scenario",
                            clicked_fn=self._on_run_demo_scenario,
                        )
                        ui.Button(
                            "Reset Growth Timeline",
                            clicked_fn=self._on_reset_growth_timeline,
                        )

                    ui.Separator(height=4)
                    ui.Label("Virtual Sensor State", height=22)
                    self._metric_labels["sensor_seed"] = self._add_info_row("Sensor Seed", "-")
                    self._metric_labels["sensor_dli"] = self._add_info_row("DLI Sensor", "-")
                    self._metric_labels["sensor_moisture"] = self._add_info_row("Soil Moisture Sensor", "-")
                    self._metric_labels["sensor_humidity"] = self._add_info_row("Humidity Sensor", "-")
                    self._metric_labels["sensor_temperature"] = self._add_info_row("Temperature Sensor", "-")
                    self._metric_labels["sensor_co2"] = self._add_info_row("CO2 Sensor", "-")

            self._window.visible = SERVICE_UI_VISIBLE
        else:
            print("[joon.smartfarm.twin] Service UI disabled; streaming viewport/API only")
        self._sync_existing_service_camera_appearance()

    def get_state_payload(self):
        return self._state_response(ok=True, message="Twin state loaded.")

    def run_daily_planning_payload(self, reason="omniops"):
        return self._run_daily_planning(reason=reason)

    def generate_blueprint_payload(self, goal="balanced", constraints=None, no_llm=False, vision_assessment=None):
        return self._generate_gemma_rag_blueprints(
            goal=goal,
            constraints=constraints,
            no_llm=no_llm,
            vision_assessment=vision_assessment,
        )

    def create_scene_payload(self, scene):
        if scene == "mature":
            return self._create_mature_scene()
        if scene == "reset":
            return self._reset_growth_timeline()
        return self._create_growth_simulation()

    def apply_blueprint_payload(self, blueprint_id):
        return self._apply_blueprint_to_scene(blueprint_id)

    def apply_actuator_payload(self, payload):
        return self._apply_actuator_control(payload)

    def _add_info_row(self, label: str, value: str):
        with ui.HStack(height=24):
            ui.Label(label, width=130)
            value_label = ui.Label(value)
        return value_label

    def _set_status(self, text: str):
        self._status_label.text = text

    def _apply_fixed_exposure_settings(self):
        settings = carb.settings.get_settings()
        for path, value in FIXED_EXPOSURE_SETTINGS.items():
            if isinstance(value, bool):
                settings.set_bool(path, value)
            elif isinstance(value, int):
                settings.set_int(path, value)
            elif isinstance(value, float):
                settings.set_float(path, value)
            else:
                settings.set(path, value)

    def _fixed_exposure_snapshot(self):
        settings = carb.settings.get_settings()
        return {path: settings.get(path) for path in FIXED_EXPOSURE_SETTINGS}

    def _register_service_api(self):
        services_main.register_endpoint(
            "get",
            "/smartfarm/state",
            self._api_get_state,
            tags=["smartfarm"],
            summary="Return the current smart farm twin state.",
        )
        services_main.register_endpoint(
            "get",
            "/smartfarm/planning/latest",
            self._api_get_latest_planning,
            tags=["smartfarm"],
            summary="Return the latest synthetic daily planning run.",
        )
        services_main.register_endpoint(
            "post",
            "/smartfarm/planning/run",
            self._api_run_daily_planning,
            tags=["smartfarm"],
            summary="Generate, simulate, and rank daily blueprint candidates.",
        )
        services_main.register_endpoint(
            "post",
            "/smartfarm/scene/mature",
            self._api_create_mature_scene,
            tags=["smartfarm"],
            summary="Create the static mature strawberry scene.",
        )
        services_main.register_endpoint(
            "post",
            "/smartfarm/scene/growth",
            self._api_create_growth_simulation,
            tags=["smartfarm"],
            summary="Create the growth simulation scene.",
        )
        services_main.register_endpoint(
            "post",
            "/smartfarm/scene/reset",
            self._api_reset_growth_timeline,
            tags=["smartfarm"],
            summary="Reset the growth timeline scene.",
        )
        services_main.register_endpoint(
            "post",
            "/smartfarm/blueprint/apply",
            self._api_apply_blueprint,
            tags=["smartfarm"],
            summary="Apply a blueprint to the USD twin.",
        )
        services_main.register_endpoint(
            "post",
            "/smartfarm/blueprint/generate",
            self._api_generate_blueprints,
            tags=["smartfarm"],
            summary="Generate Gemma/RAG-grounded blueprint candidates and validate them in the twin.",
        )
        services_main.register_endpoint(
            "post",
            "/smartfarm/actuator/apply",
            self._api_apply_actuator_control,
            tags=["smartfarm"],
            summary="Apply manual actuator controls to the USD twin.",
        )

    def _create_mature_scene(self):
        self._cancel_pending_simulation()
        stage = self._get_stage()
        if stage is None:
            self._set_status("No USD stage is available yet. Create or open a stage first.")
            return self._state_response(ok=False, message="No USD stage is available.")

        self._build_smart_farm_scene(stage, animate_growth=False)
        self._update_mature_metrics()
        self._scene_mode = "mature"
        self._applied_blueprint_id = "baseline"
        self._manual_service_summary = None
        self._current_sensor_state = BASELINE_VIRTUAL_SENSOR_STATE
        self._current_crop_state = _crop_state_from_sensor(BASELINE_VIRTUAL_SENSOR_STATE)
        self._current_actuator_state = BLUEPRINT_ACTUATOR_STATES["baseline"]
        self._apply_blueprint_visual_state(stage, "baseline")
        message = "Mature V1 scene created: runners and strawberries are fully visible."
        self._set_status(message)
        return self._state_response(ok=True, message=message)

    def _on_create_mature_scene(self):
        self._create_mature_scene()

    def _create_growth_simulation(self):
        self._cancel_pending_simulation()
        stage = self._get_stage()
        if stage is None:
            self._set_status("No USD stage is available yet. Create or open a stage first.")
            return self._state_response(ok=False, message="No USD stage is available.")

        self._build_smart_farm_scene(stage, animate_growth=True)
        self._update_baseline_metrics()
        self._scene_mode = "growth"
        self._applied_blueprint_id = "baseline"
        self._manual_service_summary = None
        self._current_sensor_state = BASELINE_VIRTUAL_SENSOR_STATE
        self._current_crop_state = _crop_state_from_sensor(BASELINE_VIRTUAL_SENSOR_STATE)
        self._current_actuator_state = BLUEPRINT_ACTUATOR_STATES["baseline"]
        self._apply_blueprint_visual_state(stage, "baseline")
        self._set_timeline_current_day(BASELINE_VIRTUAL_SENSOR_STATE["twin_day"], pause=True)
        message = "Current baseline twin created from today's synthetic sensor state."
        self._set_status(message)
        return self._state_response(ok=True, message=message)

    def _on_create_growth_simulation(self):
        self._create_growth_simulation()

    def _on_create_twin_scene(self):
        self._on_create_growth_simulation()

    def _on_run_demo_scenario(self):
        self._apply_blueprint_to_scene("plan-b-early-shipment")

    def _reset_growth_timeline(self):
        self._cancel_pending_simulation()
        stage = self._get_stage()
        if stage is None:
            self._set_status("No USD stage is available yet. Create or open a stage first.")
            return self._state_response(ok=False, message="No USD stage is available.")

        self._build_smart_farm_scene(stage, animate_growth=True)
        self._update_baseline_metrics()
        self._scene_mode = "growth"
        self._applied_blueprint_id = "baseline"
        self._manual_service_summary = None
        self._current_sensor_state = BASELINE_VIRTUAL_SENSOR_STATE
        self._current_crop_state = _crop_state_from_sensor(BASELINE_VIRTUAL_SENSOR_STATE)
        self._current_actuator_state = BLUEPRINT_ACTUATOR_STATES["baseline"]
        self._apply_blueprint_visual_state(stage, "baseline")
        self._set_timeline_current_day(BASELINE_VIRTUAL_SENSOR_STATE["twin_day"], pause=True)
        message = f'Growth timeline reset to current baseline day {BASELINE_VIRTUAL_SENSOR_STATE["twin_day"]}.'
        self._set_status(message)
        return self._state_response(ok=True, message=message)

    def _on_reset_growth_timeline(self):
        self._reset_growth_timeline()

    def _apply_blueprint_to_scene(self, blueprint_id="plan-b-early-shipment"):
        if (
            blueprint_id not in BLUEPRINT_SENSOR_STATES
            or blueprint_id not in BLUEPRINT_SERVICE_SUMMARY
            or blueprint_id not in BLUEPRINT_ACTUATOR_STATES
        ):
            message = f"Unknown blueprint id: {blueprint_id}"
            self._set_status(message)
            return self._state_response(ok=False, message=message)

        stage = self._get_stage()
        if stage is None:
            self._set_status("No USD stage is available yet. Create or open a stage first.")
            return self._state_response(ok=False, message="No USD stage is available.")

        self._cancel_pending_simulation()
        self._manual_service_summary = None

        summary = BLUEPRINT_SERVICE_SUMMARY.get(blueprint_id, BLUEPRINT_SERVICE_SUMMARY["plan-b-early-shipment"])
        if blueprint_id != "baseline":
            self._build_smart_farm_scene(stage, animate_growth=True)
            self._apply_blueprint_visual_state(stage, blueprint_id, include_crop=False)
            self._set_active_service_camera(stage)
            self._play_fast_growth_timeline(stage)
            self._update_metrics_for_blueprint(blueprint_id)
            self._scene_mode = "simulating_blueprint"
            self._applied_blueprint_id = blueprint_id
            message = (
                f'{summary["name"]} simulation started. '
                f"Fast-forwarding 60 growth days in ~{FAST_SIMULATION_SECONDS:.0f}s."
            )
            self._set_status(message)
            self._simulation_task = asyncio.ensure_future(
                self._complete_blueprint_after_fast_playback(blueprint_id)
            )
            return self._state_response(ok=True, message=message)

        if blueprint_id == "baseline":
            # Baseline is a reset-to-current-operation command. Rebuild the
            # scene instead of overlaying baseline values on top of a previously
            # optimized plan, otherwise ripe fruit/airflow/decision bars from
            # Plan A/B/C can remain visible.
            self._build_smart_farm_scene(stage, animate_growth=True)
        elif not stage.GetPrimAtPath(SMART_FARM_PATH):
            self._build_smart_farm_scene(stage, animate_growth=False)
        self._apply_blueprint_visual_state(stage, blueprint_id)
        self._set_active_service_camera(stage)
        if blueprint_id != "baseline":
            self._update_metrics_for_blueprint(blueprint_id)
        else:
            self._update_baseline_metrics()
            self._set_timeline_current_day(BASELINE_VIRTUAL_SENSOR_STATE["twin_day"], pause=True)
        self._scene_mode = "growth" if blueprint_id == "baseline" else "blueprint_applied"
        self._applied_blueprint_id = blueprint_id
        message = f'{summary["name"]} applied to the USD twin.'
        self._set_status(message)
        return self._state_response(ok=True, message=message)

    async def _api_get_state(self):
        return self._state_response(ok=True, message="Twin state loaded.")

    async def _api_get_latest_planning(self):
        if self._latest_planning_run is None:
            return self._state_response(ok=True, message="No planning run yet.")
        return {
            "ok": True,
            "message": "Latest synthetic planning run loaded.",
            "planningRun": self._latest_planning_run,
        }

    async def _api_run_daily_planning(self, payload: dict = Body(default_factory=dict)):
        provider = str(payload.get("provider", "")).lower()
        if provider in {"gemma-rag", "rag", "twinx-gemma-rag"}:
            return self._generate_gemma_rag_blueprints(
                goal=payload.get("goal", "balanced"),
                constraints=payload.get("constraints") or {},
                no_llm=bool(payload.get("noLlm", payload.get("no_llm", False))),
                vision_assessment=payload.get("visionAssessment") or payload.get("vision_assessment"),
                reason=payload.get("reason", "manual"),
            )
        return self._run_daily_planning(reason=payload.get("reason", "manual"))

    async def _api_create_mature_scene(self):
        return self._create_mature_scene()

    async def _api_create_growth_simulation(self):
        return self._create_growth_simulation()

    async def _api_reset_growth_timeline(self):
        return self._reset_growth_timeline()

    async def _api_apply_blueprint(self, payload: dict = Body(default_factory=dict)):
        blueprint_id = payload.get("blueprintId") or payload.get("blueprint_id") or "plan-b-early-shipment"
        return self._apply_blueprint_to_scene(blueprint_id)

    async def _api_generate_blueprints(self, payload: dict = Body(default_factory=dict)):
        return self._generate_gemma_rag_blueprints(
            goal=payload.get("goal", "balanced"),
            constraints=payload.get("constraints") or {},
            no_llm=bool(payload.get("noLlm", payload.get("no_llm", False))),
            vision_assessment=payload.get("visionAssessment") or payload.get("vision_assessment"),
            reason=payload.get("reason", "manual"),
        )

    async def _api_apply_actuator_control(self, payload: dict = Body(default_factory=dict)):
        return self._apply_actuator_control(payload)

    def _payload_value(self, payload, camel_key, snake_key, default):
        if camel_key in payload:
            return payload[camel_key]
        if snake_key in payload:
            return payload[snake_key]
        return default

    def _actuator_from_payload(self, payload):
        current = getattr(self, "_current_actuator_state", BLUEPRINT_ACTUATOR_STATES["baseline"])
        led = int(round(float(self._payload_value(payload, "ledIntensityPercent", "led_intensity_percent", current["led_intensity_percent"]))))
        photoperiod = int(round(float(self._payload_value(payload, "photoperiodHours", "photoperiod_hours", current["photoperiod_hours"]))))
        pulses = int(round(float(self._payload_value(payload, "irrigationPulsesPerDay", "irrigation_pulses_per_day", current["irrigation_pulses_per_day"]))))
        fan = int(round(float(self._payload_value(payload, "fanDutyPercent", "fan_duty_percent", current["fan_duty_percent"]))))
        co2 = int(round(float(self._payload_value(payload, "co2Ppm", "co2_ppm", current["co2_ppm"]))))
        water_default = bool(current.get("water_valve_open", pulses > 0))
        water_open = bool(self._payload_value(payload, "waterValveOpen", "water_valve_open", water_default))
        return {
            "led_intensity_percent": int(_clamp(led, 0, 100)),
            "photoperiod_hours": int(_clamp(photoperiod, 8, 18)),
            "water_valve_open": water_open,
            "irrigation_pulses_per_day": int(_clamp(pulses, 0, 8)),
            "fan_duty_percent": int(_clamp(fan, 0, 100)),
            "co2_ppm": int(_clamp(co2, 380, 900)),
        }

    def _sensor_state_from_actuator(self, actuator):
        led = float(actuator["led_intensity_percent"])
        photoperiod = float(actuator["photoperiod_hours"])
        pulses = float(actuator["irrigation_pulses_per_day"])
        fan = float(actuator["fan_duty_percent"])
        co2 = float(actuator["co2_ppm"])
        water_open = bool(actuator.get("water_valve_open", False))

        dli = _clamp(
            BASELINE_VIRTUAL_SENSOR_STATE["dli_mol_m2_day"] + (led - 40.0) * 0.105 + (photoperiod - 12.0) * 0.75,
            7.5,
            23.5,
        )
        moisture = _clamp(
            BASELINE_VIRTUAL_SENSOR_STATE["substrate_moisture_percent"]
            + (pulses - 1.0) * 4.5
            + (2.5 if water_open else 0.0),
            24.0,
            65.0,
        )
        humidity = _clamp(
            BASELINE_VIRTUAL_SENSOR_STATE["humidity_percent"]
            + (pulses - 1.0) * 1.8
            - (fan - 20.0) * 0.32
            - (led - 40.0) * 0.035,
            48.0,
            90.0,
        )
        temperature = _clamp(
            BASELINE_VIRTUAL_SENSOR_STATE["temperature_c"]
            + (led - 40.0) * 0.025
            + (photoperiod - 12.0) * 0.05
            - (fan - 20.0) * 0.018,
            18.0,
            29.0,
        )
        moisture_stress = max(0.0, 38.0 - moisture) * 0.010 + max(0.0, moisture - 58.0) * 0.006
        disease_pressure = _clamp(
            0.70
            + (humidity - 82.0) * 0.018
            + moisture_stress
            - (fan - 20.0) * 0.0040
            - (dli - 11.2) * 0.0060,
            0.12,
            0.84,
        )
        growth_index = _clamp(
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
            "twin_day": BASELINE_VIRTUAL_SENSOR_STATE["twin_day"],
            "crop_stage": crop_stage,
            "growth_index": round(growth_index, 3),
            "dli_mol_m2_day": round(dli, 1),
            "substrate_moisture_percent": int(round(moisture)),
            "humidity_percent": int(round(humidity)),
            "temperature_c": round(temperature, 1),
            "co2_ppm": int(round(co2)),
            "disease_risk": _risk_label_from_pressure(disease_pressure),
        }

    def _manual_summary_from_state(self, state, crop, actuator):
        maturity_gap = max(0.0, HARVEST_MATURITY_THRESHOLD - float(crop["fruitMaturity"]))
        disease_penalty_days = float(crop["diseasePressure"]) * 8.0
        harvest_day = _clamp(
            int(state["twin_day"]) + maturity_gap / 0.010 + disease_penalty_days,
            int(state["twin_day"]) + 7,
            PLANNING_MAX_HORIZON_DAYS,
        )
        baseline = BLUEPRINT_ACTUATOR_STATES["baseline"]
        baseline_load = baseline["led_intensity_percent"] * baseline["photoperiod_hours"]
        led_load = actuator["led_intensity_percent"] * actuator["photoperiod_hours"]
        opex_delta = round(
            ((led_load / max(1.0, baseline_load)) - 1.0) * 10.0
            + (actuator["irrigation_pulses_per_day"] - baseline["irrigation_pulses_per_day"]) * 1.2
            + (actuator["fan_duty_percent"] - baseline["fan_duty_percent"]) * 0.06
            + max(0, actuator["co2_ppm"] - baseline["co2_ppm"]) * 0.012
        )
        opex = "Baseline" if opex_delta == 0 else f"{opex_delta:+d}% operator load"
        return {
            "name": "Manual Actuator Control",
            "summary": "Operator-defined actuator recipe projected into synthetic sensor and crop state.",
            "operator_intent": "Preview the greenhouse response to the current manual setpoints.",
            "control_focus": (
                f'LED {actuator["led_intensity_percent"]}% / {actuator["photoperiod_hours"]}h, '
                f'irrigation {actuator["irrigation_pulses_per_day"]}/day, '
                f'fan {actuator["fan_duty_percent"]}%, CO₂ {actuator["co2_ppm"]} ppm'
            ),
            "tradeoff": "Manual settings are not optimizer-ranked; they show immediate twin response for operator exploration.",
            "expected_shipment": _shipment_date_for_day(harvest_day),
            "yield_score": int(round(crop["estimatedYield"])),
            "opex": opex,
            "actuators": {
                "led": f'LED {actuator["led_intensity_percent"]}% / {actuator["photoperiod_hours"]}h',
                "moisture": f'{state["substrate_moisture_percent"]}% substrate',
                "fan": f'{actuator["fan_duty_percent"]}% airflow',
            },
        }

    def _apply_actuator_control(self, payload):
        stage = self._get_stage()
        if stage is None:
            self._set_status("No USD stage is available yet. Create or open a stage first.")
            return self._state_response(ok=False, message="No USD stage is available.")

        self._cancel_pending_simulation()
        actuator = self._actuator_from_payload(payload)
        state = self._sensor_state_from_actuator(actuator)
        crop = _crop_state_from_sensor(state)
        summary = self._manual_summary_from_state(state, crop, actuator)

        if not stage.GetPrimAtPath(SMART_FARM_PATH):
            self._build_smart_farm_scene(stage, animate_growth=True)

        self._current_sensor_state = state
        self._current_crop_state = crop
        self._current_actuator_state = actuator
        self._manual_service_summary = summary
        self._applied_blueprint_id = "manual-actuator"
        self._scene_mode = "manual_actuator"

        growth_kpi = _growth_kpi_from_state(state, crop, summary)
        root = stage.GetPrimAtPath(SMART_FARM_PATH)
        if root:
            root.CreateAttribute("smartfarm:activeBlueprint", Sdf.ValueTypeNames.String).Set("manual-actuator")
            root.CreateAttribute("smartfarm:growthIndex", Sdf.ValueTypeNames.Float).Set(float(state["growth_index"]))
            root.CreateAttribute("smartfarm:growthHealthScore", Sdf.ValueTypeNames.Int).Set(int(growth_kpi["healthScore"]))
            root.CreateAttribute("smartfarm:fruitMaturityPercent", Sdf.ValueTypeNames.Int).Set(
                int(growth_kpi["fruitMaturityPercent"])
            )
            root.CreateAttribute("smartfarm:harvestReadinessPercent", Sdf.ValueTypeNames.Int).Set(
                int(growth_kpi["harvestReadinessPercent"])
            )
            root.CreateAttribute("smartfarm:mainLimitingFactor", Sdf.ValueTypeNames.String).Set(
                growth_kpi["mainLimitingFactor"]
            )
            root.CreateAttribute("smartfarm:recommendedBlueprint", Sdf.ValueTypeNames.String).Set(
                self._recommended_blueprint_id()
            )

        self._ensure_blue_sky(stage)
        self._apply_virtual_sensor_state_to_scene(stage, state)
        for unit_path in self._unit_paths():
            self._apply_led_profile(stage, unit_path, actuator)
            self._apply_irrigation_profile(stage, unit_path, actuator, state)
            self._apply_fan_profile(stage, unit_path, actuator)
            self._apply_co2_profile(stage, unit_path, actuator)
            self._apply_crop_profile(stage, unit_path, state, "manual-actuator")
        self._update_service_decision_panel(stage, "manual-actuator")
        self._set_active_service_camera(stage)

        message = "Manual actuator controls applied to the USD twin and virtual sensor projection."
        self._set_status(message)
        return self._state_response(ok=True, message=message)

    def _cancel_pending_simulation(self):
        task = getattr(self, "_simulation_task", None)
        if task is not None and not task.done():
            task.cancel()
        self._simulation_task = None

    def _play_fast_growth_timeline(self, stage):
        stage.SetStartTimeCode(SIMULATION_START_DAY)
        stage.SetEndTimeCode(SIMULATION_HARVEST_DAY)
        stage.SetFramesPerSecond(30.0)
        stage.SetTimeCodesPerSecond(FAST_SIMULATION_TIMECODES_PER_SECOND)
        try:
            import omni.timeline

            timeline = omni.timeline.get_timeline_interface()
            timeline.set_start_time(SIMULATION_START_DAY)
            timeline.set_end_time(SIMULATION_HARVEST_DAY)
            timeline.set_current_time(SIMULATION_START_DAY)
            timeline.play()
        except Exception as exc:
            print(f"[joon.smartfarm.twin] Fast growth timeline playback skipped: {exc}")

    async def _complete_blueprint_after_fast_playback(self, blueprint_id):
        try:
            await asyncio.sleep(FAST_SIMULATION_SECONDS)
            if self._applied_blueprint_id != blueprint_id:
                return

            stage = omni.usd.get_context().get_stage()
            if stage is None or not stage.GetPrimAtPath(SMART_FARM_PATH):
                return

            self._finalize_animated_crop_state(stage, blueprint_id)
            self._set_active_service_camera(stage)
            self._scene_mode = "blueprint_applied"
            summary = BLUEPRINT_SERVICE_SUMMARY[blueprint_id]
            message = f'{summary["name"]} simulation complete. Final twin state locked.'
            self._set_status(message)
            try:
                from omni.timeline import get_timeline_interface

                timeline = get_timeline_interface()
                timeline.pause()
                timeline.set_current_time(SIMULATION_HARVEST_DAY)
            except Exception:
                pass
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"[joon.smartfarm.twin] Fast growth completion failed: {exc}")

    def _finalize_animated_crop_state(self, stage, blueprint_id):
        """Lock the existing growth-animation crop in its final state.

        Do not create new fruit prims here.  Creating /Fruit at completion caused
        a visible pop/flash near the end of playback.  The growth scene already
        contains animated Fruit_Unripe_Left/Right prims, so only recolour and
        mark the existing crop while leaving timeline-authored transforms intact.
        """
        state = BLUEPRINT_SENSOR_STATES[blueprint_id]
        self._current_sensor_state = state
        self._current_crop_state = _crop_state_from_sensor(state)
        self._current_actuator_state = BLUEPRINT_ACTUATOR_STATES[blueprint_id]
        summary = BLUEPRINT_SERVICE_SUMMARY.get(blueprint_id, BLUEPRINT_SERVICE_SUMMARY["baseline"])
        growth_kpi = _growth_kpi_from_state(state, self._current_crop_state, summary)
        root = stage.GetPrimAtPath(SMART_FARM_PATH)
        if root:
            root.CreateAttribute("smartfarm:activeBlueprint", Sdf.ValueTypeNames.String).Set(blueprint_id)
            root.CreateAttribute("smartfarm:growthIndex", Sdf.ValueTypeNames.Float).Set(float(state["growth_index"]))
            root.CreateAttribute("smartfarm:growthHealthScore", Sdf.ValueTypeNames.Int).Set(
                int(growth_kpi["healthScore"])
            )
            root.CreateAttribute("smartfarm:fruitMaturityPercent", Sdf.ValueTypeNames.Int).Set(
                int(growth_kpi["fruitMaturityPercent"])
            )
            root.CreateAttribute("smartfarm:harvestReadinessPercent", Sdf.ValueTypeNames.Int).Set(
                int(growth_kpi["harvestReadinessPercent"])
            )
            root.CreateAttribute("smartfarm:mainLimitingFactor", Sdf.ValueTypeNames.String).Set(
                growth_kpi["mainLimitingFactor"]
            )

        fruit_color = {
            "plan-a-low-cost": (0.95, 0.34, 0.24),
            "plan-b-early-shipment": (1.0, 0.02, 0.04),
            "plan-c-disease-safe": (0.95, 0.16, 0.10),
        }.get(blueprint_id, (1.0, 0.03, 0.04))
        leaf_color = {
            "plan-a-low-cost": (0.03, 0.42, 0.15),
            "plan-b-early-shipment": (0.02, 0.48, 0.13),
            "plan-c-disease-safe": (0.02, 0.44, 0.20),
        }.get(blueprint_id, (0.02, 0.42, 0.14))

        for unit_path in self._unit_paths():
            for bed_index in range(1, len(BED_Z_POSITIONS) + 1):
                for plant_index in range(1, len(PLANT_X_POSITIONS) + 1):
                    base = f"{unit_path}/Plants/Bed_{bed_index:02d}_Plant_{plant_index:02d}"
                    leaf = stage.GetPrimAtPath(f"{base}/LeafCluster")
                    if leaf:
                        self._set_display_color(leaf, leaf_color)
                    for side_name in ("Left", "Right"):
                        fruit = stage.GetPrimAtPath(f"{base}/Fruit_Unripe_{side_name}")
                        if fruit and fruit.IsA(UsdGeom.Gprim):
                            self._set_display_color(fruit, fruit_color)

    def _get_stage(self):
        usd_context = omni.usd.get_context()
        stage = usd_context.get_stage()
        if stage is None:
            usd_context.new_stage()
            stage = usd_context.get_stage()
        return stage

    def _build_smart_farm_scene(self, stage, animate_growth=False):
        self._apply_fixed_exposure_settings()
        self._animate_growth = animate_growth
        smart_farm_path = Sdf.Path(SMART_FARM_PATH)
        if stage.GetPrimAtPath(smart_farm_path):
            stage.RemovePrim(smart_farm_path)

        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
        UsdGeom.SetStageMetersPerUnit(stage, 1.0)

        world = UsdGeom.Xform.Define(stage, "/World")
        stage.SetDefaultPrim(world.GetPrim())
        UsdGeom.Xform.Define(stage, SMART_FARM_PATH)

        greenhouse_asset = self._find_named_asset("greenhouse")
        strawberry_asset = self._find_plant_asset()
        self._strawberry_fruit_asset = self._find_strawberry_fruit_asset()
        self._selected_plant_asset = strawberry_asset
        self._metric_labels["plant_asset"].text = self._asset_label(strawberry_asset)

        self._create_site_floor(stage)
        self._create_greenhouse_units(stage, greenhouse_asset, strawberry_asset)
        self._create_lighting(stage)
        self._create_service_camera(stage)
        self._set_active_service_camera(stage)
        self._apply_virtual_sensor_state_to_scene(stage, BASELINE_VIRTUAL_SENSOR_STATE)
        if animate_growth:
            self._configure_growth_simulation_timeline(stage)
        else:
            self._configure_static_timeline(stage)
        self._update_baseline_metrics()

    def _create_service_camera(self, stage):
        UsdGeom.Scope.Define(stage, f"{SMART_FARM_PATH}/Cameras")
        camera = UsdGeom.Camera.Define(stage, SERVICE_CAMERA_PATH)
        camera.CreateFocalLengthAttr(18.0)
        camera.CreateHorizontalApertureAttr(24.0)
        camera.CreateVerticalApertureAttr(13.5)
        camera.CreateClippingRangeAttr(Gf.Vec2f(0.05, SERVICE_CAMERA_FAR_CLIP))
        camera.GetPrim().CreateAttribute("smartfarm:purpose", Sdf.ValueTypeNames.String).Set(
            "default-streaming-internal-view"
        )
        self._sync_service_camera_appearance(stage)
        return camera

    def _sync_existing_service_camera_appearance(self):
        try:
            stage = self._get_stage()
            if stage is not None:
                self._sync_service_camera_appearance(stage)
        except Exception as exc:
            print(f"[joon.smartfarm.twin] Service camera visual sync skipped: {exc}")

    def _sync_service_camera_appearance(self, stage):
        camera_prim = stage.GetPrimAtPath(SERVICE_CAMERA_PATH)
        if not camera_prim:
            return

        camera = UsdGeom.Camera(camera_prim)
        camera.CreateClippingRangeAttr().Set(Gf.Vec2f(0.05, SERVICE_CAMERA_FAR_CLIP))
        # House_01_01 local central walkway, looking down the greenhouse length.
        # USD cameras look down local -Z; Y=-90 maps that direction to world +X.
        # Keep the default streaming camera view unchanged, but make the
        # camera/frustum guide tiny in the scene so it does not dominate the
        # greenhouse when the operator is viewing from the Growth Camera.
        self._set_transform(
            camera.GetPrim(),
            translation=(-50.0, 2.45, -9.0),
            rotation=(-4.0, -90.0, 0.0),
            scale=(SERVICE_CAMERA_VISUAL_SCALE, SERVICE_CAMERA_VISUAL_SCALE, SERVICE_CAMERA_VISUAL_SCALE),
        )

    def _set_active_service_camera(self, stage):
        self._sync_service_camera_appearance(stage)
        camera_prim = stage.GetPrimAtPath(SERVICE_CAMERA_PATH)
        if not camera_prim:
            return

        try:
            from omni.kit.viewport.utility import get_active_viewport, get_viewport_from_window_name

            viewport_api = get_active_viewport() or get_viewport_from_window_name("Viewport")
            if viewport_api:
                viewport_api.camera_path = Sdf.Path(SERVICE_CAMERA_PATH)
                return
        except Exception as exc:
            print(f"[joon.smartfarm.twin] Active viewport camera update skipped: {exc}")

        try:
            stage.GetRootLayer().customLayerData = {
                **stage.GetRootLayer().customLayerData,
                "smartfarm:defaultCamera": SERVICE_CAMERA_PATH,
            }
        except Exception:
            pass

    def _create_site_floor(self, stage):
        self._create_cube(
            stage,
            f"{SMART_FARM_PATH}/Ground",
            translation=(0, -0.04, 0),
            scale=(GREENHOUSE_LENGTH * 2.0 + 10.0, 0.08, GREENHOUSE_WIDTH * 2.0 + 10.0),
            color=(0.48, 0.40, 0.30),
        )

    def _create_greenhouse_units(self, stage, greenhouse_asset, strawberry_asset):
        for unit_name, x_offset, z_offset in GREENHOUSE_UNITS:
            unit_path = f"{SMART_FARM_PATH}/{unit_name}"
            unit = UsdGeom.Xform.Define(stage, unit_path)
            self._set_transform(unit.GetPrim(), translation=(x_offset, 0, z_offset))

            self._create_unit_floor(stage, unit_path)
            if greenhouse_asset:
                UsdGeom.Xform.Define(stage, f"{unit_path}/Greenhouse")
                self._reference_asset(
                    stage,
                    f"{unit_path}/Greenhouse/ExternalModel",
                    greenhouse_asset,
                    translation=(0, 0, 0),
                    scale=(1.0, 1.0, 1.0),
                )
            else:
                self._create_greenhouse(stage, unit_path)
            self._create_growing_beds(stage, unit_path, strawberry_asset)
            self._create_actuators(stage, unit_path)
            self._create_sensors(stage, unit_path)

    def _create_unit_floor(self, stage, unit_path):
        self._create_cube(
            stage,
            f"{unit_path}/CentralWalkway",
            translation=(0, 0.02, 0),
            scale=(54, 0.035, 2.35),
            color=(0.55, 0.53, 0.47),
        )
        for z in (-8.1, 8.1):
            self._create_cube(
                stage,
                f"{unit_path}/BlueServiceMat_{self._safe_name(z)}",
                translation=(0, 0.04, z),
                scale=(52, 0.035, 1.05),
                color=(0.18, 0.43, 0.54),
            )

    def _create_greenhouse(self, stage, unit_path):
        group = f"{unit_path}/Greenhouse"
        UsdGeom.Xform.Define(stage, group)

        frame_color = (0.58, 0.64, 0.67)
        half_length = GREENHOUSE_LENGTH / 2.0
        half_width = GREENHOUSE_WIDTH / 2.0
        glass_color = (0.78, 0.93, 0.98)
        edge_color = (0.34, 0.56, 0.62)

        self._create_glass_cover_panels(stage, group, glass_color, half_length, half_width)
        self._create_glass_panel_edges(stage, group, edge_color, half_width)

        for x in (-28, -22, -16, -10, -4, 2, 8, 14, 20, 26):
            safe_x = self._safe_name(x)
            self._create_cube(stage, f"{group}/Rib_{safe_x}_LeftPost", (x, 2.1, -half_width), (0.14, 4.2, 0.14), frame_color)
            self._create_cube(stage, f"{group}/Rib_{safe_x}_RightPost", (x, 2.1, half_width), (0.14, 4.2, 0.14), frame_color)
            self._create_cube(stage, f"{group}/Rib_{safe_x}_LeftLowerArch", (x, 5.0, -6.6), (0.14, 0.14, 4.0), frame_color, rotation=(-28, 0, 0))
            self._create_cube(stage, f"{group}/Rib_{safe_x}_LeftUpperArch", (x, 7.0, -3.2), (0.14, 0.14, 3.8), frame_color, rotation=(-14, 0, 0))
            self._create_cube(stage, f"{group}/Rib_{safe_x}_RightUpperArch", (x, 7.0, 3.2), (0.14, 0.14, 3.8), frame_color, rotation=(14, 0, 0))
            self._create_cube(stage, f"{group}/Rib_{safe_x}_RightLowerArch", (x, 5.0, 6.6), (0.14, 0.14, 4.0), frame_color, rotation=(28, 0, 0))

        for z in (-half_width, -4.5, 0, 4.5, half_width):
            self._create_cube(stage, f"{group}/LongBeam_{self._safe_name(z)}", (0, 4.2 if abs(z) == half_width else 7.1, z), (GREENHOUSE_LENGTH, 0.12, 0.12), frame_color)

        for x in (-half_length, half_length):
            safe_x = self._safe_name(x)
            self._create_cube(stage, f"{group}/GlassEndFrame_{safe_x}_Left", (x, 2.2, -half_width), (0.10, 4.4, 0.10), edge_color, 0.88)
            self._create_cube(stage, f"{group}/GlassEndFrame_{safe_x}_Right", (x, 2.2, half_width), (0.10, 4.4, 0.10), edge_color, 0.88)
            self._create_cube(stage, f"{group}/GlassEndFrame_{safe_x}_Base", (x, 0.16, 0), (0.10, 0.10, GREENHOUSE_WIDTH), edge_color, 0.82)
            self._create_cube(stage, f"{group}/GlassEndFrame_{safe_x}_Ridge", (x, GREENHOUSE_RIDGE_HEIGHT, 0), (0.10, 0.10, 2.4), edge_color, 0.86)

        for z in (-7.8, -5.6, -3.4, -1.2, 1.2, 3.4, 5.6, 7.8):
            self._create_cube(
                stage,
                f"{group}/GlassRoofMullion_{self._safe_name(z)}",
                (0, 4.7, z),
                (GREENHOUSE_LENGTH, 0.13, 0.17),
                edge_color,
                0.82,
            )

    def _create_glass_cover_panels(self, stage, group, color, half_length, half_width):
        self._create_cube(stage, f"{group}/LeftWallGlass", (0, 2.1, -half_width), (GREENHOUSE_LENGTH, 4.2, 0.035), color, 0.10, roughness=0.03)
        self._create_cube(stage, f"{group}/RightWallGlass", (0, 2.1, half_width), (GREENHOUSE_LENGTH, 4.2, 0.035), color, 0.10, roughness=0.03)
        self._create_cube(stage, f"{group}/FrontGlass", (-half_length, 2.2, 0), (0.035, 4.4, GREENHOUSE_WIDTH), color, 0.08, roughness=0.03)
        self._create_cube(stage, f"{group}/BackGlass", (half_length, 2.2, 0), (0.035, 4.4, GREENHOUSE_WIDTH), color, 0.08, roughness=0.03)
        self._create_cube(stage, f"{group}/FrontUpperClosureGlass", (-half_length, 4.82, 0), (0.035, 0.88, GREENHOUSE_WIDTH), color, 0.07, roughness=0.03)
        self._create_cube(stage, f"{group}/BackUpperClosureGlass", (half_length, 4.82, 0), (0.035, 0.88, GREENHOUSE_WIDTH), color, 0.07, roughness=0.03)
        self._create_eave_arch_glass(stage, group, color)

        roof_panels = [
            ("LeftEave", -7.2, 4.7, -28, 3.2),
            ("LeftMid", -4.25, 6.15, -20, 3.1),
            ("LeftHigh", -1.95, 7.55, -10, 3.3),
            ("RightHigh", 1.95, 7.55, 10, 3.3),
            ("RightMid", 4.25, 6.15, 20, 3.1),
            ("RightEave", 7.2, 4.7, 28, 3.2),
        ]
        for name, z, y, rot_x, width in roof_panels:
            self._create_cube(
                stage,
                f"{group}/GlassRoofPanel_{name}",
                (0, y, z),
                (GREENHOUSE_LENGTH, 0.040, width),
                color,
                0.001,
                rotation=(rot_x, 0, 0),
                roughness=0.03,
            )
        self._create_cube(
            stage,
            f"{group}/GlassRidgeCap",
            (0, GREENHOUSE_RIDGE_HEIGHT - 0.08, 0),
            (GREENHOUSE_LENGTH, 0.035, 3.4),
            color,
            0.001,
            roughness=0.03,
        )
        self._create_cube(
            stage,
            f"{group}/GlassRidgeInfillLeft",
            (0, 8.03, -0.95),
            (GREENHOUSE_LENGTH, 0.035, 1.8),
            color,
            0.001,
            rotation=(-5, 0, 0),
            roughness=0.03,
        )
        self._create_cube(
            stage,
            f"{group}/GlassRidgeInfillRight",
            (0, 8.03, 0.95),
            (GREENHOUSE_LENGTH, 0.035, 1.8),
            color,
            0.001,
            rotation=(5, 0, 0),
            roughness=0.03,
        )

    def _create_eave_arch_glass(self, stage, group, color):
        arch_segments = (
            ("Lower", 4.42, 8.92, 8, 0.78),
            ("Middle", 4.72, 8.36, 18, 0.90),
            ("Upper", 5.02, 7.76, 28, 0.92),
        )
        for name, y, abs_z, abs_rot_x, width in arch_segments:
            self._create_cube(
                stage,
                f"{group}/LeftEaveArchGlass_{name}",
                (0, y, -abs_z),
                (GREENHOUSE_LENGTH, 0.035, width),
                color,
                0.001,
                rotation=(-abs_rot_x, 0, 0),
                roughness=0.03,
            )
            self._create_cube(
                stage,
                f"{group}/RightEaveArchGlass_{name}",
                (0, y, abs_z),
                (GREENHOUSE_LENGTH, 0.035, width),
                color,
                0.001,
                rotation=(abs_rot_x, 0, 0),
                roughness=0.03,
            )

    def _create_glass_panel_edges(self, stage, group, color, half_width):
        for side_name, z in (("Left", -half_width), ("Right", half_width)):
            for index, y in enumerate((1.0, 2.25, 3.5, 4.95), start=1):
                self._create_cube(
                    stage,
                    f"{group}/GlassSideMullion_{side_name}_{index}",
                    (0, y, z),
                    (GREENHOUSE_LENGTH, 0.16, 0.085),
                    color,
                    0.82,
                )

        roof_bands = [
            ("LeftEave", -7.25, 4.5, -28),
            ("LeftMid", -4.8, 6.0, -20),
            ("LeftHigh", -2.25, 7.5, -10),
            ("Ridge", 0.0, GREENHOUSE_RIDGE_HEIGHT, 0),
            ("RightHigh", 2.25, 7.5, 10),
            ("RightMid", 4.8, 6.0, 20),
            ("RightEave", 7.25, 4.5, 28),
        ]
        for name, z, y, rot_x in roof_bands:
            self._create_cube(
                stage,
                f"{group}/GlassRoofEdge_{name}",
                (0, y, z),
                (GREENHOUSE_LENGTH, 0.14, 0.52),
                color,
                0.78,
                rotation=(rot_x, 0, 0),
            )

    def _create_growing_beds(self, stage, unit_path, strawberry_asset=None):
        beds_group = f"{unit_path}/GrowingBeds"
        plants_group = f"{unit_path}/Plants"
        UsdGeom.Xform.Define(stage, beds_group)
        UsdGeom.Xform.Define(stage, plants_group)

        for bed_index, z in enumerate(BED_Z_POSITIONS, start=1):
            self._create_cube(
                stage,
                f"{beds_group}/WhiteRaisedGutter_{bed_index:02d}",
                translation=(0, GUTTER_HEIGHT, z),
                scale=(BED_LENGTH, 0.34, 0.82),
                color=(0.86, 0.86, 0.82),
            )
            self._create_cube(
                stage,
                f"{beds_group}/SoilTop_{bed_index:02d}",
                translation=(0, GUTTER_HEIGHT + 0.22, z),
                scale=(BED_LENGTH - 0.8, 0.08, 0.66),
                color=(0.15, 0.08, 0.035),
            )
            self._create_cube(
                stage,
                f"{beds_group}/IrrigationPipe_{bed_index:02d}",
                translation=(0, GUTTER_HEIGHT + 0.36, z),
                scale=(BED_LENGTH, 0.04, 0.04),
                color=(0.05, 0.08, 0.10),
            )
            self._create_cube(
                stage,
                f"{beds_group}/IrrigationFlow_{bed_index:02d}",
                translation=(0, GUTTER_HEIGHT + 0.42, z),
                scale=(BED_LENGTH - 1.0, 0.025, 0.13),
                color=(0.12, 0.62, 1.00),
                opacity=0.04,
                roughness=0.08,
            )
            for support_index, x in enumerate((-22, -14, -6, 2, 10, 18, 26), start=1):
                self._create_gutter_support(stage, beds_group, bed_index, support_index, x, z)
            for marker_index, x in enumerate((-18.0, -9.0, 0.0, 9.0, 18.0), start=1):
                self._create_soil_clump(stage, beds_group, bed_index, marker_index, x, z)
            for plant_index, x in enumerate(PLANT_X_POSITIONS, start=1):
                self._create_plant(stage, plants_group, bed_index, plant_index, x, z, strawberry_asset)

    def _create_gutter_support(self, stage, group, bed_index, support_index, x, z):
        path = f"{group}/Support_{bed_index:02d}_{support_index:02d}"
        color = (0.46, 0.50, 0.52)
        self._create_cube(stage, f"{path}_LeftLeg", (x, 0.78, z - 0.38), (0.08, 1.55, 0.08), color)
        self._create_cube(stage, f"{path}_RightLeg", (x, 0.78, z + 0.38), (0.08, 1.55, 0.08), color)
        self._create_cube(stage, f"{path}_CrossBeam", (x, 1.36, z), (0.12, 0.08, 1.10), color)
        self._create_cube(stage, f"{path}_Foot", (x, 0.08, z), (0.62, 0.08, 0.92), color)

    def _create_actuators(self, stage, unit_path):
        group = f"{unit_path}/Actuators"
        UsdGeom.Xform.Define(stage, group)
        fan_asset = self._find_fan_asset()

        for i, z in enumerate(LED_Z_POSITIONS, start=1):
            led_strip = self._create_cube(
                stage,
                f"{group}/LEDStrip_{i}",
                (0, 4.25, z),
                (BED_LENGTH, 0.08, 0.14),
                (1.0, 0.92, 0.30),
            )
            self._bind_emissive_material(stage, led_strip.GetPrim(), (1.0, 0.86, 0.28), LED_STRIP_INTENSITY)
            self._create_led_rect_light(
                stage,
                f"{group}/LEDStripLight_{i}",
                translation=(0, 4.12, z),
                width=BED_LENGTH - 1.0,
                height=0.18,
                intensity=LED_STRIP_INTENSITY,
                color=(1.0, 0.86, 0.42),
            )

        for i, x in enumerate((-18.0, 0.0, 18.0), start=1):
            self._create_cylinder(
                stage,
                f"{group}/CeilingFanDropRod_{i}",
                (x, FAN_DROP_ROD_Y, 0),
                radius=0.030,
                depth=FAN_DROP_ROD_DEPTH,
                color=(0.42, 0.46, 0.48),
            )
            if fan_asset:
                self._reference_asset(
                    stage,
                    f"{group}/CeilingFan_{i}",
                    fan_asset,
                    translation=(x, FAN_ASSET_Y, 0),
                    scale=(FAN_ASSET_SCALE, FAN_ASSET_SCALE, FAN_ASSET_SCALE),
                    rotation=FAN_ASSET_ROTATION,
                    instanceable=True,
                )
                self._create_cube(
                    stage,
                    f"{group}/CeilingFanStatusGlow_{i}",
                    (x, FAN_ASSET_Y - 0.25, 0),
                    (1.85, 0.05, 1.85),
                    (0.55, 0.95, 1.0),
                    opacity=0.0,
                    roughness=0.04,
                )
            else:
                self._create_cylinder(stage, f"{group}/CeilingFan_{i}", (x, FAN_ASSET_Y, 0), radius=0.78, depth=0.16, color=(0.12, 0.14, 0.15))
                self._create_cube(stage, f"{group}/CeilingFanHub_{i}", (x, FAN_ASSET_Y, 0), (0.30, 0.18, 0.30), (0.34, 0.38, 0.40))
                for blade_index, rotation in enumerate((0, 60, 120), start=1):
                    self._create_cube(
                        stage,
                        f"{group}/CeilingFanBlade_{i}_{blade_index}",
                        (x, FAN_ASSET_Y, 0),
                        (1.72, 0.035, 0.16),
                        (0.58, 0.62, 0.64),
                        rotation=(0, rotation, 0),
                    )
            for flow_index, y in enumerate((5.95, 5.35, 4.75), start=1):
                self._create_cube(
                    stage,
                    f"{group}/CeilingFanAirflow_{i}_{flow_index}",
                    (x, y, 0),
                    (2.35, 0.035, 0.18),
                    (0.58, 0.92, 1.0),
                    opacity=0.04,
                    rotation=(0, 0, 0),
                    roughness=0.05,
                )

        self._create_cube(stage, f"{group}/CO2Injector", (-25.8, 1.0, -7.2), (0.55, 1.1, 0.55), (0.20, 0.20, 0.24))
        self._create_cube(stage, f"{group}/WaterValve", (25.2, 0.75, 7.2), (0.60, 0.45, 0.45), (0.05, 0.28, 0.70))

    def _create_sensors(self, stage, unit_path):
        group = f"{unit_path}/Sensors"
        UsdGeom.Xform.Define(stage, group)

        sensors = [
            ("Light", (6.0, 2.18, -5.0), (0.34, 0.18, 0.34), (1.0, 0.78, 0.10)),
            ("SoilMoisture", (18.0, GUTTER_HEIGHT + 0.22, 7.2), (0.35, 0.35, 0.35), (0.06, 0.28, 0.85)),
            ("Humidity", (-18.0, 2.35, -8.92), (0.46, 0.34, 0.08), (0.90, 0.28, 0.10)),
            ("Temperature", (-14.0, 2.35, -8.92), (0.46, 0.34, 0.08), (0.74, 0.18, 0.12)),
            ("CO2", (-6.0, 2.35, 8.92), (0.46, 0.34, 0.08), (0.15, 0.15, 0.15)),
        ]
        for name, position, scale, color in sensors:
            sensor = self._create_cube(stage, f"{group}/{name}Sensor", position, scale, color)
            self._tag_sensor_prim(sensor.GetPrim(), name)
            self._create_sphere(
                stage,
                f"{group}/{name}SensorStatus",
                (position[0], position[1] + 0.28, position[2]),
                scale=(0.09, 0.09, 0.09),
                color=color,
            )

        self._create_cube(stage, f"{group}/LightSensorCollector", (6.0, 2.34, -5.0), (0.62, 0.025, 0.62), (1.0, 0.92, 0.42))
        for z in BED_Z_POSITIONS:
            safe_z = self._safe_name(z)
            self._create_cylinder(
                stage,
                f"{group}/SoilMoistureProbe_{safe_z}_A",
                (18.28, GUTTER_HEIGHT + 0.24, z - 0.18),
                radius=0.012,
                depth=0.58,
                color=(0.70, 0.78, 0.82),
            )
            self._create_cylinder(
                stage,
                f"{group}/SoilMoistureProbe_{safe_z}_B",
                (18.44, GUTTER_HEIGHT + 0.24, z + 0.18),
                radius=0.012,
                depth=0.58,
                color=(0.70, 0.78, 0.82),
            )

    def _create_lighting(self, stage):
        group = f"{SMART_FARM_PATH}/Lighting"
        UsdGeom.Xform.Define(stage, group)
        self._ensure_blue_sky(stage)

        fill_group = f"{group}/InteriorFill"
        UsdGeom.Xform.Define(stage, fill_group)
        for unit_name, x_offset, z_offset in GREENHOUSE_UNITS:
            for index, x in enumerate((-18.0, 0.0, 18.0), start=1):
                light = UsdLux.SphereLight.Define(stage, f"{fill_group}/{unit_name}_{index:02d}")
                light.CreateIntensityAttr(INTERIOR_FILL_INTENSITY)
                light.CreateRadiusAttr(0.65)
                light.CreateColorAttr(Gf.Vec3f(1.0, 0.96, 0.88))
                self._set_transform(light.GetPrim(), translation=(x_offset + x, 5.4, z_offset))


    def _ensure_blue_sky(self, stage):
        """Keep the greenhouse in a consistent blue-sky daylight environment."""
        group = f"{SMART_FARM_PATH}/Lighting"
        UsdGeom.Xform.Define(stage, group)

        dome = UsdLux.DomeLight.Define(stage, f"{group}/SoftSky")
        dome.CreateIntensityAttr(SKY_DOME_INTENSITY).Set(SKY_DOME_INTENSITY)
        dome.CreateColorAttr(BLUE_SKY_COLOR).Set(BLUE_SKY_COLOR)
        dome.GetPrim().CreateAttribute("smartfarm:environment", Sdf.ValueTypeNames.String).Set("blue-sky")

        sun = UsdLux.DistantLight.Define(stage, f"{group}/Sun")
        sun.CreateIntensityAttr(SUN_INTENSITY).Set(SUN_INTENSITY)
        sun.CreateAngleAttr(1.2).Set(1.2)
        sun.CreateColorAttr(BLUE_SKY_SUN_COLOR).Set(BLUE_SKY_SUN_COLOR)
        self._set_transform(sun.GetPrim(), rotation=(-45, 35, 0))

    def _configure_growth_simulation_timeline(self, stage):
        stage.SetStartTimeCode(SIMULATION_START_DAY)
        stage.SetEndTimeCode(SIMULATION_HARVEST_DAY)
        stage.SetFramesPerSecond(1.0)
        stage.SetTimeCodesPerSecond(1.0)
        self._sync_timeline_playback(SIMULATION_START_DAY, SIMULATION_HARVEST_DAY)

    def _configure_static_timeline(self, stage):
        stage.SetStartTimeCode(SIMULATION_START_DAY)
        stage.SetEndTimeCode(SIMULATION_START_DAY)
        stage.SetFramesPerSecond(1.0)
        stage.SetTimeCodesPerSecond(1.0)
        self._sync_timeline_playback(SIMULATION_START_DAY, SIMULATION_START_DAY)

    def _sync_timeline_playback(self, start_time, end_time):
        try:
            import omni.timeline

            timeline = omni.timeline.get_timeline_interface()
            timeline.set_start_time(start_time)
            timeline.set_end_time(end_time)
            timeline.set_current_time(start_time)
        except Exception:
            pass

    def _set_timeline_current_day(self, day, pause=True):
        try:
            import omni.timeline

            timeline = omni.timeline.get_timeline_interface()
            if pause:
                timeline.pause()
            timeline.set_current_time(float(day))
        except Exception as exc:
            print(f"[joon.smartfarm.twin] Timeline current-day update skipped: {exc}")

    def _create_plant(self, stage, group, bed_index, plant_index, x, z, strawberry_asset=None):
        base = f"{group}/Bed_{bed_index:02d}_Plant_{plant_index:02d}"
        UsdGeom.Xform.Define(stage, base)
        hang_direction = -1 if z > 0 else 1
        crown_z = z + hang_direction * 0.28
        if strawberry_asset:
            plant_scale = PLANT_INITIAL_SCALE if self._animate_growth else PLANT_FINAL_SCALE
            plant = self._reference_asset(
                stage,
                f"{base}/ExternalModel",
                strawberry_asset,
                translation=(x, GUTTER_HEIGHT + 0.42, crown_z),
                scale=(plant_scale, plant_scale, plant_scale),
                rotation=(-90, (plant_index % 4) * 35, 0),
                instanceable=True,
            )
            if self._animate_growth:
                self._animate_plant_growth(
                    plant.GetPrim(),
                    translation=(x, GUTTER_HEIGHT + 0.42, crown_z),
                    rotation=(-90, (plant_index % 4) * 35, 0),
                )
            self._create_hanging_runners(stage, base, x, z)
            self._create_strawberry_fruits(stage, base, x, z)
            return

        self._create_cylinder(
            stage,
            f"{base}/CrownStem",
            (x, GUTTER_HEIGHT + 0.14, crown_z),
            radius=0.035,
            depth=0.34,
            color=(0.12, 0.36, 0.08),
        )
        self._create_leaf(stage, f"{base}/Leaf_01", (x - 0.24, GUTTER_HEIGHT + 0.34, crown_z), (-10, 0, 30))
        self._create_leaf(stage, f"{base}/Leaf_02", (x + 0.24, GUTTER_HEIGHT + 0.34, crown_z), (-10, 0, -30))
        self._create_leaf(stage, f"{base}/Leaf_03", (x, GUTTER_HEIGHT + 0.42, crown_z + hang_direction * 0.22), (8, 0, 0))
        self._create_leaf(stage, f"{base}/Leaf_04", (x + 0.08, GUTTER_HEIGHT + 0.18, crown_z + hang_direction * 0.42), (-24, 0, 0))
        self._create_leaf(stage, f"{base}/Leaf_05", (x - 0.12, GUTTER_HEIGHT + 0.12, crown_z + hang_direction * 0.52), (-35, 0, 16))
        self._create_hanging_runners(stage, base, x, z)
        self._create_sphere(
            stage,
            f"{base}/LeafCluster",
            (x, GUTTER_HEIGHT + 0.30, crown_z + hang_direction * 0.18),
            scale=(0.40, 0.18, 0.34),
            color=(0.035, 0.40, 0.12),
        )
        self._create_strawberry_fruits(stage, base, x, z)

    def _create_hanging_runners(self, stage, base, x, bed_z):
        for side_name, side_offset in (("Left", -0.42), ("Right", 0.42)):
            runner = self._create_cylinder(
                stage,
                f"{base}/HangingRunner_{side_name}",
                (x, GUTTER_HEIGHT - 0.18, bed_z + side_offset),
                radius=0.018,
                depth=0.78,
                color=(0.10, 0.34, 0.08),
            )
            if self._animate_growth:
                self._animate_runner_growth(
                    runner.GetPrim(),
                    translation=(x, GUTTER_HEIGHT - 0.18, bed_z + side_offset),
                )

    def _create_strawberry_fruits(self, stage, base, x, bed_z):
        for side_name, side_offset in (("Left", -0.42), ("Right", 0.42)):
            fruit = self._create_strawberry_fruit(
                stage,
                f"{base}/Fruit_Unripe_{side_name}",
                self._runner_fruit_position(x, bed_z, side_offset),
                ripe=False,
            )
            if fruit:
                if self._animate_growth:
                    self._animate_fruit_growth(
                        fruit.GetPrim(),
                        translation=self._runner_fruit_position(x, bed_z, side_offset),
                        ripe=False,
                    )

    def _runner_fruit_position(self, x, bed_z, side_offset=0.42):
        return (x, GUTTER_HEIGHT - 0.56, bed_z + side_offset)

    def _create_leaf(self, stage, path, translation, rotation):
        self._create_sphere(
            stage,
            path,
            translation,
            scale=(0.26, 0.045, 0.12),
            color=(0.035, 0.42, 0.13),
            rotation=rotation,
        )

    def _create_strawberry_fruit(self, stage, path, translation, ripe=True):
        if self._strawberry_fruit_asset:
            scale = STRAWBERRY_FRUIT_ASSET_SCALE * (1.15 if ripe else 0.85)
            return self._reference_asset(
                stage,
                path,
                self._strawberry_fruit_asset,
                translation=translation,
                scale=(scale, scale, scale),
                rotation=STRAWBERRY_FRUIT_ASSET_ROTATION,
                instanceable=True,
            )

        color = (0.92, 0.04, 0.035) if ripe else (0.86, 0.72, 0.16)
        fruit = self._create_sphere(stage, path, translation, scale=(0.10, 0.14, 0.10), color=color)
        self._create_sphere(
            stage,
            f"{path}_Calyx",
            (translation[0], translation[1] + 0.11, translation[2]),
            scale=(0.08, 0.025, 0.08),
            color=(0.05, 0.30, 0.07),
        )
        return fruit

    def _animate_plant_growth(self, prim, translation, rotation):
        self._set_animated_transform(
            prim,
            translation=translation,
            rotation=rotation,
            scale_keys=(
                (SIMULATION_START_DAY, (PLANT_INITIAL_SCALE, PLANT_INITIAL_SCALE, PLANT_INITIAL_SCALE)),
                (SIMULATION_RUNNER_DAY, (0.016, 0.016, 0.016)),
                (SIMULATION_HARVEST_DAY, (PLANT_FINAL_SCALE, PLANT_FINAL_SCALE, PLANT_FINAL_SCALE)),
            ),
        )

    def _animate_runner_growth(self, prim, translation):
        self._set_visibility_animation(
            prim,
            (
                (SIMULATION_START_DAY, UsdGeom.Tokens.invisible),
                (SIMULATION_RUNNER_DAY - 0.1, UsdGeom.Tokens.invisible),
                (SIMULATION_RUNNER_DAY, UsdGeom.Tokens.inherited),
                (SIMULATION_HARVEST_DAY, UsdGeom.Tokens.inherited),
            ),
        )
        self._set_animated_transform(
            prim,
            translation=translation,
            scale_keys=(
                (SIMULATION_RUNNER_DAY, RUNNER_INITIAL_SCALE),
                (SIMULATION_HARVEST_DAY, RUNNER_FINAL_SCALE),
            ),
        )

    def _animate_fruit_growth(self, prim, translation, ripe=False):
        final_scale = STRAWBERRY_FRUIT_ASSET_SCALE * (1.15 if ripe else 0.85)
        self._set_visibility_animation(
            prim,
            (
                (SIMULATION_START_DAY, UsdGeom.Tokens.invisible),
                (SIMULATION_FRUIT_SET_DAY - 0.1, UsdGeom.Tokens.invisible),
                (SIMULATION_FRUIT_SET_DAY, UsdGeom.Tokens.inherited),
                (SIMULATION_HARVEST_DAY, UsdGeom.Tokens.inherited),
            ),
        )
        self._set_animated_transform(
            prim,
            translation=translation,
            rotation=STRAWBERRY_FRUIT_ASSET_ROTATION,
            scale_keys=(
                (
                    SIMULATION_FRUIT_SET_DAY,
                    (
                        final_scale * FRUIT_INITIAL_SCALE_FACTOR,
                        final_scale * FRUIT_INITIAL_SCALE_FACTOR,
                        final_scale * FRUIT_INITIAL_SCALE_FACTOR,
                    ),
                ),
                (
                    (SIMULATION_FRUIT_SET_DAY + SIMULATION_HARVEST_DAY) / 2.0,
                    (
                        final_scale * FRUIT_MID_SCALE_FACTOR,
                        final_scale * FRUIT_MID_SCALE_FACTOR,
                        final_scale * FRUIT_MID_SCALE_FACTOR,
                    ),
                ),
                (SIMULATION_HARVEST_DAY, (final_scale, final_scale, final_scale)),
            ),
        )

    def _create_soil_clump(self, stage, group, bed_index, marker_index, x, z):
        self._create_sphere(
            stage,
            f"{group}/SoilClump_{bed_index:02d}_{marker_index:02d}",
            translation=(x, GUTTER_HEIGHT + 0.30, z + 0.22),
            scale=(0.20, 0.05, 0.11),
            color=(0.09, 0.045, 0.02),
        )

    def _apply_demo_scenario(self, stage):
        for unit_path in self._unit_paths():
            self._highlight_leds(stage, unit_path)
            self._activate_irrigation(stage, unit_path)
            self._activate_fans(stage, unit_path)
            self._update_plants_for_harvest(stage, unit_path)

    def _apply_blueprint_visual_state(self, stage, blueprint_id, include_crop=True):
        self._apply_fixed_exposure_settings()
        state = BLUEPRINT_SENSOR_STATES[blueprint_id]
        actuator = BLUEPRINT_ACTUATOR_STATES[blueprint_id]
        self._current_sensor_state = state
        self._current_crop_state = _crop_state_from_sensor(state)
        self._current_actuator_state = actuator
        summary = BLUEPRINT_SERVICE_SUMMARY.get(blueprint_id, BLUEPRINT_SERVICE_SUMMARY["baseline"])
        growth_kpi = _growth_kpi_from_state(state, self._current_crop_state, summary)

        root = stage.GetPrimAtPath(SMART_FARM_PATH)
        if root:
            root.CreateAttribute("smartfarm:activeBlueprint", Sdf.ValueTypeNames.String).Set(blueprint_id)
            root.CreateAttribute("smartfarm:growthIndex", Sdf.ValueTypeNames.Float).Set(float(state["growth_index"]))
            root.CreateAttribute("smartfarm:growthHealthScore", Sdf.ValueTypeNames.Int).Set(
                int(growth_kpi["healthScore"])
            )
            root.CreateAttribute("smartfarm:fruitMaturityPercent", Sdf.ValueTypeNames.Int).Set(
                int(growth_kpi["fruitMaturityPercent"])
            )
            root.CreateAttribute("smartfarm:harvestReadinessPercent", Sdf.ValueTypeNames.Int).Set(
                int(growth_kpi["harvestReadinessPercent"])
            )
            root.CreateAttribute("smartfarm:mainLimitingFactor", Sdf.ValueTypeNames.String).Set(
                growth_kpi["mainLimitingFactor"]
            )
            root.CreateAttribute("smartfarm:recommendedBlueprint", Sdf.ValueTypeNames.String).Set(
                self._recommended_blueprint_id()
            )

        self._apply_virtual_sensor_state_to_scene(stage, state)
        for unit_path in self._unit_paths():
            self._apply_led_profile(stage, unit_path, actuator)
            self._apply_irrigation_profile(stage, unit_path, actuator, state)
            self._apply_fan_profile(stage, unit_path, actuator)
            self._apply_co2_profile(stage, unit_path, actuator)
            if include_crop:
                self._apply_crop_profile(stage, unit_path, state, blueprint_id)
        self._update_service_decision_panel(stage, blueprint_id)

    def _apply_led_profile(self, stage, unit_path, actuator):
        percent = actuator["led_intensity_percent"]
        intensity_factor = percent / 100.0
        # Keep all plans in the same blue-sky exposure band. The actuator
        # percentage is still encoded in metadata, strip thickness and tone, but
        # we deliberately clamp rendered light output so Plan B does not blow out
        # the greenhouse and Plan A does not look under-lit.
        intensity = LED_VISUAL_INTENSITY_MIN + (LED_VISUAL_INTENSITY_MAX - LED_VISUAL_INTENSITY_MIN) * intensity_factor
        color = (1.0, 0.80 + 0.12 * intensity_factor, 0.34 + 0.08 * intensity_factor)
        strip_thickness = 0.07 + 0.12 * intensity_factor
        strip_width = 0.10 + 0.18 * intensity_factor

        for index in range(1, 5):
            prim = stage.GetPrimAtPath(f"{unit_path}/Actuators/LEDStrip_{index}")
            if prim:
                self._set_display_color(prim, color)
                self._set_transform(
                    prim,
                    translation=(0, 4.25, LED_Z_POSITIONS[index - 1]),
                    scale=(BED_LENGTH, strip_thickness, strip_width),
                )
                prim.CreateAttribute("smartfarm:ledIntensityPercent", Sdf.ValueTypeNames.Int).Set(percent)
                prim.CreateAttribute("smartfarm:photoperiodHours", Sdf.ValueTypeNames.Int).Set(
                    actuator["photoperiod_hours"]
                )
                self._bind_emissive_material(stage, prim, color, intensity)

            light = stage.GetPrimAtPath(f"{unit_path}/Actuators/LEDStripLight_{index}")
            if light:
                UsdLux.RectLight(light).GetIntensityAttr().Set(0.0)
                UsdLux.RectLight(light).GetColorAttr().Set(Gf.Vec3f(*color))

    def _apply_irrigation_profile(self, stage, unit_path, actuator, state):
        pulses = actuator["irrigation_pulses_per_day"] if actuator["water_valve_open"] else 0
        moisture = state["substrate_moisture_percent"]
        flow_factor = min(1.0, pulses / 4.0)
        opacity = 0.04 + 0.66 * flow_factor
        flow_scale_z = 0.07 + 0.18 * flow_factor
        valve_color = (0.05, 0.25 + 0.45 * flow_factor, 0.72 + 0.25 * flow_factor)
        soil_darkness = max(0.035, 0.13 - (moisture / 100.0) * 0.08)

        self._highlight_device(
            stage,
            f"{unit_path}/Actuators/WaterValve",
            valve_color,
            scale=(0.55 + 0.25 * flow_factor, 0.42 + 0.20 * flow_factor, 0.42 + 0.20 * flow_factor),
        )

        for bed_index in range(1, len(BED_Z_POSITIONS) + 1):
            flow = stage.GetPrimAtPath(f"{unit_path}/GrowingBeds/IrrigationFlow_{bed_index:02d}")
            if flow:
                self._set_translucent_visual(stage, flow, (0.08, 0.70, 1.0), opacity, roughness=0.05)
                self._set_transform(
                    flow,
                    translation=(0, GUTTER_HEIGHT + 0.42, BED_Z_POSITIONS[bed_index - 1]),
                    scale=(BED_LENGTH - 1.0, 0.025 + 0.035 * flow_factor, flow_scale_z),
                )
                flow.CreateAttribute("smartfarm:irrigationPulsesPerDay", Sdf.ValueTypeNames.Int).Set(pulses)
            soil = stage.GetPrimAtPath(f"{unit_path}/GrowingBeds/SoilTop_{bed_index:02d}")
            if soil:
                self._set_display_color(soil, (soil_darkness, soil_darkness * 0.62, soil_darkness * 0.34))

    def _apply_fan_profile(self, stage, unit_path, actuator):
        duty = actuator["fan_duty_percent"]
        fan_factor = duty / 100.0
        opacity = 0.04 + 0.72 * fan_factor
        airflow_color = (0.38 + 0.22 * fan_factor, 0.86 + 0.10 * fan_factor, 1.0)

        for fan_index, x in enumerate((-18.0, 0.0, 18.0), start=1):
            fan = stage.GetPrimAtPath(f"{unit_path}/Actuators/CeilingFan_{fan_index}")
            hub = stage.GetPrimAtPath(f"{unit_path}/Actuators/CeilingFanHub_{fan_index}")
            glow = stage.GetPrimAtPath(f"{unit_path}/Actuators/CeilingFanStatusGlow_{fan_index}")
            if fan:
                self._set_display_color(fan, (0.10, 0.38 + 0.42 * fan_factor, 0.50 + 0.42 * fan_factor))
                fan.CreateAttribute("smartfarm:fanDutyPercent", Sdf.ValueTypeNames.Int).Set(duty)
            if hub:
                self._set_display_color(hub, airflow_color)
            if glow:
                self._set_translucent_visual(stage, glow, airflow_color, 0.10 + 0.42 * fan_factor, roughness=0.04)
                self._set_transform(
                    glow,
                    translation=(x, FAN_ASSET_Y - 0.25, 0),
                    scale=(1.2 + 1.5 * fan_factor, 0.05, 1.2 + 1.5 * fan_factor),
                )
            for flow_index, y in enumerate((5.95, 5.35, 4.75), start=1):
                airflow = stage.GetPrimAtPath(f"{unit_path}/Actuators/CeilingFanAirflow_{fan_index}_{flow_index}")
                if airflow:
                    self._set_translucent_visual(stage, airflow, airflow_color, opacity, roughness=0.04)
                    self._set_transform(
                        airflow,
                        translation=(x, y, 0),
                        scale=(1.7 + 3.0 * fan_factor, 0.035, 0.11 + 0.52 * fan_factor),
                    )

    def _apply_co2_profile(self, stage, unit_path, actuator):
        co2 = actuator["co2_ppm"]
        co2_factor = min(1.0, max(0.0, (co2 - 400) / 300.0))
        injector = stage.GetPrimAtPath(f"{unit_path}/Actuators/CO2Injector")
        if injector:
            color = (0.20 + 0.20 * co2_factor, 0.22 + 0.55 * co2_factor, 0.24 + 0.18 * co2_factor)
            self._set_display_color(injector, color)
            self._set_transform(
                injector,
                translation=(-25.8, 1.0, -7.2),
                scale=(0.48 + 0.28 * co2_factor, 1.0 + 0.35 * co2_factor, 0.48 + 0.28 * co2_factor),
            )
            injector.CreateAttribute("smartfarm:co2SetpointPpm", Sdf.ValueTypeNames.Int).Set(co2)

    def _apply_crop_profile(self, stage, unit_path, state, blueprint_id):
        growth_index = state["growth_index"]
        crop_state = _crop_state_from_sensor(state)
        maturity = float(crop_state["fruitMaturity"])
        disease = float(crop_state["diseasePressure"])
        fruit_scale_factor = _clamp(0.35 + maturity * 0.85, 0.35, 1.20)
        if maturity < 0.55:
            fruit_color = (0.84, 0.66, 0.18)  # immature yellow/orange
        elif maturity < 0.75:
            fruit_color = (0.94, 0.35, 0.18)  # turning
        else:
            fruit_color = (0.98, 0.08, 0.06)  # ripe
        leaf_vigor = _clamp(growth_index - disease * 0.18, 0.18, 0.75)
        leaf_color = (
            0.03 + max(0.0, disease - 0.45) * 0.08,
            0.30 + leaf_vigor * 0.38,
            0.10 + leaf_vigor * 0.16,
        )

        for bed_index in range(1, len(BED_Z_POSITIONS) + 1):
            for plant_index in range(1, len(PLANT_X_POSITIONS) + 1):
                base = f"{unit_path}/Plants/Bed_{bed_index:02d}_Plant_{plant_index:02d}"
                leaf = stage.GetPrimAtPath(f"{base}/LeafCluster")
                fruit = stage.GetPrimAtPath(f"{base}/Fruit")
                if leaf:
                    self._set_display_color(leaf, leaf_color)
                    self._set_transform(
                        leaf,
                        translation=self._get_translate_value(leaf),
                        scale=(0.34 + 0.30 * growth_index, 0.17 + 0.13 * growth_index, 0.30 + 0.24 * growth_index),
                    )
                if not fruit and blueprint_id != "baseline" and plant_index in (1, 3, 6, 9, 12):
                    self._create_strawberry_fruit(
                        stage,
                        f"{base}/Fruit",
                        self._fruit_position_for(bed_index, plant_index),
                        ripe=maturity >= 0.75,
                    )
                    fruit = stage.GetPrimAtPath(f"{base}/Fruit")
                if fruit:
                    if fruit.IsA(UsdGeom.Gprim):
                        self._set_display_color(fruit, fruit_color)
                        self._set_transform(
                            fruit,
                            translation=self._get_translate_value(fruit),
                            scale=(
                                0.08 + 0.07 * fruit_scale_factor,
                                0.10 + 0.06 * fruit_scale_factor,
                                0.08 + 0.07 * fruit_scale_factor,
                            ),
                        )
                    else:
                        scale = STRAWBERRY_FRUIT_ASSET_SCALE * fruit_scale_factor
                        self._set_transform(
                            fruit,
                            translation=self._get_translate_value(fruit),
                            rotation=STRAWBERRY_FRUIT_ASSET_ROTATION,
                            scale=(scale, scale, scale),
                        )

    def _update_service_decision_panel(self, stage, selected_blueprint_id):
        panel_path = f"{SMART_FARM_PATH}/ServiceDecisionPanel"
        if stage.GetPrimAtPath(panel_path):
            stage.RemovePrim(panel_path)
        UsdGeom.Xform.Define(stage, panel_path)

        ranked = self._ranked_blueprints()
        recommended_id = ranked[0]["blueprintId"] if ranked else selected_blueprint_id
        for index, item in enumerate(ranked):
            score = item["score"]
            blueprint_id = item["blueprintId"]
            is_selected = blueprint_id == selected_blueprint_id
            is_recommended = blueprint_id == recommended_id
            color = (0.18, 0.82, 0.36) if is_recommended else (0.30, 0.45, 0.72)
            if is_selected:
                color = (1.0, 0.78, 0.18)
            bar = self._create_cube(
                stage,
                f"{panel_path}/ScoreBar_{index + 1}_{self._safe_name(blueprint_id)}",
                translation=(-21 + index * 14.0, 8.6, -21.5),
                scale=(3.0 + score / 10.0, 0.28, 0.56),
                color=color,
                opacity=0.82,
                roughness=0.08,
            )
            prim = bar.GetPrim()
            prim.CreateAttribute("smartfarm:blueprintId", Sdf.ValueTypeNames.String).Set(blueprint_id)
            prim.CreateAttribute("smartfarm:score", Sdf.ValueTypeNames.Float).Set(float(score))
            prim.CreateAttribute("smartfarm:selected", Sdf.ValueTypeNames.Bool).Set(is_selected)
            prim.CreateAttribute("smartfarm:recommended", Sdf.ValueTypeNames.Bool).Set(is_recommended)

    def _sensor_metric_values(self, state):
        return {
            "sensor_seed": state["scenario_seed"],
            "sensor_dli": f'{state["dli_mol_m2_day"]:.1f} mol/m2/day',
            "sensor_moisture": f'{state["substrate_moisture_percent"]}% substrate',
            "sensor_humidity": f'{state["humidity_percent"]}% RH',
            "sensor_temperature": f'{state["temperature_c"]:.1f} C',
            "sensor_co2": f'{state["co2_ppm"]} ppm',
        }

    def _update_baseline_metrics(self):
        metrics = {
            "stage": "Flowering / delayed fruit set",
            "scenario": "60-day growth simulation ready",
            "light": "LED 40% / 12h",
            "moisture": "31% substrate",
            "fan": "0% idle",
            "expected_shipment": "2026-12-28",
            "yield_score": "72 / 100",
            "opex": "Baseline",
            "recommendation": "Press Timeline Play, then run Gemma 4.0 blueprint",
        }
        metrics.update(self._sensor_metric_values(BASELINE_VIRTUAL_SENSOR_STATE))
        for key, value in metrics.items():
            self._metric_labels[key].text = value

    def _update_mature_metrics(self):
        metrics = {
            "stage": "Mature fruiting scene",
            "scenario": "Static V1 environment",
            "light": "LED 40% / 12h",
            "moisture": "31% substrate",
            "fan": "0% idle",
            "expected_shipment": "2026-12-28",
            "yield_score": "72 / 100",
            "opex": "Baseline",
            "recommendation": "Use Growth Simulation for Timeline playback",
        }
        metrics.update(self._sensor_metric_values(BASELINE_VIRTUAL_SENSOR_STATE))
        for key, value in metrics.items():
            self._metric_labels[key].text = value

    def _update_demo_metrics(self):
        metrics = {
            "stage": "Fruiting -> early harvest",
            "scenario": "Gemma 4.0: LED + irrigation + fan",
            "light": "LED 80% / 16h",
            "moisture": "48% substrate",
            "fan": "55% airflow",
            "expected_shipment": "2026-12-22",
            "yield_score": "87 / 100",
            "opex": "+18% electricity/water",
            "recommendation": "Keep optimized schedule",
        }
        metrics.update(self._sensor_metric_values(OPTIMIZED_VIRTUAL_SENSOR_STATE))
        for key, value in metrics.items():
            self._metric_labels[key].text = value

    def _update_metrics_for_blueprint(self, blueprint_id):
        summary = BLUEPRINT_SERVICE_SUMMARY.get(blueprint_id, BLUEPRINT_SERVICE_SUMMARY["plan-b-early-shipment"])
        state = BLUEPRINT_SENSOR_STATES.get(blueprint_id, OPTIMIZED_VIRTUAL_SENSOR_STATE)
        metrics = {
            "stage": state["crop_stage"].replace("_", " ").title(),
            "scenario": f'Gemma 4.0: {summary["name"]}',
            "light": summary["actuators"]["led"],
            "moisture": summary["actuators"]["moisture"],
            "fan": summary["actuators"]["fan"],
            "expected_shipment": summary["expected_shipment"],
            "yield_score": f'{summary["yield_score"]} / 100',
            "opex": summary["opex"],
            "recommendation": "Applied by Smart Farm service API",
        }
        metrics.update(self._sensor_metric_values(state))
        for key, value in metrics.items():
            self._metric_labels[key].text = value

    def _current_blueprint_snapshot(self, goal="balanced", constraints=None, vision_assessment=None):
        base_sensor = copy.deepcopy(getattr(self, "_current_sensor_state", BASELINE_VIRTUAL_SENSOR_STATE))
        base_crop = copy.deepcopy(getattr(self, "_current_crop_state", _crop_state_from_sensor(base_sensor)))
        actuator = copy.deepcopy(getattr(self, "_current_actuator_state", BLUEPRINT_ACTUATOR_STATES["baseline"]))
        summary = BLUEPRINT_SERVICE_SUMMARY.get(
            self._applied_blueprint_id or "baseline", BLUEPRINT_SERVICE_SUMMARY["baseline"]
        )
        growth_kpi = _growth_kpi_from_state(base_sensor, base_crop, summary)
        return build_state_snapshot(
            base_sensor,
            base_crop,
            actuator,
            growth_kpi=growth_kpi,
            vision_assessment=vision_assessment,
            goal=goal,
            constraints=constraints or {},
            reference_date=PLANNING_REFERENCE_DATE,
        )

    def _generate_gemma_rag_blueprints(
        self,
        goal="balanced",
        constraints=None,
        no_llm=False,
        vision_assessment=None,
        reason="manual",
    ):
        """Generate Gemma/RAG-grounded candidates from current twin state.

        The external TwinX RAG service is treated as a knowledge/setpoint
        provider.  The local twin remains the validator: it compares current
        sensor/crop state to the RAG advice, creates candidate actuator recipes,
        runs the existing harvest simulation, ranks the outcomes, and registers
        generated candidates so Apply works exactly like static plans.
        """
        base_sensor = copy.deepcopy(getattr(self, "_current_sensor_state", BASELINE_VIRTUAL_SENSOR_STATE))
        base_crop = copy.deepcopy(getattr(self, "_current_crop_state", _crop_state_from_sensor(base_sensor)))
        snapshot = self._current_blueprint_snapshot(
            goal=goal,
            constraints=constraints,
            vision_assessment=vision_assessment,
        )

        try:
            rag_request_trace = {}
            try:
                generated = self._rag_client.generate_blueprints(snapshot, candidate_count=3, no_llm=no_llm)
                rag_request_trace = dict(getattr(self._rag_client, "last_request_trace", {}) or {})
                rag_advice = generated["ragAdvice"]
                gap_analysis = generated.get("gapAnalysis") or analyze_gap(snapshot, rag_advice)
                candidate_specs = list(generated.get("candidates") or [])
                generation_mode = generated.get("generationMode", "gemma_json")
                rag_status = (
                    "live_blueprint_generator_with_fallback"
                    if generated.get("warnings") or generation_mode == "deterministic_fallback"
                    else "live_blueprint_generator"
                )
                rag_recommended_id = generated.get("recommendedCandidateId")
            except RagAdapterError as generate_exc:
                if not is_blueprint_generation_unsupported(generate_exc):
                    raise
                # Backward-compatible path for the current TwinX RAG deployment:
                # /recommend returns date/stage setpoints, while the local Twin
                # converts those setpoints and the Baseline snapshot into
                # candidate actuator recipes.
                rag_advice = self._rag_client.recommend(snapshot, no_llm=no_llm)
                rag_request_trace = dict(getattr(self._rag_client, "last_request_trace", {}) or {})
                gap_analysis = analyze_gap(snapshot, rag_advice)
                candidate_specs = generate_blueprint_candidates(snapshot, rag_advice, gap_analysis)
                rag_status = f"legacy_recommend_fallback: {generate_exc}"
                rag_recommended_id = None
        except RagAdapterError as exc:
            fallback = self._run_daily_planning(reason=f"{reason}:rag_unavailable")
            if self._latest_planning_run is not None:
                self._latest_planning_run["gemmaRagStatus"] = f"unavailable: {exc}"
                self._latest_planning_run["source"] = PLANNER_VERSION
                self._latest_planning_run["ragRequestTrace"] = dict(
                    getattr(self._rag_client, "last_request_trace", {}) or {}
                )
                self._latest_planning_run["decisionRationale"] += (
                    f" External TwinX RAG was unavailable ({exc}); deterministic planner fallback was used."
                )
            fallback["message"] = (
                "TwinX Gemma/RAG unavailable; deterministic daily planner fallback completed. "
                f"{exc}"
            )
            fallback["planningRun"] = self._latest_planning_run
            self._set_status(fallback["message"])
            return fallback

        baseline_comparison = self._build_planning_candidate(
            "baseline",
            base_sensor,
            base_crop,
            BLUEPRINT_ACTUATOR_STATES["baseline"],
            meta={
                "provider": "current-twin",
                "kind": "baseline_current_state",
                "name": "Baseline / Current Twin",
                "tagline": "Fixed representation of the current observed Twin state.",
                "operatorIntent": "Represent the current farm state; not a generated plan candidate.",
                "controlFocus": BLUEPRINT_SERVICE_SUMMARY["baseline"].get("control_focus", ""),
                "tradeoff": BLUEPRINT_SERVICE_SUMMARY["baseline"].get("tradeoff", ""),
                "rationale": "Baseline is the current Twin state used as the generation and simulation anchor.",
            },
        )
        candidates = []
        for spec in candidate_specs:
            candidates.append(
                self._build_planning_candidate(
                    spec["id"],
                    base_sensor,
                    base_crop,
                    spec["actuatorState"],
                    meta=spec,
                )
            )

        candidates, quality_gate_summary = self._apply_twin_quality_gate(candidates, base_sensor, base_crop)
        if quality_gate_summary["repairedCount"]:
            rag_status = f"{rag_status}+twin_quality_gate"

        plan_slot_rotation = self._planning_run_seq % 3
        candidates = assign_rotating_plan_slots(candidates, rotation=plan_slot_rotation)
        self._refresh_candidate_branch_slots(candidates)
        rag_recommended_display_id = None
        if rag_recommended_id:
            for candidate in candidates:
                if candidate.get("sourceCandidateId") == rag_recommended_id:
                    rag_recommended_display_id = candidate.get("id")
                    break

        ranked = sorted(candidates, key=lambda item: item["score"], reverse=True)
        recommended_id = ranked[0]["id"] if ranked else None
        for candidate in candidates:
            candidate["recommended"] = candidate["id"] == recommended_id

        self._planning_run_seq += 1
        run_id = f"ragrun-{self._planning_run_seq:04d}-{uuid.uuid4().hex[:8]}"
        top_factor = (gap_analysis.get("limitingFactors") or ["current state gap"])[0]
        generation_criteria = self._build_generation_criteria(
            goal,
            constraints,
            base_sensor,
            base_crop,
            vision_assessment=vision_assessment,
            rag_advice=rag_advice,
            gap_analysis=gap_analysis,
            rag_request_trace=rag_request_trace,
            quality_gate=quality_gate_summary,
        )
        self._latest_planning_run = {
            "contractVersion": PLANNING_CONTRACT_VERSION,
            "runId": run_id,
            "createdAt": date.today().isoformat(),
            "reason": reason,
            "goal": goal,
            "currentDay": int(base_crop["day"]),
            "source": "twinx-gemma-rag-adapter-v1",
            "gemmaRagStatus": rag_status,
            "currentStateSnapshot": snapshot,
            "currentSensorState": self._sensor_state_response(base_sensor),
            "currentCropState": base_crop,
            "baselineComparison": baseline_comparison,
            "ragAdvice": rag_advice,
            "gapAnalysis": gap_analysis,
            "generationCriteria": generation_criteria,
            "ragRequestTrace": rag_request_trace,
            "ragRecommendedCandidateId": rag_recommended_id,
            "ragRecommendedDisplayBlueprintId": rag_recommended_display_id,
            "qualityGate": quality_gate_summary,
            "planSlotPolicy": {
                "mode": "rotating_score_slot",
                "rotation": plan_slot_rotation,
                "description": (
                    "Plan A/B/C are neutral display slots. Generated candidates are scored by the Twin, "
                    "then score ranks rotate across A/B/C each run so letters do not imply fixed strategy."
                ),
            },
            "recommendedBlueprintId": recommended_id,
            "candidates": candidates,
            "decisionRationale": (
                f"Recommended {recommended_id}: Gemma/RAG advice identified {top_factor}; "
                "the SmartFarm twin converted it into actuator candidates and selected the best "
                "rolling-horizon simulation score. "
                + (
                    f"Twin quality gate repaired {quality_gate_summary['repairedCount']} infeasible candidate(s) once. "
                    if quality_gate_summary["repairedCount"]
                    else ""
                )
                + "Plan letters are rotating display slots, not fixed strategy classes."
            ),
        }

        self._publish_planning_candidates(candidates)
        message = f"Gemma/RAG blueprint run {run_id} completed. Recommended {recommended_id}."
        self._set_status(message)
        return self._state_response(ok=True, message=message)

    def _apply_twin_quality_gate(self, candidates, base_sensor, base_crop):
        """Repair clearly infeasible Gemma/RAG candidates once, then re-score.

        The original Gemma proposal is preserved in each repaired candidate's
        ``qualityGate`` metadata.  Scores are never overwritten: repaired plans
        pass through the same `_build_planning_candidate` simulation as every
        other plan.
        """

        repaired_candidates = []
        repairs = []
        for index, candidate in enumerate(candidates):
            if not candidate_needs_quality_repair(
                candidate,
                min_score=QUALITY_GATE_MIN_SCORE,
                max_horizon_days=PLANNING_MAX_HORIZON_DAYS,
                disease_pressure_limit=DISEASE_PRESSURE_LIMIT,
            ):
                repaired_candidates.append(candidate)
                continue

            repaired = self._repair_infeasible_candidate_once(candidate, index, base_sensor, base_crop)
            repaired_candidates.append(repaired)
            if repaired is not candidate and repaired.get("qualityGate", {}).get("status") == "repaired":
                repairs.append(repaired["qualityGate"])

        return repaired_candidates, {
            "mode": "repair_infeasible_candidates_once",
            "minViableScore": QUALITY_GATE_MIN_SCORE,
            "targetScore": QUALITY_GATE_TARGET_SCORE,
            "repairedCount": len(repairs),
            "repairs": repairs,
            "note": (
                "Original Gemma/RAG candidates are preserved in candidate.qualityGate and original* fields; "
                "the repaired actuator recipe is re-simulated by the Twin before ranking."
            ),
        }

    def _repair_infeasible_candidate_once(self, candidate, index, base_sensor, base_crop):
        original_score = self._candidate_score(candidate)
        original_actuator = self._snake_actuator_from_candidate(candidate)
        source_id = candidate.get("sourceCandidateId") or candidate.get("blueprintId") or candidate.get("id") or f"candidate-{index + 1}"
        source_name = candidate.get("sourceCandidateName") or candidate.get("name") or candidate.get("label") or source_id

        best_repaired = None
        for profile_name, actuator in self._quality_gate_repair_profiles(original_actuator, index, base_sensor, base_crop):
            repaired_id = f"{source_id}-quality-gate-{profile_name}"
            repaired = self._build_planning_candidate(
                repaired_id,
                base_sensor,
                base_crop,
                actuator,
                meta=self._quality_gate_meta(candidate, profile_name, actuator, original_score),
            )
            repaired["qualityGateProfile"] = profile_name
            if best_repaired is None or self._candidate_score(repaired) > self._candidate_score(best_repaired):
                best_repaired = repaired
            if not candidate_needs_quality_repair(
                repaired,
                min_score=QUALITY_GATE_TARGET_SCORE,
                max_horizon_days=PLANNING_MAX_HORIZON_DAYS,
                disease_pressure_limit=DISEASE_PRESSURE_LIMIT,
            ):
                best_repaired = repaired
                break

        if best_repaired is None or self._candidate_score(best_repaired) <= original_score:
            candidate["qualityGate"] = {
                "status": "kept_original",
                "reason": self._quality_gate_reason(candidate),
                "originalCandidateId": source_id,
                "originalCandidateName": source_name,
                "originalScore": original_score,
                "message": "Twin quality gate found no improving safe repair; original Gemma/RAG candidate kept.",
            }
            return candidate

        repaired_score = self._candidate_score(best_repaired)
        best_repaired["sourceCandidateId"] = source_id
        best_repaired["sourceCandidateName"] = source_name
        best_repaired["sourceCandidateScore"] = original_score
        best_repaired["originalScore"] = original_score
        best_repaired["originalActuatorTarget"] = candidate.get("actuatorTarget")
        best_repaired["originalPredicted"] = candidate.get("predicted")
        best_repaired["originalSimulation"] = candidate.get("simulation")
        best_repaired["qualityGate"] = {
            "status": "repaired",
            "reason": self._quality_gate_reason(candidate),
            "profile": str(best_repaired.get("qualityGateProfile") or "safe_repair"),
            "originalCandidateId": source_id,
            "originalCandidateName": source_name,
            "originalScore": original_score,
            "repairedScore": repaired_score,
            "scoreDelta": round(repaired_score - original_score, 1),
            "originalActuatorTarget": candidate.get("actuatorTarget"),
            "repairedActuatorTarget": best_repaired.get("actuatorTarget"),
            "message": "Gemma/RAG proposal was infeasible in Twin; airflow/light/CO2 were repaired once and re-simulated.",
        }
        return best_repaired

    def _quality_gate_repair_profiles(self, original_actuator, index, base_sensor, base_crop):
        dli_gap = max(0.0, 16.0 - float(base_sensor.get("dli_mol_m2_day", 16.0)))
        humidity_excess = max(0.0, float(base_sensor.get("humidity_percent", 70.0)) - 70.0)
        moisture_gap = max(0.0, 44.0 - float(base_sensor.get("substrate_moisture_percent", 44.0)))
        disease_pressure = float(base_crop.get("diseasePressure", 0.42))
        high_disease = disease_pressure >= DISEASE_PRESSURE_LIMIT or humidity_excess >= 8.0

        base_pulses = 2 if high_disease else 3
        if moisture_gap >= 8.0:
            base_pulses += 1
        base_pulses = int(_clamp(base_pulses, 2, 4))

        variants = [
            (
                "fast-safe",
                {
                    "led_intensity_percent": int(_clamp(78 + dli_gap * 1.7, 74, 88)),
                    "photoperiod_hours": int(_clamp(15 + dli_gap * 0.18, 15, 17)),
                    "irrigation_pulses_per_day": int(_clamp(base_pulses, 2, 4)),
                    "fan_duty_percent": int(_clamp(74 + humidity_excess * 0.8, 72, 92)),
                    "co2_ppm": int(_clamp(720 + dli_gap * 18, 650, 820)),
                },
            ),
            (
                "balanced-safe",
                {
                    "led_intensity_percent": int(_clamp(68 + dli_gap * 1.5, 66, 82)),
                    "photoperiod_hours": int(_clamp(14 + dli_gap * 0.18, 14, 16)),
                    "irrigation_pulses_per_day": int(_clamp(base_pulses, 2, 3)),
                    "fan_duty_percent": int(_clamp(78 + humidity_excess * 0.7, 74, 94)),
                    "co2_ppm": int(_clamp(640 + dli_gap * 14, 580, 760)),
                },
            ),
            (
                "airflow-safe",
                {
                    "led_intensity_percent": int(_clamp(60 + dli_gap * 1.4, 60, 76)),
                    "photoperiod_hours": int(_clamp(14 + dli_gap * 0.12, 14, 16)),
                    "irrigation_pulses_per_day": int(_clamp(base_pulses - (1 if high_disease else 0), 2, 3)),
                    "fan_duty_percent": int(_clamp(86 + humidity_excess * 0.7, 82, 96)),
                    "co2_ppm": int(_clamp(600 + dli_gap * 10, 560, 720)),
                },
            ),
        ]

        if index:
            variants = variants[index % len(variants):] + variants[:index % len(variants)]

        for profile_name, patch in variants:
            actuator = dict(original_actuator)
            actuator.update(patch)
            actuator["water_valve_open"] = bool(actuator.get("irrigation_pulses_per_day", 0) > 0)
            yield profile_name, actuator

    def _quality_gate_meta(self, candidate, profile_name, actuator, original_score):
        provider = str(candidate.get("provider") or "twinx-gemma-rag")
        if "quality-gate" not in provider:
            provider = f"{provider}+twin-quality-gate"
        reason = (
            f"Twin quality gate repaired an infeasible Gemma/RAG proposal using the {profile_name} profile. "
            f"Original score was {original_score:.1f}/100; repaired score is computed by re-simulation."
        )
        return {
            "provider": provider,
            "kind": f"{candidate.get('kind', 'gemma_rag_generated')}_quality_repaired",
            "name": candidate.get("name"),
            "tagline": candidate.get("tagline") or "Gemma/RAG candidate repaired once by Twin quality gate.",
            "operatorIntent": candidate.get("operatorIntent") or reason,
            "controlFocus": (
                f"Quality gate {profile_name}: LED {actuator['led_intensity_percent']}% / "
                f"{actuator['photoperiod_hours']}h, irrigation {actuator['irrigation_pulses_per_day']}/day, "
                f"fan {actuator['fan_duty_percent']}%, CO2 {actuator['co2_ppm']} ppm"
            ),
            "tradeoff": (
                "Transparent repair: preserves the original Gemma candidate in JSON trace, but uses a safer "
                "actuator recipe for Twin ranking."
            ),
            "rationale": reason,
            "expectedSensorShift": candidate.get("expectedSensorShift", {}),
            "ragEvidence": candidate.get("ragEvidence", []),
            "ragAdvice": candidate.get("ragAdvice"),
            "gapAnalysis": candidate.get("gapAnalysis"),
            "qualityGateProfile": profile_name,
        }

    def _snake_actuator_from_candidate(self, candidate):
        raw = candidate.get("actuatorTarget") or candidate.get("actuatorState") or {}
        if not hasattr(raw, "get"):
            raw = {}

        def number(*keys, default):
            for key in keys:
                if raw.get(key) is not None:
                    try:
                        return float(raw.get(key))
                    except (TypeError, ValueError):
                        break
            return float(default)

        return {
            "led_intensity_percent": int(_clamp(number("ledIntensityPercent", "led_intensity_percent", default=70), 0, 100)),
            "photoperiod_hours": int(_clamp(number("photoperiodHours", "photoperiod_hours", default=15), 8, 18)),
            "water_valve_open": bool(raw.get("waterValveOpen", raw.get("water_valve_open", True))),
            "irrigation_pulses_per_day": int(_clamp(number("irrigationPulsesPerDay", "irrigation_pulses_per_day", default=3), 0, 8)),
            "fan_duty_percent": int(_clamp(number("fanDutyPercent", "fan_duty_percent", default=70), 0, 100)),
            "co2_ppm": int(_clamp(number("co2Ppm", "co2_ppm", default=650), 380, 900)),
        }

    def _quality_gate_reason(self, candidate):
        reasons = []
        score = self._candidate_score(candidate)
        if score < QUALITY_GATE_MIN_SCORE:
            reasons.append(f"score {score:.1f} below {QUALITY_GATE_MIN_SCORE:.0f}")
        predicted = candidate.get("predicted") or {}
        if str(predicted.get("diseaseRisk") or "").lower() == "high":
            reasons.append("high disease risk")
        simulation = candidate.get("simulation") or {}
        if int(simulation.get("harvestDay", 0) or 0) >= int(simulation.get("maxHorizonDays", PLANNING_MAX_HORIZON_DAYS) or PLANNING_MAX_HORIZON_DAYS):
            reasons.append("harvest not reached within horizon")
        final_crop = simulation.get("finalCropState") or {}
        try:
            disease_pressure = float(final_crop.get("diseasePressure", 0.0))
            if disease_pressure > DISEASE_PRESSURE_LIMIT:
                reasons.append(f"disease pressure {disease_pressure:.2f} above {DISEASE_PRESSURE_LIMIT:.2f}")
        except (TypeError, ValueError):
            pass
        return "; ".join(reasons) or "candidate failed quality gate"

    def _candidate_score(self, candidate):
        try:
            return float(candidate.get("score", 0.0))
        except (TypeError, ValueError):
            return 0.0

    def _readiness_percent_from_crop(self, crop_state):
        maturity = float(crop_state.get("fruitMaturity", 0.0))
        yield_score = float(crop_state.get("estimatedYield", 0.0))
        disease_pressure = float(crop_state.get("diseasePressure", 0.0))
        readiness = maturity * 62.0 + (yield_score / 100.0) * 22.0 + (1.0 - disease_pressure) * 16.0
        return round(_clamp(readiness, 0.0, 100.0), 1)

    def _trajectory_from_simulation(self, base_crop, sim):
        start_day = int(base_crop.get("day", 0))
        harvest_day = int(sim.get("harvestDay", start_day))
        points = [
            {
                "label": "current",
                "day": start_day,
                "dayOffset": 0,
                "maturityPercent": round(float(base_crop.get("fruitMaturity", 0.0)) * 100.0, 1),
                "harvestReadinessPercent": self._readiness_percent_from_crop(base_crop),
                "diseasePressurePercent": round(float(base_crop.get("diseasePressure", 0.0)) * 100.0, 1),
                "yieldScore": round(float(base_crop.get("estimatedYield", 0.0)), 1),
                "opexDeltaPercent": 0,
            }
        ]
        daily_states = list(sim.get("dailyStates") or [])
        wanted_offsets = {7, 14, 21, 28, 35, 42, 49, 56}
        seen_days = {start_day}
        for index, state in enumerate(daily_states):
            day = int(state.get("day", start_day))
            offset = max(0, day - start_day)
            is_terminal = index == len(daily_states) - 1 or day >= harvest_day
            if offset not in wanted_offsets and not is_terminal:
                continue
            if day in seen_days:
                continue
            seen_days.add(day)
            crop_point = {
                "fruitMaturity": float(state.get("fruitMaturity", 0.0)),
                "diseasePressure": float(state.get("diseasePressure", 0.0)),
                "estimatedYield": float(state.get("estimatedYield", 0.0)),
            }
            points.append(
                {
                    "label": "harvest" if day >= harvest_day and harvest_day < PLANNING_MAX_HORIZON_DAYS else f"D+{offset}",
                    "day": day,
                    "dayOffset": offset,
                    "maturityPercent": round(crop_point["fruitMaturity"] * 100.0, 1),
                    "harvestReadinessPercent": self._readiness_percent_from_crop(crop_point),
                    "diseasePressurePercent": round(crop_point["diseasePressure"] * 100.0, 1),
                    "yieldScore": round(crop_point["estimatedYield"], 1),
                    "opexDeltaPercent": int(sim.get("opexDeltaPercent", 0)),
                }
            )
            if is_terminal:
                break
        if len(points) > 8:
            return points[:7] + [points[-1]]
        return points

    def _actuator_recipe_text(self, actuator):
        return (
            f"LED {actuator['led_intensity_percent']}%/{actuator['photoperiod_hours']}h | "
            f"Irr {actuator['irrigation_pulses_per_day']}/day | "
            f"Fan {actuator['fan_duty_percent']}% | CO2 {actuator['co2_ppm']} ppm"
        )

    def _branch_metadata(self, blueprint_id, name, kind, provider, rationale, actuator, sim, base_sensor, base_crop, meta):
        days_earlier = max(0, BASELINE_HARVEST_DAY - int(sim.get("harvestDay", BASELINE_HARVEST_DAY)))
        basis = "Gemma/RAG proposal" if "gemma" in str(provider).lower() or "rag" in str(provider).lower() else "Twin deterministic proposal"
        if str(kind).startswith("baseline"):
            basis = "Current Twin baseline"
        drivers = []
        if float(base_sensor.get("dli_mol_m2_day", 16.0)) < 14.0:
            drivers.append("low DLI")
        if float(base_sensor.get("humidity_percent", 70.0)) > 72.0:
            drivers.append("high humidity")
        if float(base_sensor.get("substrate_moisture_percent", 44.0)) < 40.0:
            drivers.append("low substrate moisture")
        if float(base_crop.get("diseasePressure", 0.0)) >= DISEASE_PRESSURE_LIMIT:
            drivers.append("high disease pressure")
        if not drivers:
            drivers.append("current crop state")
        validation_passed = (
            float(sim.get("score", 0.0)) > 0.0
            and int(sim.get("harvestDay", PLANNING_MAX_HORIZON_DAYS)) < PLANNING_MAX_HORIZON_DAYS
            and float((sim.get("finalCropState") or {}).get("diseasePressure", 1.0)) <= DISEASE_PRESSURE_LIMIT
            and float(sim.get("yieldScore", 0.0)) >= MIN_ACCEPTABLE_YIELD_SCORE
        )
        return {
            "branchId": blueprint_id,
            "displaySlot": name,
            "candidateBasis": basis,
            "stateDrivers": drivers,
            "whyGenerated": meta.get("operatorIntent") or rationale,
            "actuatorRecipe": self._actuator_recipe_text(actuator),
            "riskSummary": (
                f"{sim.get('diseaseRisk', '-')} disease risk | OpEx {int(sim.get('opexDeltaPercent', 0)):+d}% | "
                f"{sim.get('riskNote', '')}"
            ),
            "replanTrigger": (
                "Replan when camera/readiness is >8pt below this trajectory, disease pressure crosses "
                f"{int(DISEASE_PRESSURE_LIMIT * 100)}%, or new RAG evidence changes the limiting factor."
            ),
            "validationSummary": (
                f"Twin score {float(sim.get('score', 0.0)):.1f}/100 | ship -{days_earlier}d | "
                f"yield {int(sim.get('yieldScore', 0))}/100"
            ),
            "validationPassed": validation_passed,
        }

    def _vision_state_for_criteria(self, vision_assessment):
        if not vision_assessment:
            return {
                "attached": False,
                "summary": "No camera capture attached to this generation run.",
            }
        return {
            "attached": True,
            "source": vision_assessment.get("source"),
            "provider": vision_assessment.get("provider"),
            "visionModelStatus": vision_assessment.get("visionModelStatus"),
            "growthProgressPercent": vision_assessment.get(
                "growthProgressPercent", vision_assessment.get("harvestReadinessPercent")
            ),
            "healthScore": vision_assessment.get("healthScore"),
            "diseaseRisk": vision_assessment.get("diseaseRisk"),
            "phenotypeStage": vision_assessment.get("phenotypeStage"),
        }

    def _build_generation_criteria(
        self,
        goal,
        constraints,
        base_sensor,
        base_crop,
        vision_assessment=None,
        rag_advice=None,
        gap_analysis=None,
        rag_request_trace=None,
        quality_gate=None,
    ):
        rag_advice = rag_advice or {}
        gap_analysis = gap_analysis or {}
        rag_request_trace = rag_request_trace or {}
        quality_gate = quality_gate or {}
        sources = list(rag_advice.get("evidence") or [])
        return {
            "contractVersion": PLANNING_CONTRACT_VERSION,
            "objective": goal,
            "objectiveWeights": dict(PLANNING_OBJECTIVE_WEIGHTS),
            "scoreFormula": {
                "activePath": "planning_run_candidates",
                "planningRunCandidateFormula": (
                    "clamp(daysEarlier * 1.4 + yieldScore * 0.65 + costSavingBonus "
                    "- positiveOpexDelta * 0.40 - diseasePenalty - unsafeHarvestPenalty "
                    "+ disease-context adjustment, 0, 100)"
                ),
                "planningRunTerms": {
                    "costSavingBonus": "min(max(0, -opexDeltaPercent), 8) * 0.30",
                    "diseasePenalty": "labelPenalty(high=42, controlled=10, low=0, other=24) + diseasePressure * 30",
                    "unsafeHarvestPenalty": "22 when harvestDay >= maxHorizonDays, else 0",
                    "diseaseContextAdjustment": (
                        "+18 for disease-safe under high baseline pressure; -20 for low-cost under high baseline pressure; "
                        "-8 for early-shipment when high baseline pressure and harvest is within 5 days"
                    ),
                },
                "staticFallbackFormula": (
                    "clamp(yieldScore + daysEarlier * 0.80 + costSavingBonus "
                    "- positiveOpexDelta * 0.25 - diseasePenalty - LEDStressPenalty, 0, 100)"
                ),
                "staticFallbackTerms": {
                    "costSavingBonus": "max(0, -opexPercent) * 0.20",
                    "diseasePenalty": "riskPenalty(high=18, controlled=3, low=0, other=8)",
                    "LEDStressPenalty": "max(0, ledIntensityPercent - 80) * 0.08",
                },
                "note": (
                    "Generation uses the planning-run candidate formula. The static fallback formula is listed only "
                    "for pre-generation UI rows when no planningRun exists."
                ),
            },
            "usedSensorState": self._sensor_state_response(base_sensor),
            "usedCropState": {
                "day": int(base_crop.get("day", 0)),
                "fruitMaturityPercent": round(float(base_crop.get("fruitMaturity", 0.0)) * 100.0, 1),
                "diseasePressurePercent": round(float(base_crop.get("diseasePressure", 0.0)) * 100.0, 1),
                "estimatedYield": round(float(base_crop.get("estimatedYield", 0.0)), 1),
            },
            "usedVisionState": self._vision_state_for_criteria(vision_assessment),
            "ragDocsCount": len(sources),
            "ragProvider": rag_advice.get("provider"),
            "ragModel": rag_advice.get("model"),
            "ragEndpoint": rag_request_trace.get("path"),
            "gapFactors": list(gap_analysis.get("limitingFactors") or [])[:4],
            "constraints": constraints or {},
            "twinValidation": {
                "horizonDays": PLANNING_MAX_HORIZON_DAYS,
                "harvestMaturityThresholdPercent": int(round(HARVEST_MATURITY_THRESHOLD * 100)),
                "minYieldScore": MIN_ACCEPTABLE_YIELD_SCORE,
                "diseasePressureLimitPercent": int(round(DISEASE_PRESSURE_LIMIT * 100)),
                "scoreBasis": "earlier shipment + yield - OpEx - disease/safety penalties, then Twin quality gate",
            },
            "qualityGate": {
                "mode": quality_gate.get("mode", "none"),
                "minViableScore": quality_gate.get("minViableScore", QUALITY_GATE_MIN_SCORE),
                "repairedCount": quality_gate.get("repairedCount", 0),
            },
            "branchingPolicy": {
                "mode": "branch_candidates_then_replan",
                "description": "Plan A/B/C are neutral branch slots; applying one does not erase the others.",
                "replanTriggers": [
                    "camera/readiness >8pt below branch trajectory",
                    f"disease pressure >{int(DISEASE_PRESSURE_LIMIT * 100)}%",
                    "new RAG evidence or sensor gap changes limiting factor",
                ],
            },
        }

    def _refresh_candidate_branch_slots(self, candidates):
        for candidate in candidates:
            branch = candidate.get("branch")
            if isinstance(branch, dict):
                branch["branchId"] = candidate.get("id") or candidate.get("blueprintId")
                branch["displaySlot"] = candidate.get("name") or candidate.get("label")
                if candidate.get("sourceCandidateId"):
                    branch["sourceCandidateId"] = candidate.get("sourceCandidateId")
                if candidate.get("sourceScoreRank"):
                    branch["sourceScoreRank"] = candidate.get("sourceScoreRank")

    def _run_daily_planning(self, reason="manual"):
        """POC deterministic replacement for the future Gemma/RAG planner.

        It treats the current virtual sensor/crop state as today's observation,
        generates three operating prescriptions, simulates each to harvest with
        a lightweight daily transition model, ranks them, and stores the result
        in memory.  Phase3 can persist this object to Postgres without changing
        the web contract.
        """
        base_sensor = copy.deepcopy(getattr(self, "_current_sensor_state", BASELINE_VIRTUAL_SENSOR_STATE))
        base_crop = copy.deepcopy(getattr(self, "_current_crop_state", _crop_state_from_sensor(base_sensor)))
        actuator_targets = _candidate_actuators_from_state(base_sensor)
        candidates = []
        for blueprint_id in ("baseline", "plan-a-low-cost", "plan-b-early-shipment", "plan-c-disease-safe"):
            candidates.append(self._build_planning_candidate(blueprint_id, base_sensor, base_crop, actuator_targets[blueprint_id]))

        ranked = sorted(candidates, key=lambda item: item["score"], reverse=True)
        recommended_id = ranked[0]["id"] if ranked else None
        for candidate in candidates:
            candidate["recommended"] = candidate["id"] == recommended_id

        self._planning_run_seq += 1
        run_id = f"planrun-{self._planning_run_seq:04d}-{uuid.uuid4().hex[:8]}"
        generation_criteria = self._build_generation_criteria(
            "deterministic_daily_planning",
            {},
            base_sensor,
            base_crop,
            rag_advice={"provider": PLANNER_VERSION, "model": "local-twin-simulator", "evidence": []},
            gap_analysis={"limitingFactors": [_growth_limiting_factor(base_sensor)]},
        )
        self._latest_planning_run = {
            "contractVersion": PLANNING_CONTRACT_VERSION,
            "runId": run_id,
            "createdAt": date.today().isoformat(),
            "reason": reason,
            "currentDay": int(base_crop["day"]),
            "source": PLANNER_VERSION,
            "gemmaRagStatus": "pending_external_pipeline",
            "currentSensorState": self._sensor_state_response(base_sensor),
            "currentCropState": base_crop,
            "generationCriteria": generation_criteria,
            "recommendedBlueprintId": recommended_id,
            "candidates": candidates,
            "decisionRationale": (
                f"Recommended {recommended_id}: best V2 disease-aware rolling-horizon score from synthetic "
                "sensor/crop transition model. Gemma/RAG candidate generation is intentionally "
                "stubbed until the external pipeline is delivered."
            ),
        }

        self._publish_planning_candidates(candidates)
        message = f"Daily planning run {run_id} completed. Recommended {recommended_id}."
        self._set_status(message)
        return self._state_response(ok=True, message=message)

    def _build_planning_candidate(self, blueprint_id, base_sensor, base_crop, actuator, meta=None):
        meta = meta or {}
        sim = _simulate_to_harvest(base_sensor, base_crop, actuator, blueprint_id)
        default_names = {
            "baseline": "Baseline",
            "plan-a-low-cost": "Plan A",
            "plan-b-early-shipment": "Plan B",
            "plan-c-disease-safe": "Plan C",
            "blueprint-a": "Plan A",
            "blueprint-b": "Plan B",
            "blueprint-c": "Plan C",
        }
        name = default_names.get(blueprint_id, meta.get("name") or blueprint_id.replace("-", " ").title())
        if str(meta.get("name") or meta.get("label") or "").lower() in {"plan a", "blueprint a"}:
            name = "Plan A"
        elif str(meta.get("name") or meta.get("label") or "").lower() in {"plan b", "blueprint b"}:
            name = "Plan B"
        elif str(meta.get("name") or meta.get("label") or "").lower() in {"plan c", "blueprint c"}:
            name = "Plan C"
        kind = meta.get("kind") or {
            "baseline": "baseline",
            "plan-a-low-cost": "low_cost",
            "plan-b-early-shipment": "early_shipment",
            "plan-c-disease-safe": "disease_safe",
            "blueprint-a": "generated",
            "blueprint-b": "generated",
            "blueprint-c": "generated",
        }.get(blueprint_id, "generated")
        tagline = meta.get("tagline") or {
            "baseline": "Current operation projected forward from today's synthetic state.",
            "plan-a-low-cost": "Moderate correction while limiting LED and airflow cost.",
            "plan-b-early-shipment": "Aggressive DLI + CO₂ push for earliest viable harvest.",
            "plan-c-disease-safe": "Humidity-first control with stronger airflow safety margin.",
        }.get(blueprint_id, "Generated candidate from current sensor/crop state.")
        sensor_target = _sensor_from_actuator(base_sensor, sim["finalCropState"], actuator, blueprint_id)
        horizon = max(1, int(sim["harvestDay"]) - int(base_crop["day"]))
        rationale = meta.get("rationale") or self._planning_rationale(blueprint_id, base_sensor, sim, actuator)
        provider = meta.get("provider", "synthetic-deterministic")
        trajectory = self._trajectory_from_simulation(base_crop, sim)
        branch = self._branch_metadata(blueprint_id, name, kind, provider, rationale, actuator, sim, base_sensor, base_crop, meta)
        candidate = {
            "id": blueprint_id,
            "blueprintId": blueprint_id,
            "kind": kind,
            "provider": provider,
            "name": name,
            "tagline": tagline,
            "horizonDays": horizon,
            "targetShipmentDate": sim["shipmentDate"],
            "sensorTarget": {
                "dliMolM2Day": sensor_target["dli_mol_m2_day"],
                "soilMoisturePercent": sensor_target["substrate_moisture_percent"],
                "humidityPercent": sensor_target["humidity_percent"],
                "temperatureC": sensor_target["temperature_c"],
                "co2Ppm": sensor_target["co2_ppm"],
            },
            "actuatorTarget": {
                "ledIntensityPercent": actuator["led_intensity_percent"],
                "photoperiodHours": actuator["photoperiod_hours"],
                "waterValveOpen": actuator["water_valve_open"],
                "irrigationPulsesPerDay": actuator["irrigation_pulses_per_day"],
                "fanDutyPercent": actuator["fan_duty_percent"],
                "co2Ppm": actuator["co2_ppm"],
            },
            "predicted": {
                "shipmentDate": sim["shipmentDate"],
                "yieldScore": sim["yieldScore"],
                "opexDeltaPercent": sim["opexDeltaPercent"],
                "diseaseRisk": sim["diseaseRisk"],
                "riskNote": sim["riskNote"],
            },
            "recommended": False,
            "score": sim["score"],
            "scoreBreakdown": sim.get("scoreBreakdown", {}),
            "rationale": rationale,
            "operatorIntent": meta.get("operatorIntent", rationale),
            "controlFocus": meta.get("controlFocus", ""),
            "tradeoff": meta.get("tradeoff", ""),
            "expectedSensorShift": meta.get("expectedSensorShift", {}),
            "ragEvidence": meta.get("ragEvidence", []),
            "ragAdvice": meta.get("ragAdvice"),
            "gapAnalysis": meta.get("gapAnalysis"),
            "branch": branch,
            "trajectory": trajectory,
            "simulation": {
                "startDay": int(base_crop["day"]),
                "harvestDay": sim["harvestDay"],
                "maxHorizonDays": PLANNING_MAX_HORIZON_DAYS,
                "scoreBreakdown": sim.get("scoreBreakdown", {}),
                "dailyStates": sim["dailyStates"],
                "finalCropState": sim["finalCropState"],
            },
        }
        return candidate

    def _planning_rationale(self, blueprint_id, base_sensor, sim, actuator):
        days_earlier = BASELINE_HARVEST_DAY - int(sim["harvestDay"])
        drivers = []
        if base_sensor["dli_mol_m2_day"] < 14:
            drivers.append("DLI below target")
        if base_sensor["humidity_percent"] > 72:
            drivers.append("humidity pressure high")
        if base_sensor["substrate_moisture_percent"] < 40:
            drivers.append("substrate moisture low")
        if sim["diseaseRisk"] == "high":
            drivers.append("harvest blocked by disease pressure")
        elif blueprint_id in {"plan-c-disease-safe", "blueprint-c"} and base_sensor["humidity_percent"] > 72:
            drivers.append("disease-safe airflow reduces RH risk")
        if not drivers:
            drivers.append("current envelope stable")
        return (
            f"{', '.join(drivers)}; LED {actuator['led_intensity_percent']}%, "
            f"{actuator['photoperiod_hours']}h photo, fan {actuator['fan_duty_percent']}% -> "
            f"{max(0, days_earlier)}d earlier, yield {sim['yieldScore']}, "
            f"disease {sim['diseaseRisk']}."
        )

    def _publish_planning_candidates(self, candidates):
        for candidate in candidates:
            blueprint_id = candidate["id"]
            if blueprint_id == "baseline":
                # Keep baseline as the immutable reset/current-operation anchor.
                # The planning-run baseline comparison remains available in
                # self._latest_planning_run, but the runtime registry must not
                # be overwritten with projected harvest-day state.
                continue
            sensor = candidate["sensorTarget"]
            actuator = candidate["actuatorTarget"]
            prediction = candidate["predicted"]
            BLUEPRINT_SENSOR_STATES[blueprint_id] = {
                "scenario_seed": f"daily-planning-{blueprint_id}",
                "twin_day": int(candidate["simulation"]["finalCropState"]["day"]),
                "crop_stage": "daily_planning_projection",
                "growth_index": float(candidate["simulation"]["finalCropState"]["fruitMaturity"]),
                "dli_mol_m2_day": sensor["dliMolM2Day"],
                "substrate_moisture_percent": sensor["soilMoisturePercent"],
                "humidity_percent": sensor["humidityPercent"],
                "temperature_c": sensor["temperatureC"],
                "co2_ppm": sensor["co2Ppm"],
                "disease_risk": prediction["diseaseRisk"],
            }
            BLUEPRINT_ACTUATOR_STATES[blueprint_id] = {
                "led_intensity_percent": actuator["ledIntensityPercent"],
                "photoperiod_hours": actuator["photoperiodHours"],
                "water_valve_open": actuator["waterValveOpen"],
                "irrigation_pulses_per_day": actuator["irrigationPulsesPerDay"],
                "fan_duty_percent": actuator["fanDutyPercent"],
                "co2_ppm": actuator.get("co2Ppm", sensor["co2Ppm"]),
            }
            opex = "Baseline" if blueprint_id == "baseline" else f"{prediction['opexDeltaPercent']:+d}% electricity/water"
            control_focus = candidate.get("controlFocus") or (
                f"LED {actuator['ledIntensityPercent']}% / {actuator['photoperiodHours']}h, "
                f"irrigation {actuator['irrigationPulsesPerDay']}/day, "
                f"fan {actuator['fanDutyPercent']}%, CO₂ {actuator.get('co2Ppm', sensor['co2Ppm'])} ppm"
            )
            source_label = candidate.get("provider", "synthetic-deterministic")
            BLUEPRINT_SERVICE_SUMMARY[blueprint_id] = {
                "name": candidate["name"],
                "summary": candidate.get("tagline") or candidate.get("rationale", "Planner-generated blueprint candidate."),
                "operator_intent": candidate.get("operatorIntent") or candidate.get("rationale", "Planner-generated daily control candidate."),
                "control_focus": control_focus,
                "tradeoff": candidate.get("tradeoff") or f"Projected OpEx {opex}; disease risk {prediction['diseaseRisk']}.",
                "expected_shipment": prediction["shipmentDate"],
                "yield_score": prediction["yieldScore"],
                "opex": opex,
                "source": source_label,
                "rag_evidence": candidate.get("ragEvidence", []),
                "actuators": {
                    "led": f"LED {actuator['ledIntensityPercent']}% / {actuator['photoperiodHours']}h",
                    "moisture": f"{sensor['soilMoisturePercent']}% substrate",
                    "fan": f"{actuator['fanDutyPercent']}% airflow",
                },
            }

    def _recommended_blueprint_id(self):
        ranked = self._ranked_blueprints()
        return ranked[0]["blueprintId"] if ranked else "plan-b-early-shipment"

    def _ranked_blueprints(self):
        if getattr(self, "_latest_planning_run", None):
            candidates = []
            for candidate in self._latest_planning_run.get("candidates", []):
                prediction = candidate.get("predicted", {})
                blueprint_id = candidate.get("id") or candidate.get("blueprintId")
                summary = BLUEPRINT_SERVICE_SUMMARY.get(blueprint_id, {})
                candidates.append({
                    "blueprintId": blueprint_id,
                    "blueprintName": candidate.get("name"),
                    "summary": summary.get("summary", candidate.get("rationale", "")),
                    "operatorIntent": candidate.get("operatorIntent") or summary.get("operator_intent", candidate.get("rationale", "")),
                    "controlFocus": candidate.get("controlFocus") or summary.get("control_focus", ""),
                    "tradeoff": candidate.get("tradeoff") or summary.get("tradeoff", ""),
                    "provider": candidate.get("provider", summary.get("source", "")),
                    "score": candidate.get("score", 0),
                    "scoreBreakdown": candidate.get("scoreBreakdown", {}),
                    "expectedShipment": prediction.get("shipmentDate"),
                    "yieldScore": prediction.get("yieldScore"),
                    "opex": f"{prediction.get('opexDeltaPercent', 0):+d}% electricity/water",
                    "daysEarlier": self._days_earlier(prediction.get("shipmentDate", "")),
                    "diseaseRisk": prediction.get("diseaseRisk"),
                    "rationale": candidate.get("rationale", ""),
                    "ragEvidence": candidate.get("ragEvidence", []),
                    "gapAnalysis": candidate.get("gapAnalysis"),
                    "predicted": prediction,
                    "actuatorTarget": candidate.get("actuatorTarget", {}),
                    "sensorTarget": candidate.get("sensorTarget", {}),
                    "branch": candidate.get("branch", {}),
                    "trajectory": candidate.get("trajectory", []),
                    "simulation": candidate.get("simulation", {}),
                })
            if candidates:
                return sorted(candidates, key=lambda item: item["score"], reverse=True)
        candidates = []
        for blueprint_id in ("plan-a-low-cost", "plan-b-early-shipment", "plan-c-disease-safe"):
            candidates.append(self._score_blueprint(blueprint_id))
        return sorted(candidates, key=lambda item: item["score"], reverse=True)

    def _score_blueprint(self, blueprint_id):
        summary = BLUEPRINT_SERVICE_SUMMARY[blueprint_id]
        state = BLUEPRINT_SENSOR_STATES[blueprint_id]
        actuator = BLUEPRINT_ACTUATOR_STATES[blueprint_id]

        yield_score = float(summary["yield_score"])
        days_earlier = self._days_earlier(summary["expected_shipment"])
        opex_percent = self._parse_opex_percent(summary["opex"])
        disease_penalty = {"high": 18.0, "controlled": 3.0, "low": 0.0}.get(state["disease_risk"], 8.0)
        energy_penalty = max(0.0, opex_percent) * 0.25
        cost_saving_bonus = max(0.0, -opex_percent) * 0.20
        early_shipment_bonus = days_earlier * 0.80
        actuator_stress_penalty = max(0.0, actuator["led_intensity_percent"] - 80) * 0.08
        raw_score = yield_score + early_shipment_bonus + cost_saving_bonus - energy_penalty - disease_penalty - actuator_stress_penalty
        score = raw_score
        score = round(max(0.0, min(100.0, score)), 1)
        return {
            "blueprintId": blueprint_id,
            "blueprintName": summary["name"],
            "summary": summary.get("summary", ""),
            "operatorIntent": summary.get("operator_intent", ""),
            "controlFocus": summary.get("control_focus", ""),
            "tradeoff": summary.get("tradeoff", ""),
            "score": score,
            "scoreBreakdown": {
                "daysEarlier": days_earlier,
                "earlyShipmentBonus": round(early_shipment_bonus, 1),
                "yieldContribution": round(yield_score, 1),
                "costSavingBonus": round(cost_saving_bonus, 1),
                "opexPenalty": round(energy_penalty, 1),
                "diseasePenalty": round(disease_penalty, 1),
                "unsafeHarvestPenalty": round(actuator_stress_penalty, 1),
                "diseaseContextAdjustment": 0.0,
                "rawScore": round(raw_score, 1),
                "finalScore": score,
                "formula": "static fallback: yield + ship + cost - opex - disease - LED stress",
            },
            "expectedShipment": summary["expected_shipment"],
            "yieldScore": summary["yield_score"],
            "opex": summary["opex"],
            "daysEarlier": days_earlier,
            "diseaseRisk": state["disease_risk"],
            "rationale": (
                f'{days_earlier}d early, yield {summary["yield_score"]}, '
                f'disease {state["disease_risk"]}, opex {summary["opex"]}'
            ),
        }

    def _days_earlier(self, expected_shipment):
        try:
            baseline = date.fromisoformat(BLUEPRINT_SERVICE_SUMMARY["baseline"]["expected_shipment"])
            candidate = date.fromisoformat(expected_shipment)
            return max(0, (baseline - candidate).days)
        except Exception:
            return 0

    def _parse_opex_percent(self, text):
        if text == "Baseline":
            return 0.0
        token = text.split("%", 1)[0].strip()
        try:
            return float(token)
        except ValueError:
            return 0.0

    def _sensor_state_response(self, state):
        return {
            "scenarioSeed": state["scenario_seed"],
            "twinDay": state["twin_day"],
            "cropStage": state["crop_stage"],
            "growthIndex": state["growth_index"],
            "dliMolM2Day": state["dli_mol_m2_day"],
            "soilMoisturePercent": state["substrate_moisture_percent"],
            "humidityPercent": state["humidity_percent"],
            "temperatureC": state["temperature_c"],
            "co2Ppm": state["co2_ppm"],
            "diseaseRisk": state["disease_risk"],
        }

    def _state_response(self, ok=True, message=""):
        stage = omni.usd.get_context().get_stage()
        if self._applied_blueprint_id == "manual-actuator" and self._manual_service_summary:
            summary = self._manual_service_summary
        else:
            summary = BLUEPRINT_SERVICE_SUMMARY.get(
                self._applied_blueprint_id or "baseline", BLUEPRINT_SERVICE_SUMMARY["baseline"]
            )
        state = self._current_sensor_state
        crop = getattr(self, "_current_crop_state", _crop_state_from_sensor(state))
        actuator = getattr(self, "_current_actuator_state", BLUEPRINT_ACTUATOR_STATES["baseline"])
        ranked = self._ranked_blueprints()
        recommended = ranked[0] if ranked else None
        rag_advice = (self._latest_planning_run or {}).get("ragAdvice") if self._latest_planning_run else None
        gap_analysis = (self._latest_planning_run or {}).get("gapAnalysis") if self._latest_planning_run else None
        generation_criteria = (
            (self._latest_planning_run or {}).get("generationCriteria") if self._latest_planning_run else None
        )
        return {
            "ok": ok,
            "message": message,
            "sceneMode": self._scene_mode,
            "hasStage": stage is not None,
            "smartFarmPath": SMART_FARM_PATH,
            "appliedBlueprintId": self._applied_blueprint_id,
            "view": {
                "defaultCameraPath": SERVICE_CAMERA_PATH,
                "serviceUiVisible": SERVICE_UI_VISIBLE,
            },
            "simulation": {
                "fastPlaybackSeconds": FAST_SIMULATION_SECONDS,
                "timelineStartDay": SIMULATION_START_DAY,
                "timelineEndDay": SIMULATION_HARVEST_DAY,
            },
            "rendering": {
                "fixedExposure": self._fixed_exposure_snapshot(),
            },
            "sensorState": self._sensor_state_response(state),
            "cropState": crop,
            "growthKpi": _growth_kpi_from_state(state, crop, summary),
            "actuatorState": {
                "ledIntensityPercent": actuator["led_intensity_percent"],
                "photoperiodHours": actuator["photoperiod_hours"],
                "waterValveOpen": actuator["water_valve_open"],
                "irrigationPulsesPerDay": actuator["irrigation_pulses_per_day"],
                "fanDutyPercent": actuator["fan_duty_percent"],
                "co2Ppm": actuator["co2_ppm"],
            },
            "result": {
                "blueprintId": self._applied_blueprint_id or "baseline",
                "blueprintName": summary["name"],
                "expectedShipment": summary["expected_shipment"],
                "yieldScore": summary["yield_score"],
                "opex": summary["opex"],
            },
            "recommendation": {
                "recommendedBlueprintId": recommended["blueprintId"] if recommended else None,
                "rationale": recommended["rationale"] if recommended else "",
                "scores": ranked,
            },
            "ragAdvice": rag_advice,
            "gapAnalysis": gap_analysis,
            "generationCriteria": generation_criteria,
            "planningRun": self._latest_planning_run,
        }

    def _highlight_leds(self, stage, unit_path):
        for index in range(1, 5):
            prim = stage.GetPrimAtPath(f"{unit_path}/Actuators/LEDStrip_{index}")
            if prim:
                self._set_display_color(prim, (1.0, 0.95, 0.25))
                self._set_transform(prim, translation=(0, 4.25, LED_Z_POSITIONS[index - 1]), scale=(BED_LENGTH, 0.14, 0.20))

            light = stage.GetPrimAtPath(f"{unit_path}/Actuators/LEDStripLight_{index}")
            if light:
                UsdLux.RectLight(light).GetIntensityAttr().Set(0.0)
                UsdLux.RectLight(light).GetColorAttr().Set(Gf.Vec3f(1.0, 0.92, 0.34))
            strip = stage.GetPrimAtPath(f"{unit_path}/Actuators/LEDStrip_{index}")
            if strip:
                self._bind_emissive_material(stage, strip, (1.0, 0.92, 0.30), LED_STRIP_INTENSITY)

    def _activate_irrigation(self, stage, unit_path):
        self._highlight_device(stage, f"{unit_path}/Actuators/WaterValve", (0.05, 0.55, 1.00), scale=(0.72, 0.56, 0.56))
        self._highlight_device(stage, f"{unit_path}/Sensors/SoilMoistureSensor", (0.12, 0.82, 0.48), scale=(0.46, 0.46, 0.46))
        for bed_index in range(1, len(BED_Z_POSITIONS) + 1):
            flow = stage.GetPrimAtPath(f"{unit_path}/GrowingBeds/IrrigationFlow_{bed_index:02d}")
            if flow:
                self._set_translucent_visual(stage, flow, (0.08, 0.70, 1.0), 0.68, roughness=0.05)
            soil = stage.GetPrimAtPath(f"{unit_path}/GrowingBeds/SoilTop_{bed_index:02d}")
            if soil:
                self._set_display_color(soil, (0.09, 0.055, 0.035))

    def _activate_fans(self, stage, unit_path):
        self._highlight_device(stage, f"{unit_path}/Sensors/HumiditySensor", (0.12, 0.78, 0.92), scale=(0.52, 0.38, 0.10))
        self._highlight_device(stage, f"{unit_path}/Sensors/TemperatureSensor", (0.95, 0.48, 0.18), scale=(0.52, 0.38, 0.10))
        self._highlight_device(stage, f"{unit_path}/Sensors/CO2Sensor", (0.45, 0.82, 0.45), scale=(0.52, 0.38, 0.10))
        for fan_index in range(1, 4):
            fan = stage.GetPrimAtPath(f"{unit_path}/Actuators/CeilingFan_{fan_index}")
            hub = stage.GetPrimAtPath(f"{unit_path}/Actuators/CeilingFanHub_{fan_index}")
            glow = stage.GetPrimAtPath(f"{unit_path}/Actuators/CeilingFanStatusGlow_{fan_index}")
            if fan:
                self._set_display_color(fan, (0.12, 0.70, 0.92))
            if hub:
                self._set_display_color(hub, (0.72, 0.95, 1.00))
            if glow:
                self._set_translucent_visual(stage, glow, (0.55, 0.95, 1.0), 0.36, roughness=0.04)
            for blade_index in range(1, 4):
                blade = stage.GetPrimAtPath(f"{unit_path}/Actuators/CeilingFanBlade_{fan_index}_{blade_index}")
                if blade:
                    self._set_display_color(blade, (0.62, 0.88, 0.95))
            for flow_index in range(1, 4):
                airflow = stage.GetPrimAtPath(f"{unit_path}/Actuators/CeilingFanAirflow_{fan_index}_{flow_index}")
                if airflow:
                    self._set_translucent_visual(stage, airflow, (0.55, 0.95, 1.0), 0.62, roughness=0.04)

    def _apply_virtual_sensor_state_to_scene(self, stage, state):
        for unit_path in self._unit_paths():
            self._update_sensor_prim(
                stage,
                f"{unit_path}/Sensors/LightSensor",
                f'{state["dli_mol_m2_day"]:.1f} mol/m2/day',
                (0.52, 0.90, 0.30) if state["dli_mol_m2_day"] >= 15.0 else (1.0, 0.66, 0.10),
            )
            moisture_color = (
                (0.12, 0.82, 0.48) if state["substrate_moisture_percent"] >= 42 else (0.06, 0.28, 0.85)
            )
            self._update_sensor_prim(
                stage,
                f"{unit_path}/Sensors/SoilMoistureSensor",
                f'{state["substrate_moisture_percent"]}% substrate',
                moisture_color,
            )
            for z in BED_Z_POSITIONS:
                safe_z = self._safe_name(z)
                for suffix in ("A", "B"):
                    probe = stage.GetPrimAtPath(f"{unit_path}/Sensors/SoilMoistureProbe_{safe_z}_{suffix}")
                    if probe:
                        self._set_display_color(probe, moisture_color)
            self._update_sensor_prim(
                stage,
                f"{unit_path}/Sensors/HumiditySensor",
                f'{state["humidity_percent"]}% RH',
                (0.12, 0.78, 0.92) if state["humidity_percent"] <= 72 else (0.95, 0.32, 0.12),
            )
            self._update_sensor_prim(
                stage,
                f"{unit_path}/Sensors/TemperatureSensor",
                f'{state["temperature_c"]:.1f} C',
                (0.52, 0.90, 0.30) if 18.0 <= state["temperature_c"] <= 25.0 else (0.95, 0.32, 0.12),
            )
            self._update_sensor_prim(
                stage,
                f"{unit_path}/Sensors/CO2Sensor",
                f'{state["co2_ppm"]} ppm',
                (0.52, 0.90, 0.30) if state["co2_ppm"] >= 600 else (0.15, 0.15, 0.15),
            )

    def _update_sensor_prim(self, stage, path, reading, color):
        prim = stage.GetPrimAtPath(path)
        if not prim:
            return
        self._set_display_color(prim, color)
        prim.CreateAttribute("smartfarm:reading", Sdf.ValueTypeNames.String).Set(reading)
        status = stage.GetPrimAtPath(f"{path}Status")
        if status:
            self._set_display_color(status, color)

    def _highlight_device(self, stage, path, color, scale):
        prim = stage.GetPrimAtPath(path)
        if not prim:
            return
        self._set_display_color(prim, color)
        translate_op = self._get_translate_value(prim)
        self._set_transform(prim, translation=translate_op, scale=scale)

    def _update_plants_for_harvest(self, stage, unit_path):
        for bed_index in range(1, len(BED_Z_POSITIONS) + 1):
            for plant_index in range(1, len(PLANT_X_POSITIONS) + 1):
                base = f"{unit_path}/Plants/Bed_{bed_index:02d}_Plant_{plant_index:02d}"
                leaf = stage.GetPrimAtPath(f"{base}/LeafCluster")
                fruit = stage.GetPrimAtPath(f"{base}/Fruit")
                if leaf:
                    self._set_display_color(leaf, (0.02, 0.40, 0.12))
                    self._set_transform(
                        leaf,
                        translation=self._get_translate_value(leaf),
                        scale=(0.50, 0.24, 0.42),
                    )
                if fruit:
                    if fruit.IsA(UsdGeom.Gprim):
                        self._set_display_color(fruit, (1.0, 0.03, 0.04))
                        self._set_transform(
                            fruit,
                            translation=self._get_translate_value(fruit),
                            scale=(0.12, 0.16, 0.12),
                        )
                    else:
                        scale = STRAWBERRY_FRUIT_ASSET_SCALE * 1.15
                        self._set_transform(
                            fruit,
                            translation=self._get_translate_value(fruit),
                            rotation=STRAWBERRY_FRUIT_ASSET_ROTATION,
                            scale=(scale, scale, scale),
                        )
                elif plant_index in (1, 3, 6, 9, 12):
                    self._create_strawberry_fruit(
                        stage,
                        f"{base}/Fruit",
                        self._fruit_position_for(bed_index, plant_index),
                        ripe=True,
                    )

    def _fruit_position_for(self, bed_index, plant_index):
        x = PLANT_X_POSITIONS[plant_index - 1]
        z = BED_Z_POSITIONS[bed_index - 1]
        side_offset = -0.42 if z > 0 else 0.42
        return self._runner_fruit_position(x, z, side_offset)

    def _unit_paths(self):
        return [f"{SMART_FARM_PATH}/{unit_name}" for unit_name, _x, _z in GREENHOUSE_UNITS]

    def _create_cube(self, stage, path, translation, scale, color, opacity=1.0, rotation=None, roughness=0.22):
        cube = UsdGeom.Cube.Define(stage, path)
        cube.CreateSizeAttr(1.0)
        cube.CreateDisplayColorAttr([Gf.Vec3f(*color)])
        cube.CreateDisplayOpacityAttr([opacity])
        if opacity < 1.0:
            self._bind_preview_material(stage, cube.GetPrim(), color, opacity, roughness)
        self._set_transform(cube.GetPrim(), translation=translation, rotation=rotation, scale=scale)
        return cube

    def _create_sphere(self, stage, path, translation, scale, color, opacity=1.0, rotation=None):
        sphere = UsdGeom.Sphere.Define(stage, path)
        sphere.CreateRadiusAttr(1.0)
        sphere.CreateDisplayColorAttr([Gf.Vec3f(*color)])
        sphere.CreateDisplayOpacityAttr([opacity])
        if opacity < 1.0:
            self._bind_preview_material(stage, sphere.GetPrim(), color, opacity)
        self._set_transform(sphere.GetPrim(), translation=translation, rotation=rotation, scale=scale)
        return sphere

    def _create_cylinder(self, stage, path, translation, radius, depth, color, opacity=1.0):
        cylinder = UsdGeom.Cylinder.Define(stage, path)
        cylinder.CreateRadiusAttr(radius)
        cylinder.CreateHeightAttr(depth)
        cylinder.CreateAxisAttr(UsdGeom.Tokens.y)
        cylinder.CreateDisplayColorAttr([Gf.Vec3f(*color)])
        cylinder.CreateDisplayOpacityAttr([opacity])
        self._set_transform(cylinder.GetPrim(), translation=translation)
        return cylinder

    def _create_led_rect_light(self, stage, path, translation, width, height, intensity, color):
        light = UsdLux.RectLight.Define(stage, path)
        light.CreateWidthAttr(width)
        light.CreateHeightAttr(height)
        light.CreateIntensityAttr(intensity)
        light.CreateColorAttr(Gf.Vec3f(*color))
        self._set_transform(light.GetPrim(), translation=translation, rotation=(-90, 0, 0))
        return light

    def _reference_asset(self, stage, path, asset_path, translation, scale, rotation=None, instanceable=False):
        xform = UsdGeom.Xform.Define(stage, path)
        xform.GetPrim().GetReferences().AddReference(str(asset_path))
        xform.GetPrim().SetInstanceable(instanceable)
        self._set_transform(xform.GetPrim(), translation=translation, rotation=rotation, scale=scale)
        return xform

    def _tag_sensor_prim(self, prim, sensor_name):
        prim.CreateAttribute("smartfarm:isPhysicalSensor", Sdf.ValueTypeNames.Bool).Set(True)
        prim.CreateAttribute("smartfarm:sensorName", Sdf.ValueTypeNames.String).Set(sensor_name)
        prim.CreateAttribute("smartfarm:source", Sdf.ValueTypeNames.String).Set("virtual-sensor-adapter")

    def _bind_preview_material(self, stage, prim, color, opacity, roughness=0.22):
        material = self._create_preview_material(stage, color, opacity, roughness)
        UsdShade.MaterialBindingAPI(prim).Bind(material)

    def _bind_emissive_material(self, stage, prim, color, intensity):
        material = self._create_preview_material(
            stage,
            color,
            1.0,
            roughness=0.04,
            emission=intensity / EMISSIVE_INTENSITY_DIVISOR,
        )
        UsdShade.MaterialBindingAPI(prim).Bind(material)

    def _create_preview_material(self, stage, color, opacity, roughness=0.22, emission=0.0):
        material_name = (
            f"Preview_{self._safe_name(opacity)}_{self._safe_name(roughness)}_{self._safe_name(emission)}_"
            f"{int(color[0] * 255)}_{int(color[1] * 255)}_{int(color[2] * 255)}"
        )
        material_path = f"{SMART_FARM_PATH}/Looks/{material_name}"
        UsdGeom.Scope.Define(stage, f"{SMART_FARM_PATH}/Looks")
        material = UsdShade.Material.Define(stage, material_path)
        shader = UsdShade.Shader.Define(stage, f"{material_path}/Shader")
        shader.CreateIdAttr("UsdPreviewSurface")
        shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*color))
        shader.CreateInput("opacity", Sdf.ValueTypeNames.Float).Set(opacity)
        shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(roughness)
        if emission:
            shader.CreateInput("emissiveColor", Sdf.ValueTypeNames.Color3f).Set(
                Gf.Vec3f(color[0] * emission, color[1] * emission, color[2] * emission)
            )
        material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
        return material

    def _set_transform(self, prim, translation=None, rotation=None, scale=None):
        xformable = UsdGeom.Xformable(prim)
        xformable.ClearXformOpOrder()
        if translation is not None:
            xformable.AddTranslateOp().Set(Gf.Vec3d(*translation))
        if rotation is not None:
            xformable.AddRotateXYZOp().Set(Gf.Vec3f(*rotation))
        if scale is not None:
            xformable.AddScaleOp().Set(Gf.Vec3f(*scale))

    def _set_animated_transform(self, prim, translation=None, rotation=None, scale_keys=()):
        xformable = UsdGeom.Xformable(prim)
        xformable.ClearXformOpOrder()
        if translation is not None:
            xformable.AddTranslateOp().Set(Gf.Vec3d(*translation))
        if rotation is not None:
            xformable.AddRotateXYZOp().Set(Gf.Vec3f(*rotation))
        if scale_keys:
            scale_op = xformable.AddScaleOp()
            for time_code, scale in scale_keys:
                scale_op.Set(Gf.Vec3f(*scale), time_code)

    def _set_visibility_animation(self, prim, visibility_keys):
        visibility_attr = UsdGeom.Imageable(prim).CreateVisibilityAttr()
        for time_code, value in visibility_keys:
            visibility_attr.Set(value, time_code)

    def _set_display_color(self, prim, color):
        if not prim.IsA(UsdGeom.Gprim):
            return
        imageable = UsdGeom.Gprim(prim)
        imageable.CreateDisplayColorAttr([Gf.Vec3f(*color)])

    def _set_translucent_visual(self, stage, prim, color, opacity, roughness=0.10):
        if not prim.IsA(UsdGeom.Gprim):
            return
        imageable = UsdGeom.Gprim(prim)
        imageable.CreateDisplayColorAttr([Gf.Vec3f(*color)])
        imageable.CreateDisplayOpacityAttr([opacity])
        self._bind_preview_material(stage, prim, color, opacity, roughness)

    def _get_translate_value(self, prim):
        for op in UsdGeom.Xformable(prim).GetOrderedXformOps():
            if op.GetOpType() == UsdGeom.XformOp.TypeTranslate:
                return tuple(op.Get())
        return (0, 0, 0)

    def _safe_name(self, value):
        return str(value).replace("-", "neg").replace(".", "_")

    def _find_named_asset(self, name):
        for extension in (".usd", ".usda", ".usdc"):
            candidate = ASSET_DIR / f"{name}{extension}"
            if candidate.exists():
                return candidate
        return None

    def _find_plant_asset(self):
        for relative_path in PLANT_ASSET_CANDIDATES:
            if relative_path.startswith(("http://", "https://", "omniverse://")):
                return relative_path
            for root in (OWN_TYPE_DIR, ASSET_DIR):
                candidate = root / relative_path
                if candidate.exists():
                    return candidate
        return None

    def _find_strawberry_fruit_asset(self):
        for relative_path in STRAWBERRY_FRUIT_ASSET_CANDIDATES:
            for root in (OWN_TYPE_DIR, ASSET_DIR):
                candidate = root / relative_path
                if candidate.exists():
                    return candidate
        return None

    def _find_fan_asset(self):
        for relative_path in FAN_ASSET_CANDIDATES:
            if relative_path.startswith(("http://", "https://", "omniverse://")):
                return relative_path
            for root in (OWN_TYPE_DIR, ASSET_DIR):
                candidate = root / relative_path
                if candidate.exists():
                    return candidate
        return None

    def _asset_label(self, asset_path):
        if asset_path is None:
            return "Procedural fallback"
        if isinstance(asset_path, str):
            return asset_path.rsplit("/", 1)[-1]
        return f"{asset_path.parent.name}/{asset_path.name}"

    def on_shutdown(self):
        """This is called every time the extension is deactivated. It is used
        to clean up the extension state."""
        global _ACTIVE_EXTENSION
        if _ACTIVE_EXTENSION is self:
            _ACTIVE_EXTENSION = None
        self._cancel_pending_simulation()
        for verb, url in getattr(self, "_service_endpoints", []):
            try:
                services_main.deregister_endpoint(verb, url)
            except Exception:
                pass
        print("[joon.smartfarm.twin] Extension shutdown")
