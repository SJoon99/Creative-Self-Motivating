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
            "Create Twin Scene requested. The next step will generate the greenhouse USD prims.",
        )

        await scenario_button.click()
        self.assertEqual(
            status_label.widget.text,
            "Demo scenario selected: 16h photoperiod + CO2, expected shipment 2026-12-22, yield score 87.",
        )
