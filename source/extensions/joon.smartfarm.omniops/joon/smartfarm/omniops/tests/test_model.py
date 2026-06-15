import unittest

from joon.smartfarm.omniops.model import (
    BLUEPRINTS,
    ranked_blueprints,
    state_for_blueprint,
    state_for_manual_actuator,
    vision_assessment_from_state,
)


class OmniOpsModelTest(unittest.TestCase):
    def test_all_blueprints_have_kpi(self):
        for blueprint_id in BLUEPRINTS:
            state = state_for_blueprint(blueprint_id)
            self.assertIn("kpi", state)
            self.assertGreaterEqual(state["kpi"]["healthScore"], 0)
            self.assertLessEqual(state["kpi"]["healthScore"], 100)
            self.assertIn("timeline", state)
            self.assertGreater(len(state["timeline"]), 0)

    def test_ranked_blueprints_recommend_early_or_safe_plan(self):
        ranked = ranked_blueprints()
        self.assertEqual(len(ranked), 3)
        self.assertIn(ranked[0]["blueprintId"], {"plan-b-early-shipment", "plan-c-disease-safe"})
        self.assertGreaterEqual(ranked[0]["score"], ranked[-1]["score"])
        for row in ranked:
            self.assertIn("operatorIntent", row)
            self.assertIn("controlFocus", row)
            self.assertIn("tradeoff", row)
            self.assertGreater(len(row["operatorIntent"]), 10)

    def test_plan_improves_baseline_health(self):
        baseline = state_for_blueprint("baseline")
        plan_b = state_for_blueprint("plan-b-early-shipment")
        self.assertGreater(plan_b["kpi"]["healthScore"], baseline["kpi"]["healthScore"])
        self.assertGreater(plan_b["kpi"]["harvestReadinessPercent"], baseline["kpi"]["harvestReadinessPercent"])

    def test_manual_actuator_projection_changes_sensors_plausibly(self):
        baseline = state_for_blueprint("baseline")
        manual = state_for_manual_actuator(
            {
                "led_intensity_percent": 80,
                "photoperiod_hours": 16,
                "water_valve_open": True,
                "irrigation_pulses_per_day": 3,
                "fan_duty_percent": 70,
                "co2_ppm": 650,
            }
        )
        self.assertGreater(manual["sensor"]["dli_mol_m2_day"], baseline["sensor"]["dli_mol_m2_day"])
        self.assertGreater(manual["sensor"]["substrate_moisture_percent"], baseline["sensor"]["substrate_moisture_percent"])
        self.assertLess(manual["sensor"]["humidity_percent"], baseline["sensor"]["humidity_percent"])
        self.assertGreater(manual["sensor"]["co2_ppm"], baseline["sensor"]["co2_ppm"])
        self.assertLessEqual(manual["crop"]["diseasePressure"], baseline["crop"]["diseasePressure"])
        self.assertGreater(manual["kpi"]["healthScore"], baseline["kpi"]["healthScore"])

    def test_virtual_camera_vision_assessment_is_provider_ready(self):
        state = state_for_blueprint("plan-b-early-shipment")
        assessment = vision_assessment_from_state(
            state["sensor"],
            state["crop"],
            camera_path="/World/SmartFarm/Cameras/GrowthPhenotypeCamera",
            capture_path="/tmp/growth-camera.png",
            observed_at="2026-06-14T12:00:00Z",
        )
        self.assertEqual(assessment["source"], "virtual-camera-observed")
        self.assertEqual(assessment["provider"], "foundation-model-adapter/mock")
        self.assertGreaterEqual(assessment["healthScore"], 0)
        self.assertLessEqual(assessment["healthScore"], 100)
        self.assertGreaterEqual(assessment["growthProgressPercent"], 0)
        self.assertLessEqual(assessment["growthProgressPercent"], 100)
        self.assertGreater(len(assessment["traits"]), 0)


if __name__ == "__main__":
    unittest.main()
