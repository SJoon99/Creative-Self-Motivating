# SPDX-FileCopyrightText: Copyright (c) 2024 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

from pathlib import Path

import omni.ext
import omni.ui as ui
import omni.usd
from pxr import Gf, Sdf, UsdGeom, UsdLux, UsdShade


DEFAULT_STATUS = "Ready to create the first smart farm twin scene."
SMART_FARM_PATH = "/World/SmartFarm"
EXTENSION_ROOT = Path(__file__).resolve().parents[3]
ASSET_DIR = EXTENSION_ROOT / "assets"
GREENHOUSE_LENGTH = 56.0
GREENHOUSE_WIDTH = 18.0
GREENHOUSE_WALL_HEIGHT = 4.2
GREENHOUSE_RIDGE_HEIGHT = 8.4
BED_LENGTH = 46.0
BED_Z_POSITIONS = (-6.2, -3.8, 3.8, 6.2)
PLANT_X_POSITIONS = (-21, -17, -13, -9, -5, -1, 3, 7, 11, 15, 19, 23)
GUTTER_HEIGHT = 1.55
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

        self._metric_labels = {}
        self._selected_plant_asset = None
        self._window = ui.Window("Smart Farm Twin", width=480, height=560)
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
            value_label = ui.Label(value)
        return value_label

    def _set_status(self, text: str):
        self._status_label.text = text

    def _on_create_twin_scene(self):
        stage = self._get_stage()
        if stage is None:
            self._set_status("No USD stage is available yet. Create or open a stage first.")
            return

        self._build_smart_farm_scene(stage)
        self._set_status(
            "Twin scene created: 2x2 vinyl greenhouse block, raised strawberry gutters, sensors, LEDs, and fans."
        )

    def _on_run_demo_scenario(self):
        stage = self._get_stage()
        if stage is None:
            self._set_status("No USD stage is available yet. Create or open a stage first.")
            return

        if not stage.GetPrimAtPath(SMART_FARM_PATH):
            self._build_smart_farm_scene(stage)

        self._apply_demo_scenario(stage)
        self._update_demo_metrics()
        self._set_status(
            "Recommended scenario applied: 16h photoperiod + CO2. Shipment target is met with yield score 87."
        )

    def _get_stage(self):
        usd_context = omni.usd.get_context()
        stage = usd_context.get_stage()
        if stage is None:
            usd_context.new_stage()
            stage = usd_context.get_stage()
        return stage

    def _build_smart_farm_scene(self, stage):
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
        self._selected_plant_asset = strawberry_asset
        self._metric_labels["plant_asset"].text = self._asset_label(strawberry_asset)

        self._create_site_floor(stage)
        self._create_greenhouse_units(stage, greenhouse_asset, strawberry_asset)
        self._create_lighting(stage)

    def _create_site_floor(self, stage):
        self._create_cube(
            stage,
            f"{SMART_FARM_PATH}/Ground",
            translation=(0, -0.04, 0),
            scale=(GREENHOUSE_LENGTH * 2.0 + 10.0, 0.08, GREENHOUSE_WIDTH * 2.0 + 10.0),
            color=(0.34, 0.26, 0.18),
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
            color=(0.42, 0.39, 0.33),
        )
        for z in (-8.1, 8.1):
            self._create_cube(
                stage,
                f"{unit_path}/BlueServiceMat_{self._safe_name(z)}",
                translation=(0, 0.04, z),
                scale=(52, 0.035, 1.05),
                color=(0.18, 0.43, 0.54),
            )
        for x in (-24, -16, -8, 0, 8, 16, 24):
            self._create_cube(
                stage,
                f"{unit_path}/AisleSoilPatch_{self._safe_name(x)}",
                translation=(x, 0.06, 0.0),
                scale=(1.2, 0.025, 0.8),
                color=(0.17, 0.10, 0.055),
                opacity=0.8,
            )
            self._create_sphere(
                stage,
                f"{unit_path}/FallenStrawberries_{self._safe_name(x)}",
                translation=(x + 0.38, 0.13, 0.28),
                scale=(0.10, 0.08, 0.10),
                color=(0.90, 0.04, 0.03),
            )

    def _create_greenhouse(self, stage, unit_path):
        group = f"{unit_path}/Greenhouse"
        UsdGeom.Xform.Define(stage, group)

        frame_color = (0.58, 0.64, 0.67)
        half_length = GREENHOUSE_LENGTH / 2.0
        half_width = GREENHOUSE_WIDTH / 2.0
        cover_color = (0.70, 0.91, 0.98)
        seam_color = (0.42, 0.72, 0.88)

        self._create_vinyl_cover_panels(stage, group, cover_color, half_length, half_width)
        self._create_vinyl_film_strips(stage, group, seam_color, half_width)

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
            self._create_cube(stage, f"{group}/VinylEndOutline_{safe_x}_Left", (x, 2.2, -half_width), (0.09, 4.4, 0.09), seam_color, 0.70)
            self._create_cube(stage, f"{group}/VinylEndOutline_{safe_x}_Right", (x, 2.2, half_width), (0.09, 4.4, 0.09), seam_color, 0.70)
            self._create_cube(stage, f"{group}/VinylEndOutline_{safe_x}_Base", (x, 0.16, 0), (0.09, 0.09, GREENHOUSE_WIDTH), seam_color, 0.58)
            self._create_cube(stage, f"{group}/VinylEndOutline_{safe_x}_Ridge", (x, GREENHOUSE_RIDGE_HEIGHT, 0), (0.09, 0.09, 2.4), seam_color, 0.62)

        for z in (-7.8, -5.6, -3.4, -1.2, 1.2, 3.4, 5.6, 7.8):
            self._create_cube(
                stage,
                f"{group}/VinylSeam_{self._safe_name(z)}",
                (0, 4.7, z),
                (GREENHOUSE_LENGTH, 0.12, 0.15),
                seam_color,
                0.68,
            )

    def _create_vinyl_cover_panels(self, stage, group, color, half_length, half_width):
        self._create_cube(stage, f"{group}/LeftWallVinylSheet", (0, 2.1, -half_width), (GREENHOUSE_LENGTH, 4.2, 0.045), color, 0.28)
        self._create_cube(stage, f"{group}/RightWallVinylSheet", (0, 2.1, half_width), (GREENHOUSE_LENGTH, 4.2, 0.045), color, 0.28)
        self._create_cube(stage, f"{group}/FrontVinylSheet", (-half_length, 2.2, 0), (0.045, 4.4, GREENHOUSE_WIDTH), color, 0.22)
        self._create_cube(stage, f"{group}/BackVinylSheet", (half_length, 2.2, 0), (0.045, 4.4, GREENHOUSE_WIDTH), color, 0.22)

        roof_panels = [
            ("LeftEave", -7.2, 4.7, -28, 3.2),
            ("LeftMid", -4.25, 6.15, -20, 3.1),
            ("LeftHigh", -1.65, 7.55, -10, 2.6),
            ("RightHigh", 1.65, 7.55, 10, 2.6),
            ("RightMid", 4.25, 6.15, 20, 3.1),
            ("RightEave", 7.2, 4.7, 28, 3.2),
        ]
        for name, z, y, rot_x, width in roof_panels:
            self._create_cube(
                stage,
                f"{group}/VinylRoofSheet_{name}",
                (0, y, z),
                (GREENHOUSE_LENGTH, 0.055, width),
                color,
                0.26,
                rotation=(rot_x, 0, 0),
            )

    def _create_vinyl_film_strips(self, stage, group, color, half_width):
        for side_name, z in (("Left", -half_width), ("Right", half_width)):
            for index, y in enumerate((1.0, 2.25, 3.5), start=1):
                self._create_cube(
                    stage,
                    f"{group}/VinylSideFilm_{side_name}_{index}",
                    (0, y, z),
                    (GREENHOUSE_LENGTH, 0.18, 0.075),
                    color,
                    0.66,
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
                f"{group}/VinylRoofFilm_{name}",
                (0, y, z),
                (GREENHOUSE_LENGTH, 0.13, 0.72),
                color,
                0.62,
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

        for i, z in enumerate((-5.5, -3.1, 3.1, 5.5), start=1):
            self._create_cube(stage, f"{group}/LEDStrip_{i}", (0, 4.25, z), (BED_LENGTH, 0.06, 0.10), (1.0, 0.86, 0.32))

        for i, x in enumerate((-27.6, 27.6), start=1):
            self._create_cylinder(stage, f"{group}/VentFan_{i}", (x, 3.0, 0), radius=1.0, depth=0.20, color=(0.10, 0.13, 0.16))
            self._create_cube(stage, f"{group}/VentFanHub_{i}", (x, 3.0, 0), (0.36, 0.36, 0.36), (0.35, 0.40, 0.44))

        self._create_cube(stage, f"{group}/CO2Injector", (-25.8, 1.0, -7.2), (0.55, 1.1, 0.55), (0.20, 0.20, 0.24))
        self._create_cube(stage, f"{group}/WaterValve", (25.2, 0.75, 7.2), (0.60, 0.45, 0.45), (0.05, 0.28, 0.70))

    def _create_sensors(self, stage, unit_path):
        group = f"{unit_path}/Sensors"
        UsdGeom.Xform.Define(stage, group)

        sensors = [
            ("TemperatureHumidity", (-18.0, 2.2, -7.2), (0.90, 0.28, 0.10)),
            ("CO2", (-6.0, 2.2, 7.2), (0.15, 0.15, 0.15)),
            ("Light", (6.0, 4.5, -7.2), (1.0, 0.78, 0.10)),
            ("SoilMoisture", (18.0, 1.35, 7.2), (0.06, 0.28, 0.85)),
        ]
        for name, position, color in sensors:
            self._create_cube(stage, f"{group}/{name}Sensor", position, (0.35, 0.35, 0.35), color)

    def _create_lighting(self, stage):
        group = f"{SMART_FARM_PATH}/Lighting"
        UsdGeom.Xform.Define(stage, group)

        dome = UsdLux.DomeLight.Define(stage, f"{group}/SoftSky")
        dome.CreateIntensityAttr(250.0)

        sun = UsdLux.DistantLight.Define(stage, f"{group}/Sun")
        sun.CreateIntensityAttr(1800.0)
        sun.CreateAngleAttr(0.8)
        self._set_transform(sun.GetPrim(), rotation=(-45, 35, 0))

    def _create_plant(self, stage, group, bed_index, plant_index, x, z, strawberry_asset=None):
        base = f"{group}/Bed_{bed_index:02d}_Plant_{plant_index:02d}"
        UsdGeom.Xform.Define(stage, base)
        hang_direction = -1 if z > 0 else 1
        crown_z = z + hang_direction * 0.28
        fruit_z = z + hang_direction * 0.42
        if strawberry_asset:
            self._reference_asset(
                stage,
                f"{base}/ExternalModel",
                strawberry_asset,
                translation=(x, GUTTER_HEIGHT + 0.42, crown_z),
                scale=(0.020, 0.020, 0.020),
                rotation=(-90, (plant_index % 4) * 35, 0),
                instanceable=True,
            )
            self._create_cylinder(
                stage,
                f"{base}/HangingRunner",
                (x + 0.08, GUTTER_HEIGHT - 0.18, fruit_z),
                radius=0.018,
                depth=0.78,
                color=(0.10, 0.34, 0.08),
            )
            if plant_index in (2, 5, 8, 11):
                self._create_strawberry_fruit(stage, f"{base}/Fruit", (x - 0.16, GUTTER_HEIGHT - 0.30, fruit_z), ripe=True)
                self._create_strawberry_fruit(stage, f"{base}/Fruit_Unripe", (x + 0.18, GUTTER_HEIGHT - 0.12, fruit_z + hang_direction * 0.16), ripe=False)
            elif plant_index in (3, 7, 10):
                self._create_strawberry_fruit(stage, f"{base}/Fruit_Unripe", (x + 0.12, GUTTER_HEIGHT - 0.16, fruit_z), ripe=False)
            return

        self._create_cylinder(
            stage,
            f"{base}/CrownStem",
            (x, GUTTER_HEIGHT + 0.14, crown_z),
            radius=0.035,
            depth=0.34,
            color=(0.12, 0.36, 0.08),
        )
        self._create_cylinder(
            stage,
            f"{base}/HangingRunner",
            (x + 0.08, GUTTER_HEIGHT - 0.18, fruit_z),
            radius=0.018,
            depth=0.78,
            color=(0.10, 0.34, 0.08),
        )
        self._create_leaf(stage, f"{base}/Leaf_01", (x - 0.24, GUTTER_HEIGHT + 0.34, crown_z), (-10, 0, 30))
        self._create_leaf(stage, f"{base}/Leaf_02", (x + 0.24, GUTTER_HEIGHT + 0.34, crown_z), (-10, 0, -30))
        self._create_leaf(stage, f"{base}/Leaf_03", (x, GUTTER_HEIGHT + 0.42, crown_z + hang_direction * 0.22), (8, 0, 0))
        self._create_leaf(stage, f"{base}/Leaf_04", (x + 0.08, GUTTER_HEIGHT + 0.18, crown_z + hang_direction * 0.42), (-24, 0, 0))
        self._create_leaf(stage, f"{base}/Leaf_05", (x - 0.12, GUTTER_HEIGHT + 0.12, crown_z + hang_direction * 0.52), (-35, 0, 16))
        self._create_sphere(
            stage,
            f"{base}/LeafCluster",
            (x, GUTTER_HEIGHT + 0.30, crown_z + hang_direction * 0.18),
            scale=(0.40, 0.18, 0.34),
            color=(0.035, 0.40, 0.12),
        )
        self._create_sphere(
            stage,
            f"{base}/Flower",
            (x + 0.22, GUTTER_HEIGHT - 0.02, fruit_z),
            scale=(0.055, 0.055, 0.055),
            color=(0.95, 0.95, 0.90),
        )

        if plant_index in (2, 5, 8, 11):
            self._create_strawberry_fruit(stage, f"{base}/Fruit", (x - 0.16, GUTTER_HEIGHT - 0.32, fruit_z), ripe=True)
            self._create_strawberry_fruit(stage, f"{base}/Fruit_Unripe", (x + 0.18, GUTTER_HEIGHT - 0.14, fruit_z + hang_direction * 0.16), ripe=False)
        elif plant_index in (3, 7, 10):
            self._create_strawberry_fruit(stage, f"{base}/Fruit_Unripe", (x + 0.12, GUTTER_HEIGHT - 0.18, fruit_z), ripe=False)

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
        color = (0.92, 0.04, 0.035) if ripe else (0.86, 0.72, 0.16)
        self._create_sphere(stage, path, translation, scale=(0.10, 0.14, 0.10), color=color)
        self._create_sphere(
            stage,
            f"{path}_Calyx",
            (translation[0], translation[1] + 0.11, translation[2]),
            scale=(0.08, 0.025, 0.08),
            color=(0.05, 0.30, 0.07),
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
            self._highlight_device(stage, f"{unit_path}/Actuators/CO2Injector", (0.10, 0.60, 1.00), scale=(0.48, 1.05, 0.48))
            self._highlight_device(stage, f"{unit_path}/Sensors/CO2Sensor", (0.10, 0.60, 1.00), scale=(0.48, 0.48, 0.48))
            self._update_plants_for_harvest(stage, unit_path)

    def _update_demo_metrics(self):
        metrics = {
            "stage": "Fruiting -> Early harvest",
            "scenario": "16h photoperiod + CO2",
            "expected_shipment": "2026-12-22",
            "yield_score": "87 / 100",
            "opex": "+18% electricity",
            "recommendation": "Recommended",
        }
        for key, value in metrics.items():
            self._metric_labels[key].text = value

    def _highlight_leds(self, stage, unit_path):
        led_z_positions = (-5.5, -3.1, 3.1, 5.5)
        for index in range(1, 5):
            prim = stage.GetPrimAtPath(f"{unit_path}/Actuators/LEDStrip_{index}")
            if not prim:
                continue
            self._set_display_color(prim, (1.0, 0.95, 0.25))
            self._set_transform(prim, translation=(0, 4.25, led_z_positions[index - 1]), scale=(BED_LENGTH, 0.14, 0.20))

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
                flower = stage.GetPrimAtPath(f"{base}/Flower")
                fruit = stage.GetPrimAtPath(f"{base}/Fruit")
                if leaf:
                    self._set_display_color(leaf, (0.02, 0.40, 0.12))
                    self._set_transform(
                        leaf,
                        translation=self._get_translate_value(leaf),
                        scale=(0.50, 0.24, 0.42),
                    )
                if flower:
                    self._set_display_color(flower, (1.0, 1.0, 0.92))
                if fruit:
                    self._set_display_color(fruit, (1.0, 0.03, 0.04))
                    self._set_transform(
                        fruit,
                        translation=self._get_translate_value(fruit),
                        scale=(0.12, 0.16, 0.12),
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
        hang_direction = -1 if z > 0 else 1
        return (x - 0.16, GUTTER_HEIGHT - 0.32, z + hang_direction * 0.42)

    def _unit_paths(self):
        return [f"{SMART_FARM_PATH}/{unit_name}" for unit_name, _x, _z in GREENHOUSE_UNITS]

    def _create_cube(self, stage, path, translation, scale, color, opacity=1.0, rotation=None):
        cube = UsdGeom.Cube.Define(stage, path)
        cube.CreateSizeAttr(1.0)
        cube.CreateDisplayColorAttr([Gf.Vec3f(*color)])
        cube.CreateDisplayOpacityAttr([opacity])
        if opacity < 1.0:
            self._bind_preview_material(stage, cube.GetPrim(), color, opacity)
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

    def _reference_asset(self, stage, path, asset_path, translation, scale, rotation=None, instanceable=False):
        xform = UsdGeom.Xform.Define(stage, path)
        xform.GetPrim().GetReferences().AddReference(str(asset_path))
        xform.GetPrim().SetInstanceable(instanceable)
        self._set_transform(xform.GetPrim(), translation=translation, rotation=rotation, scale=scale)
        return xform

    def _bind_preview_material(self, stage, prim, color, opacity):
        material = self._create_preview_material(stage, color, opacity)
        UsdShade.MaterialBindingAPI(prim).Bind(material)

    def _create_preview_material(self, stage, color, opacity):
        material_name = f"Preview_{self._safe_name(opacity)}_{int(color[0] * 255)}_{int(color[1] * 255)}_{int(color[2] * 255)}"
        material_path = f"{SMART_FARM_PATH}/Looks/{material_name}"
        UsdGeom.Scope.Define(stage, f"{SMART_FARM_PATH}/Looks")
        material = UsdShade.Material.Define(stage, material_path)
        shader = UsdShade.Shader.Define(stage, f"{material_path}/Shader")
        shader.CreateIdAttr("UsdPreviewSurface")
        shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*color))
        shader.CreateInput("opacity", Sdf.ValueTypeNames.Float).Set(opacity)
        shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(0.22)
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

    def _set_display_color(self, prim, color):
        imageable = UsdGeom.Gprim(prim)
        imageable.CreateDisplayColorAttr([Gf.Vec3f(*color)])

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
            candidate = ASSET_DIR / relative_path
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
        print("[joon.smartfarm.twin] Extension shutdown")
