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
import omni.usd
from pxr import Gf, Sdf, UsdGeom, UsdLux


DEFAULT_STATUS = "Ready to create the first smart farm twin scene."
SMART_FARM_PATH = "/World/SmartFarm"
GREENHOUSE_LENGTH = 56.0
GREENHOUSE_WIDTH = 18.0
GREENHOUSE_WALL_HEIGHT = 4.2
GREENHOUSE_RIDGE_HEIGHT = 8.4
BED_LENGTH = 46.0


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
        self._window = ui.Window("Smart Farm Twin", width=460, height=520)
        with self._window.frame:
            with ui.VStack(spacing=8, height=0):
                ui.Label("Strawberry Early-Shipment Twin", height=24)
                ui.Separator(height=4)

                self._add_info_row("Project", "Strawberry Early-Shipment Twin")
                self._add_info_row("Facility", "Single-span greenhouse")
                self._add_info_row("Crop", "Seolhyang strawberry")
                self._metric_labels["stage"] = self._add_info_row("Stage", "Vegetative growth")
                self._add_info_row("Target Shipment", "2026-12-22")
                self._metric_labels["scenario"] = self._add_info_row("Scenario", "Not run")
                self._metric_labels["expected_shipment"] = self._add_info_row("Expected Shipment", "-")
                self._metric_labels["yield_score"] = self._add_info_row("Yield Score", "-")
                self._metric_labels["opex"] = self._add_info_row("OpEx Delta", "-")
                self._metric_labels["recommendation"] = self._add_info_row("Recommendation", "-")

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
            "Twin scene created: arched greenhouse, soil beds, 64 strawberry plants, sensors, LEDs, and fans."
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

        self._create_floor(stage)
        self._create_greenhouse(stage)
        self._create_growing_beds(stage)
        self._create_actuators(stage)
        self._create_sensors(stage)
        self._create_lighting(stage)

    def _create_floor(self, stage):
        self._create_cube(
            stage,
            f"{SMART_FARM_PATH}/Ground",
            translation=(0, -0.04, 0),
            scale=(66, 0.08, 28),
            color=(0.31, 0.24, 0.15),
        )

    def _create_greenhouse(self, stage):
        group = f"{SMART_FARM_PATH}/Greenhouse"
        UsdGeom.Xform.Define(stage, group)

        frame_color = (0.72, 0.78, 0.82)
        cover_color = (0.72, 0.90, 0.98)

        half_length = GREENHOUSE_LENGTH / 2.0
        half_width = GREENHOUSE_WIDTH / 2.0

        self._create_cube(stage, f"{group}/LeftWallCover", (0, 2.1, -half_width), (GREENHOUSE_LENGTH, 4.2, 0.08), cover_color, 0.18)
        self._create_cube(stage, f"{group}/RightWallCover", (0, 2.1, half_width), (GREENHOUSE_LENGTH, 4.2, 0.08), cover_color, 0.18)
        self._create_cube(stage, f"{group}/FrontCover", (-half_length, 2.2, 0), (0.08, 4.4, GREENHOUSE_WIDTH), cover_color, 0.14)
        self._create_cube(stage, f"{group}/BackCover", (half_length, 2.2, 0), (0.08, 4.4, GREENHOUSE_WIDTH), cover_color, 0.14)

        roof_panels = [
            ("LeftLower", -6.7, 4.9, -28),
            ("LeftUpper", -3.4, 7.0, -14),
            ("Ridge", 0.0, GREENHOUSE_RIDGE_HEIGHT, 0),
            ("RightUpper", 3.4, 7.0, 14),
            ("RightLower", 6.7, 4.9, 28),
        ]
        for name, z, y, rot_x in roof_panels:
            self._create_cube(
                stage,
                f"{group}/ArchedRoofCover_{name}",
                (0, y, z),
                (GREENHOUSE_LENGTH, 0.08, 3.8),
                cover_color,
                0.16,
                rotation=(rot_x, 0, 0),
            )

        for x in (-28, -20, -12, -4, 4, 12, 20, 28):
            safe_x = self._safe_name(x)
            self._create_cube(stage, f"{group}/Rib_{safe_x}_LeftPost", (x, 2.1, -half_width), (0.14, 4.2, 0.14), frame_color)
            self._create_cube(stage, f"{group}/Rib_{safe_x}_RightPost", (x, 2.1, half_width), (0.14, 4.2, 0.14), frame_color)
            self._create_cube(stage, f"{group}/Rib_{safe_x}_LeftLowerArch", (x, 5.0, -6.6), (0.14, 0.14, 4.0), frame_color, rotation=(-28, 0, 0))
            self._create_cube(stage, f"{group}/Rib_{safe_x}_LeftUpperArch", (x, 7.0, -3.2), (0.14, 0.14, 3.8), frame_color, rotation=(-14, 0, 0))
            self._create_cube(stage, f"{group}/Rib_{safe_x}_RightUpperArch", (x, 7.0, 3.2), (0.14, 0.14, 3.8), frame_color, rotation=(14, 0, 0))
            self._create_cube(stage, f"{group}/Rib_{safe_x}_RightLowerArch", (x, 5.0, 6.6), (0.14, 0.14, 4.0), frame_color, rotation=(28, 0, 0))

        for z in (-half_width, -4.5, 0, 4.5, half_width):
            self._create_cube(stage, f"{group}/LongBeam_{self._safe_name(z)}", (0, 4.2 if abs(z) == half_width else 7.1, z), (GREENHOUSE_LENGTH, 0.12, 0.12), frame_color)

    def _create_growing_beds(self, stage):
        beds_group = f"{SMART_FARM_PATH}/GrowingBeds"
        plants_group = f"{SMART_FARM_PATH}/Plants"
        UsdGeom.Xform.Define(stage, beds_group)
        UsdGeom.Xform.Define(stage, plants_group)

        bed_z_positions = [-6.3, -4.5, -2.7, -0.9, 0.9, 2.7, 4.5, 6.3]
        for bed_index, z in enumerate(bed_z_positions, start=1):
            self._create_cube(
                stage,
                f"{beds_group}/Bed_{bed_index:02d}",
                translation=(0, 0.28, z),
                scale=(BED_LENGTH, 0.36, 0.82),
                color=(0.23, 0.13, 0.08),
            )
            self._create_cube(
                stage,
                f"{beds_group}/SoilTop_{bed_index:02d}",
                translation=(0, 0.49, z),
                scale=(BED_LENGTH - 0.8, 0.06, 0.70),
                color=(0.15, 0.08, 0.035),
            )
            self._create_cube(
                stage,
                f"{beds_group}/IrrigationPipe_{bed_index:02d}",
                translation=(0, 0.72, z),
                scale=(BED_LENGTH, 0.05, 0.05),
                color=(0.05, 0.08, 0.10),
            )
            for marker_index, x in enumerate((-18.0, -9.0, 0.0, 9.0, 18.0), start=1):
                self._create_soil_clump(stage, beds_group, bed_index, marker_index, x, z)
            for plant_index, x in enumerate((-20, -14, -8, -2, 2, 8, 14, 20), start=1):
                self._create_plant(stage, plants_group, bed_index, plant_index, x, z)

    def _create_actuators(self, stage):
        group = f"{SMART_FARM_PATH}/Actuators"
        UsdGeom.Xform.Define(stage, group)

        for i, z in enumerate((-5.4, -1.8, 1.8, 5.4), start=1):
            self._create_cube(stage, f"{group}/LEDStrip_{i}", (0, 4.25, z), (BED_LENGTH, 0.06, 0.10), (1.0, 0.86, 0.32))

        for i, x in enumerate((-27.6, 27.6), start=1):
            self._create_cylinder(stage, f"{group}/VentFan_{i}", (x, 3.0, 0), radius=1.0, depth=0.20, color=(0.10, 0.13, 0.16))
            self._create_cube(stage, f"{group}/VentFanHub_{i}", (x, 3.0, 0), (0.36, 0.36, 0.36), (0.35, 0.40, 0.44))

        self._create_cube(stage, f"{group}/CO2Injector", (-25.8, 1.0, -7.2), (0.55, 1.1, 0.55), (0.20, 0.20, 0.24))
        self._create_cube(stage, f"{group}/WaterValve", (25.2, 0.75, 7.2), (0.60, 0.45, 0.45), (0.05, 0.28, 0.70))

    def _create_sensors(self, stage):
        group = f"{SMART_FARM_PATH}/Sensors"
        UsdGeom.Xform.Define(stage, group)

        sensors = [
            ("TemperatureHumidity", (-18.0, 2.0, -7.2), (0.90, 0.28, 0.10)),
            ("CO2", (-6.0, 2.0, 7.2), (0.15, 0.15, 0.15)),
            ("Light", (6.0, 4.5, -7.2), (1.0, 0.78, 0.10)),
            ("SoilMoisture", (18.0, 0.8, 7.2), (0.06, 0.28, 0.85)),
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

    def _create_plant(self, stage, group, bed_index, plant_index, x, z):
        base = f"{group}/Bed_{bed_index:02d}_Plant_{plant_index:02d}"
        UsdGeom.Xform.Define(stage, base)
        self._create_cylinder(stage, f"{base}/Stem", (x, 0.78, z), radius=0.045, depth=0.36, color=(0.12, 0.36, 0.08))
        self._create_leaf(stage, f"{base}/Leaf_01", (x - 0.18, 0.98, z), (-12, 0, 28))
        self._create_leaf(stage, f"{base}/Leaf_02", (x + 0.18, 0.98, z), (-12, 0, -28))
        self._create_leaf(stage, f"{base}/Leaf_03", (x, 1.04, z - 0.18), (8, 0, 0))
        self._create_leaf(stage, f"{base}/Leaf_04", (x, 1.04, z + 0.18), (-8, 0, 0))
        self._create_sphere(stage, f"{base}/LeafCluster", (x, 1.08, z), scale=(0.28, 0.12, 0.24), color=(0.04, 0.44, 0.14))
        self._create_sphere(stage, f"{base}/Flower", (x + 0.18, 1.22, z + 0.10), scale=(0.055, 0.055, 0.055), color=(0.95, 0.95, 0.90))

        if plant_index in (2, 5, 8):
            self._create_sphere(stage, f"{base}/Fruit", (x - 0.16, 1.08, z - 0.10), scale=(0.09, 0.08, 0.08), color=(0.88, 0.05, 0.06))

    def _create_leaf(self, stage, path, translation, rotation):
        self._create_sphere(
            stage,
            path,
            translation,
            scale=(0.26, 0.045, 0.12),
            color=(0.035, 0.42, 0.13),
            rotation=rotation,
        )

    def _create_soil_clump(self, stage, group, bed_index, marker_index, x, z):
        self._create_sphere(
            stage,
            f"{group}/SoilClump_{bed_index:02d}_{marker_index:02d}",
            translation=(x, 0.56, z + 0.22),
            scale=(0.22, 0.06, 0.12),
            color=(0.09, 0.045, 0.02),
        )

    def _apply_demo_scenario(self, stage):
        self._highlight_leds(stage)
        self._highlight_device(stage, f"{SMART_FARM_PATH}/Actuators/CO2Injector", (0.10, 0.60, 1.00), scale=(0.48, 1.05, 0.48))
        self._highlight_device(stage, f"{SMART_FARM_PATH}/Sensors/CO2Sensor", (0.10, 0.60, 1.00), scale=(0.48, 0.48, 0.48))
        self._update_plants_for_harvest(stage)

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

    def _highlight_leds(self, stage):
        led_z_positions = (-5.4, -1.8, 1.8, 5.4)
        for index in range(1, 5):
            prim = stage.GetPrimAtPath(f"{SMART_FARM_PATH}/Actuators/LEDStrip_{index}")
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

    def _update_plants_for_harvest(self, stage):
        for bed_index in range(1, 9):
            for plant_index in range(1, 9):
                base = f"{SMART_FARM_PATH}/Plants/Bed_{bed_index:02d}_Plant_{plant_index:02d}"
                leaf = stage.GetPrimAtPath(f"{base}/LeafCluster")
                flower = stage.GetPrimAtPath(f"{base}/Flower")
                fruit = stage.GetPrimAtPath(f"{base}/Fruit")
                if leaf:
                    self._set_display_color(leaf, (0.02, 0.40, 0.12))
                    self._set_transform(
                        leaf,
                        translation=self._get_translate_value(leaf),
                        scale=(0.42, 0.24, 0.36),
                    )
                if flower:
                    self._set_display_color(flower, (1.0, 1.0, 0.92))
                if fruit:
                    self._set_display_color(fruit, (1.0, 0.03, 0.04))
                    self._set_transform(
                        fruit,
                        translation=self._get_translate_value(fruit),
                        scale=(0.11, 0.10, 0.10),
                    )
                elif plant_index in (1, 3, 6):
                    self._create_sphere(
                        stage,
                        f"{base}/Fruit",
                        self._fruit_position_for(bed_index, plant_index),
                        scale=(0.10, 0.09, 0.09),
                        color=(1.0, 0.03, 0.04),
                    )

    def _fruit_position_for(self, bed_index, plant_index):
        bed_z_positions = [-6.3, -4.5, -2.7, -0.9, 0.9, 2.7, 4.5, 6.3]
        plant_x_positions = [-20, -14, -8, -2, 2, 8, 14, 20]
        x = plant_x_positions[plant_index - 1]
        z = bed_z_positions[bed_index - 1]
        return (x - 0.16, 1.08, z - 0.10)

    def _create_cube(self, stage, path, translation, scale, color, opacity=1.0, rotation=None):
        cube = UsdGeom.Cube.Define(stage, path)
        cube.CreateSizeAttr(1.0)
        cube.CreateDisplayColorAttr([Gf.Vec3f(*color)])
        cube.CreateDisplayOpacityAttr([opacity])
        self._set_transform(cube.GetPrim(), translation=translation, rotation=rotation, scale=scale)
        return cube

    def _create_sphere(self, stage, path, translation, scale, color, opacity=1.0, rotation=None):
        sphere = UsdGeom.Sphere.Define(stage, path)
        sphere.CreateRadiusAttr(1.0)
        sphere.CreateDisplayColorAttr([Gf.Vec3f(*color)])
        sphere.CreateDisplayOpacityAttr([opacity])
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

    def on_shutdown(self):
        """This is called every time the extension is deactivated. It is used
        to clean up the extension state."""
        print("[joon.smartfarm.twin] Extension shutdown")
