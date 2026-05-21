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

# Having a test class dervived from omni.kit.test.AsyncTestCase declared on the
# root of module will make it auto-discoverable by omni.kit.test
class Test(omni.kit.test.AsyncTestCase):
    # Before running each test
    async def setUp(self):
        pass

    # After running each test
    async def tearDown(self):
        pass

    async def test_smart_farm_panel_buttons(self):
        # Find a label in our window
        status_label = ui_test.find(
            "Smart Farm Twin//Frame/**/Label[*].text=='Ready to create the first smart farm twin scene.'"
        )

        # Find buttons in our window
        create_button = ui_test.find(
            "Smart Farm Twin//Frame/**/Button[*].text=='Create Twin Scene'"
        )
        scenario_button = ui_test.find(
            "Smart Farm Twin//Frame/**/Button[*].text=='Run Demo Scenario'"
        )

        self.assertEqual(
            status_label.widget.text,
            "Ready to create the first smart farm twin scene.",
        )

        await create_button.click()
        self.assertEqual(
            status_label.widget.text,
            "Twin scene created: arched greenhouse, soil beds, 64 strawberry plants, sensors, LEDs, and fans.",
        )

        stage = omni.usd.get_context().get_stage()
        self.assertTrue(stage.GetPrimAtPath("/World/SmartFarm"))
        self.assertTrue(stage.GetPrimAtPath("/World/SmartFarm/Greenhouse"))
        self.assertTrue(stage.GetPrimAtPath("/World/SmartFarm/Greenhouse/ArchedRoofCover_Ridge"))
        self.assertTrue(stage.GetPrimAtPath("/World/SmartFarm/GrowingBeds/Bed_01"))
        self.assertTrue(stage.GetPrimAtPath("/World/SmartFarm/GrowingBeds/SoilTop_01"))
        self.assertTrue(stage.GetPrimAtPath("/World/SmartFarm/Plants/Bed_01_Plant_01/LeafCluster"))
        self.assertTrue(stage.GetPrimAtPath("/World/SmartFarm/Plants/Bed_01_Plant_01/Leaf_01"))
        self.assertTrue(stage.GetPrimAtPath("/World/SmartFarm/Sensors/CO2Sensor"))

        await scenario_button.click()
        self.assertEqual(
            status_label.widget.text,
            "Recommended scenario applied: 16h photoperiod + CO2. Shipment target is met with yield score 87.",
        )
        self.assertTrue(stage.GetPrimAtPath("/World/SmartFarm/Plants/Bed_01_Plant_01/Fruit"))
