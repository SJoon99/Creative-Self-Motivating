# SPDX-FileCopyrightText: Copyright (c) 2024 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

import omni.ext
import omni.ui as ui


DEFAULT_STATUS = "Ready to create the first smart farm twin scene."


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

        self._window = ui.Window("Smart Farm Twin", width=420, height=360)
        with self._window.frame:
            with ui.VStack(spacing=8, height=0):
                ui.Label("Strawberry Early-Shipment Twin", height=24)
                ui.Separator(height=4)

                self._add_info_row("Project", "Strawberry Early-Shipment Twin")
                self._add_info_row("Facility", "Single-span greenhouse")
                self._add_info_row("Crop", "Seolhyang strawberry")
                self._add_info_row("Stage", "Vegetative growth")
                self._add_info_row("Target Shipment", "2026-12-22")
                self._add_info_row("Scenario", "16h photoperiod + CO2")

                ui.Spacer(height=8)
                self._status_label = ui.Label(DEFAULT_STATUS, word_wrap=True)
                ui.Spacer(height=8)

                with ui.HStack(spacing=8, height=32):
                    ui.Button(
                        "Create Twin Scene",
                        clicked_fn=self._on_create_twin_scene,
                    )
                    ui.Button(
                        "Run Demo Scenario",
                        clicked_fn=self._on_run_demo_scenario,
                    )

    def _add_info_row(self, label: str, value: str):
        with ui.HStack(height=24):
            ui.Label(label, width=130)
            ui.Label(value)

    def _set_status(self, text: str):
        self._status_label.text = text

    def _on_create_twin_scene(self):
        self._set_status(
            "Create Twin Scene requested. The next step will generate the greenhouse USD prims."
        )

    def _on_run_demo_scenario(self):
        self._set_status(
            "Demo scenario selected: 16h photoperiod + CO2, expected shipment 2026-12-22, yield score 87."
        )

    def on_shutdown(self):
        """This is called every time the extension is deactivated. It is used
        to clean up the extension state."""
        print("[joon.smartfarm.twin] Extension shutdown")
