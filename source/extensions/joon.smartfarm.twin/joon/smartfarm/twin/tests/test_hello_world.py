# SPDX-FileCopyrightText: Copyright (c) 2024 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

# NOTE:
#   omni.kit.test - std python's unittest module with additional wrapping to add
#   suport for async/await tests
#   For most things refer to unittest docs:
#   https://docs.python.org/3/library/unittest.html
import omni.kit.test

# Extension for writing UI tests (to simulate UI interaction)
import omni.kit.ui_test as ui_test
import omni.usd
from pxr import UsdGeom

# Having a test class dervived from omni.kit.test.AsyncTestCase declared on the
# root of module will make it auto-discoverable by omni.kit.test
class Test(omni.kit.test.AsyncTestCase):
    # Before running each test
    async def setUp(self):
        pass

    # After running each test
    async def tearDown(self):
        pass

    def _translation_of(self, prim):
        for op in UsdGeom.Xformable(prim).GetOrderedXformOps():
            if op.GetOpType() == UsdGeom.XformOp.TypeTranslate:
                return tuple(round(float(value), 2) for value in op.Get())
        return None

    async def test_smart_farm_panel_buttons(self):
        # Find a label in our window
        status_label = ui_test.find(
            "Smart Farm Twin//Frame/**/Label[*].text=='Ready to create the first smart farm twin scene.'"
        )

        # Find buttons in our window
        mature_button = ui_test.find(
            "Smart Farm Twin//Frame/**/Button[*].text=='Create Mature Scene'"
        )
        growth_button = ui_test.find(
            "Smart Farm Twin//Frame/**/Button[*].text=='Create Growth Simulation'"
        )
        scenario_button = ui_test.find(
            "Smart Farm Twin//Frame/**/Button[*].text=='Run Demo Scenario'"
        )

        self.assertEqual(
            status_label.widget.text,
            "Ready to create the first smart farm twin scene.",
        )

        await mature_button.click()
        self.assertEqual(
            status_label.widget.text,
            "Mature V1 scene created: runners and strawberries are fully visible.",
        )

        stage = omni.usd.get_context().get_stage()
        self.assertEqual(stage.GetEndTimeCode(), 0.0)
        self.assertTrue(stage.GetPrimAtPath("/World/SmartFarm/House_01_01/Plants/Bed_01_Plant_01/HangingRunner_Left"))
        self.assertTrue(stage.GetPrimAtPath("/World/SmartFarm/House_01_01/Plants/Bed_01_Plant_01/Fruit_Unripe_Left"))

        await growth_button.click()
        self.assertEqual(
            status_label.widget.text,
            "Growth simulation created: press Play on the Timeline to watch 0-60 days.",
        )

        stage = omni.usd.get_context().get_stage()
        self.assertEqual(stage.GetStartTimeCode(), 0.0)
        self.assertEqual(stage.GetEndTimeCode(), 60.0)
        self.assertTrue(stage.GetPrimAtPath("/World/SmartFarm"))
        self.assertTrue(stage.GetPrimAtPath("/World/SmartFarm/House_01_01"))
        self.assertTrue(stage.GetPrimAtPath("/World/SmartFarm/House_01_02"))
        self.assertTrue(stage.GetPrimAtPath("/World/SmartFarm/House_02_01"))
        self.assertTrue(stage.GetPrimAtPath("/World/SmartFarm/House_02_02"))
        self.assertTrue(stage.GetPrimAtPath("/World/SmartFarm/House_01_01/Greenhouse"))
        self.assertTrue(stage.GetPrimAtPath("/World/SmartFarm/House_01_01/Greenhouse/GlassRoofPanel_LeftMid"))
        self.assertTrue(stage.GetPrimAtPath("/World/SmartFarm/House_01_01/Greenhouse/GlassRidgeCap"))
        self.assertTrue(stage.GetPrimAtPath("/World/SmartFarm/House_01_01/Greenhouse/LeftEaveArchGlass_Middle"))
        self.assertTrue(stage.GetPrimAtPath("/World/SmartFarm/House_01_01/GrowingBeds/WhiteRaisedGutter_01"))
        self.assertTrue(stage.GetPrimAtPath("/World/SmartFarm/House_01_01/GrowingBeds/SoilTop_01"))
        self.assertTrue(stage.GetPrimAtPath("/World/SmartFarm/House_01_01/GrowingBeds/IrrigationFlow_01"))
        self.assertTrue(stage.GetPrimAtPath("/World/SmartFarm/House_01_01/Plants/Bed_01_Plant_01/ExternalModel"))
        self.assertTrue(stage.GetPrimAtPath("/World/SmartFarm/House_01_01/Plants/Bed_01_Plant_01/HangingRunner_Left"))
        self.assertTrue(stage.GetPrimAtPath("/World/SmartFarm/House_01_01/Plants/Bed_01_Plant_01/HangingRunner_Right"))
        self.assertTrue(stage.GetPrimAtPath("/World/SmartFarm/House_01_01/Plants/Bed_01_Plant_01/Fruit_Unripe_Left"))
        self.assertTrue(stage.GetPrimAtPath("/World/SmartFarm/House_01_01/Plants/Bed_01_Plant_01/Fruit_Unripe_Right"))
        runner = UsdGeom.Imageable(
            stage.GetPrimAtPath("/World/SmartFarm/House_01_01/Plants/Bed_01_Plant_01/HangingRunner_Left")
        )
        fruit = UsdGeom.Imageable(
            stage.GetPrimAtPath("/World/SmartFarm/House_01_01/Plants/Bed_01_Plant_01/Fruit_Unripe_Left")
        )
        self.assertEqual(runner.GetVisibilityAttr().Get(0.0), UsdGeom.Tokens.invisible)
        self.assertEqual(runner.GetVisibilityAttr().Get(20.0), UsdGeom.Tokens.inherited)
        self.assertEqual(fruit.GetVisibilityAttr().Get(0.0), UsdGeom.Tokens.invisible)
        self.assertEqual(fruit.GetVisibilityAttr().Get(38.0), UsdGeom.Tokens.inherited)
        self.assertFalse(stage.GetPrimAtPath("/World/SmartFarm/House_01_01/Plants/Bed_01_Plant_01/Flower"))
        self.assertTrue(stage.GetPrimAtPath("/World/SmartFarm/House_01_01/Actuators/LEDStripLight_1"))
        self.assertTrue(stage.GetPrimAtPath("/World/SmartFarm/House_01_01/Actuators/CeilingFan_1"))
        self.assertTrue(stage.GetPrimAtPath("/World/SmartFarm/House_01_01/Actuators/CeilingFan_3"))
        self.assertTrue(stage.GetPrimAtPath("/World/SmartFarm/House_01_01/Actuators/CeilingFanAirflow_1_1"))
        self.assertFalse(stage.GetPrimAtPath("/World/SmartFarm/House_01_01/AisleSoilPatch_neg24"))
        self.assertFalse(stage.GetPrimAtPath("/World/SmartFarm/House_01_01/FallenStrawberries_neg24"))
        self.assertTrue(stage.GetPrimAtPath("/World/SmartFarm/House_01_01/Sensors/CO2Sensor"))
        self.assertTrue(stage.GetPrimAtPath("/World/SmartFarm/House_01_01/Sensors/LightSensor"))
        self.assertTrue(stage.GetPrimAtPath("/World/SmartFarm/House_01_01/Sensors/SoilMoistureSensor"))
        self.assertTrue(stage.GetPrimAtPath("/World/SmartFarm/House_01_01/Sensors/SoilMoistureProbe_neg6_2_A"))
        self.assertTrue(stage.GetPrimAtPath("/World/SmartFarm/House_01_01/Sensors/HumiditySensor"))
        self.assertTrue(stage.GetPrimAtPath("/World/SmartFarm/House_01_01/Sensors/TemperatureSensor"))
        self.assertTrue(stage.GetPrimAtPath("/World/SmartFarm/House_01_01/Sensors/LightSensorStatus"))
        self.assertFalse(stage.GetPrimAtPath("/World/SmartFarm/House_01_01/Sensors/AirflowSensor"))
        self.assertFalse(stage.GetPrimAtPath("/World/SmartFarm/House_01_01/Sensors/SensorHubSensor"))
        light_sensor = stage.GetPrimAtPath("/World/SmartFarm/House_01_01/Sensors/LightSensor")
        soil_sensor = stage.GetPrimAtPath("/World/SmartFarm/House_01_01/Sensors/SoilMoistureSensor")
        humidity_sensor = stage.GetPrimAtPath("/World/SmartFarm/House_01_01/Sensors/HumiditySensor")
        temperature_sensor = stage.GetPrimAtPath("/World/SmartFarm/House_01_01/Sensors/TemperatureSensor")
        co2_sensor = stage.GetPrimAtPath("/World/SmartFarm/House_01_01/Sensors/CO2Sensor")
        self.assertEqual(self._translation_of(light_sensor), (6.0, 2.18, -5.0))
        self.assertEqual(self._translation_of(soil_sensor), (18.0, 1.77, 7.2))
        self.assertEqual(self._translation_of(humidity_sensor), (-18.0, 2.35, -8.92))
        self.assertEqual(self._translation_of(temperature_sensor), (-14.0, 2.35, -8.92))
        self.assertEqual(self._translation_of(co2_sensor), (-6.0, 2.35, 8.92))
        self.assertEqual(light_sensor.GetAttribute("smartfarm:isPhysicalSensor").Get(), True)
        self.assertEqual(light_sensor.GetAttribute("smartfarm:source").Get(), "virtual-sensor-adapter")
        self.assertEqual(light_sensor.GetAttribute("smartfarm:reading").Get(), "11.2 mol/m2/day")
        self.assertEqual(soil_sensor.GetAttribute("smartfarm:reading").Get(), "31% substrate")
        self.assertEqual(humidity_sensor.GetAttribute("smartfarm:reading").Get(), "82% RH")
        self.assertEqual(temperature_sensor.GetAttribute("smartfarm:reading").Get(), "24.8 C")
        self.assertEqual(co2_sensor.GetAttribute("smartfarm:reading").Get(), "420 ppm")
        self.assertTrue(stage.GetPrimAtPath("/World/SmartFarm/Lighting/InteriorFill/House_01_01_01"))
        self.assertFalse(stage.GetPrimAtPath("/World/SmartFarm/House_01_01/Plants/Bed_01_Plant_01/Fruit"))

        await scenario_button.click()
        self.assertEqual(
            status_label.widget.text,
            "Gemma 4.0 blueprint applied: LED, irrigation, and fan controls recover the shipment target.",
        )
        self.assertEqual(light_sensor.GetAttribute("smartfarm:reading").Get(), "17.8 mol/m2/day")
        self.assertEqual(soil_sensor.GetAttribute("smartfarm:reading").Get(), "48% substrate")
        self.assertEqual(humidity_sensor.GetAttribute("smartfarm:reading").Get(), "68% RH")
        self.assertEqual(temperature_sensor.GetAttribute("smartfarm:reading").Get(), "23.6 C")
        self.assertEqual(co2_sensor.GetAttribute("smartfarm:reading").Get(), "650 ppm")
        self.assertTrue(stage.GetPrimAtPath("/World/SmartFarm/House_01_01/Plants/Bed_01_Plant_01/Fruit"))
        self.assertTrue(stage.GetPrimAtPath("/World/SmartFarm/House_02_02/Plants/Bed_01_Plant_01/Fruit"))
