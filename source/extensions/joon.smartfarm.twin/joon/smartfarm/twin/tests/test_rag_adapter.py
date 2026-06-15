import json
import unittest
import urllib.error

from joon.smartfarm.twin.rag_adapter import (
    RagAdapterError,
    SmartFarmRagClient,
    analyze_gap,
    assign_rotating_plan_slots,
    build_state_snapshot,
    candidate_needs_quality_repair,
    generate_blueprint_candidates,
    is_blueprint_generation_unsupported,
    normalize_blueprint_generation,
    normalize_rag_recommendation,
)


SENSOR = {
    "scenario_seed": "test",
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
CROP = {
    "day": 34,
    "vegetativeGrowth": 0.68,
    "flowering": 0.64,
    "fruitSet": 0.49,
    "fruitMaturity": 0.44,
    "diseasePressure": 0.70,
    "estimatedYield": 67,
}
ACTUATOR = {
    "led_intensity_percent": 40,
    "photoperiod_hours": 12,
    "water_valve_open": False,
    "irrigation_pulses_per_day": 1,
    "fan_duty_percent": 20,
    "co2_ppm": 420,
}
RAG_PAYLOAD = {
    "date": "2026-10-23",
    "planting_date": "2026-09-19",
    "days_after_planting": 34,
    "growth_stage": "개화기",
    "setpoints": {
        "temp_day_c": {"min": 18, "max": 23, "target": 20},
        "temp_night_c": {"min": 7, "max": 10, "target": 8},
        "humidity_pct": {"min": 60, "max": 70, "target": 65},
        "co2_ppm": {"min": 1000, "max": 1500, "target": 1200},
        "supplemental_light": {"on": True, "hours_per_day": 4, "note": "전조"},
        "nutrient": {"ec_ds_m": 1.0, "ph": 6.2},
    },
    "sources": ["농업기술길잡이40_딸기 p.59", "농업기술길잡이40_딸기 p.115"],
    "explanation": "문헌 기반 설명",
}
BLUEPRINT_PAYLOAD = {
    "provider": "twinx-gemma-rag",
    "model": "gemma4",
    "objective": "earliest_viable_shipment",
    "baselineSummary": "DLI and moisture are below the target range while humidity is high.",
    "evidence": [{"source": "manual.pdf", "page": 12, "summary": "DLI and humidity guidance"}],
    "candidates": [
        {
            "id": "blueprint-a",
            "label": "Blueprint A",
            "intent": "Earliest feasible shipment",
            "actuatorTargets": {
                "ledIntensityPercent": 78,
                "photoperiodHours": 16,
                "irrigationPulsesPerDay": 3,
                "fanDutyPercent": 58,
                "co2Ppm": 720,
            },
            "rationale": "Correct the dominant DLI and CO₂ gaps while controlling humidity.",
        }
    ],
}


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload
        self.status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class RagAdapterTest(unittest.TestCase):
    def test_normalizes_rag_recommendation(self):
        advice = normalize_rag_recommendation(RAG_PAYLOAD)
        self.assertEqual(advice["provider"], "twinx-gemma-rag")
        self.assertEqual(advice["growthStage"], "개화기")
        self.assertEqual(advice["recommendedSetpoints"]["humidityPct"]["target"], 65)
        self.assertEqual(len(advice["evidence"]), 2)

    def test_gap_analysis_uses_current_sensor_and_crop_state(self):
        snapshot = build_state_snapshot(SENSOR, CROP, ACTUATOR)
        advice = normalize_rag_recommendation(RAG_PAYLOAD)
        gap = analyze_gap(snapshot, advice)
        self.assertGreater(gap["deviationScore"], 30)
        keys = {row["key"] for row in gap["deviations"][:4]}
        self.assertIn("humidityPct", keys)
        self.assertIn("co2Ppm", keys)
        self.assertIn("diseasePressure", keys)

    def test_generates_distinct_applicable_candidate_actuators(self):
        snapshot = build_state_snapshot(SENSOR, CROP, ACTUATOR)
        advice = normalize_rag_recommendation(RAG_PAYLOAD)
        gap = analyze_gap(snapshot, advice)
        candidates = generate_blueprint_candidates(snapshot, advice, gap)
        self.assertEqual(len(candidates), 3)
        by_id = {item["id"]: item for item in candidates}
        self.assertEqual([item["name"] for item in candidates], ["Plan A", "Plan B", "Plan C"])
        self.assertGreater(by_id["blueprint-a"]["actuatorState"]["led_intensity_percent"], ACTUATOR["led_intensity_percent"])
        self.assertGreater(by_id["blueprint-c"]["actuatorState"]["fan_duty_percent"], by_id["blueprint-b"]["actuatorState"]["fan_duty_percent"])
        for item in candidates:
            self.assertIn("ragEvidence", item)
            self.assertIn("controlFocus", item)
            for key in ("operatorIntent", "tradeoff", "rationale", "controlFocus"):
                item[key].encode("ascii")
                self.assertNotIn("?", item[key])

    def test_rotating_plan_slots_decouple_letters_from_fixed_candidate_order(self):
        candidates = [
            {"id": "gemma-first", "name": "Gemma first", "score": 0.0},
            {"id": "gemma-best", "name": "Gemma best", "score": 58.0},
            {"id": "gemma-middle", "name": "Gemma middle", "score": 20.0},
        ]

        first_run = assign_rotating_plan_slots(candidates, rotation=0)
        second_run = assign_rotating_plan_slots(candidates, rotation=1)
        third_run = assign_rotating_plan_slots(candidates, rotation=2)

        self.assertEqual([item["name"] for item in first_run], ["Plan A", "Plan B", "Plan C"])
        self.assertEqual({item["sourceCandidateId"]: item["id"] for item in first_run}["gemma-best"], "blueprint-a")
        self.assertEqual({item["sourceCandidateId"]: item["id"] for item in second_run}["gemma-best"], "blueprint-b")
        self.assertEqual({item["sourceCandidateId"]: item["id"] for item in third_run}["gemma-best"], "blueprint-c")
        self.assertEqual({item["sourceCandidateId"]: item["score"] for item in second_run}["gemma-first"], 0.0)
        self.assertEqual({item["sourceCandidateId"]: item["sourceScoreRank"] for item in second_run}["gemma-best"], 1)
        self.assertEqual({item["sourceCandidateId"]: item["sourceCandidateName"] for item in second_run}["gemma-best"], "Gemma best")

    def test_quality_gate_flags_only_infeasible_generated_candidates(self):
        bad = {
            "score": 0.0,
            "predicted": {"diseaseRisk": "high"},
            "simulation": {
                "harvestDay": 90,
                "maxHorizonDays": 90,
                "finalCropState": {"diseasePressure": 0.76},
            },
        }
        repaired_viable = {
            "score": 58.0,
            "predicted": {"diseaseRisk": "controlled"},
            "simulation": {
                "harvestDay": 58,
                "maxHorizonDays": 90,
                "finalCropState": {"diseasePressure": 0.42},
            },
        }

        self.assertTrue(
            candidate_needs_quality_repair(
                bad,
                min_score=20.0,
                max_horizon_days=90,
                disease_pressure_limit=0.62,
            )
        )
        self.assertFalse(
            candidate_needs_quality_repair(
                repaired_viable,
                min_score=20.0,
                max_horizon_days=90,
                disease_pressure_limit=0.62,
            )
        )

    def test_client_calls_current_rag_contract(self):
        seen = {}

        def opener(request, timeout):
            seen["url"] = request.full_url
            seen["timeout"] = timeout
            seen["body"] = json.loads(request.data.decode("utf-8"))
            seen["auth"] = request.headers.get("Authorization")
            return _FakeResponse(RAG_PAYLOAD)

        snapshot = build_state_snapshot(SENSOR, CROP, ACTUATOR)
        client = SmartFarmRagClient("http://rag.example", "secret", timeout=7, opener=opener)
        advice = client.recommend(snapshot, no_llm=True)
        self.assertEqual(seen["url"], "http://rag.example/recommend")
        self.assertTrue(seen["body"]["no_llm"])
        self.assertEqual(seen["body"]["responseLanguage"], "en-US")
        self.assertIn("English ASCII", seen["body"]["uiTextContract"])
        self.assertEqual(seen["auth"], "Bearer secret")
        self.assertEqual(advice["growthStage"], "개화기")
        self.assertEqual(client.last_request_trace["path"], "/recommend")
        self.assertEqual(client.last_request_trace["statusCode"], 200)
        self.assertTrue(client.last_request_trace["ok"])
        self.assertEqual(client.last_request_trace["bodySummary"]["date"], "2026-10-23")

    def test_normalizes_state_aware_blueprint_generation(self):
        snapshot = build_state_snapshot(SENSOR, CROP, ACTUATOR, vision_assessment={"diseaseRisk": "high"})
        generated = normalize_blueprint_generation(BLUEPRINT_PAYLOAD, snapshot)
        self.assertEqual(generated["ragAdvice"]["provider"], "twinx-gemma-rag")
        self.assertEqual(generated["candidates"][0]["id"], "blueprint-a")
        self.assertEqual(generated["candidates"][0]["name"], "Plan A")
        self.assertEqual(generated["candidates"][0]["label"], "Plan A")
        self.assertEqual(generated["candidates"][0]["actuatorState"]["led_intensity_percent"], 78)
        self.assertEqual(generated["candidates"][0]["ragEvidence"][0]["source"], "manual.pdf")

    def test_non_ascii_generated_plan_text_falls_back_to_ui_safe_english(self):
        payload = {
            **BLUEPRINT_PAYLOAD,
            "candidates": [
                {
                    "id": "blueprint-a",
                    "label": "Blueprint A",
                    "intent": "CO2 보강으로 조기 출하를 유도",
                    "tradeoff": "전력비 상승",
                    "rationale": "습도가 높고 광량이 부족합니다",
                    "actuatorTargets": {
                        "ledIntensityPercent": 78,
                        "photoperiodHours": 16,
                        "irrigationPulsesPerDay": 3,
                        "fanDutyPercent": 58,
                        "co2Ppm": 720,
                    },
                }
            ],
        }
        generated = normalize_blueprint_generation(payload, build_state_snapshot(SENSOR, CROP, ACTUATOR))
        candidate = generated["candidates"][0]
        for key in ("operatorIntent", "tradeoff", "rationale", "controlFocus"):
            candidate[key].encode("ascii")
            self.assertNotIn("?", candidate[key])
        self.assertIn("Gemma/RAG candidate", candidate["rationale"])

    def test_state_aware_blueprint_generation_clamps_actuators_and_preserves_warnings(self):
        payload = {
            **BLUEPRINT_PAYLOAD,
            "generationMode": "deterministic_fallback",
            "warnings": ["Gemma JSON generation fallback"],
            "candidates": [
                {
                    "id": "blueprint-a",
                    "label": "Blueprint A",
                    "generationWarning": "Gemma JSON generation fallback",
                    "actuatorTargets": {
                        "ledIntensityPercent": 140,
                        "photoperiodHours": 25,
                        "irrigationPulsesPerDay": -2,
                        "fanDutyPercent": 180,
                        "co2Ppm": 1400,
                    },
                }
            ],
        }
        snapshot = build_state_snapshot(SENSOR, CROP, ACTUATOR)
        generated = normalize_blueprint_generation(payload, snapshot)
        actuator = generated["candidates"][0]["actuatorState"]
        self.assertEqual(actuator["led_intensity_percent"], 100)
        self.assertEqual(actuator["photoperiod_hours"], 18)
        self.assertEqual(actuator["irrigation_pulses_per_day"], 0)
        self.assertEqual(actuator["fan_duty_percent"], 100)
        self.assertEqual(actuator["co2_ppm"], 900)
        self.assertEqual(generated["generationMode"], "deterministic_fallback")
        self.assertEqual(generated["warnings"], ["Gemma JSON generation fallback"])
        self.assertEqual(generated["candidates"][0]["generationWarning"], "Gemma JSON generation fallback")

    def test_client_calls_state_aware_blueprint_contract(self):
        seen = {}

        def opener(request, timeout):
            seen["url"] = request.full_url
            seen["timeout"] = timeout
            seen["body"] = json.loads(request.data.decode("utf-8"))
            seen["auth"] = request.headers.get("Authorization")
            return _FakeResponse(BLUEPRINT_PAYLOAD)

        snapshot = build_state_snapshot(SENSOR, CROP, ACTUATOR, vision_assessment={"diseaseRisk": "high"})
        client = SmartFarmRagClient("http://rag.example", "secret", timeout=7, opener=opener)
        generated = client.generate_blueprints(snapshot, candidate_count=3, no_llm=True)
        self.assertEqual(seen["url"], "http://rag.example/blueprints/generate")
        self.assertEqual(seen["body"]["baseline"]["sensorState"]["humidity_percent"], 82)
        self.assertEqual(seen["body"]["baseline"]["visionAssessment"]["diseaseRisk"], "high")
        self.assertEqual(seen["body"]["candidateCount"], 3)
        self.assertTrue(seen["body"]["no_llm"])
        self.assertEqual(seen["body"]["responseLanguage"], "en-US")
        self.assertIn("English ASCII", seen["body"]["uiTextContract"])
        self.assertEqual(seen["auth"], "Bearer secret")
        self.assertEqual(generated["candidates"][0]["name"], "Plan A")
        trace = client.last_request_trace
        self.assertEqual(trace["path"], "/blueprints/generate")
        self.assertEqual(trace["statusCode"], 200)
        self.assertTrue(trace["ok"])
        self.assertEqual(trace["bodySummary"]["candidateCount"], 3)
        self.assertTrue(trace["bodySummary"]["hasVisionAssessment"])
        self.assertEqual(trace["bodySummary"]["sensor"]["humidity_percent"], 82)

    def test_http_status_controls_legacy_endpoint_fallback(self):
        def opener_404(_request, timeout):
            raise urllib.error.HTTPError("http://rag.example/blueprints/generate", 404, "Not Found", {}, None)

        def opener_500(_request, timeout):
            raise urllib.error.HTTPError("http://rag.example/blueprints/generate", 500, "Server Error", {}, None)

        snapshot = build_state_snapshot(SENSOR, CROP, ACTUATOR)
        missing_client = SmartFarmRagClient("http://rag.example", opener=opener_404)
        with self.assertRaises(RagAdapterError) as missing:
            missing_client.generate_blueprints(snapshot)
        self.assertEqual(missing.exception.status_code, 404)
        self.assertTrue(is_blueprint_generation_unsupported(missing.exception))
        self.assertFalse(missing_client.last_request_trace["ok"])
        self.assertEqual(missing_client.last_request_trace["statusCode"], 404)

        error_client = SmartFarmRagClient("http://rag.example", opener=opener_500)
        with self.assertRaises(RagAdapterError) as server_error:
            error_client.generate_blueprints(snapshot)
        self.assertEqual(server_error.exception.status_code, 500)
        self.assertFalse(is_blueprint_generation_unsupported(server_error.exception))
        self.assertFalse(error_client.last_request_trace["ok"])
        self.assertEqual(error_client.last_request_trace["statusCode"], 500)

    def test_client_requires_base_url(self):
        with self.assertRaises(RagAdapterError):
            SmartFarmRagClient().recommend(build_state_snapshot(SENSOR, CROP, ACTUATOR))


if __name__ == "__main__":
    unittest.main()
