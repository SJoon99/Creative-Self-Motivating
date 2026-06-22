from __future__ import annotations

import asyncio
import base64
import json
import os
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Mapping

import omni.ext
import omni.kit.app
import omni.ui as ui
import omni.usd

from .model import BLUEPRINTS, project_days, state_for_blueprint, state_for_manual_actuator, vision_assessment_from_state

try:
    from joon.smartfarm.twin.extension import get_active_extension
except Exception:  # pragma: no cover - only used when the twin extension is unavailable.
    get_active_extension = None

SMART_FARM_PATH = "/World/SmartFarm"
GROWTH_CAMERA_PATH = f"{SMART_FARM_PATH}/Cameras/GrowthPhenotypeCamera"
GROWTH_CAMERA_NEAR_CLIP = 0.05
GROWTH_CAMERA_FAR_CLIP = 9.0
GROWTH_CAMERA_VISUAL_SCALE = 0.006
GROWTH_CAMERA_FILL_LIGHT_PATH = f"{SMART_FARM_PATH}/Cameras/GrowthPhenotypeFillLight"
GROWTH_CAMERA_FILL_INTENSITY = 90.0
BLUE_SKY_DOME_PATH = f"{SMART_FARM_PATH}/Lighting/SoftSky"
BLUE_SKY_SUN_PATH = f"{SMART_FARM_PATH}/Lighting/Sun"
BLUE_SKY_DOME_INTENSITY = 260.0
BLUE_SKY_SUN_INTENSITY = 520.0
TWIN_API_BASE = "http://127.0.0.1:8011/smartfarm"
PANEL_TITLE = "SmartFarm OmniOps Dock"
EVIDENCE_TITLE = "SmartFarm Evidence"
RAG_TRACE_TITLE = "SmartFarm RAG Trace"
BLUEPRINT_DAG_TITLE = "SmartFarm Blueprint DAG"
STRAWBERRY_VIEW_TITLE = "SmartFarm Strawberry Live View"
STRAWBERRY_VIEW_DOCK_RATIO = 0.30
STRAWBERRY_VIEW_WINDOW_WIDTH = 480
STRAWBERRY_VIEW_WINDOW_HEIGHT = 460
PANEL_BG = 0xFF171A1F
CARD_BG = 0xFF20262E
CARD_BG_DARK = 0xFF1A1F26
TEXT_MUTED = 0xFF9AA4B2
TEXT_MAIN = 0xFFE6EAF0
ACCENT_BLUE = 0xFF4CC9F0
ACCENT_GREEN = 0xFF80ED99
ACCENT_AMBER = 0xFFFFB703
ACCENT_RED = 0xFFFF5C5C
EXTENSION_ROOT = Path(__file__).resolve().parents[3]
PROJECT_ROOT = next(
    (
        parent
        for parent in (EXTENSION_ROOT, *EXTENSION_ROOT.parents)
        if (parent / "source").is_dir() and (parent / "_build").is_dir()
    ),
    EXTENSION_ROOT,
)
VISION_CAPTURE_DIR = PROJECT_ROOT / "logs" / "smartfarm-vision"
PLANNING_TRACE_DIR = PROJECT_ROOT / "logs" / "smartfarm-blueprints"
BLUEPRINT_DAG_IMAGE_DIR = PLANNING_TRACE_DIR / "dag"
VISION_ANALYZE_PATHS = ("/vision/analyze", "/analyze/growth", "/phenotype/analyze", "/analyze")
SENSOR_HISTORY_LEN = 54
SENSOR_POLL_FRAMES = 60
SENSOR_SERIES = (
    ("dli_mol_m2_day", "DLI", "mol/m²/day", 8.0, 24.0, 0xFF4CC9F0),
    ("substrate_moisture_percent", "Substrate", "%", 24.0, 65.0, 0xFF4895EF),
    ("humidity_percent", "Humidity", "% RH", 48.0, 90.0, 0xFFB5179E),
    ("temperature_c", "Temp", "°C", 18.0, 29.0, 0xFFFFB703),
    ("co2_ppm", "CO₂", "ppm", 380.0, 900.0, 0xFF80ED99),
)
ACTUATOR_CONTROLS = (
    ("led_intensity_percent", "LED intensity", "%", 0, 100),
    ("photoperiod_hours", "Photoperiod", "h", 8, 18),
    ("irrigation_pulses_per_day", "Irrigation pulses", "/day", 0, 8),
    ("fan_duty_percent", "Fan duty", "%", 0, 100),
    ("co2_ppm", "CO₂ setpoint", "ppm", 380, 900),
)

PLAN_BUTTON_LABELS = ("Plan A", "Plan B", "Plan C")
PLAN_LABEL_BY_ID = {
    "plan-a-low-cost": "Plan A",
    "plan-b-early-shipment": "Plan B",
    "plan-c-disease-safe": "Plan C",
    "blueprint-a": "Plan A",
    "blueprint-b": "Plan B",
    "blueprint-c": "Plan C",
}
STATIC_BLUEPRINT_ID_BY_PLAN_LABEL = {
    "Plan A": "plan-a-low-cost",
    "Plan B": "plan-b-early-shipment",
    "Plan C": "plan-c-disease-safe",
}


def _plain_plan_name(value: Any, blueprint_id: str = "") -> str:
    text = str(value or "")
    if blueprint_id in PLAN_LABEL_BY_ID:
        return PLAN_LABEL_BY_ID[blueprint_id]
    lowered = text.lower()
    if "plan a" in lowered or "blueprint a" in lowered:
        return "Plan A"
    if "plan b" in lowered or "blueprint b" in lowered:
        return "Plan B"
    if "plan c" in lowered or "blueprint c" in lowered:
        return "Plan C"
    return text or blueprint_id or "-"


def _plan_order(row: Mapping[str, Any]) -> int:
    blueprint_id = str(row.get("blueprintId") or row.get("id") or "")
    label = _plain_plan_name(row.get("name") or row.get("blueprintName"), blueprint_id)
    try:
        return PLAN_BUTTON_LABELS.index(label)
    except ValueError:
        return len(PLAN_BUTTON_LABELS)


class OmniOpsExtension(omni.ext.IExt):
    """Omniverse-first operator cockpit for the existing SmartFarm twin.

    This extension does not create a replacement farm.  It loads alongside
    joon.smartfarm.twin and drives the existing /World/SmartFarm scene through
    the already implemented SmartFarm Twin service endpoints.  WebRTC remains a
    remote screen transport only.
    """

    def on_startup(self, _ext_id):
        print("[joon.smartfarm.omniops] startup")
        self._state: Dict[str, Any] = self._fallback_state("baseline")
        self._selected_blueprint = "baseline"
        self._control_window = None
        self._evidence_window = None
        self._rag_trace_window = None
        self._blueprint_dag_window = None
        self._strawberry_view_window = None
        self._labels: Dict[str, ui.Label] = {}
        self._vision_labels: Dict[str, ui.Label] = {}
        self._trend_labels = []
        self._score_labels = []
        self._log_labels = []
        self._rag_trace_labels = []
        self._vision_evidence_labels = []
        self._evidence_summary_labels: Dict[str, ui.Label] = {}
        self._evidence_summary_bars: Dict[str, ui.ProgressBar] = {}
        self._growth_status_bars: Dict[str, ui.ProgressBar] = {}
        self._camera_screen_labels: Dict[str, ui.Label] = {}
        self._camera_viewport_widget = None
        self._camera_viewport_frame = None
        self._timeline_rows = []
        self._score_rows = []
        self._criteria_labels: Dict[str, ui.Label] = {}
        self._score_weight_rows: Dict[str, Dict[str, Any]] = {}
        self._feedback_response_labels: Dict[str, ui.Label] = {}
        self._decision_graph_rows = []
        self._decision_graph_plot_error_reported = False
        self._blueprint_dag_nodes: Dict[str, Dict[str, Any]] = {}
        self._blueprint_dag_plan_nodes = []
        self._blueprint_dag_edges: Dict[str, ui.Label] = {}
        self._blueprint_dag_summary: Dict[str, ui.Label] = {}
        self._blueprint_dag_image = None
        self._blueprint_dag_image_path: Path | None = None
        self._blueprint_dag_render_seq = 0
        self._blueprint_decision_history: list[Dict[str, Any]] = []
        self._blueprint_generation_history: list[Dict[str, Any]] = []
        self._active_generation_run_id: str | None = None
        self._apply_buttons = []
        self._apply_button_blueprint_ids = ["plan-a-low-cost", "plan-b-early-shipment", "plan-c-disease-safe"]
        self._vision_card_labels: Dict[str, ui.Label] = {}
        self._vision_card_bars: Dict[str, ui.ProgressBar] = {}
        self._sensor_value_labels: Dict[str, ui.Label] = {}
        self._sensor_plots: Dict[str, ui.Plot] = {}
        self._sensor_history: Dict[str, list[float]] = {}
        self._actuator_models: Dict[str, ui.AbstractValueModel] = {}
        self._actuator_value_labels: Dict[str, ui.Label] = {}
        self._actuator_dirty = False
        self._syncing_actuator_models = False
        self._water_valve_open = False
        self._logs = ["OmniOps loaded. Existing /World/SmartFarm twin is the source of truth."]
        self._rag_trace_lines = ["SmartFarm RAG Trace ready. Click Generate Gemma/RAG Blueprints to capture live API evidence."]
        self._latest_vision_assessment: Dict[str, Any] | None = None
        self._capture_seq = 0
        self._capture_task = None
        self._update_subscription = None
        self._dock_task = None
        self._evidence_dock_task = None
        self._rag_trace_dock_task = None
        self._blueprint_dag_dock_task = None
        self._strawberry_view_dock_task = None
        self._dock_retry_frames = 0
        self._evidence_dock_retry_frames = 0
        self._startup_frames_remaining = 30
        self._poll_frames_remaining = SENSOR_POLL_FRAMES
        self._startup_synced = False
        self._docked = False
        self._evidence_docked = False
        self._rag_trace_docked = False
        self._blueprint_dag_docked = False
        self._strawberry_view_docked = False
        self._build_control_window()
        self._build_evidence_window()
        self._build_rag_trace_window()
        self._build_blueprint_dag_window()
        self._build_strawberry_view_window()
        self._refresh_ui()
        self._dock_task = asyncio.ensure_future(self._dock_operator_panel_async())
        self._evidence_dock_task = asyncio.ensure_future(self._dock_evidence_panel_async())
        self._rag_trace_dock_task = asyncio.ensure_future(self._dock_rag_trace_panel_async())
        self._blueprint_dag_dock_task = asyncio.ensure_future(self._dock_blueprint_dag_panel_async())
        self._strawberry_view_dock_task = asyncio.ensure_future(self._dock_strawberry_view_async())
        self._update_subscription = (
            omni.kit.app.get_app()
            .get_update_event_stream()
            .create_subscription_to_pop(self._on_update, name="joon.smartfarm.omniops.update")
        )

    def on_shutdown(self):
        print("[joon.smartfarm.omniops] shutdown")
        if self._camera_viewport_widget is not None:
            try:
                self._camera_viewport_widget.destroy()
            except Exception:
                pass
            self._camera_viewport_widget = None
        self._camera_viewport_frame = None
        self._update_subscription = None
        if self._dock_task is not None:
            try:
                self._dock_task.cancel()
            except Exception:
                pass
            self._dock_task = None
        if self._evidence_dock_task is not None:
            try:
                self._evidence_dock_task.cancel()
            except Exception:
                pass
            self._evidence_dock_task = None
        if self._rag_trace_dock_task is not None:
            try:
                self._rag_trace_dock_task.cancel()
            except Exception:
                pass
            self._rag_trace_dock_task = None
        if self._blueprint_dag_dock_task is not None:
            try:
                self._blueprint_dag_dock_task.cancel()
            except Exception:
                pass
            self._blueprint_dag_dock_task = None
        if self._strawberry_view_dock_task is not None:
            try:
                self._strawberry_view_dock_task.cancel()
            except Exception:
                pass
            self._strawberry_view_dock_task = None
        if self._capture_task is not None:
            try:
                self._capture_task.cancel()
            except Exception:
                pass
            self._capture_task = None
        self._control_window = None
        self._evidence_window = None
        self._rag_trace_window = None
        self._blueprint_dag_window = None
        if self._strawberry_view_window is not None:
            try:
                self._strawberry_view_window.destroy()
            except Exception:
                pass
            self._strawberry_view_window = None

    # ------------------------------------------------------------------ UI --

    def _build_control_window(self):
        # Keep the operator window hidden until a dock target is available.
        # Showing it before docking is what produced the floating popup the
        # evaluator had to manually move.
        self._control_window = ui.Window(
            PANEL_TITLE,
            dockPreference=ui.DockPreference.RIGHT,
            width=680,
            height=1080,
            visible=False,
        )
        try:
            self._control_window.detachable = False
        except Exception:
            pass
        try:
            self._control_window.deferred_dock_in("Layer", ui.DockPolicy.CURRENT_WINDOW_IS_ACTIVE)
        except Exception:
            pass
        with self._control_window.frame:
            with ui.ScrollingFrame():
                with ui.VStack(spacing=9, height=0):
                    ui.Label("Omniverse SmartFarm Operator", height=24)
                    ui.Label(
                        "Docked operator panel for the existing /World/SmartFarm twin. Web remains only a stream viewer.",
                        word_wrap=True,
                        height=44,
                    )
                    ui.Separator(height=4)

                    ui.Label("Twin Source", height=20)
                    self._labels["scene"] = self._row("Scene Root", SMART_FARM_PATH)
                    self._labels["mode"] = self._row("Scene Mode", "-")
                    self._labels["active"] = self._row("Active Blueprint", "-")

                    ui.Separator(height=4)
                    ui.Label("Growth Status", height=20)
                    with ui.VStack(spacing=6, height=0):
                        with ui.HStack(spacing=6, height=62):
                            self._growth_status_card("health", "Health", ACCENT_GREEN)
                            self._growth_status_card("maturity", "Maturity", ACCENT_AMBER)
                            self._growth_status_card("readiness", "Ready", ACCENT_BLUE)
                        with ui.Frame(height=82, style={"background_color": CARD_BG_DARK, "border_radius": 8, "padding": 8}):
                            with ui.VStack(spacing=3):
                                self._labels["ship"] = self._row("Expected Ship", "-")
                                self._labels["risk"] = self._row("Disease Risk", "-")
                                self._labels["limiter"] = self._row("Main Limiter", "-")

                    ui.Separator(height=4)
                    ui.Label("Virtual Sensors · live trend", height=20)
                    self._build_sensor_graphs()

                    ui.Separator(height=4)
                    ui.Label("Actuator Controls", height=20)
                    self._build_actuator_controls()

                    ui.Separator(height=4)
                    ui.Label("Blueprint Apply", height=20)
                    with ui.VStack(spacing=5, height=0):
                        for idx, label in enumerate(PLAN_BUTTON_LABELS):
                            button = ui.Button(
                                label,
                                height=30,
                                clicked_fn=lambda i=idx: self._apply_plan_button(i),
                            )
                            self._apply_buttons.append(button)
                    with ui.HStack(spacing=8, height=32):
                        ui.Button("Create Current Twin", clicked_fn=lambda: self._post_scene("growth"))
                        ui.Button("Reset Baseline", clicked_fn=lambda: self._reset_demo_baseline())
                    with ui.HStack(spacing=8, height=32):
                        ui.Button("Run Daily Planning", clicked_fn=self._run_daily_planning)
                        ui.Button("Refresh State", clicked_fn=self._load_state_from_api)
                    with ui.HStack(spacing=8, height=32):
                        ui.Button("Generate Gemma/RAG Blueprints", clicked_fn=self._generate_rag_blueprints)
                        ui.Button("Apply Recommended", clicked_fn=self._apply_recommended_blueprint)

                    ui.Separator(height=4)
                    ui.Label("Growth Camera", height=20)
                    self._vision_labels["camera"] = self._row("Camera", GROWTH_CAMERA_PATH)
                    self._vision_labels["last_capture"] = self._row("Last Capture", "Not captured")
                    self._vision_labels["vision_health"] = self._row("Vision Health", "-")
                    self._vision_labels["vision_maturity"] = self._row("Growth Progress", "-")
                    self._vision_labels["vision_risk"] = self._row("Vision Risk", "-")
                    with ui.HStack(spacing=8, height=34):
                        ui.Button("Focus Growth Camera", clicked_fn=self._focus_growth_camera)
                        ui.Button("Capture & Analyze Growth", clicked_fn=self._capture_and_analyze_growth)
                    ui.Separator(height=4)
                    self._labels["status"] = ui.Label("Ready", word_wrap=True, height=72)

    def _build_evidence_window(self):
        self._evidence_window = ui.Window(
            EVIDENCE_TITLE,
            # DockPreference has no BOTTOM value in some Kit builds; actual
            # bottom placement is requested later through DockPosition.BOTTOM.
            dockPreference=ui.DockPreference.RIGHT,
            width=1440,
            height=460,
            visible=False,
        )
        try:
            self._evidence_window.detachable = False
        except Exception:
            pass
        try:
            self._evidence_window.deferred_dock_in("Console", ui.DockPolicy.CURRENT_WINDOW_IS_ACTIVE)
        except Exception:
            pass
        with self._evidence_window.frame:
            with ui.ScrollingFrame(style={"background_color": PANEL_BG}):
                with ui.VStack(spacing=8, height=0):
                    with ui.HStack(height=28):
                        ui.Label(
                            "SmartFarm Evidence Dashboard",
                            height=24,
                            style={"color": TEXT_MAIN, "font_size": 18},
                        )
                        ui.Spacer()
                        ui.Label(
                            "Explainability · ranking · virtual vision · operator audit",
                            width=420,
                            height=22,
                            style={"color": TEXT_MUTED},
                        )

                    with ui.HStack(spacing=8, height=76):
                        self._metric_card("recommended", "Recommended Plan", "-", width=205, accent=ACCENT_GREEN)
                        self._metric_card("applied", "Applied Plan", "-", width=205, accent=ACCENT_BLUE)
                        self._metric_card("ai_run", "Gemma/RAG Run", "Not run", width=250, accent=ACCENT_AMBER)
                        self._metric_card("vision", "Growth Camera", "-", width=245, accent=ACCENT_BLUE)

                    ui.Separator(height=4)

                    with ui.HStack(spacing=12, height=0):
                        with self._dashboard_card(width=910):
                            ui.Label("Blueprint Trajectory & Score Basis", height=22, style={"color": TEXT_MAIN, "font_size": 16})
                            ui.Label(
                                "Time-series preview plus explicit score weights, generation inputs, and feedback-response mapping. DAG flow is in the SmartFarm Blueprint DAG panel.",
                                height=34,
                                word_wrap=True,
                                style={"color": TEXT_MUTED},
                            )
                            with ui.HStack(spacing=8, height=226):
                                self._build_decision_graph_card()
                                self._build_score_weight_card()
                            ui.Separator(height=4)
                            with ui.HStack(spacing=8, height=176):
                                self._build_generation_criteria_card()
                                self._build_feedback_response_card()
                            ui.Separator(height=4)
                            ui.Label("Blueprint Branch Candidates", height=22, style={"color": TEXT_MAIN, "font_size": 16})
                            ui.Label(
                                "Plan A/B/C are neutral branch slots. Each card explains the actuator recipe, why it was generated, risk, and replan trigger.",
                                height=34,
                                word_wrap=True,
                                style={"color": TEXT_MUTED},
                            )
                            with ui.HStack(spacing=8, height=216):
                                for _ in range(3):
                                    self._score_rows.append(self._score_row())

    def _build_embedded_camera_view(self):
        try:
            # If the farm scene already exists, author the growth camera before
            # binding the embedded viewport. If it does not exist yet, the
            # startup/update path will create it and re-bind this widget.
            self._ensure_growth_camera()
        except Exception:
            pass
        try:
            from pxr import Sdf
            from omni.kit.widget.viewport import ViewportWidget

            if self._camera_viewport_widget is not None:
                try:
                    self._camera_viewport_widget.destroy()
                except Exception:
                    pass
            self._camera_viewport_widget = ViewportWidget(
                camera_path=GROWTH_CAMERA_PATH,
                resolution="fill_frame",
                height=178,
                width=410,
            )
            try:
                self._camera_viewport_widget.fill_frame = True
                self._camera_viewport_widget.viewport_api.updates_enabled = True
                self._camera_viewport_widget.viewport_api.camera_path = Sdf.Path(GROWTH_CAMERA_PATH)
                self._camera_viewport_widget.viewport_api.fill_frame = True
            except Exception:
                pass
        except Exception as exc:
            with ui.VStack(spacing=4):
                ui.Spacer(height=34)
                ui.Label(
                    "GrowthPhenotypeCamera",
                    height=24,
                    alignment=ui.Alignment.CENTER,
                    style={"color": TEXT_MAIN, "font_size": 16},
                )
                ui.Label(
                    "Embedded viewport unavailable; use Focus Camera for live main viewport.",
                    height=48,
                    alignment=ui.Alignment.CENTER,
                    word_wrap=True,
                    style={"color": TEXT_MUTED},
                )
                ui.Label(str(exc), height=28, alignment=ui.Alignment.CENTER, word_wrap=True, style={"color": ACCENT_RED})

    def _build_rag_trace_window(self):
        self._rag_trace_window = ui.Window(
            RAG_TRACE_TITLE,
            dockPreference=ui.DockPreference.RIGHT,
            width=1180,
            height=460,
            visible=False,
        )
        try:
            self._rag_trace_window.detachable = False
        except Exception:
            pass
        try:
            self._rag_trace_window.deferred_dock_in("Console", ui.DockPolicy.CURRENT_WINDOW_IS_ACTIVE)
        except Exception:
            pass
        try:
            PLANNING_TRACE_DIR.mkdir(parents=True, exist_ok=True)
            (PLANNING_TRACE_DIR / "rag-trace.log").touch(exist_ok=True)
        except Exception as exc:
            print(f"[joon.smartfarm.omniops] rag trace log init skipped: {exc}")

        with self._rag_trace_window.frame:
            with ui.ScrollingFrame(style={"background_color": 0xFF0E1116}):
                with ui.VStack(spacing=4, height=0):
                    with ui.HStack(height=30):
                        ui.Label(
                            "SmartFarm RAG Trace",
                            height=24,
                            style={"color": ACCENT_GREEN, "font_size": 18},
                        )
                        ui.Spacer()
                        ui.Label(
                            f"text log: {PLANNING_TRACE_DIR / 'rag-trace.log'}",
                            width=560,
                            height=22,
                            style={"color": TEXT_MUTED},
                        )
                    ui.Label(
                        "Shows live blueprint API calls, endpoint status, RAG source count, gap factors, candidate scores, and saved JSON trace files.",
                        height=24,
                        word_wrap=True,
                        style={"color": TEXT_MUTED},
                    )
                    ui.Separator(height=4)
                    for _ in range(30):
                        label = ui.Label(
                            "",
                            height=20,
                            word_wrap=True,
                            style={"color": 0xFFB7F7C1, "font_size": 13},
                        )
                        self._rag_trace_labels.append(label)
        self._refresh_rag_trace()

    def _build_blueprint_dag_window(self):
        self._blueprint_dag_window = ui.Window(
            BLUEPRINT_DAG_TITLE,
            dockPreference=ui.DockPreference.RIGHT,
            width=1180,
            height=460,
            visible=False,
        )
        try:
            self._blueprint_dag_window.detachable = False
        except Exception:
            pass
        try:
            self._blueprint_dag_window.deferred_dock_in("Console", ui.DockPolicy.CURRENT_WINDOW_IS_ACTIVE)
        except Exception:
            pass
        with self._blueprint_dag_window.frame:
            with ui.ScrollingFrame(style={"background_color": 0xFF0E1116}):
                self._build_blueprint_dag_panel()
        self._refresh_blueprint_dag()

    def _build_blueprint_dag_panel(self):
        self._blueprint_dag_nodes = {}
        self._blueprint_dag_plan_nodes = []
        self._blueprint_dag_edges = {}
        self._blueprint_dag_summary = {}
        image_path = self._render_blueprint_dag_image()
        with ui.Frame(width=1148, style={"background_color": CARD_BG_DARK, "border_radius": 8, "padding": 10}):
            with ui.VStack(spacing=8, height=0):
                with ui.HStack(height=28):
                    ui.Label("SmartFarm Blueprint DAG / Branch Decision Graph", height=24, style={"color": ACCENT_BLUE, "font_size": 20})
                    ui.Spacer()
                    self._blueprint_dag_summary["run"] = ui.Label("not generated", width=190, style={"color": TEXT_MUTED})
                ui.Label(
                    "Git-branch style visual: main DAG path is acyclic; red feedback edge shows replan/rollback to Generate when a selected branch fails.",
                    height=34,
                    word_wrap=True,
                    style={"color": TEXT_MUTED},
                )
                ui.Separator(height=4)
                try:
                    try:
                        self._blueprint_dag_image = ui.Image(str(image_path), width=1118, height=430)
                    except TypeError:
                        self._blueprint_dag_image = ui.Image(image_url=str(image_path), width=1118, height=430)
                except Exception as exc:
                    self._blueprint_dag_image = None
                    ui.Label(
                        f"Blueprint DAG image preview unavailable: {exc}. PNG saved at {image_path}",
                        height=52,
                        word_wrap=True,
                        style={"color": ACCENT_RED},
                    )
                self._blueprint_dag_summary["image"] = ui.Label(
                    f"graph image: {image_path.name}",
                    height=18,
                    style={"color": TEXT_MUTED, "font_size": 12},
                )

                with ui.HStack(spacing=12, height=168):
                    with ui.VStack(width=215, spacing=10):
                        self._blueprint_dag_nodes["state"] = self._dag_node(
                            "Current State",
                            "sensor + camera + current Twin",
                            "baseline snapshot",
                            ACCENT_GREEN,
                            width=215,
                            height=62,
                        )
                        self._blueprint_dag_edges["state_generate"] = ui.Label(
                            "        |\n        v",
                            height=24,
                            alignment=ui.Alignment.CENTER,
                            style={"color": ACCENT_GREEN, "font_size": 15},
                        )
                        self._blueprint_dag_nodes["generate"] = self._dag_node(
                            "Generate",
                            "Gemma/RAG Blueprint call",
                            "waiting",
                            ACCENT_BLUE,
                            width=215,
                            height=66,
                        )

                    with ui.VStack(width=120, spacing=4):
                        ui.Spacer(height=42)
                        self._blueprint_dag_edges["fanout"] = ui.Label(
                            "FAN-OUT\n=======>\nA / B / C",
                            height=76,
                            alignment=ui.Alignment.CENTER,
                            word_wrap=True,
                            style={"color": ACCENT_BLUE, "font_size": 16},
                        )

                    with ui.VStack(width=342, spacing=8):
                        for plan_name, color in (("Plan A", ACCENT_BLUE), ("Plan B", ACCENT_GREEN), ("Plan C", ACCENT_AMBER)):
                            node = self._dag_node(
                                plan_name,
                                "branch candidate",
                                "score -",
                                color,
                                width=342,
                                height=48,
                                show_bar=True,
                            )
                            self._blueprint_dag_plan_nodes.append(node)

                    with ui.VStack(width=130, spacing=4):
                        ui.Spacer(height=42)
                        self._blueprint_dag_edges["fanout_validate"] = ui.Label(
                            "SIMULATE\n+ SCORE\n=======>",
                            height=82,
                            alignment=ui.Alignment.CENTER,
                            word_wrap=True,
                            style={"color": ACCENT_AMBER, "font_size": 15},
                        )

                    with ui.VStack(width=285, spacing=10):
                        self._blueprint_dag_nodes["validate"] = self._dag_node(
                            "Twin Validation",
                            "simulate + quality gate + ranking",
                            "waiting",
                            ACCENT_AMBER,
                            width=285,
                            height=64,
                            show_bar=True,
                        )
                        self._blueprint_dag_edges["decision"] = ui.Label(
                            "        | best valid branch\n        v",
                            height=24,
                            alignment=ui.Alignment.CENTER,
                            style={"color": ACCENT_GREEN, "font_size": 14},
                        )
                        self._blueprint_dag_nodes["recommended"] = self._dag_node(
                            "Recommended / Apply",
                            "selected best branch",
                            "no recommendation yet",
                            ACCENT_GREEN,
                            width=285,
                            height=64,
                            show_bar=True,
                        )

                with ui.Frame(height=64, style={"background_color": 0xFF25161A, "border_radius": 8, "padding": 8}):
                    with ui.HStack(spacing=10):
                        self._blueprint_dag_nodes["replan"] = self._dag_node(
                            "Replan Loop",
                            "failed / low-confidence / state drift",
                            "trigger not set",
                            ACCENT_RED,
                            width=360,
                            height=58,
                        )
                        self._blueprint_dag_edges["replan_loop"] = ui.Label(
                            "Plan branch misses Twin trajectory or camera state diverges  ======>  return to Generate with updated state",
                            height=54,
                            alignment=ui.Alignment.CENTER,
                            word_wrap=True,
                            style={"color": ACCENT_RED, "font_size": 15},
                        )

                self._blueprint_dag_summary["legend"] = ui.Label(
                    "Legend: A/B/C are branch candidates, not fixed personalities. The red loop is the rollback/replan path when the selected branch becomes invalid.",
                    height=34,
                    word_wrap=True,
                    style={"color": TEXT_MUTED},
                )

    def _dag_node(self, title: str, body: str, footer: str, color: int, *, width: int, height: int = 0, show_bar: bool = False):
        node: Dict[str, Any] = {}
        with ui.Frame(width=width, height=height, style={"background_color": 0xFF111820, "border_radius": 8, "padding": 7}):
            with ui.VStack(spacing=3):
                with ui.HStack(height=18):
                    node["marker"] = ui.Label("[]", width=20, style={"color": color, "font_size": 13})
                    node["title"] = ui.Label(title, height=20, style={"color": TEXT_MAIN, "font_size": 15})
                node["body"] = ui.Label(body, height=32, word_wrap=True, style={"color": TEXT_MUTED, "font_size": 12})
                if show_bar:
                    node["bar"] = ui.ProgressBar(height=7, style={"color": color, "border_radius": 4})
                node["footer"] = ui.Label(footer, height=26, word_wrap=True, style={"color": TEXT_MAIN, "font_size": 12})
        return node

    def _render_blueprint_dag_image(self) -> Path:
        """Render the branch decision graph as a real PNG, not just UI cards.

        The main path is a DAG: State -> Generate -> candidate branches ->
        Twin validation -> Recommended.  The red return line is explicitly a
        feedback/replan edge, analogous to checking out a previous git branch
        after a failed experiment; it is intentionally outside the acyclic
        mainline.
        """
        BLUEPRINT_DAG_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
        self._blueprint_dag_render_seq += 1
        image_path = BLUEPRINT_DAG_IMAGE_DIR / f"blueprint-dag-live-{self._blueprint_dag_render_seq % 4}.png"
        self._blueprint_dag_image_path = image_path
        try:
            from PIL import Image, ImageDraw, ImageFont
        except Exception as exc:
            fallback = BLUEPRINT_DAG_IMAGE_DIR / "blueprint-dag-unavailable.txt"
            fallback.write_text(f"Pillow unavailable for DAG render: {exc}\n", encoding="utf-8")
            return image_path

        width, height = 1120, 430
        image = Image.new("RGB", (width, height), (10, 14, 20))
        draw = ImageDraw.Draw(image)

        def font(size: int, bold: bool = False):
            name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
            for path in (
                f"/usr/share/fonts/truetype/dejavu/{name}",
                f"/usr/share/fonts/truetype/liberation2/{'LiberationSans-Bold.ttf' if bold else 'LiberationSans-Regular.ttf'}",
            ):
                try:
                    return ImageFont.truetype(path, size)
                except Exception:
                    pass
            return ImageFont.load_default()

        title_font = font(17, True)
        label_font = font(13, False)
        small_font = font(11, False)
        tiny_font = font(10, False)
        white = (232, 236, 242)
        muted = (150, 160, 178)
        dark_node = (18, 26, 36)
        border = (60, 72, 90)
        blue = (76, 201, 240)
        green = (128, 237, 153)
        amber = (255, 183, 3)
        red = (255, 92, 92)
        purple = (188, 128, 255)

        rows = self._ordered_plan_rows(include_fallback=False)
        planning_run = self._state.get("planningRun") if isinstance(self._state.get("planningRun"), Mapping) else {}
        rag_advice = self._state.get("ragAdvice") or planning_run.get("ragAdvice") or {}
        criteria = self._generation_criteria()
        sensor = self._state.get("sensor") if isinstance(self._state.get("sensor"), Mapping) else {}
        recommended_id = str(
            planning_run.get("recommendedBlueprintId")
            or (rows[0].get("blueprintId") if rows else "")
            or (rows[0].get("id") if rows else "")
        )
        recommended = next(
            (row for row in rows if str(row.get("blueprintId") or row.get("id") or "") == recommended_id),
            rows[0] if rows else {},
        )

        def text_size(text: str, active_font):
            box = draw.textbbox((0, 0), text, font=active_font)
            return box[2] - box[0], box[3] - box[1]

        def fit_text(text: Any, max_width: int, active_font) -> str:
            safe = self._ui_safe_text(text, "")
            if not safe:
                return "-"
            while safe and text_size(safe, active_font)[0] > max_width:
                safe = safe[:-1]
            return safe.rstrip() + ("..." if str(text).strip() and safe != str(text).strip() else "")

        def wrapped_lines(text: Any, max_width: int, active_font, max_lines: int):
            words = self._ui_safe_text(text, "-").split()
            lines: list[str] = []
            current = ""
            for word in words:
                trial = f"{current} {word}".strip()
                if text_size(trial, active_font)[0] <= max_width:
                    current = trial
                    continue
                if current:
                    lines.append(current)
                current = word
                if len(lines) >= max_lines:
                    break
            if current and len(lines) < max_lines:
                lines.append(current)
            if len(lines) > max_lines:
                lines = lines[:max_lines]
            if len(lines) == max_lines and words:
                lines[-1] = fit_text(lines[-1], max_width, active_font)
            return lines or ["-"]

        def node(
            rect,
            title: str,
            body: str,
            footer: str,
            color,
            score: float | None = None,
            recommended_node: bool = False,
            applied_node: bool = False,
        ):
            x1, y1, x2, y2 = rect
            fill = (20, 30, 42)
            outline = border
            stroke = 2
            if recommended_node:
                fill = (21, 45, 34)
                outline = green
                stroke = 3
            if applied_node:
                fill = (35, 24, 52)
                outline = purple
                stroke = 4
            draw.rounded_rectangle(rect, radius=14, fill=fill, outline=outline, width=stroke)
            draw.rectangle((x1, y1, x1 + 8, y2), fill=color)
            draw.text((x1 + 18, y1 + 10), fit_text(title, x2 - x1 - 32, title_font), fill=white, font=title_font)
            y = y1 + 38
            for line in wrapped_lines(body, x2 - x1 - 28, label_font, 2):
                draw.text((x1 + 18, y), line, fill=muted, font=label_font)
                y += 16
            if score is not None:
                bar_x1, bar_y1, bar_x2, bar_y2 = x1 + 18, y2 - 30, x2 - 18, y2 - 20
                draw.rounded_rectangle((bar_x1, bar_y1, bar_x2, bar_y2), radius=5, fill=(36, 43, 54))
                fill_x = bar_x1 + int(max(0.0, min(1.0, score / 100.0)) * (bar_x2 - bar_x1))
                draw.rounded_rectangle((bar_x1, bar_y1, fill_x, bar_y2), radius=5, fill=color)
            draw.text((x1 + 18, y2 - 17), fit_text(footer, x2 - x1 - 32, tiny_font), fill=white, font=tiny_font)

        def center(rect):
            x1, y1, x2, y2 = rect
            return ((x1 + x2) // 2, (y1 + y2) // 2)

        def arrow(points, color, width_px=4):
            if len(points) < 2:
                return
            draw.line(points, fill=color, width=width_px, joint="curve")
            x1, y1 = points[-2]
            x2, y2 = points[-1]
            dx, dy = x2 - x1, y2 - y1
            length = max((dx * dx + dy * dy) ** 0.5, 0.1)
            ux, uy = dx / length, dy / length
            px, py = -uy, ux
            size = 11
            tip = (x2, y2)
            left = (x2 - ux * size + px * size * 0.55, y2 - uy * size + py * size * 0.55)
            right = (x2 - ux * size - px * size * 0.55, y2 - uy * size - py * size * 0.55)
            draw.polygon([tip, left, right], fill=color)

        # Header.
        draw.text((24, 14), "Blueprint branch graph", fill=white, font=font(22, True))
        draw.text(
            (24, 42),
            "mainline DAG + red replan feedback edge (git-branch style)",
            fill=muted,
            font=label_font,
        )
        run_id = planning_run.get("runId") or "not generated"
        draw.text((900, 42), fit_text(f"run: {run_id}", 190, label_font), fill=muted, font=label_font)

        state_rect = (24, 70, 210, 154)
        generate_rect = (24, 218, 210, 308)
        plan_rects = [(390, 52, 610, 126), (390, 150, 610, 224), (390, 248, 610, 322)]
        validate_rect = (780, 82, 1050, 164)
        recommended_rect = (780, 228, 1050, 312)

        state_body = (
            f"DLI {sensor.get('dli_mol_m2_day', '-')} | RH {sensor.get('humidity_percent', '-')}% | "
            f"CO2 {sensor.get('co2_ppm', '-')}ppm"
        )
        vision = criteria.get("usedVisionState") if isinstance(criteria.get("usedVisionState"), Mapping) else {}
        node(state_rect, "Current Twin State", state_body, f"camera {'attached' if vision.get('attached') else 'not attached'}", green)

        sources = list(rag_advice.get("evidence") or [])
        provider = rag_advice.get("provider") or planning_run.get("source") or "Gemma/RAG"
        status = planning_run.get("gemmaRagStatus") or planning_run.get("source") or "waiting"
        node(generate_rect, "Generate Blueprint", f"{self._planner_status_short(str(status), str(provider))} | RAG src {len(sources)}", "Gemma/RAG + current state", blue)

        arrow([(117, 154), (117, 218)], green)
        draw.text((226, 188), "state snapshot", fill=muted, font=small_font)

        branch_colors = [blue, green, amber]
        for idx, rect in enumerate(plan_rects):
            if idx < len(rows):
                row = rows[idx]
                row_id = str(row.get("blueprintId") or row.get("id") or "")
                score = self._score_value(row)
                branch = row.get("branch") if isinstance(row.get("branch"), Mapping) else {}
                title = self._plan_label(row)
                body = f"{self._format_score(score)} | {self._format_ship_delta(row)} | OpEx {self._format_opex(row)}"
                applied = row_id == str(getattr(self, "_selected_blueprint", ""))
                if applied:
                    footer = "APPLIED NOW"
                elif row_id == recommended_id:
                    footer = "RECOMMENDED"
                else:
                    footer = branch.get("candidateBasis", "branch candidate")
                node(rect, title, body, footer, branch_colors[idx], score, recommended_node=row_id == recommended_id, applied_node=applied)
            else:
                node(rect, f"Plan {chr(ord('A') + idx)}", "branch candidate not generated", "click Generate", branch_colors[idx], 0.0)

        gen_out = (210, 263)
        for idx, rect in enumerate(plan_rects):
            x1, y1, _x2, y2 = rect
            target = (x1, (y1 + y2) // 2)
            bend_x = 300
            arrow([gen_out, (bend_x, gen_out[1]), (bend_x, target[1]), target], branch_colors[idx], 4)
        draw.text((246, 262), "fan-out", fill=blue, font=label_font)

        for idx, rect in enumerate(plan_rects):
            _x1, y1, x2, y2 = rect
            source = (x2, (y1 + y2) // 2)
            target = (validate_rect[0], center(validate_rect)[1])
            bend_x = 690
            arrow([source, (bend_x, source[1]), (bend_x, target[1]), target], branch_colors[idx], 4)
        draw.text((645, 58), "simulate + score", fill=amber, font=label_font)

        validation = criteria.get("twinValidation") if isinstance(criteria.get("twinValidation"), Mapping) else {}
        quality_gate = planning_run.get("qualityGate") if isinstance(planning_run.get("qualityGate"), Mapping) else {}
        repaired = int(self._as_float(quality_gate.get("repairedCount"), 0.0)) if quality_gate else 0
        valid_scores = [self._score_value(row) for row in rows if self._score_value(row) is not None]
        avg_score = sum(valid_scores) / len(valid_scores) if valid_scores else 0.0
        node(
            validate_rect,
            "Twin Validation",
            f"maturity>={validation.get('harvestMaturityThresholdPercent', '-')} yield>={validation.get('minYieldScore', '-')}",
            f"quality gate repaired {repaired}",
            amber,
            avg_score,
        )

        rec_score = self._score_value(recommended) if recommended else None
        rec_title = f"Recommended: {self._plan_label(recommended)}" if recommended else "Recommended"
        rec_body = self._dag_recommended_body(recommended)
        rec_branch = recommended.get("branch") if isinstance(recommended.get("branch"), Mapping) else {}
        node(
            recommended_rect,
            rec_title,
            rec_body,
            rec_branch.get("validationSummary", "waiting for valid branch"),
            green,
            rec_score,
            bool(recommended),
            str(recommended.get("blueprintId") or recommended.get("id") or "") == str(getattr(self, "_selected_blueprint", "")),
        )
        arrow([(center(validate_rect)[0], validate_rect[3]), (center(validate_rect)[0], recommended_rect[1])], green, 5)

        # Red feedback/replan edge: intentionally makes this a decision graph,
        # not a pure DAG, matching the requested git-branch mental model.
        loop_y = 338
        arrow([(915, recommended_rect[3]), (915, loop_y), (116, loop_y), (116, generate_rect[3])], red, 4)
        draw.text((365, loop_y - 18), "replan / rollback if selected branch misses camera or Twin trajectory", fill=red, font=label_font)
        draw.text((24, 328), "DAG mainline", fill=muted, font=tiny_font)
        draw.text((948, 328), "feedback edge", fill=red, font=tiny_font)

        self._draw_generation_selection_lane(draw, width, height, label_font, small_font, tiny_font, white, muted, purple, green, red, blue)

        image.save(image_path)
        return image_path

    def _draw_generation_selection_lane(self, draw, width, height, label_font, small_font, tiny_font, white, muted, purple, green, red, blue):
        history = list(getattr(self, "_blueprint_generation_history", []) or [])
        y = 382
        draw.line([(24, y), (width - 24, y)], fill=(44, 54, 70), width=2)
        draw.text((24, y - 26), "Generate-run selection chain (git branch timeline)", fill=white, font=label_font)
        if not history:
            draw.text(
                (330, y - 24),
                "No Generate yet: Generate creates A/B/C candidates; selecting one links this run to the next Generate.",
                fill=muted,
                font=small_font,
            )
            return

        max_nodes = min(6, len(history))
        visible = history[-max_nodes:]
        start_x = 70
        gap = 170 if max_nodes <= 6 else 140
        node_points = []
        for idx, entry in enumerate(visible):
            x = start_x + idx * gap
            node_points.append((x, y))
            is_last = idx == len(visible) - 1
            selected = bool(entry.get("selectedBlueprintId"))
            color = purple if is_last and selected else green if selected else blue
            draw.ellipse((x - 10, y - 10, x + 10, y + 10), fill=color, outline=(238, 238, 238), width=2)
            run_short = str(entry.get("runId") or f"run-{entry.get('index', idx + 1)}")
            if len(run_short) > 12:
                run_short = run_short[:4] + "..." + run_short[-4:]
            label = str(entry.get("selectedLabel") or "pending")
            score = entry.get("selectedScore")
            score_text = self._format_score(score) if score is not None else "score n/a"
            draw.text((x - 44, y + 16), self._ui_safe_text(run_short, "run"), fill=muted, font=tiny_font)
            draw.text((x - 44, y + 30), self._ui_safe_text(label, "pending"), fill=white, font=small_font)
            draw.text((x - 44, y + 46), self._ui_safe_text(f"{entry.get('time', '-')} | {score_text}", "selection"), fill=muted, font=tiny_font)
            if is_last:
                draw.text((x - 34, y - 30), "CURRENT RUN", fill=color, font=tiny_font)

        for idx in range(len(node_points) - 1):
            x1, y1 = node_points[idx]
            x2, y2 = node_points[idx + 1]
            draw.line([(x1 + 12, y1), (x2 - 12, y2)], fill=purple, width=3)
            draw.polygon([(x2 - 12, y2), (x2 - 24, y2 - 6), (x2 - 24, y2 + 6)], fill=purple)
            prev_label = visible[idx].get("selectedLabel") or "pending"
            next_label = visible[idx + 1].get("selectedLabel") or "pending"
            draw.text(
                (x1 + 30, y1 - 18),
                self._ui_safe_text(f"{prev_label} -> {next_label}", "selection link"),
                fill=purple,
                font=tiny_font,
            )

        if len(history) > max_nodes:
            draw.text((24, y + 58), f"+{len(history) - max_nodes} earlier generate run(s)", fill=muted, font=tiny_font)

    def _set_blueprint_dag_image_source(self, image_path: Path):
        self._set_ui_label(
            self._blueprint_dag_summary.get("image"),
            f"graph image: {image_path.name} | saved {image_path.parent}",
        )
        image = self._blueprint_dag_image
        if image is None:
            return
        url = str(image_path)
        # Different Kit builds expose slightly different image-source attrs.
        for attr in ("source_url", "image_url", "url"):
            try:
                setattr(image, attr, url)
                return
            except Exception:
                pass
        for method_name in ("set_source_url", "set_image_url", "set_url"):
            method = getattr(image, method_name, None)
            if method is None:
                continue
            try:
                method(url)
                return
            except Exception:
                pass

    def _build_strawberry_view_window(self):
        try:
            from pxr import Sdf
            from omni.kit.viewport.window import ViewportWindow

            self._strawberry_view_window = ViewportWindow(
                STRAWBERRY_VIEW_TITLE,
                width=STRAWBERRY_VIEW_WINDOW_WIDTH,
                height=STRAWBERRY_VIEW_WINDOW_HEIGHT,
                visible=False,
                dockPreference=ui.DockPreference.RIGHT,
                dock_tab_bar_visible=True,
            )
            viewport_api = self._strawberry_view_window.viewport_api
            if viewport_api:
                viewport_api.camera_path = Sdf.Path(GROWTH_CAMERA_PATH)
                viewport_api.updates_enabled = True
                viewport_api.fill_frame = True
        except Exception as exc:
            self._strawberry_view_window = ui.Window(
                STRAWBERRY_VIEW_TITLE,
                width=STRAWBERRY_VIEW_WINDOW_WIDTH,
                height=STRAWBERRY_VIEW_WINDOW_HEIGHT,
                visible=False,
                dockPreference=ui.DockPreference.RIGHT,
            )
            with self._strawberry_view_window.frame:
                with ui.VStack(spacing=8, style={"background_color": PANEL_BG}):
                    ui.Spacer(height=24)
                    ui.Label(
                        "Live strawberry viewport unavailable",
                        height=24,
                        alignment=ui.Alignment.CENTER,
                        style={"color": TEXT_MAIN},
                    )
                    ui.Label(
                        str(exc),
                        height=90,
                        alignment=ui.Alignment.CENTER,
                        word_wrap=True,
                        style={"color": ACCENT_RED},
                    )

    def _build_sensor_graphs(self):
        for key, title, unit, scale_min, scale_max, color in SENSOR_SERIES:
            current = float(self._state["sensor"].get(key, scale_min))
            self._sensor_history[key] = [current] * SENSOR_HISTORY_LEN
            with ui.VStack(spacing=3, height=0):
                with ui.HStack(height=20):
                    ui.Label(title, width=132)
                    value_label = ui.Label(self._format_sensor_value(key, current, unit), word_wrap=True)
                    self._sensor_value_labels[key] = value_label
                plot = ui.Plot(
                    ui.Type.LINE,
                    scale_min,
                    scale_max,
                    *self._sensor_history[key],
                    height=48,
                    style={"color": color, "background_color": 0xFF1F2328, "padding": 2},
                )
                self._sensor_plots[key] = plot

    def _build_actuator_controls(self):
        actuator = self._state["actuator"]
        self._water_valve_open = bool(actuator.get("water_valve_open", False))
        for key, title, unit, minimum, maximum in ACTUATOR_CONTROLS:
            value = int(round(float(actuator.get(key, minimum))))
            with ui.VStack(spacing=3, height=0):
                with ui.HStack(height=20):
                    ui.Label(title, width=160)
                    value_label = ui.Label(f"{value} {unit}", word_wrap=True)
                    self._actuator_value_labels[key] = value_label
                slider = ui.IntSlider(min=minimum, max=maximum, height=22, style={"draw_mode": ui.SliderDrawMode.FILLED})
                slider.model.set_value(value)
                slider.model.add_value_changed_fn(lambda model, k=key, u=unit: self._on_actuator_model_changed(k, u, model))
                self._actuator_models[key] = slider.model
        with ui.HStack(spacing=8, height=32):
            self._labels["water_valve"] = ui.Label(self._water_valve_text(), width=180)
            ui.Button("Toggle Valve", clicked_fn=self._toggle_water_valve)
        with ui.HStack(spacing=8, height=32):
            ui.Button("Apply Manual Controls", clicked_fn=self._apply_manual_actuators)
            ui.Button("Sync From Twin", clicked_fn=self._load_state_from_api)

    def _growth_status_card(self, key: str, title: str, accent: int):
        with ui.Frame(width=108, height=58, style={"background_color": CARD_BG_DARK, "border_radius": 8, "padding": 7}):
            with ui.VStack(spacing=3):
                ui.Label(title, height=16, style={"color": TEXT_MUTED, "font_size": 12})
                self._labels[key] = ui.Label("-", height=22, alignment=ui.Alignment.CENTER, style={"color": TEXT_MAIN, "font_size": 15})
                self._growth_status_bars[key] = ui.ProgressBar(height=5, style={"color": accent, "border_radius": 4})

    def _dashboard_card(self, width: int, height: int = 0):
        return ui.Frame(
            width=width,
            height=height,
            style={"background_color": CARD_BG, "border_radius": 8, "padding": 8},
        )

    def _metric_card(self, key: str, title: str, value: str, *, width: int, accent: int):
        with self._dashboard_card(width=width, height=70):
            with ui.VStack(spacing=3):
                ui.Label(title, height=18, style={"color": TEXT_MUTED, "font_size": 13})
                label = ui.Label(value, height=25, word_wrap=True, style={"color": TEXT_MAIN, "font_size": 17})
                bar = ui.ProgressBar(height=5, style={"color": accent, "border_radius": 4})
                self._evidence_summary_labels[key] = label
                self._evidence_summary_bars[key] = bar

    def _build_generation_criteria_card(self):
        with ui.Frame(width=300, height=166, style={"background_color": CARD_BG_DARK, "border_radius": 8, "padding": 8}):
            with ui.VStack(spacing=2):
                ui.Label("Generate input basis", height=18, style={"color": ACCENT_AMBER, "font_size": 14})
                for key, title in (
                    ("sensor", "Sensor"),
                    ("vision", "Vision"),
                    ("rag", "RAG docs"),
                    ("validation", "Twin check"),
                    ("weights", "Formula"),
                ):
                    self._criteria_labels[key] = self._compact_key_value(title, "-")

    def _build_score_weight_card(self):
        with ui.Frame(width=286, height=218, style={"background_color": CARD_BG_DARK, "border_radius": 8, "padding": 8}):
            with ui.VStack(spacing=3):
                ui.Label("Score / objective weights", height=18, style={"color": ACCENT_GREEN, "font_size": 14})
                for key, title, color in (
                    ("earliestShipment", "Ship earlier", ACCENT_BLUE),
                    ("yield", "Yield", ACCENT_GREEN),
                    ("diseaseControl", "Disease ctrl", ACCENT_AMBER),
                    ("opex", "OpEx", TEXT_MUTED),
                    ("actuatorSafety", "Safety", ACCENT_RED),
                ):
                    row = {}
                    with ui.HStack(spacing=5, height=26):
                        row["name"] = ui.Label(title, width=82, style={"color": TEXT_MUTED})
                        row["bar"] = ui.ProgressBar(width=112, height=9, style={"color": color, "border_radius": 4})
                        row["value"] = ui.Label("-", style={"color": TEXT_MAIN})
                    self._score_weight_rows[key] = row
                self._criteria_labels["score_basis"] = ui.Label(
                    "Score = ship earlier + yield + cost saving - OpEx - disease - safety risk + context.",
                    height=48,
                    word_wrap=True,
                    style={"color": TEXT_MUTED, "font_size": 12},
                )

    def _build_feedback_response_card(self):
        with ui.Frame(width=286, height=166, style={"background_color": CARD_BG_DARK, "border_radius": 8, "padding": 8}):
            with ui.VStack(spacing=3):
                ui.Label("Feedback response map", height=18, style={"color": ACCENT_BLUE, "font_size": 14})
                for key, text in (
                    ("basis", "1. Generate basis visible"),
                    ("branch", "2. Plan A/B/C are branch candidates"),
                    ("graph", "3. Decision graph compares trajectories"),
                    ("replan", "4. Replan trigger explains rollback path"),
                    ("weights", "5. Score weights shown explicitly"),
                ):
                    self._feedback_response_labels[key] = ui.Label(
                        f"ON - {text}",
                        height=22,
                        word_wrap=True,
                        style={"color": TEXT_MAIN},
                    )

    def _build_decision_graph_card(self):
        with ui.Frame(width=604, height=226, style={"background_color": CARD_BG_DARK, "border_radius": 8, "padding": 8}):
            with ui.VStack(spacing=4):
                with ui.HStack(height=20):
                    ui.Label("Blueprint Trajectory Preview - readiness over time", height=18, style={"color": ACCENT_BLUE, "font_size": 15})
                    ui.Spacer()
                    ui.Label("sparkline + bars", width=128, style={"color": TEXT_MUTED})
                with ui.HStack(height=18):
                    ui.Label("Branch", width=56, style={"color": TEXT_MUTED})
                    ui.Label("Future trajectory", width=296, style={"color": TEXT_MUTED})
                    ui.Label("Score", width=82, style={"color": TEXT_MUTED})
                    ui.Label("Outcome metrics", style={"color": TEXT_MUTED})
                for color in (ACCENT_BLUE, ACCENT_GREEN, ACCENT_AMBER):
                    self._decision_graph_rows.append(self._decision_graph_row(color))

    def _decision_graph_row(self, color: int):
        row = {}
        with ui.Frame(height=58, style={"background_color": 0xFF111820, "border_radius": 6, "padding": 6}):
            with ui.HStack(spacing=8):
                row["name"] = ui.Label("-", width=56, style={"color": TEXT_MAIN, "font_size": 14})
                with ui.VStack(width=166, spacing=2):
                    row["timeline"] = ui.Label("Generate to draw trajectory", height=18, style={"color": TEXT_MAIN})
                    with ui.HStack(spacing=3, height=12):
                        bars = []
                        for _ in range(5):
                            bar = ui.ProgressBar(width=30, height=8, style={"color": color, "border_radius": 4})
                            bars.append(bar)
                        row["milestone_bars"] = bars
                row["plot"] = ui.Plot(
                    ui.Type.LINE,
                    0.0,
                    100.0,
                    *([0.0] * 8),
                    width=110,
                    height=42,
                    style={"color": color, "background_color": 0xFF0B1016, "padding": 2},
                )
                with ui.VStack(width=76, spacing=2):
                    row["score"] = ui.Label("score -", height=17, style={"color": TEXT_MAIN})
                    row["score_bar"] = ui.ProgressBar(height=8, style={"color": color, "border_radius": 4})
                    row["rank"] = ui.Label("-", height=15, style={"color": TEXT_MUTED, "font_size": 12})
                with ui.VStack(spacing=2):
                    row["ready"] = ui.Label("ready -", height=17, style={"color": TEXT_MAIN})
                    row["disease"] = ui.Label("disease -", height=17, style={"color": TEXT_MUTED})
                    row["opex"] = ui.Label("OpEx -", height=17, style={"color": TEXT_MUTED})
        return row

    def _timeline_row(self):
        row = {}
        with ui.VStack(spacing=2, height=48):
            with ui.HStack(height=18):
                row["day"] = ui.Label("-", width=50, style={"color": TEXT_MAIN})
                row["maturity"] = ui.Label("-", width=86, style={"color": TEXT_MAIN})
                row["risk"] = ui.Label("-", width=100, style={"color": TEXT_MUTED})
                row["yield"] = ui.Label("-", style={"color": TEXT_MUTED})
            row["bar"] = ui.ProgressBar(height=7, style={"color": ACCENT_GREEN, "border_radius": 4})
            row["detail"] = ui.Label("-", height=18, word_wrap=True, style={"color": TEXT_MUTED})
        return row

    def _score_row(self):
        row = {}
        with ui.Frame(width=286, height=210, style={"background_color": CARD_BG_DARK, "border_radius": 8, "padding": 8}):
            with ui.VStack(spacing=3):
                with ui.HStack(height=22):
                    row["marker"] = ui.Label("-", width=18, style={"color": ACCENT_AMBER})
                    row["name"] = ui.Label("-", width=70, word_wrap=True, style={"color": TEXT_MAIN, "font_size": 15})
                    row["score"] = ui.Label("-", width=70, alignment=ui.Alignment.RIGHT, style={"color": TEXT_MAIN})
                    ui.Spacer(width=6)
                    row["ship"] = ui.Label("-", style={"color": TEXT_MUTED})
                row["bar"] = ui.ProgressBar(height=6, style={"color": ACCENT_AMBER, "border_radius": 4})
                row["intent"] = ui.Label("-", height=34, word_wrap=True, style={"color": TEXT_MAIN})
                row["controls"] = ui.Label("-", height=28, word_wrap=True, style={"color": TEXT_MUTED})
                row["tradeoff"] = ui.Label("-", height=42, word_wrap=True, style={"color": TEXT_MUTED})
                row["basis"] = ui.Label("-", height=52, word_wrap=True, style={"color": TEXT_MUTED, "font_size": 12})
        return row

    def _compact_key_value(self, title: str, value: str):
        with ui.HStack(height=22):
            ui.Label(title, width=78, style={"color": TEXT_MUTED})
            label = ui.Label(value, word_wrap=True, style={"color": TEXT_MAIN})
        return label

    def _row(self, label: str, value: str):
        with ui.HStack(height=24):
            ui.Label(label, width=150)
            value_label = ui.Label(value, word_wrap=True)
        return value_label

    def _set_status(self, text: str):
        self._labels["status"].text = text
        self._logs.append(f"{datetime.now().strftime('%H:%M:%S')} · {text}")
        self._logs = self._logs[-8:]
        self._refresh_logs()

    def _refresh_ui(self):
        sensor = self._state["sensor"]
        actuator = self._state["actuator"]
        crop = self._state["crop"]
        kpi = self._state["kpi"]
        self._labels["scene"].text = self._state.get("smartFarmPath", SMART_FARM_PATH)
        self._labels["mode"].text = self._state.get("sceneMode", "fallback")
        self._labels["active"].text = self._state.get("blueprintId", "baseline")
        self._labels["health"].text = f"{kpi['healthScore']}/100"
        self._labels["maturity"].text = f"{kpi['fruitMaturityPercent']}%"
        self._labels["readiness"].text = f"{kpi['harvestReadinessPercent']}%"
        self._labels["ship"].text = str(kpi["expectedShip"])
        self._labels["risk"].text = str(kpi["diseaseRisk"])
        self._labels["limiter"].text = str(kpi["mainLimitingFactor"])
        self._set_progress_bar(self._growth_status_bars.get("health"), self._as_float(kpi.get("healthScore"), 0.0) / 100.0)
        self._set_progress_bar(self._growth_status_bars.get("maturity"), self._as_float(kpi.get("fruitMaturityPercent"), 0.0) / 100.0)
        self._set_progress_bar(self._growth_status_bars.get("readiness"), self._as_float(kpi.get("harvestReadinessPercent"), 0.0) / 100.0)
        self._record_sensor_sample(sensor)
        self._refresh_sensor_graphs(sensor)
        self._sync_actuator_controls(actuator)
        self._refresh_evidence_summary()
        self._refresh_trends()
        self._refresh_generation_criteria()
        self._refresh_decision_graph()
        self._refresh_blueprint_dag()
        self._refresh_scores()
        self._refresh_apply_buttons()
        self._refresh_vision()
        self._refresh_logs()

    def _refresh_evidence_summary(self):
        ranked = self._state.get("ranked") or []
        recommended = ranked[0] if ranked else {}
        active_id = str(self._state.get("blueprintId", "baseline"))
        active_name = self._state.get("name") or BLUEPRINTS.get(active_id, {}).get("name", active_id)
        kpi = self._state.get("kpi") or {}
        planning_run = self._state.get("planningRun") or {}
        rag_advice = self._state.get("ragAdvice") or planning_run.get("ragAdvice") or {}

        recommended_id = str(recommended.get("blueprintId") or recommended.get("id") or "")
        recommended_name = recommended.get("name", recommended.get("blueprintName", "-"))
        recommended_score = self._score_value(recommended)
        self._set_ui_label(
            self._evidence_summary_labels.get("recommended"),
            (
                f"{self._short_plan_name(recommended_name, recommended_id)} · score {recommended_score:.0f}/100"
                if recommended_score is not None
                else self._short_plan_name(recommended_name, recommended_id)
            ),
        )
        self._set_ui_label(
            self._evidence_summary_labels.get("applied"),
            f"{self._short_plan_name(active_name, active_id)} · health {kpi.get('healthScore', '-')}/100",
        )
        self._set_ui_label(self._evidence_summary_labels.get("health"), f"{kpi.get('healthScore', '-')}/100")
        self._set_ui_label(self._evidence_summary_labels.get("maturity"), f"{kpi.get('fruitMaturityPercent', '-')}%")
        self._set_ui_label(self._evidence_summary_labels.get("risk"), self._risk_chip(kpi.get("diseaseRisk", "-")))

        assessment = self._latest_vision_assessment
        if assessment:
            vision_health = self._as_float(assessment.get("healthScore"), 0.0)
            growth_progress = self._as_float(
                assessment.get("growthProgressPercent", assessment.get("harvestReadinessPercent", 0.0)),
                0.0,
            )
            self._set_ui_label(
                self._evidence_summary_labels.get("vision"),
                f"{int(round(growth_progress))}% growth · {self._vision_provider_label(assessment)}",
            )
            self._set_progress_bar(self._evidence_summary_bars.get("vision"), growth_progress / 100.0)
        else:
            self._set_ui_label(self._evidence_summary_labels.get("vision"), "Not captured")
            self._set_progress_bar(self._evidence_summary_bars.get("vision"), 0.0)

        if planning_run:
            candidates = list(planning_run.get("candidates") or [])
            sources = list(rag_advice.get("evidence") or [])
            status = str(planning_run.get("gemmaRagStatus") or planning_run.get("source") or "planning-run")
            provider = str(rag_advice.get("provider") or planning_run.get("source") or "Gemma/RAG")
            self._set_ui_label(
                self._evidence_summary_labels.get("ai_run"),
                f"{self._planner_status_short(status, provider)} · {len(candidates)} plans · {len(sources)} src",
            )
            self._set_progress_bar(self._evidence_summary_bars.get("ai_run"), self._planner_status_ratio(status, provider))
        else:
            self._set_ui_label(self._evidence_summary_labels.get("ai_run"), "Generate to prove AI")
            self._set_progress_bar(self._evidence_summary_bars.get("ai_run"), 0.0)

        self._set_progress_bar(
            self._evidence_summary_bars.get("recommended"),
            (recommended_score or 0.0) / 100.0,
        )
        self._set_progress_bar(
            self._evidence_summary_bars.get("applied"),
            self._as_float(kpi.get("healthScore"), 0.0) / 100.0,
        )
        self._set_progress_bar(
            self._evidence_summary_bars.get("health"),
            self._as_float(kpi.get("healthScore"), 0.0) / 100.0,
        )
        self._set_progress_bar(
            self._evidence_summary_bars.get("maturity"),
            self._as_float(kpi.get("fruitMaturityPercent"), 0.0) / 100.0,
        )
        self._set_progress_bar(
            self._evidence_summary_bars.get("risk"),
            self._risk_ratio(kpi.get("diseaseRisk", "-")),
        )

    def _refresh_trends(self):
        evidence = self._state.get("evidence") or []
        timeline = self._state.get("timeline") or []
        for idx, label in enumerate(self._trend_labels):
            label.text = f"• {evidence[idx]}" if idx < len(evidence) else ""

        base_day = int(timeline[0].get("day", 0)) if timeline else 0
        for idx, widgets in enumerate(self._timeline_rows):
            if idx >= len(timeline):
                self._set_ui_label(widgets.get("day"), "")
                self._set_ui_label(widgets.get("maturity"), "")
                self._set_ui_label(widgets.get("risk"), "")
                self._set_ui_label(widgets.get("yield"), "")
                self._set_ui_label(widgets.get("detail"), "")
                self._set_progress_bar(widgets.get("bar"), 0.0)
                continue
            row = timeline[idx]
            crop = row.get("crop", {})
            sensor = row.get("sensor", {})
            day = int(row.get("day", base_day))
            offset = max(0, day - base_day)
            maturity = int(round(self._as_float(crop.get("fruitMaturity"), 0.0) * 100.0))
            disease = int(round(self._as_float(crop.get("diseasePressure"), 0.0) * 100.0))
            yield_score = self._as_float(crop.get("estimatedYield"), 0.0)
            dli = self._as_float(sensor.get("dli_mol_m2_day"), 0.0)
            self._set_ui_label(widgets.get("day"), f"D+{offset}")
            self._set_ui_label(widgets.get("maturity"), f"{maturity}% mature")
            self._set_ui_label(widgets.get("risk"), f"{disease}% disease")
            self._set_ui_label(widgets.get("yield"), f"yield {yield_score:.1f}")
            self._set_ui_label(widgets.get("detail"), f"DLI {dli:.1f} | stage {sensor.get('crop_stage', '-')}")
            self._set_progress_bar(widgets.get("bar"), maturity / 100.0)

    def _refresh_generation_criteria(self):
        criteria = self._generation_criteria()
        if not self._criteria_labels:
            return
        if not criteria:
            sensor = self._state.get("sensor") or {}
            self._refresh_score_weight_rows({})
            self._set_ui_label(self._criteria_labels.get("weights"), "Generate to show score formula")
            self._set_ui_label(
                self._criteria_labels.get("sensor"),
                f"DLI {sensor.get('dli_mol_m2_day', '-')} | RH {sensor.get('humidity_percent', '-')}% | CO2 {sensor.get('co2_ppm', '-')}ppm",
            )
            self._set_ui_label(self._criteria_labels.get("vision"), "No capture attached")
            self._set_ui_label(self._criteria_labels.get("rag"), "0 docs | not called")
            self._set_ui_label(self._criteria_labels.get("validation"), "Waiting for Twin simulation")
            return

        weights = criteria.get("objectiveWeights") if isinstance(criteria.get("objectiveWeights"), Mapping) else {}
        self._refresh_score_weight_rows(weights)
        formula = criteria.get("scoreFormula") if isinstance(criteria.get("scoreFormula"), Mapping) else {}
        active_formula = self._ui_safe_text(formula.get("planningRunCandidateFormula"), "score formula unavailable")
        self._set_ui_label(self._criteria_labels.get("weights"), active_formula)

        sensor = criteria.get("usedSensorState") if isinstance(criteria.get("usedSensorState"), Mapping) else {}
        self._set_ui_label(
            self._criteria_labels.get("sensor"),
            f"DLI {self._first_present(sensor, 'dliMolM2Day', 'dli_mol_m2_day', default='-')} | "
            f"RH {self._first_present(sensor, 'humidityPercent', 'humidity_percent', default='-')}% | "
            f"CO2 {self._first_present(sensor, 'co2Ppm', 'co2_ppm', default='-')}ppm",
        )

        vision = criteria.get("usedVisionState") if isinstance(criteria.get("usedVisionState"), Mapping) else {}
        if vision.get("attached"):
            growth = self._first_present(vision, "growthProgressPercent", "harvestReadinessPercent", default="-")
            self._set_ui_label(
                self._criteria_labels.get("vision"),
                f"{growth}% growth | {vision.get('diseaseRisk', '-')} | {vision.get('provider', '-')}",
            )
        else:
            self._set_ui_label(self._criteria_labels.get("vision"), "No camera capture attached")

        rag_docs = int(self._as_float(criteria.get("ragDocsCount"), 0.0))
        rag_provider = criteria.get("ragProvider") or (self._state.get("ragAdvice") or {}).get("provider") or "-"
        self._set_ui_label(self._criteria_labels.get("rag"), f"{rag_docs} docs | {rag_provider}")

        validation = criteria.get("twinValidation") if isinstance(criteria.get("twinValidation"), Mapping) else {}
        self._set_ui_label(
            self._criteria_labels.get("validation"),
            f"maturity >={validation.get('harvestMaturityThresholdPercent', '-')}% | "
            f"yield >={validation.get('minYieldScore', '-')} | "
            f"disease <={validation.get('diseasePressureLimitPercent', '-')}%",
        )

    def _refresh_score_weight_rows(self, weights: Mapping[str, Any]):
        labels = {
            "earliestShipment": "Ship earlier",
            "yield": "Yield",
            "diseaseControl": "Disease ctrl",
            "opex": "OpEx",
            "actuatorSafety": "Safety",
        }
        for key, row in self._score_weight_rows.items():
            weight = self._as_float(weights.get(key), 0.0) if isinstance(weights, Mapping) else 0.0
            self._set_ui_label(row.get("name"), labels.get(key, key))
            self._set_ui_label(row.get("value"), f"{weight * 100:.0f}%")
            self._set_progress_bar(row.get("bar"), weight)
        if self._score_weight_rows:
            if weights:
                weight_text = (
                    f"Ship {self._as_float(weights.get('earliestShipment'), 0.0) * 100:.0f}, "
                    f"Yield {self._as_float(weights.get('yield'), 0.0) * 100:.0f}, "
                    f"Disease {self._as_float(weights.get('diseaseControl'), 0.0) * 100:.0f}, "
                    f"OpEx {self._as_float(weights.get('opex'), 0.0) * 100:.0f}, "
                    f"Safety {self._as_float(weights.get('actuatorSafety'), 0.0) * 100:.0f}"
                )
                self._set_ui_label(
                    self._criteria_labels.get("score_basis"),
                    f"Objective weights: {weight_text}. Candidate score also shows raw Twin penalties.",
                )
            else:
                self._set_ui_label(
                    self._criteria_labels.get("score_basis"),
                    "Generate to load objective weights and candidate score basis.",
                )

    def _refresh_decision_graph(self):
        rows = self._ordered_plan_rows(include_fallback=False)
        for idx, widgets in enumerate(self._decision_graph_rows):
            if idx >= len(rows):
                label = PLAN_BUTTON_LABELS[idx] if idx < len(PLAN_BUTTON_LABELS) else "Branch"
                self._set_ui_label(widgets.get("name"), label)
                self._set_ui_label(widgets.get("score"), "score -")
                self._set_ui_label(widgets.get("timeline"), "Generate to draw trajectory")
                self._set_ui_label(widgets.get("rank"), "waiting")
                self._set_ui_label(widgets.get("ready"), "ready -")
                self._set_ui_label(widgets.get("disease"), "disease -")
                self._set_ui_label(widgets.get("opex"), "OpEx -")
                self._set_plot_data(widgets.get("plot"), [0.0] * 8)
                self._set_progress_bar(widgets.get("score_bar"), 0.0)
                for bar in widgets.get("milestone_bars", []):
                    self._set_progress_bar(bar, 0.0)
                continue
            row = rows[idx]
            trajectory = self._trajectory_points(row)
            values = [self._trajectory_readiness(point) for point in trajectory] or [0.0]
            final_point = trajectory[-1] if trajectory else {}
            score = self._score_value(row)
            ready = self._trajectory_readiness(final_point)
            disease = self._first_present(final_point, "diseasePressurePercent", default=None)
            if disease is None:
                disease = self._risk_ratio(row.get("diseaseRisk", "-")) * 100.0
            milestones = self._trajectory_milestones(row, trajectory, count=5)
            self._set_ui_label(widgets.get("name"), self._plan_label(row))
            self._set_ui_label(widgets.get("score"), self._format_score(score))
            self._set_ui_label(widgets.get("timeline"), self._trajectory_summary(row, milestones))
            self._set_ui_label(widgets.get("rank"), self._graph_branch_note(row))
            self._set_ui_label(widgets.get("ready"), f"ready {ready:.0f}%")
            self._set_ui_label(widgets.get("disease"), f"disease {self._as_float(disease, 0.0):.0f}%")
            self._set_ui_label(widgets.get("opex"), f"OpEx {self._format_opex(row)}")
            self._set_plot_data(widgets.get("plot"), values)
            self._set_progress_bar(widgets.get("score_bar"), (score or 0.0) / 100.0)
            for bar, point in zip(widgets.get("milestone_bars", []), milestones):
                self._set_progress_bar(bar, self._trajectory_readiness(point) / 100.0)

    def _refresh_blueprint_dag(self):
        if not self._blueprint_dag_nodes:
            return
        image_path = self._render_blueprint_dag_image()
        self._set_blueprint_dag_image_source(image_path)
        planning_run = self._state.get("planningRun") if isinstance(self._state.get("planningRun"), Mapping) else {}
        rag_advice = self._state.get("ragAdvice") or planning_run.get("ragAdvice") or {}
        criteria = self._generation_criteria()
        rows = self._ordered_plan_rows(include_fallback=False)
        recommended_id = str(
            planning_run.get("recommendedBlueprintId")
            or (rows[0].get("blueprintId") if rows else "")
            or (rows[0].get("id") if rows else "")
        )

        run_id = planning_run.get("runId") or "-"
        self._set_ui_label(self._blueprint_dag_summary.get("run"), f"run {run_id}" if run_id != "-" else "not generated")

        sensor = self._state.get("sensor") if isinstance(self._state.get("sensor"), Mapping) else {}
        vision = criteria.get("usedVisionState") if isinstance(criteria.get("usedVisionState"), Mapping) else {}
        self._set_dag_node(
            "state",
            title="Current State",
            body=(
                f"DLI {sensor.get('dli_mol_m2_day', '-')} | RH {sensor.get('humidity_percent', '-')}% | "
                f"CO2 {sensor.get('co2_ppm', '-')}ppm"
            ),
            footer=f"camera {'attached' if vision.get('attached') else 'not attached'} | baseline is fixed current twin",
        )

        provider = rag_advice.get("provider") or planning_run.get("source") or "Gemma/RAG"
        status = planning_run.get("gemmaRagStatus") or planning_run.get("source") or "waiting"
        sources = list(rag_advice.get("evidence") or [])
        weights = criteria.get("objectiveWeights") if isinstance(criteria.get("objectiveWeights"), Mapping) else {}
        self._set_dag_node(
            "generate",
            title="Generate",
            body=f"{self._planner_status_short(str(status), str(provider))} | sources {len(sources)}",
            footer=(
                f"weights ship {self._as_float(weights.get('earliestShipment'), 0.0) * 100:.0f}% "
                f"yield {self._as_float(weights.get('yield'), 0.0) * 100:.0f}%"
                if weights
                else "waiting for objective weights"
            ),
        )

        for idx, node in enumerate(self._blueprint_dag_plan_nodes):
            if idx >= len(rows):
                label = PLAN_BUTTON_LABELS[idx] if idx < len(PLAN_BUTTON_LABELS) else f"Plan {idx + 1}"
                self._set_dag_node_widget(
                    node,
                    title=label,
                    body="branch candidate not generated yet",
                    footer="click Generate Gemma/RAG Blueprints",
                    progress=0.0,
                )
                continue
            row = rows[idx]
            row_id = str(row.get("blueprintId") or row.get("id") or "")
            score = self._score_value(row)
            branch = row.get("branch") if isinstance(row.get("branch"), Mapping) else {}
            marker = "R" if row_id == recommended_id else "B"
            self._set_ui_label(node.get("marker"), f"[{marker}]")
            self._set_dag_node_widget(
                node,
                title=self._plan_label(row),
                body=self._dag_plan_body(row),
                footer=(
                    f"{self._format_score(score)} | {self._format_ship_delta(row)} | "
                    f"{'repair' if (row.get('qualityGate') or {}).get('status') == 'repaired' else 'validate'}"
                    if isinstance(row.get("qualityGate"), Mapping)
                    else f"{self._format_score(score)} | {self._format_ship_delta(row)} | {branch.get('candidateBasis', 'branch')}"
                ),
                progress=(score or 0.0) / 100.0,
            )

        validation = criteria.get("twinValidation") if isinstance(criteria.get("twinValidation"), Mapping) else {}
        quality_gate = planning_run.get("qualityGate") if isinstance(planning_run.get("qualityGate"), Mapping) else {}
        valid_scores = [self._score_value(row) for row in rows if self._score_value(row) is not None]
        avg_score = sum(valid_scores) / len(valid_scores) if valid_scores else 0.0
        repaired = int(self._as_float(quality_gate.get("repairedCount"), 0.0)) if quality_gate else 0
        self._set_dag_node(
            "validate",
            title="Twin Validation",
            body=(
                f"floor maturity>={validation.get('harvestMaturityThresholdPercent', '-')} "
                f"yield>={validation.get('minYieldScore', '-')}"
            ),
            footer=f"disease<={validation.get('diseasePressureLimitPercent', '-')} | repaired {repaired}",
            progress=avg_score / 100.0,
        )

        trigger = self._first_replan_trigger(rows, criteria)
        self._set_dag_node(
            "replan",
            title="Replan Loop",
            body="if selected branch misses trajectory",
            footer=trigger,
        )

        recommended = next(
            (row for row in rows if str(row.get("blueprintId") or row.get("id") or "") == recommended_id),
            rows[0] if rows else {},
        )
        rec_score = self._score_value(recommended) if recommended else None
        branch = recommended.get("branch") if isinstance(recommended.get("branch"), Mapping) else {}
        self._set_dag_node(
            "recommended",
            title=f"Recommended: {self._plan_label(recommended) if recommended else '-'}",
            body=self._dag_recommended_body(recommended),
            footer=branch.get("validationSummary") or "Generate to select a validated branch.",
            progress=(rec_score or 0.0) / 100.0,
        )

        self._set_ui_label(
            self._blueprint_dag_edges.get("state_generate"),
            "        |\n        v",
        )
        self._set_ui_label(
            self._blueprint_dag_edges.get("fanout"),
            f"FAN-OUT\n=======>\n{len(rows) or 3} branches",
        )
        self._set_ui_label(
            self._blueprint_dag_edges.get("fanout_validate"),
            "SIMULATE\n+ SCORE\n=======>",
        )
        self._set_ui_label(
            self._blueprint_dag_edges.get("decision"),
            f"        | {self._plan_label(recommended) if recommended else 'best valid branch'}\n        v",
        )
        self._set_ui_label(
            self._blueprint_dag_edges.get("replan_loop"),
            "FAILED / DRIFT  ======>  return to Generate with updated sensor + camera + RAG state",
        )

    def _set_dag_node(self, key: str, *, title: str | None = None, body: str | None = None, footer: str | None = None, progress: float | None = None):
        self._set_dag_node_widget(self._blueprint_dag_nodes.get(key), title=title, body=body, footer=footer, progress=progress)

    def _set_dag_node_widget(self, node, *, title: str | None = None, body: str | None = None, footer: str | None = None, progress: float | None = None):
        if not isinstance(node, Mapping):
            return
        if title is not None:
            self._set_ui_label(node.get("title"), self._truncate_ui(title, 42))
        if body is not None:
            self._set_ui_label(node.get("body"), self._truncate_ui(body, 92))
        if footer is not None:
            self._set_ui_label(node.get("footer"), self._truncate_ui(footer, 96))
        if progress is not None:
            self._set_progress_bar(node.get("bar"), progress)

    def _dag_plan_body(self, row: Mapping[str, Any]) -> str:
        branch = row.get("branch") if isinstance(row.get("branch"), Mapping) else {}
        if branch.get("stateDrivers"):
            drivers = branch.get("stateDrivers") or []
            return "drivers: " + ", ".join(str(item) for item in drivers[:3])
        actuator = row.get("actuatorTarget") if isinstance(row.get("actuatorTarget"), Mapping) else {}
        if actuator:
            return (
                f"LED {self._first_present(actuator, 'ledIntensityPercent', default='-')} | "
                f"Fan {self._first_present(actuator, 'fanDutyPercent', default='-')} | "
                f"CO2 {self._first_present(actuator, 'co2Ppm', default='-')}"
            )
        return self._plan_provider_label(row)

    def _dag_recommended_body(self, row: Mapping[str, Any]) -> str:
        if not row:
            return "No branch has been generated yet."
        return (
            f"{self._format_score(self._score_value(row))} | {self._format_ship_delta(row)} | "
            f"{self._format_opex(row)} OpEx"
        )

    def _first_replan_trigger(self, rows: list[Mapping[str, Any]], criteria: Mapping[str, Any]) -> str:
        for row in rows:
            branch = row.get("branch") if isinstance(row.get("branch"), Mapping) else {}
            trigger = self._ui_safe_text(branch.get("replanTrigger"), "")
            if trigger:
                return trigger
        policy = criteria.get("branchingPolicy") if isinstance(criteria.get("branchingPolicy"), Mapping) else {}
        triggers = policy.get("replanTriggers") if isinstance(policy.get("replanTriggers"), list) else []
        if triggers:
            return self._ui_safe_text(triggers[0], "Replan when branch evidence diverges from Twin trajectory.")
        return "Replan when camera/readiness diverges from trajectory."

    def _truncate_ui(self, text: Any, limit: int) -> str:
        safe = self._ui_safe_text(text, "")
        if len(safe) <= limit:
            return safe
        return safe[: max(0, limit - 3)].rstrip() + "..."

    def _ordered_plan_rows(self, *, include_fallback: bool = True):
        planning_run = self._state.get("planningRun") or {}
        rows = list(planning_run.get("candidates") or [])
        if not rows and include_fallback:
            rows = list(self._state.get("ranked") or [])
        if not rows and include_fallback:
            rows = [
                {"blueprintId": key, "name": meta.get("name", key)}
                for key, meta in BLUEPRINTS.items()
                if key != "baseline"
            ]

        ranked_by_label = {}
        for ranked_row in list(self._state.get("ranked") or []):
            label = self._plan_label(ranked_row)
            if label in PLAN_BUTTON_LABELS and label not in ranked_by_label:
                ranked_by_label[label] = ranked_row

        dedup = {}
        for row in rows:
            blueprint_id = str(row.get("blueprintId") or row.get("id") or "")
            if not blueprint_id or blueprint_id == "baseline":
                continue
            label = self._plan_label(row)
            if label not in PLAN_BUTTON_LABELS:
                continue
            dedup[label] = self._enrich_plan_row(row, ranked_by_label.get(label), label)

        if include_fallback:
            for label in PLAN_BUTTON_LABELS:
                if label in dedup or label not in ranked_by_label:
                    continue
                dedup[label] = self._enrich_plan_row(ranked_by_label[label], None, label)

        return [dedup[label] for label in PLAN_BUTTON_LABELS if label in dedup]

    def _refresh_apply_buttons(self):
        # Keep Plan A/B/C disabled until Generate/Planning produces real branch candidates.
        # This prevents the demo reset state from showing stale static fallback plans.
        rows = self._ordered_plan_rows(include_fallback=False)
        self._apply_button_blueprint_ids = []
        for idx, button in enumerate(self._apply_buttons):
            if idx < len(rows):
                row = rows[idx]
                blueprint_id = str(row.get("blueprintId") or row.get("id"))
                self._apply_button_blueprint_ids.append(blueprint_id)
                try:
                    button.text = _plain_plan_name(row.get("name") or row.get("blueprintName"), blueprint_id)
                    button.enabled = True
                except Exception:
                    pass
            else:
                self._apply_button_blueprint_ids.append("")
                try:
                    button.text = PLAN_BUTTON_LABELS[idx] if idx < len(PLAN_BUTTON_LABELS) else "-"
                    button.enabled = False
                except Exception:
                    pass

    def _apply_plan_button(self, index: int):
        if index >= len(self._apply_button_blueprint_ids):
            self._refresh_apply_buttons()
        try:
            blueprint_id = self._apply_button_blueprint_ids[index]
        except IndexError:
            blueprint_id = ""
        if not blueprint_id:
            self._set_status("No generated Plan is available. Click Generate Gemma/RAG Blueprints first.")
            return
        self._apply_blueprint(blueprint_id)

    def _refresh_scores(self):
        ranked = self._state.get("ranked") or []
        planning_run = self._state.get("planningRun") or {}
        rows = self._ordered_plan_rows(include_fallback=False)
        active_id = str(self._state.get("blueprintId", "baseline"))
        recommended_id = str(
            planning_run.get("recommendedBlueprintId")
            or (ranked[0] if ranked else {}).get("blueprintId")
            or (ranked[0] if ranked else {}).get("id")
            or ""
        )
        for idx, widgets in enumerate(self._score_rows):
            if idx >= len(rows):
                label = PLAN_BUTTON_LABELS[idx] if idx < len(PLAN_BUTTON_LABELS) else "Plan"
                self._set_ui_label(widgets.get("marker"), "")
                self._set_ui_label(widgets.get("name"), label)
                self._set_ui_label(widgets.get("score"), "-")
                self._set_ui_label(widgets.get("ship"), "waiting")
                self._set_ui_label(widgets.get("intent"), "Generate Gemma/RAG Blueprints to create this plan from current sensor + camera context.")
                self._set_ui_label(widgets.get("controls"), "No generated actuator recipe yet.")
                self._set_ui_label(widgets.get("tradeoff"), "Plan explanation will appear here after generation.")
                self._set_ui_label(widgets.get("basis"), "Score weights appear after generation.")
                self._set_widget_visible(widgets.get("bar"), False)
                self._set_progress_bar(widgets.get("bar"), 0.0)
                continue
            row = rows[idx]
            blueprint_id = str(row.get("blueprintId") or row.get("id") or "")
            marker = "R" if blueprint_id == recommended_id else ("A" if blueprint_id == active_id else "")
            score = self._score_value(row)
            yield_score = self._first_present(row, "yieldScore", "yield_score", default="-")
            self._set_ui_label(widgets.get("marker"), marker)
            self._set_ui_label(widgets.get("name"), self._short_plan_name(row.get("name", row.get("blueprintName", "-")), blueprint_id))
            self._set_ui_label(widgets.get("score"), self._format_score(score))
            self._set_ui_label(widgets.get("ship"), self._format_ship_delta(row))
            self._set_ui_label(widgets.get("intent"), self._plan_intent(row))
            self._set_ui_label(widgets.get("controls"), self._plan_controls(row))
            self._set_ui_label(
                widgets.get("tradeoff"),
                f"AI {self._plan_provider_label(row)} | Yield {yield_score} | OpEx {self._format_opex(row)} | {self._plan_tradeoff(row)}",
            )
            self._set_ui_label(widgets.get("basis"), self._plan_score_basis(row))
            self._set_widget_visible(widgets.get("bar"), score is not None)
            self._set_progress_bar(widgets.get("bar"), (score or 0.0) / 100.0)

    def _refresh_logs(self):
        for idx, label in enumerate(self._log_labels):
            try:
                label.text = f"{idx + 1}. {self._logs[-1 - idx]}"
            except IndexError:
                label.text = ""

    def _append_rag_trace(self, *lines: Any):
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted = [f"{timestamp} | {line}" for line in lines if str(line).strip()]
        if not formatted:
            return
        self._rag_trace_lines.extend(formatted)
        self._rag_trace_lines = self._rag_trace_lines[-120:]
        try:
            PLANNING_TRACE_DIR.mkdir(parents=True, exist_ok=True)
            with (PLANNING_TRACE_DIR / "rag-trace.log").open("a", encoding="utf-8") as f:
                for line in formatted:
                    f.write(line + "\n")
        except Exception as exc:
            print(f"[joon.smartfarm.omniops] rag trace log write failed: {exc}")
        self._refresh_rag_trace()

    def _refresh_rag_trace(self):
        if not self._rag_trace_labels:
            return
        visible = list(self._rag_trace_lines[-len(self._rag_trace_labels):])
        for idx, label in enumerate(self._rag_trace_labels):
            label.text = visible[idx] if idx < len(visible) else ""

    def _refresh_vision(self):
        assessment = self._latest_vision_assessment
        if assessment:
            self._vision_labels["camera"].text = str(assessment.get("cameraPath", GROWTH_CAMERA_PATH))
            capture_path = str(assessment.get("capturePath", "-"))
            self._vision_labels["last_capture"].text = Path(capture_path).name if capture_path else "-"
            self._vision_labels["vision_health"].text = (
                f"{assessment.get('healthScore', '-')}/100 ({assessment.get('confidence', '-')})"
            )
            self._vision_labels["vision_maturity"].text = (
                f"{assessment.get('growthProgressPercent', assessment.get('harvestReadinessPercent', '-'))}%"
            )
            self._vision_labels["vision_risk"].text = str(assessment.get("diseaseRisk", "-"))
            rows = [
                f"Source: {assessment.get('source', '-')}",
                f"Provider: {self._vision_provider_label(assessment)}",
                f"Status: {assessment.get('visionModelStatus', '-')}",
                f"Stage: {assessment.get('phenotypeStage', '-')}",
                f"Growth {assessment.get('growthProgressPercent', '-')}% · health {assessment.get('healthScore', '-')} · maturity {assessment.get('fruitMaturityPercent', '-')}% · readiness {assessment.get('harvestReadinessPercent', '-')}%",
                f"Capture: {capture_path}",
                f"Basis: {assessment.get('basis', '-')}",
            ]
            rows.extend(str(item) for item in assessment.get("traits", [])[:2])
        else:
            if "camera" in self._vision_labels:
                self._vision_labels["camera"].text = GROWTH_CAMERA_PATH
                self._vision_labels["last_capture"].text = "Not captured"
                self._vision_labels["vision_health"].text = "-"
                self._vision_labels["vision_maturity"].text = "-"
                self._vision_labels["vision_risk"].text = "-"
            rows = [
                "No vision assessment yet.",
                "Click Capture & Analyze Growth in the OmniOps Dock.",
                "Gemma vision is used only when SMARTFARM_VISION_BASE_URL or SMARTFARM_RAG_BASE_URL is configured.",
                "Real farm divergence/assimilation is intentionally out of scope for this phase.",
            ]
        self._refresh_vision_card(assessment)
        for idx, label in enumerate(self._vision_evidence_labels):
            label.text = rows[idx] if idx < len(rows) else ""

    def _refresh_camera_screen(self, assessment: Mapping[str, Any] | None):
        if not self._camera_screen_labels:
            return
        if assessment:
            capture_path = Path(str(assessment.get("capturePath", "")))
            status = str(assessment.get("captureStatus", "capture metadata saved"))
            stage = str(assessment.get("phenotypeStage", "strawberry phenotype"))
            confidence = str(assessment.get("confidence", "-"))
            provider_label = self._vision_provider_label(assessment)
            self._set_ui_label(
                self._camera_screen_labels.get("status"),
                f"Live viewport · latest capture: {capture_path.name if str(capture_path) else 'captured frame'}",
            )
            self._set_ui_label(
                self._camera_screen_labels.get("summary"),
                f"{stage} · {provider_label} · confidence {confidence} · {status}",
            )
            return
        self._set_ui_label(self._camera_screen_labels.get("status"), "Live viewport: GrowthPhenotypeCamera")
        self._set_ui_label(
            self._camera_screen_labels.get("summary"),
            "Embedded camera is live. Capture Frame stores a PNG and updates AI readout metadata.",
        )

    def _refresh_vision_card(self, assessment: Mapping[str, Any] | None):
        self._refresh_camera_screen(assessment)
        if assessment:
            capture_path = str(assessment.get("capturePath", ""))
            health = self._as_float(assessment.get("healthScore"), 0.0)
            maturity = self._as_float(assessment.get("fruitMaturityPercent"), 0.0)
            growth_progress = self._as_float(
                assessment.get("growthProgressPercent", assessment.get("harvestReadinessPercent", 0.0)),
                0.0,
            )
            readiness = self._as_float(assessment.get("harvestReadinessPercent"), 0.0)
            traits = list(assessment.get("traits", []) or [])
            self._set_ui_label(
                self._vision_card_labels.get("capture"),
                f"Latest: {Path(capture_path).name if capture_path else '-'}",
            )
            self._set_ui_label(
                self._vision_card_labels.get("provider"),
                f"{assessment.get('source', '-')} · {self._vision_provider_label(assessment)}",
            )
            self._set_ui_label(self._vision_card_labels.get("stage"), str(assessment.get("phenotypeStage", "-")))
            self._set_ui_label(self._vision_card_labels.get("health"), f"{health:.0f}/100 ({assessment.get('confidence', '-')})")
            self._set_ui_label(self._vision_card_labels.get("maturity"), f"{growth_progress:.0f}% growth")
            self._set_ui_label(self._vision_card_labels.get("readiness"), f"{readiness:.0f}%")
            self._set_ui_label(self._vision_card_labels.get("risk"), self._risk_chip(assessment.get("diseaseRisk", "-")))
            self._set_ui_label(self._vision_card_labels.get("basis"), str(assessment.get("basis", "-")))
            self._set_ui_label(self._vision_card_labels.get("trait_1"), str(traits[0]) if len(traits) > 0 else "-")
            self._set_ui_label(self._vision_card_labels.get("trait_2"), str(traits[1]) if len(traits) > 1 else "-")
            self._set_progress_bar(self._vision_card_bars.get("health"), health / 100.0)
            self._set_ui_label(
                self._evidence_summary_labels.get("vision"),
                f"{growth_progress:.0f}% growth · {self._vision_provider_label(assessment)}",
            )
            self._set_progress_bar(self._evidence_summary_bars.get("vision"), growth_progress / 100.0)
            return

        self._set_ui_label(self._vision_card_labels.get("capture"), "Not captured")
        self._set_ui_label(self._vision_card_labels.get("provider"), "Waiting for Gemma/RAG vision or local fallback")
        self._set_ui_label(self._vision_card_labels.get("stage"), "Ready for virtual crop-camera capture")
        self._set_ui_label(self._vision_card_labels.get("health"), "-")
        self._set_ui_label(self._vision_card_labels.get("maturity"), "-")
        self._set_ui_label(self._vision_card_labels.get("readiness"), "-")
        self._set_ui_label(self._vision_card_labels.get("risk"), "-")
        self._set_ui_label(self._vision_card_labels.get("basis"), "Virtual camera + Gemma/RAG vision adapter when configured")
        self._set_ui_label(self._vision_card_labels.get("trait_1"), "Click Capture & Analyze Growth in the right Dock.")
        self._set_ui_label(self._vision_card_labels.get("trait_2"), "Real camera/model provider remains out of this POC phase.")
        self._set_progress_bar(self._vision_card_bars.get("health"), 0.0)
        self._set_ui_label(self._evidence_summary_labels.get("vision"), "No capture")
        self._set_progress_bar(self._evidence_summary_bars.get("vision"), 0.0)

    def _set_ui_label(self, label, text: Any):
        if label is not None:
            label.text = str(text)

    def _set_progress_bar(self, progress_bar, value: float):
        if progress_bar is None:
            return
        try:
            progress_bar.model.set_value(max(0.0, min(1.0, float(value))))
        except Exception:
            pass

    def _set_widget_visible(self, widget, visible: bool):
        if widget is None:
            return
        try:
            widget.visible = bool(visible)
        except Exception:
            pass

    def _as_float(self, value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _is_present(self, value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str) and value.strip().lower() in {"", "-", "--", "n/a", "none", "null"}:
            return False
        return True

    def _ui_safe_text(self, value: Any, fallback: str) -> str:
        text = str(value or "").strip()
        if not text:
            return fallback
        text = (
            text.replace("CO₂", "CO2")
            .replace("°", " deg ")
            .replace("·", " | ")
            .replace("≥", ">=")
            .replace("≤", "<=")
        )
        try:
            text.encode("ascii")
        except UnicodeEncodeError:
            return fallback
        if text.count("?") >= 2:
            return fallback
        return " ".join(text.split())

    def _first_present(self, mapping: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
        for key in keys:
            value = mapping.get(key)
            if self._is_present(value):
                return value
        return default

    def _generation_criteria(self) -> Mapping[str, Any]:
        planning_run = self._state.get("planningRun") or {}
        criteria = self._state.get("generationCriteria") or planning_run.get("generationCriteria") or {}
        return criteria if isinstance(criteria, Mapping) else {}

    def _set_plot_data(self, plot, values: list[float]):
        if plot is None:
            return
        padded = list(values[:8])
        if not padded:
            padded = [0.0]
        while len(padded) < 8:
            padded.append(padded[-1])
        try:
            plot.set_data(*[max(0.0, min(100.0, float(value))) for value in padded[:8]])
        except Exception as exc:
            if not self._decision_graph_plot_error_reported:
                self._decision_graph_plot_error_reported = True
                message = f"Decision graph plot update failed: {type(exc).__name__}: {exc}"
                print(f"[joon.smartfarm.omniops] {message}")
                try:
                    self._append_rag_trace(message)
                except Exception as trace_exc:
                    print(f"[joon.smartfarm.omniops] decision graph error trace failed: {trace_exc}")

    def _trajectory_points(self, row: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        trajectory = row.get("trajectory")
        if isinstance(trajectory, list) and trajectory:
            return [point for point in trajectory if isinstance(point, Mapping)]
        simulation = row.get("simulation") if isinstance(row.get("simulation"), Mapping) else {}
        daily = simulation.get("dailyStates") if isinstance(simulation.get("dailyStates"), list) else []
        points: list[Mapping[str, Any]] = []
        for item in daily[:8]:
            if not isinstance(item, Mapping):
                continue
            maturity = self._as_float(item.get("fruitMaturity"), 0.0) * 100.0
            disease = self._as_float(item.get("diseasePressure"), 0.0) * 100.0
            yield_score = self._as_float(item.get("estimatedYield"), 0.0)
            readiness = maturity * 0.62 + yield_score * 0.22 + (100.0 - disease) * 0.16
            points.append(
                {
                    "day": item.get("day"),
                    "maturityPercent": maturity,
                    "harvestReadinessPercent": readiness,
                    "diseasePressurePercent": disease,
                    "yieldScore": yield_score,
                }
            )
        return points

    def _trajectory_readiness(self, point: Mapping[str, Any]) -> float:
        if not isinstance(point, Mapping):
            return 0.0
        value = self._first_present(point, "harvestReadinessPercent", "readinessPercent", default=None)
        if value is not None:
            return self._as_float(value, 0.0)
        maturity = self._as_float(self._first_present(point, "maturityPercent", default=0.0), 0.0)
        disease = self._as_float(self._first_present(point, "diseasePressurePercent", default=0.0), 0.0)
        yield_score = self._as_float(self._first_present(point, "yieldScore", default=0.0), 0.0)
        return max(0.0, min(100.0, maturity * 0.62 + yield_score * 0.22 + (100.0 - disease) * 0.16))

    def _trajectory_milestones(self, row: Mapping[str, Any], trajectory: list[Mapping[str, Any]], *, count: int) -> list[Mapping[str, Any]]:
        if count <= 0:
            return []
        if not trajectory:
            return [{} for _ in range(count)]
        if len(trajectory) == 1:
            return [trajectory[0] for _ in range(count)]
        sampled = []
        for idx in range(count):
            source_idx = int(round(idx * (len(trajectory) - 1) / max(1, count - 1)))
            sampled.append(trajectory[source_idx])
        return sampled

    def _trajectory_summary(self, row: Mapping[str, Any], milestones: list[Mapping[str, Any]]) -> str:
        simulation = row.get("simulation") if isinstance(row.get("simulation"), Mapping) else {}
        start_day = self._as_float(simulation.get("startDay"), None)
        if start_day is None and milestones:
            start_day = self._as_float(milestones[0].get("day"), 0.0)
        parts = []
        for point in milestones[:5]:
            day = self._as_float(point.get("day"), start_day or 0.0)
            offset = max(0, int(round(day - (start_day or day))))
            parts.append(f"D+{offset}:{self._trajectory_readiness(point):.0f}%")
        return "  >  ".join(parts) if parts else "trajectory unavailable"

    def _graph_branch_note(self, row: Mapping[str, Any]) -> str:
        branch = row.get("branch") if isinstance(row.get("branch"), Mapping) else {}
        trigger = self._ui_safe_text(branch.get("replanTrigger"), "")
        if trigger:
            return "replan rule set"
        score = self._score_value(row)
        if score is None:
            return "waiting"
        return "validated branch"

    def _plan_label(self, row: Mapping[str, Any]) -> str:
        blueprint_id = str(row.get("blueprintId") or row.get("id") or "")
        return _plain_plan_name(row.get("name") or row.get("blueprintName") or row.get("label"), blueprint_id)

    def _enrich_plan_row(
        self,
        row: Mapping[str, Any],
        ranked_row: Mapping[str, Any] | None,
        label: str,
    ) -> Dict[str, Any]:
        """Merge generated text with ranked/simulated metrics for complete Plan A/B/C cards.

        Some external Gemma/RAG deployments return textual candidate specs, while
        the Twin service returns the simulated score in `recommendation.scores`.
        The UI card needs both.  This merge prevents missing score fields from
        being rendered as misleading `0%` or `ship --d`.
        """

        ranked_row = ranked_row or {}
        merged: Dict[str, Any] = dict(ranked_row)
        merged.update({k: v for k, v in row.items() if self._is_present(v)})

        row_score = self._score_value(row)
        ranked_score = self._score_value(ranked_row)
        if ranked_score is not None and (row_score is None or row_score <= 0.0 < ranked_score):
            merged["score"] = ranked_score

        predicted = row.get("predicted") if isinstance(row.get("predicted"), Mapping) else {}
        ranked_predicted = ranked_row.get("predicted") if isinstance(ranked_row.get("predicted"), Mapping) else {}
        for target_key, keys in {
            "expectedShipment": ("expectedShipment", "targetShipmentDate", "shipmentDate"),
            "yieldScore": ("yieldScore", "yield_score"),
            "diseaseRisk": ("diseaseRisk",),
            "opexDeltaPercent": ("opexDeltaPercent",),
        }.items():
            if self._is_present(merged.get(target_key)):
                continue
            value = self._first_present(row, *keys)
            if value is None:
                value = self._first_present(predicted, *keys)
            if value is None:
                value = self._first_present(ranked_row, *keys)
            if value is None:
                value = self._first_present(ranked_predicted, *keys)
            if value is not None:
                merged[target_key] = value

        if not self._is_present(merged.get("daysEarlier")):
            ranked_days = self._first_present(ranked_row, "daysEarlier")
            merged["daysEarlier"] = ranked_days if ranked_days is not None else self._days_earlier_from_row(merged)

        blueprint_id = str(merged.get("blueprintId") or merged.get("id") or "")
        if not blueprint_id and label in STATIC_BLUEPRINT_ID_BY_PLAN_LABEL:
            blueprint_id = STATIC_BLUEPRINT_ID_BY_PLAN_LABEL[label]
        merged["blueprintId"] = blueprint_id
        merged["name"] = label
        return merged

    def _score_value(self, row: Mapping[str, Any]) -> float | None:
        value = row.get("score")
        if not self._is_present(value):
            return None
        try:
            score = max(0.0, min(100.0, float(value)))
        except (TypeError, ValueError):
            return None
        predicted = row.get("predicted") if isinstance(row.get("predicted"), Mapping) else {}
        has_simulated_metrics = any(
            self._is_present(self._first_present(row, key))
            or self._is_present(self._first_present(predicted, key))
            for key in ("expectedShipment", "targetShipmentDate", "shipmentDate", "yieldScore", "opexDeltaPercent")
        )
        if score == 0.0 and not has_simulated_metrics:
            return None
        return score

    def _format_score(self, score: float | None) -> str:
        return "score n/a" if score is None else f"{score:.0f}/100"

    def _days_earlier_from_row(self, row: Mapping[str, Any]) -> int | None:
        expected = (
            self._first_present(row, "expectedShipment", "targetShipmentDate", "shipmentDate")
            or self._first_present(row.get("predicted", {}) if isinstance(row.get("predicted"), Mapping) else {}, "shipmentDate")
        )
        if not self._is_present(expected):
            blueprint_id = str(row.get("blueprintId") or row.get("id") or "")
            static_id = blueprint_id if blueprint_id in BLUEPRINTS else STATIC_BLUEPRINT_ID_BY_PLAN_LABEL.get(self._plan_label(row), "")
            if static_id in BLUEPRINTS:
                expected = BLUEPRINTS[static_id].get("expected_ship")
        baseline = (
            self._first_present(
                (self._state.get("planningRun") or {}).get("baselineComparison", {}),
                "expectedShipment",
                "targetShipmentDate",
                "shipmentDate",
            )
            or self._first_present(
                ((self._state.get("planningRun") or {}).get("baselineComparison", {}).get("predicted") or {}),
                "shipmentDate",
            )
            or BLUEPRINTS["baseline"].get("expected_ship")
        )
        try:
            baseline_date = datetime.fromisoformat(str(baseline)[:10])
            candidate_date = datetime.fromisoformat(str(expected)[:10])
            return max(0, (baseline_date - candidate_date).days)
        except Exception:
            return None

    def _format_ship_delta(self, row: Mapping[str, Any]) -> str:
        days = self._first_present(row, "daysEarlier")
        if days is None:
            days = self._days_earlier_from_row(row)
        try:
            rounded = int(round(float(days)))
            return "ship ±0d" if rounded == 0 else f"ship -{rounded}d"
        except (TypeError, ValueError):
            expected = (
                self._first_present(row, "expectedShipment", "targetShipmentDate", "shipmentDate")
                or self._first_present(row.get("predicted", {}) if isinstance(row.get("predicted"), Mapping) else {}, "shipmentDate")
            )
            return f"ship {str(expected)[:10]}" if self._is_present(expected) else "ship n/a"

    def _plan_provider_label(self, row: Mapping[str, Any]) -> str:
        provider = str(row.get("provider") or row.get("source") or "").lower()
        if "gemma" in provider or "rag" in provider:
            evidence_count = len(row.get("ragEvidence") or [])
            return f"Gemma/RAG{'+' + str(evidence_count) + ' docs' if evidence_count else ''}"
        if "current-twin" in provider:
            return "Current Twin"
        if "synthetic" in provider or "deterministic" in provider:
            return "Twin simulator"
        return str(row.get("provider") or row.get("source") or "Twin simulator")

    def _vision_provider_label(self, assessment: Mapping[str, Any] | None) -> str:
        if not assessment:
            return "No capture"
        status = str(assessment.get("visionModelStatus") or "")
        mode = str(assessment.get("analysisMode") or "")
        confidence = str(assessment.get("confidence") or "")
        provider = str(assessment.get("provider") or "")
        joined = f"{status} {mode} {confidence} {provider}".lower()
        if "fallback" in joined and ("gemma" in joined or "rag" in joined):
            return "Gemma request + fallback"
        if status == "gemma-vision" or ("gemma" in provider.lower() and "fallback" not in joined):
            return "Gemma vision"
        if status.startswith("fallback") or "mock" in provider.lower():
            return "Local fallback"
        return provider or "Vision adapter"

    def _planner_status_short(self, status: str, provider: str = "") -> str:
        text = f"{status} {provider}".lower()
        if "unavailable" in text:
            return "Offline fallback"
        if "pending_external" in text or "deterministic" in text:
            return "Twin fallback"
        if "legacy_recommend" in text:
            return "Gemma legacy"
        if "fallback" in text and ("gemma" in text or "rag" in text):
            return "Gemma + fallback"
        if "gemma" in text or "rag" in text or "live_blueprint_generator" in text:
            return "Gemma live"
        return "Planner run"

    def _planner_status_ratio(self, status: str, provider: str = "") -> float:
        label = self._planner_status_short(status, provider)
        if label == "Gemma live":
            return 1.0
        if label in {"Gemma + fallback", "Gemma legacy"}:
            return 0.72
        if label == "Twin fallback":
            return 0.45
        if label == "Offline fallback":
            return 0.25
        return 0.55

    def _risk_ratio(self, risk: Any) -> float:
        risk_text = str(risk).lower()
        if risk_text == "low":
            return 0.25
        if risk_text == "controlled":
            return 0.55
        if risk_text == "high":
            return 0.90
        return 0.45

    def _risk_chip(self, risk: Any) -> str:
        risk_text = str(risk).lower()
        if risk_text == "low":
            return "LOW risk"
        if risk_text == "controlled":
            return "CONTROLLED"
        if risk_text == "high":
            return "HIGH risk"
        return str(risk)

    def _short_plan_name(self, name: Any, blueprint_id: str = "") -> str:
        return _plain_plan_name(name, blueprint_id)

    def _blueprint_meta(self, row: Mapping[str, Any]) -> Mapping[str, Any]:
        blueprint_id = str(row.get("blueprintId", ""))
        return BLUEPRINTS.get(blueprint_id, {})

    def _plan_intent(self, row: Mapping[str, Any]) -> str:
        meta = self._blueprint_meta(row)
        label = self._plan_label(row)
        branch = row.get("branch") if isinstance(row.get("branch"), Mapping) else {}
        text = (
            branch.get("whyGenerated")
            or row.get("operatorIntent")
            or row.get("summary")
            or meta.get("operator_intent")
            or meta.get("summary")
            or row.get("rationale")
            or "-"
        )
        return self._ui_safe_text(text, f"{label}: generated from current sensor, crop, and Gemma/RAG context.")

    def _plan_controls(self, row: Mapping[str, Any]) -> str:
        meta = self._blueprint_meta(row)
        branch = row.get("branch") if isinstance(row.get("branch"), Mapping) else {}
        if branch.get("actuatorRecipe"):
            return self._ui_safe_text(
                f"Actuators: {branch.get('actuatorRecipe')}",
                "Actuators: generated recipe from current sensor, vision, and RAG context",
            )
        control_focus = row.get("controlFocus") or meta.get("control_focus")
        if control_focus:
            return self._ui_safe_text(f"Controls: {control_focus}", "Controls: generated actuator recipe from Gemma/RAG context")
        actuator = (
            row.get("actuatorTarget")
            or row.get("actuatorTargets")
            or row.get("actuatorState")
            or {}
        )
        if isinstance(actuator, Mapping) and actuator:
            return (
                "Controls: "
                f"LED {self._first_present(actuator, 'ledIntensityPercent', 'led_intensity_percent', default='-')}%/"
                f"{self._first_present(actuator, 'photoperiodHours', 'photoperiod_hours', default='-')}h | "
                f"Irr {self._first_present(actuator, 'irrigationPulsesPerDay', 'irrigation_pulses_per_day', default='-')}/day | "
                f"Fan {self._first_present(actuator, 'fanDutyPercent', 'fan_duty_percent', default='-')}% | "
                f"CO2 {self._first_present(actuator, 'co2Ppm', 'co2_ppm', default='-')} ppm"
            )
        blueprint_id = str(row.get("blueprintId", ""))
        actuator = BLUEPRINTS.get(blueprint_id, {}).get("actuator", {})
        if actuator:
            return (
                "Controls: "
                f"LED {actuator.get('led_intensity_percent', '-')}%/{actuator.get('photoperiod_hours', '-')}h | "
                f"Irr {actuator.get('irrigation_pulses_per_day', '-')}/day | "
                f"Fan {actuator.get('fan_duty_percent', '-')}% | CO2 {actuator.get('co2_ppm', '-')} ppm"
            )
        return "Controls: -"

    def _plan_tradeoff(self, row: Mapping[str, Any]) -> str:
        validation_note = self._plan_validation_note(row)
        if validation_note:
            return f"Twin validation floor: {validation_note}."
        meta = self._blueprint_meta(row)
        branch = row.get("branch") if isinstance(row.get("branch"), Mapping) else {}
        if branch.get("riskSummary"):
            risk = self._ui_safe_text(branch.get("riskSummary"), "Twin risk is available in the JSON trace.")
            trigger = self._ui_safe_text(branch.get("replanTrigger"), "")
            return f"{risk} | {trigger}" if trigger else risk
        predicted = row.get("predicted") if isinstance(row.get("predicted"), Mapping) else {}
        tradeoff = row.get("tradeoff") or predicted.get("riskNote") or meta.get("tradeoff")
        if tradeoff:
            return self._ui_safe_text(tradeoff, "Twin simulation compares shipment timing, yield, OpEx, and disease risk.")
        return f"{self._risk_chip(row.get('diseaseRisk', '-'))}"

    def _plan_validation_note(self, row: Mapping[str, Any]) -> str:
        score = self._score_value(row)
        if score is None or score > 0.0:
            return ""
        predicted = row.get("predicted") if isinstance(row.get("predicted"), Mapping) else {}
        reasons: list[str] = []
        disease = str(
            self._first_present(row, "diseaseRisk")
            or self._first_present(predicted, "diseaseRisk")
            or ""
        ).lower()
        if disease == "high":
            reasons.append("high disease pressure")
        days = self._first_present(row, "daysEarlier")
        if days is None:
            days = self._days_earlier_from_row(row)
        try:
            if float(days) <= 0:
                reasons.append("no earlier viable shipment vs Baseline")
        except (TypeError, ValueError):
            pass
        return ", ".join(reasons) if reasons else "candidate missed planning constraints"

    def _format_opex(self, row: Mapping[str, Any]) -> str:
        if "opexDeltaPercent" in row:
            return f"{self._as_float(row.get('opexDeltaPercent'), 0.0):+.0f}%"
        predicted = row.get("predicted") if isinstance(row.get("predicted"), Mapping) else {}
        if "opexDeltaPercent" in predicted:
            return f"{self._as_float(predicted.get('opexDeltaPercent'), 0.0):+.0f}%"
        if "opex" in row:
            return str(row.get("opex"))
        return "n/a"

    def _plan_score_basis(self, row: Mapping[str, Any]) -> str:
        breakdown = row.get("scoreBreakdown") if isinstance(row.get("scoreBreakdown"), Mapping) else {}
        if not breakdown:
            simulation = row.get("simulation") if isinstance(row.get("simulation"), Mapping) else {}
            breakdown = simulation.get("scoreBreakdown") if isinstance(simulation.get("scoreBreakdown"), Mapping) else {}
        if breakdown:
            ship = self._as_float(breakdown.get("earlyShipmentBonus"), 0.0)
            yield_term = self._as_float(breakdown.get("yieldContribution"), 0.0)
            cost = self._as_float(breakdown.get("costSavingBonus"), 0.0)
            opex = self._as_float(breakdown.get("opexPenalty"), 0.0)
            disease = self._as_float(breakdown.get("diseasePenalty"), 0.0)
            safety = self._as_float(breakdown.get("unsafeHarvestPenalty"), 0.0)
            context = self._as_float(breakdown.get("diseaseContextAdjustment"), 0.0)
            return self._ui_safe_text(
                f"Basis: ship {ship:+.1f}, yield {yield_term:+.1f}, cost {cost:+.1f}, "
                f"OpEx -{opex:.1f}, disease -{disease:.1f}, safety -{safety:.1f}, ctx {context:+.1f}",
                "Score basis: generated from Twin simulation terms.",
            )

        weights = self._generation_criteria().get("objectiveWeights")
        if isinstance(weights, Mapping) and weights:
            return self._ui_safe_text(
                "Weights: "
                f"ship {self._as_float(weights.get('earliestShipment'), 0.0) * 100:.0f}%, "
                f"yield {self._as_float(weights.get('yield'), 0.0) * 100:.0f}%, "
                f"disease {self._as_float(weights.get('diseaseControl'), 0.0) * 100:.0f}%, "
                f"OpEx {self._as_float(weights.get('opex'), 0.0) * 100:.0f}%, "
                f"safety {self._as_float(weights.get('actuatorSafety'), 0.0) * 100:.0f}%",
                "Weights are loaded from generation criteria.",
            )
        return "Basis: score terms appear after Generate/Twin simulation."

    def _format_sensor_value(self, key: str, value: float, unit: str) -> str:
        if key in {"co2_ppm", "humidity_percent", "substrate_moisture_percent"}:
            return f"{int(round(value))} {unit}"
        return f"{value:.1f} {unit}"

    def _record_sensor_sample(self, sensor: Mapping[str, Any]):
        for key, _title, _unit, _scale_min, _scale_max, _color in SENSOR_SERIES:
            value = float(sensor.get(key, 0.0))
            history = self._sensor_history.setdefault(key, [value] * SENSOR_HISTORY_LEN)
            history.append(value)
            del history[:-SENSOR_HISTORY_LEN]

    def _refresh_sensor_graphs(self, sensor: Mapping[str, Any]):
        for key, _title, unit, _scale_min, _scale_max, _color in SENSOR_SERIES:
            value = float(sensor.get(key, 0.0))
            label = self._sensor_value_labels.get(key)
            if label:
                label.text = self._format_sensor_value(key, value, unit)
            plot = self._sensor_plots.get(key)
            if plot:
                plot.set_data(*self._sensor_history.get(key, [value] * SENSOR_HISTORY_LEN))

    def _sync_actuator_controls(self, actuator: Mapping[str, Any], force: bool = False):
        if self._actuator_dirty and not force:
            return
        self._syncing_actuator_models = True
        try:
            self._water_valve_open = bool(actuator.get("water_valve_open", False))
            if "water_valve" in self._labels:
                self._labels["water_valve"].text = self._water_valve_text()
            for key, _title, unit, _minimum, _maximum in ACTUATOR_CONTROLS:
                value = int(round(float(actuator.get(key, 0))))
                model = self._actuator_models.get(key)
                if model:
                    model.set_value(value)
                label = self._actuator_value_labels.get(key)
                if label:
                    label.text = f"{value} {unit}"
        finally:
            self._syncing_actuator_models = False

    def _on_actuator_model_changed(self, key: str, unit: str, model):
        value = int(round(model.get_value_as_float()))
        label = self._actuator_value_labels.get(key)
        if label:
            label.text = f"{value} {unit}"
        if not self._syncing_actuator_models:
            self._actuator_dirty = True
            self._preview_manual_actuator_state()

    def _water_valve_text(self) -> str:
        return f"Water valve: {'OPEN' if self._water_valve_open else 'CLOSED'}"

    def _toggle_water_valve(self):
        self._water_valve_open = not self._water_valve_open
        if "water_valve" in self._labels:
            self._labels["water_valve"].text = self._water_valve_text()
        self._actuator_dirty = True
        self._preview_manual_actuator_state()

    def _actuator_state_from_controls(self) -> Dict[str, Any]:
        values = {}
        for key, _title, _unit, _minimum, _maximum in ACTUATOR_CONTROLS:
            model = self._actuator_models.get(key)
            values[key] = int(round(model.get_value_as_float())) if model else int(self._state["actuator"].get(key, 0))
        return {
            "led_intensity_percent": values["led_intensity_percent"],
            "photoperiod_hours": values["photoperiod_hours"],
            "water_valve_open": self._water_valve_open,
            "irrigation_pulses_per_day": values["irrigation_pulses_per_day"],
            "fan_duty_percent": values["fan_duty_percent"],
            "co2_ppm": values["co2_ppm"],
        }

    def _actuator_payload_from_controls(self) -> Dict[str, Any]:
        values = self._actuator_state_from_controls()
        return {
            "ledIntensityPercent": values["led_intensity_percent"],
            "photoperiodHours": values["photoperiod_hours"],
            "waterValveOpen": self._water_valve_open,
            "irrigationPulsesPerDay": values["irrigation_pulses_per_day"],
            "fanDutyPercent": values["fan_duty_percent"],
            "co2Ppm": values["co2_ppm"],
        }

    def _preview_manual_actuator_state(self):
        try:
            preview = state_for_manual_actuator(self._actuator_state_from_controls())
            preview["sceneMode"] = "manual_preview"
            preview["smartFarmPath"] = self._state.get("smartFarmPath", SMART_FARM_PATH)
            self._state = preview
            self._refresh_ui()
            if "status" in self._labels:
                self._labels["status"].text = (
                    "Manual actuator preview updated. Sensor/KPI values are projected locally; "
                    "click Apply Manual Controls to mutate the USD twin."
                )
        except Exception as exc:
            if "status" in self._labels:
                self._labels["status"].text = f"Manual actuator preview failed: {exc}"

    async def _dock_operator_panel_async(self):
        """Dock OmniOps as a selectable tab next to the Layer panel.

        Kit restores the default workspace over the first few frames.  If our
        window is made visible before a valid dock target exists, ImGui creates
        it as a floating popup and persists that layout.  The loop below briefly
        makes the window visible only inside the same frame where an immediate
        dock request succeeds; otherwise it hides it again before the next draw.
        """
        app = omni.kit.app.get_app()
        for _ in range(8):
            await app.next_update_async()

        for attempt in range(1, 361):
            if self._control_window is None or self._docked:
                return

            # Ensure the Layer-side dock target exists before docking. The
            # desired UX is a normal selectable tab beside Layer, not a full
            # replacement right split and not a floating popup.
            for title in ("Stage", "Layer", "Layers"):
                try:
                    ui.Workspace.show_window(title, True)
                except Exception:
                    pass

            docked_to = self._try_dock_operator_panel_once()
            if docked_to:
                for _ in range(3):
                    await app.next_update_async()
                self._finalize_operator_panel_dock(docked_to)
                return

            try:
                self._control_window.visible = False
            except Exception:
                pass
            try:
                self._control_window.deferred_dock_in("Layer", ui.DockPolicy.CURRENT_WINDOW_IS_ACTIVE)
            except Exception:
                pass

            self._dock_retry_frames = attempt
            if attempt in {1, 30, 120, 300}:
                print(f"[joon.smartfarm.omniops] waiting for right dock target; retry={attempt}")
            await app.next_update_async()

        # Last-resort fallback: keep the UI usable, but make the failure explicit
        # in logs instead of silently persisting a floating popup layout.
        if self._control_window is not None:
            try:
                self._control_window.visible = True
            except Exception:
                pass
        print("[joon.smartfarm.omniops] WARNING: right dock target was not found; OmniOps left visible for recovery")

    def _try_dock_operator_panel_once(self) -> str | None:
        if self._control_window is None:
            return None

        try:
            self._control_window.visible = True
        except Exception:
            return None

        # Prefer a SAME-tab dock into Layer so the operator can switch between
        # Layer and SmartFarm OmniOps from the same right-side tab strip.  The
        # actual Kit window title is singular "Layer"; keep "Layers" as a
        # compatibility fallback for older layouts.
        targets = (
            ("Layer", ui.DockPosition.SAME, 0.5),
            ("Layers", ui.DockPosition.SAME, 0.5),
            ("Stage", ui.DockPosition.SAME, 0.5),
            ("Property", ui.DockPosition.SAME, 0.5),
            ("Details", ui.DockPosition.SAME, 0.5),
            ("DockSpace", ui.DockPosition.RIGHT, 0.30),
        )
        for target_title, position, ratio in targets:
            try:
                if self._control_window.dock_in_window(target_title, position, ratio):
                    print(f"[joon.smartfarm.omniops] requested dock into {target_title}")
                    return target_title
            except Exception:
                pass
        return None

    def _finalize_operator_panel_dock(self, docked_to: str):
        if self._control_window is None:
            return
        try:
            self._control_window.focus()
        except Exception:
            pass
        try:
            self._control_window.width = 680
        except Exception:
            pass
        try:
            self._control_window.dock_order = 1
            self._control_window.dock_tab_bar_visible = True
            self._control_window.dock_tab_bar_enabled = True
        except Exception:
            pass
        self._hide_non_layer_right_side_windows(docked_to)
        self._docked = True
        print(f"[joon.smartfarm.omniops] docked as Layer-tab panel via {docked_to}")

    def _hide_non_layer_right_side_windows(self, docked_to: str):
        # Keep Stage/Layer visible so OmniOps remains a selectable neighboring
        # tab. Hide only the stock Property/Details panes when they are not the
        # actual fallback dock target.
        for title in ("Property", "Details"):
            try:
                if title != docked_to:
                    ui.Workspace.show_window(title, False)
            except Exception:
                pass

    async def _dock_evidence_panel_async(self):
        """Dock SmartFarm Evidence into the bottom Console/Content stack."""
        app = omni.kit.app.get_app()
        for _ in range(12):
            await app.next_update_async()

        for attempt in range(1, 241):
            if self._evidence_window is None or self._evidence_docked:
                return

            for title in ("Console", "Content"):
                try:
                    ui.Workspace.show_window(title, True)
                except Exception:
                    pass

            docked_to = self._try_dock_evidence_panel_once()
            if docked_to:
                for _ in range(2):
                    await app.next_update_async()
                self._finalize_evidence_panel_dock(docked_to)
                return

            try:
                self._evidence_window.visible = False
            except Exception:
                pass
            try:
                self._evidence_window.deferred_dock_in("Console", ui.DockPolicy.CURRENT_WINDOW_IS_ACTIVE)
            except Exception:
                pass
            self._evidence_dock_retry_frames = attempt
            if attempt in {1, 30, 120}:
                print(f"[joon.smartfarm.omniops] waiting for bottom evidence dock target; retry={attempt}")
            await app.next_update_async()

        if self._evidence_window is not None:
            try:
                self._evidence_window.visible = True
            except Exception:
                pass
        print("[joon.smartfarm.omniops] WARNING: bottom dock target was not found; Evidence left visible for recovery")

    def _try_dock_evidence_panel_once(self) -> str | None:
        if self._evidence_window is None:
            return None
        try:
            self._evidence_window.visible = True
        except Exception:
            return None

        targets = (
            ("Console", ui.DockPosition.SAME, 0.5),
            ("Content", ui.DockPosition.SAME, 0.5),
            ("Content Browser", ui.DockPosition.SAME, 0.5),
            ("DockSpace", ui.DockPosition.BOTTOM, 0.24),
        )
        for target_title, position, ratio in targets:
            try:
                if self._evidence_window.dock_in_window(target_title, position, ratio):
                    print(f"[joon.smartfarm.omniops] requested evidence dock into {target_title}")
                    return target_title
            except Exception:
                pass
        return None

    def _finalize_evidence_panel_dock(self, docked_to: str):
        if self._evidence_window is None:
            return
        try:
            self._evidence_window.height = 460
            self._evidence_window.dock_order = 2
            self._evidence_window.dock_tab_bar_visible = True
            self._evidence_window.dock_tab_bar_enabled = True
        except Exception:
            pass
        self._evidence_docked = True
        print(f"[joon.smartfarm.omniops] docked SmartFarm Evidence bottom panel via {docked_to}")

    async def _dock_rag_trace_panel_async(self):
        """Dock RAG Trace as a selectable neighboring bottom tab for class demos."""
        app = omni.kit.app.get_app()
        for _ in range(18):
            await app.next_update_async()

        for attempt in range(1, 181):
            if self._rag_trace_window is None or self._rag_trace_docked:
                return

            if not self._evidence_docked:
                await app.next_update_async()
                continue

            try:
                self._rag_trace_window.visible = True
            except Exception:
                return

            targets = (
                (EVIDENCE_TITLE, ui.DockPosition.SAME, 0.5),
                ("Console", ui.DockPosition.SAME, 0.5),
                ("Content", ui.DockPosition.SAME, 0.5),
            )
            for target_title, position, ratio in targets:
                try:
                    if self._rag_trace_window.dock_in_window(target_title, position, ratio):
                        for _ in range(2):
                            await app.next_update_async()
                        self._finalize_rag_trace_dock(target_title)
                        return
                except Exception:
                    pass

            try:
                self._rag_trace_window.deferred_dock_in("Console", ui.DockPolicy.CURRENT_WINDOW_IS_ACTIVE)
                self._rag_trace_window.visible = False
            except Exception:
                pass
            if attempt in {1, 45, 120}:
                print(f"[joon.smartfarm.omniops] waiting for RAG Trace dock target; retry={attempt}")
            await app.next_update_async()

        if self._rag_trace_window is not None:
            try:
                self._rag_trace_window.visible = True
            except Exception:
                pass
        print("[joon.smartfarm.omniops] WARNING: RAG Trace dock target not found; trace left visible")

    def _finalize_rag_trace_dock(self, docked_to: str):
        if self._rag_trace_window is None:
            return
        try:
            self._rag_trace_window.height = 460
            self._rag_trace_window.dock_order = 3
            self._rag_trace_window.dock_tab_bar_visible = True
            self._rag_trace_window.dock_tab_bar_enabled = True
        except Exception:
            pass
        self._rag_trace_docked = True
        self._append_rag_trace(f"RAG Trace panel docked next to Evidence via {docked_to}")
        print(f"[joon.smartfarm.omniops] docked SmartFarm RAG Trace panel via {docked_to}")

    async def _dock_blueprint_dag_panel_async(self):
        """Dock Blueprint DAG as its own selectable bottom tab next to RAG Trace."""
        app = omni.kit.app.get_app()
        for _ in range(22):
            await app.next_update_async()

        for attempt in range(1, 181):
            if self._blueprint_dag_window is None or self._blueprint_dag_docked:
                return

            if not self._rag_trace_docked and not self._evidence_docked:
                await app.next_update_async()
                continue

            try:
                self._blueprint_dag_window.visible = True
            except Exception:
                return

            targets = (
                (RAG_TRACE_TITLE, ui.DockPosition.SAME, 0.5),
                (EVIDENCE_TITLE, ui.DockPosition.SAME, 0.5),
                ("Console", ui.DockPosition.SAME, 0.5),
            )
            for target_title, position, ratio in targets:
                try:
                    if self._blueprint_dag_window.dock_in_window(target_title, position, ratio):
                        for _ in range(2):
                            await app.next_update_async()
                        self._finalize_blueprint_dag_dock(target_title)
                        return
                except Exception:
                    pass

            try:
                self._blueprint_dag_window.deferred_dock_in("Console", ui.DockPolicy.CURRENT_WINDOW_IS_ACTIVE)
                self._blueprint_dag_window.visible = False
            except Exception:
                pass
            if attempt in {1, 45, 120}:
                print(f"[joon.smartfarm.omniops] waiting for Blueprint DAG dock target; retry={attempt}")
            await app.next_update_async()

        if self._blueprint_dag_window is not None:
            try:
                self._blueprint_dag_window.visible = True
            except Exception:
                pass
        print("[joon.smartfarm.omniops] WARNING: Blueprint DAG dock target not found; DAG left visible")

    def _finalize_blueprint_dag_dock(self, docked_to: str):
        if self._blueprint_dag_window is None:
            return
        try:
            self._blueprint_dag_window.height = 460
            self._blueprint_dag_window.dock_order = 4
            self._blueprint_dag_window.dock_tab_bar_visible = True
            self._blueprint_dag_window.dock_tab_bar_enabled = True
        except Exception:
            pass
        self._blueprint_dag_docked = True
        self._refresh_blueprint_dag()
        self._append_rag_trace(f"Blueprint DAG panel docked next to RAG Trace via {docked_to}")
        print(f"[joon.smartfarm.omniops] docked SmartFarm Blueprint DAG panel via {docked_to}")

    async def _dock_strawberry_view_async(self):
        """Dock live strawberry camera as the 30% right split of the bottom dashboard."""
        app = omni.kit.app.get_app()
        for _ in range(18):
            await app.next_update_async()

        for attempt in range(1, 241):
            if self._strawberry_view_window is None or self._strawberry_view_docked:
                return

            if not self._evidence_docked:
                await app.next_update_async()
                continue

            try:
                self._strawberry_view_window.visible = True
            except Exception:
                return

            self._ensure_growth_camera_for_dashboard()
            self._sync_strawberry_view_window()

            try:
                if self._strawberry_view_window.dock_in_window(EVIDENCE_TITLE, ui.DockPosition.RIGHT, STRAWBERRY_VIEW_DOCK_RATIO):
                    for _ in range(2):
                        await app.next_update_async()
                    self._finalize_strawberry_view_dock()
                    return
            except Exception:
                pass

            try:
                self._strawberry_view_window.deferred_dock_in(EVIDENCE_TITLE, ui.DockPolicy.CURRENT_WINDOW_IS_ACTIVE)
            except Exception:
                pass

            if attempt in {1, 30, 120}:
                print(f"[joon.smartfarm.omniops] waiting to dock strawberry live view; retry={attempt}")
            await app.next_update_async()

        print("[joon.smartfarm.omniops] WARNING: Strawberry live view was left visible; bottom 8:2 docking failed")

    def _finalize_strawberry_view_dock(self):
        if self._strawberry_view_window is None:
            return
        try:
            self._strawberry_view_window.width = STRAWBERRY_VIEW_WINDOW_WIDTH
            self._strawberry_view_window.height = STRAWBERRY_VIEW_WINDOW_HEIGHT
            self._strawberry_view_window.dock_order = 3
            self._strawberry_view_window.dock_tab_bar_visible = True
            self._strawberry_view_window.dock_tab_bar_enabled = True
        except Exception:
            pass
        self._strawberry_view_docked = True
        self._sync_strawberry_view_window()
        print("[joon.smartfarm.omniops] docked SmartFarm Strawberry Live View as bottom-right 30% panel")

    # --------------------------------------------------------------- actions --

    def _on_update(self, _event):
        try:
            self._on_update_impl(_event)
        except Exception as exc:
            print(f"[joon.smartfarm.omniops] update loop failed: {exc}")
            import traceback

            traceback.print_exc()
            self._set_status(f"OmniOps update loop recovered after error: {exc}")

    def _on_update_impl(self, _event):
        if not self._startup_synced:
            self._startup_frames_remaining -= 1
            if self._startup_frames_remaining > 0:
                return
            self._startup_synced = True
            if not self._stage_has_existing_farm():
                self._set_status("Existing farm scene not found; creating current baseline twin in-process.")
                self._post_scene("growth")
            else:
                self._ensure_growth_camera_for_dashboard()
                self._load_state_from_api()
            return

        self._poll_frames_remaining -= 1
        if self._poll_frames_remaining <= 0:
            self._poll_frames_remaining = SENSOR_POLL_FRAMES
            if not self._stage_has_growth_camera():
                self._ensure_growth_camera_for_dashboard()
            self._poll_state_from_api()

    def _focus_growth_camera(self):
        try:
            if not self._ensure_growth_camera():
                raise RuntimeError("Existing /World/SmartFarm scene is not available yet.")
            self._set_viewport_camera(GROWTH_CAMERA_PATH)
            self._sync_embedded_camera_viewport()
            self._sync_strawberry_view_window()
            self._set_status("Viewport focused on Growth Camera for strawberry phenotype view.")
        except Exception as exc:
            self._set_status(f"Growth Camera focus failed. {exc}")

    def _capture_and_analyze_growth(self):
        if self._capture_task is not None and not self._capture_task.done():
            self._set_status("Growth Camera analysis is already running.")
            return
        self._capture_task = asyncio.ensure_future(self._capture_and_analyze_growth_async())

    async def _capture_and_analyze_growth_async(self):
        try:
            if not self._ensure_growth_camera():
                raise RuntimeError("Existing /World/SmartFarm scene is not available yet.")
            self._set_viewport_camera(GROWTH_CAMERA_PATH)
            self._sync_strawberry_view_window()
            self._capture_seq += 1
            timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
            blueprint_id = str(self._state.get("blueprintId", "baseline")).replace("/", "_")
            VISION_CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
            image_path = VISION_CAPTURE_DIR / f"{timestamp}_{self._capture_seq:03d}_{blueprint_id}.png"

            capture_status = self._request_viewport_capture(image_path)
            for _ in range(2):
                await omni.kit.app.get_app().next_update_async()
            capture_ready = await self._wait_for_capture_file(image_path)

            observed_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
            fallback_assessment = vision_assessment_from_state(
                self._state["sensor"],
                self._state["crop"],
                camera_path=GROWTH_CAMERA_PATH,
                capture_path=str(image_path),
                observed_at=observed_at,
            )
            assessment = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._analyze_growth_capture_with_gemma(
                    image_path,
                    observed_at,
                    fallback_assessment,
                    capture_ready=capture_ready,
                ),
            )
            assessment["captureStatus"] = capture_status
            sidecar_path = self._write_vision_sidecar(image_path, assessment)
            self._latest_vision_assessment = assessment
            self._refresh_vision()
            self._append_rag_trace(
                (
                    "Capture clicked: POST TwinX "
                    f"{assessment.get('visionEndpointPath', '/vision/analyze')} "
                    f"image={image_path.name} bytes={assessment.get('imageBytes', image_path.stat().st_size if image_path.exists() else '-')}"
                ),
                (
                    "Vision status: "
                    f"{assessment.get('visionModelStatus', '-')} · "
                    f"{self._vision_provider_label(assessment)} · "
                    f"mode={assessment.get('analysisMode', '-')} · "
                    f"http={assessment.get('visionHttpStatus', '-')} · "
                    f"auth={'yes' if assessment.get('visionAuthConfigured') else 'no'}"
                ),
                self._vision_fallback_reason_line(assessment),
            )
            self._set_status(
                "Growth Camera capture analyzed "
                f"({assessment['source']}, {self._vision_provider_label(assessment)}, "
                f"growth {assessment.get('growthProgressPercent', assessment.get('harvestReadinessPercent', '-'))}%). "
                f"Metadata: {sidecar_path.name}"
            )
        except Exception as exc:
            self._set_status(f"Growth Camera capture/analyze failed. {exc}")

    async def _wait_for_capture_file(self, image_path: Path, frames: int = 45) -> bool:
        for _ in range(frames):
            if image_path.exists() and image_path.stat().st_size > 0:
                return True
            await omni.kit.app.get_app().next_update_async()
        return image_path.exists() and image_path.stat().st_size > 0

    def _analyze_growth_capture_with_gemma(
        self,
        image_path: Path,
        observed_at: str,
        fallback_assessment: Mapping[str, Any],
        *,
        capture_ready: bool,
    ) -> Dict[str, Any]:
        assessment = dict(fallback_assessment)
        if not capture_ready:
            assessment["provider"] = "foundation-model-adapter/mock"
            assessment["visionModelStatus"] = "fallback:no-capture-image-file"
            assessment["basis"] = "metadata-only capture + deterministic phenotype estimator"
            return assessment

        base_url = self._vision_base_url()
        if not base_url:
            assessment["visionModelStatus"] = "fallback:SMARTFARM_VISION_BASE_URL/SMARTFARM_RAG_BASE_URL not configured"
            return assessment

        try:
            return self._request_gemma_growth_assessment(base_url, image_path, observed_at, assessment)
        except Exception as exc:
            assessment["provider"] = "foundation-model-adapter/mock"
            assessment["visionModelStatus"] = f"fallback:gemma-vision-unavailable:{exc}"
            assessment["basis"] = "Gemma/RAG vision request failed; deterministic phenotype estimator used"
            return assessment

    def _vision_base_url(self) -> str:
        return (os.getenv("SMARTFARM_VISION_BASE_URL") or os.getenv("SMARTFARM_RAG_BASE_URL") or "").rstrip("/")

    def _vision_token(self) -> str:
        token = os.getenv("SMARTFARM_VISION_TOKEN") or os.getenv("SMARTFARM_RAG_TOKEN") or ""
        token_file = os.getenv("SMARTFARM_VISION_TOKEN_FILE") or os.getenv("SMARTFARM_RAG_TOKEN_FILE") or ""
        if not token and token_file:
            try:
                token = Path(token_file).read_text(encoding="utf-8").strip()
            except OSError:
                token = ""
        return token

    def _request_gemma_growth_assessment(
        self,
        base_url: str,
        image_path: Path,
        observed_at: str,
        fallback_assessment: Mapping[str, Any],
    ) -> Dict[str, Any]:
        image_bytes = image_path.read_bytes()
        body = {
            "facilityId": "smartfarm-spark-a7ce",
            "cameraPath": GROWTH_CAMERA_PATH,
            "capturePath": str(image_path),
            "observedAt": observed_at,
            "imageMimeType": "image/png",
            "imageBase64": base64.b64encode(image_bytes).decode("ascii"),
            "objective": (
                "Analyze the strawberry crop image. Return current growth progress as a percent of the full "
                "0-100 crop cycle, plus fruit set, canopy vigor, fruit maturity, harvest readiness, health, "
                "disease risk, phenotype stage, confidence, and concise visual evidence."
            ),
            "sensorContext": self._state.get("sensor", {}),
            "cropContext": self._state.get("crop", {}),
            "kpiContext": self._state.get("kpi", {}),
            "fallbackAssessment": dict(fallback_assessment),
        }
        token = self._vision_token()
        timeout = float(os.getenv("SMARTFARM_VISION_TIMEOUT") or os.getenv("SMARTFARM_RAG_TIMEOUT") or 30)
        configured_path = os.getenv("SMARTFARM_VISION_ANALYZE_PATH", "").strip()
        paths = (configured_path,) if configured_path else VISION_ANALYZE_PATHS
        last_error: Exception | None = None
        for path in paths:
            if not path:
                continue
            url = f"{base_url}{path if path.startswith('/') else '/' + path}"
            req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST")
            req.add_header("Accept", "application/json")
            req.add_header("Content-Type", "application/json")
            if token:
                req.add_header("Authorization", f"Bearer {token}")
            try:
                with urllib.request.urlopen(req, timeout=timeout) as response:
                    status_code = getattr(response, "status", 200)
                    payload = json.loads(response.read().decode("utf-8"))
                assessment = self._normalize_gemma_growth_assessment(payload, fallback_assessment, path)
                assessment["visionEndpointPath"] = path
                assessment["visionHttpStatus"] = status_code
                assessment["visionAuthConfigured"] = bool(token)
                assessment["imageBytes"] = int(assessment.get("imageBytes") or len(image_bytes))
                return assessment
            except urllib.error.HTTPError as exc:
                last_error = exc
                if configured_path or exc.code not in {404, 405}:
                    break
            except Exception as exc:
                last_error = exc
                if configured_path:
                    break
        raise RuntimeError(str(last_error or "no vision endpoint response"))

    def _normalize_gemma_growth_assessment(
        self,
        payload: Mapping[str, Any],
        fallback_assessment: Mapping[str, Any],
        endpoint_path: str,
    ) -> Dict[str, Any]:
        raw = payload.get("assessment") if isinstance(payload.get("assessment"), Mapping) else payload
        assessment = dict(fallback_assessment)
        provider = raw.get("provider") or payload.get("provider") or "twinx-gemma-vision"
        progress = self._first_percent(
            raw,
            "growthProgressPercent",
            "growthPercent",
            "cropProgressPercent",
            "cycleProgressPercent",
            "percentOfFullCycle",
            "harvestReadinessPercent",
        )
        maturity = self._first_percent(raw, "fruitMaturityPercent", "maturityPercent", "ripenessPercent")
        fruit_set = self._first_percent(raw, "fruitSetPercent", "fruitSet", "flowerToFruitSetPercent")
        canopy = self._first_percent(raw, "canopyVigorPercent", "canopyPercent", "vegetativeGrowthPercent")
        health = self._first_percent(raw, "healthScore", "healthPercent", "cropHealthPercent")
        readiness = self._first_percent(raw, "harvestReadinessPercent", "readinessPercent")
        if progress is not None:
            assessment["growthProgressPercent"] = progress
        if maturity is not None:
            assessment["fruitMaturityPercent"] = maturity
        if fruit_set is not None:
            assessment["fruitSetPercent"] = fruit_set
        if canopy is not None:
            assessment["canopyVigorPercent"] = canopy
        if health is not None:
            assessment["healthScore"] = health
        if readiness is not None:
            assessment["harvestReadinessPercent"] = readiness
        if raw.get("phenotypeStage") or raw.get("growthStage"):
            assessment["phenotypeStage"] = str(raw.get("phenotypeStage") or raw.get("growthStage"))
        if raw.get("diseaseRisk"):
            assessment["diseaseRisk"] = str(raw.get("diseaseRisk"))
        if raw.get("confidence"):
            assessment["confidence"] = str(raw.get("confidence"))
        evidence = raw.get("traits") or raw.get("visualEvidence") or raw.get("evidence")
        if isinstance(evidence, list) and evidence:
            assessment["traits"] = [str(item) for item in evidence[:6]]
        elif raw.get("summary"):
            assessment["traits"] = [str(raw.get("summary"))]
        if raw.get("recommendation"):
            assessment["recommendation"] = str(raw.get("recommendation"))
        if raw.get("summary"):
            assessment["summary"] = str(raw.get("summary"))
        if raw.get("imageBytes") is not None:
            try:
                assessment["imageBytes"] = int(raw.get("imageBytes"))
            except (TypeError, ValueError):
                assessment["imageBytes"] = raw.get("imageBytes")
        mode = str(raw.get("analysisMode") or payload.get("analysisMode") or "").strip()
        confidence_text = str(raw.get("confidence") or assessment.get("confidence") or "").lower()
        is_fallback = "fallback" in mode.lower() or "fallback" in confidence_text
        assessment["analysisMode"] = mode or ("gemma_vision_fallback" if is_fallback else "gemma_vision_json")
        assessment["source"] = "virtual-camera-gemma-fallback" if is_fallback else "virtual-camera-gemma-observed"
        assessment["provider"] = str(provider)
        assessment["basis"] = str(raw.get("basis") or f"captured PNG sent to Gemma/RAG vision endpoint {endpoint_path}")
        assessment["visionModelStatus"] = "gemma-vision-fallback" if is_fallback else "gemma-vision"
        return assessment

    def _vision_fallback_reason_line(self, assessment: Mapping[str, Any]) -> str:
        status_text = " ".join(
            str(assessment.get(key) or "")
            for key in ("visionModelStatus", "analysisMode", "confidence", "basis")
        ).lower()
        traits = [str(item) for item in assessment.get("traits") or []]
        reason = next((item for item in traits if "fallback reason" in item.lower()), "")
        if not reason and "fallback" in status_text:
            reason = str(assessment.get("basis") or "Gemma vision response used fallback fields.")
        return f"Vision fallback reason: {reason}" if reason else ""

    def _first_percent(self, raw: Mapping[str, Any], *keys: str) -> int | None:
        for key in keys:
            if key not in raw:
                continue
            try:
                value = float(raw[key])
            except (TypeError, ValueError):
                continue
            if 0.0 <= value <= 1.0:
                value *= 100.0
            return int(round(max(0.0, min(100.0, value))))
        return None

    def _ensure_blue_sky(self, stage):
        """Keep OmniOps-authored scene touches aligned with the Twin blue-sky baseline."""
        from pxr import Gf, Sdf, UsdGeom, UsdLux

        lighting_group = f"{SMART_FARM_PATH}/Lighting"
        UsdGeom.Xform.Define(stage, lighting_group)

        dome = UsdLux.DomeLight.Define(stage, BLUE_SKY_DOME_PATH)
        dome.CreateIntensityAttr(BLUE_SKY_DOME_INTENSITY).Set(BLUE_SKY_DOME_INTENSITY)
        dome.CreateColorAttr(Gf.Vec3f(0.42, 0.68, 1.00)).Set(Gf.Vec3f(0.42, 0.68, 1.00))
        dome.GetPrim().CreateAttribute("smartfarm:environment", Sdf.ValueTypeNames.String).Set("blue-sky")

        sun = UsdLux.DistantLight.Define(stage, BLUE_SKY_SUN_PATH)
        sun.CreateIntensityAttr(BLUE_SKY_SUN_INTENSITY).Set(BLUE_SKY_SUN_INTENSITY)
        sun.CreateAngleAttr(1.2).Set(1.2)
        sun.CreateColorAttr(Gf.Vec3f(1.00, 0.93, 0.78)).Set(Gf.Vec3f(1.00, 0.93, 0.78))
        UsdGeom.XformCommonAPI(sun.GetPrim()).SetRotate(Gf.Vec3f(-45.0, 35.0, 0.0))

    def _ensure_growth_camera(self) -> bool:
        stage = omni.usd.get_context().get_stage()
        if stage is None or not stage.GetPrimAtPath(SMART_FARM_PATH):
            return False

        from pxr import Gf, Sdf, UsdGeom, UsdLux

        self._ensure_blue_sky(stage)

        UsdGeom.Scope.Define(stage, f"{SMART_FARM_PATH}/Cameras")
        camera = UsdGeom.Camera.Define(stage, GROWTH_CAMERA_PATH)
        # Phenotype camera is a close crop-inspection camera, not the service
        # streaming camera. Keep its far clip, lens, and authored scale focused
        # on the target plant crown plus nearby leaves/fruit so the embedded
        # view also works before fruit set, when no strawberry is visible yet.
        camera.CreateFocalLengthAttr().Set(38.0)
        camera.CreateHorizontalApertureAttr().Set(32.0)
        camera.CreateVerticalApertureAttr().Set(18.0)
        camera.CreateClippingRangeAttr().Set(Gf.Vec2f(GROWTH_CAMERA_NEAR_CLIP, GROWTH_CAMERA_FAR_CLIP))
        prim = camera.GetPrim()
        prim.CreateAttribute("smartfarm:purpose", Sdf.ValueTypeNames.String).Set("growth-phenotype-camera")
        prim.CreateAttribute("smartfarm:source", Sdf.ValueTypeNames.String).Set("virtual-camera-observed")
        prim.CreateAttribute("smartfarm:provider", Sdf.ValueTypeNames.String).Set("foundation-model-adapter/mock")

        # Keep the camera inside House_01_01, in the south aisle just beside
        # Bed_01, and aim at the Plant_06 crown/leaf cluster instead of only
        # the fruit. This keeps the view meaningful in early growth stages
        # before any strawberry fruit is visible:
        #   unit offset (-28, -9) + Plant_06 x=-1 + Bed_01 z=-6.2
        #   => target plant around (-29.0, 1.50, -15.2).
        # A look-at transform avoids manual Euler drift and keeps the small
        # embedded viewport centered on the crop instead of the aisle/walls.
        eye = Gf.Vec3d(-26.2, 1.75, -17.5)
        target = Gf.Vec3d(-29.0, 1.50, -15.2)
        camera_xform = Gf.Matrix4d(1.0).SetLookAt(eye, target, Gf.Vec3d(0.0, 1.0, 0.0)).GetInverse()
        xformable = UsdGeom.Xformable(prim)
        xformable.ClearXformOpOrder()
        xformable.AddTransformOp().Set(camera_xform)
        xformable.AddScaleOp().Set(
            Gf.Vec3f(GROWTH_CAMERA_VISUAL_SCALE, GROWTH_CAMERA_VISUAL_SCALE, GROWTH_CAMERA_VISUAL_SCALE)
        )

        # Small local fill for the phenotype view. This brightens the crop-camera
        # angle without raising the whole greenhouse lighting/exposure setup.
        fill = UsdLux.SphereLight.Define(stage, GROWTH_CAMERA_FILL_LIGHT_PATH)
        fill.CreateIntensityAttr(GROWTH_CAMERA_FILL_INTENSITY)
        fill.CreateRadiusAttr(0.30)
        fill.CreateColorAttr(Gf.Vec3f(1.0, 0.96, 0.88))
        fill.GetPrim().CreateAttribute("smartfarm:purpose", Sdf.ValueTypeNames.String).Set("growth-camera-soft-fill")
        fill_xform = UsdGeom.XformCommonAPI(fill.GetPrim())
        fill_xform.SetTranslate(Gf.Vec3d(-26.7, 1.90, -16.4))
        self._sync_embedded_camera_viewport()
        self._sync_strawberry_view_window()
        return True

    def _sync_embedded_camera_viewport(self):
        if self._camera_viewport_widget is None:
            return
        try:
            from pxr import Sdf

            viewport_api = self._camera_viewport_widget.viewport_api
            viewport_api.camera_path = Sdf.Path(GROWTH_CAMERA_PATH)
            viewport_api.updates_enabled = True
            viewport_api.fill_frame = True
        except Exception:
            pass

    def _sync_strawberry_view_window(self):
        if self._strawberry_view_window is None:
            return
        try:
            from pxr import Sdf

            viewport_api = getattr(self._strawberry_view_window, "viewport_api", None)
            if viewport_api:
                viewport_api.camera_path = Sdf.Path(GROWTH_CAMERA_PATH)
                viewport_api.updates_enabled = True
                viewport_api.fill_frame = True
        except Exception:
            pass

    def _rebuild_embedded_camera_viewport(self):
        if self._camera_viewport_widget is not None or self._camera_viewport_frame is None:
            return
        try:
            self._camera_viewport_frame.clear()
            with self._camera_viewport_frame:
                self._build_embedded_camera_view()
        except Exception as exc:
            print(f"[joon.smartfarm.omniops] embedded Growth Camera viewport rebuild skipped: {exc}")

    def _ensure_growth_camera_for_dashboard(self) -> bool:
        if not self._stage_has_existing_farm():
            self._set_ui_label(
                self._camera_screen_labels.get("status"),
                "Growth camera waiting for /World/SmartFarm scene.",
            )
            self._set_ui_label(
                self._camera_screen_labels.get("summary"),
                "The dashboard viewport will attach automatically after the SmartFarm scene is created.",
            )
            return False

        if self._camera_viewport_widget is None:
            self._rebuild_embedded_camera_viewport()

        try:
            ready = self._ensure_growth_camera()
        except Exception as exc:
            print(f"[joon.smartfarm.omniops] growth camera ensure failed: {exc}")
            ready = False

        if ready:
            self._sync_embedded_camera_viewport()
            self._sync_strawberry_view_window()
            self._set_ui_label(
                self._camera_screen_labels.get("status"),
                "Live viewport: GrowthPhenotypeCamera",
            )
            self._set_ui_label(
                self._camera_screen_labels.get("summary"),
                "Embedded camera is always bound to the in-farm growth-stage view.",
            )
        return ready

    def _set_viewport_camera(self, camera_path: str):
        from pxr import Sdf

        try:
            from omni.kit.viewport.utility import get_active_viewport, get_viewport_from_window_name

            viewport_api = get_active_viewport() or get_viewport_from_window_name("Viewport")
            if viewport_api:
                viewport_api.camera_path = Sdf.Path(camera_path)
        except Exception as exc:
            print(f"[joon.smartfarm.omniops] viewport camera update skipped: {exc}")

    def _request_viewport_capture(self, image_path: Path) -> str:
        try:
            import omni.kit.renderer_capture

            renderer_capture = omni.kit.renderer_capture.acquire_renderer_capture_interface()
            renderer_capture.capture_next_frame_swapchain(str(image_path))
            return "swapchain-capture-requested"
        except Exception as exc:
            # Keep the POC flow usable even when running in a headless/streaming
            # environment where swapchain capture may not be available.
            return f"metadata-only; swapchain capture unavailable: {exc}"

    def _write_vision_sidecar(self, image_path: Path, assessment: Mapping[str, Any]) -> Path:
        sidecar_path = image_path.with_suffix(".json")
        payload = {
            "capturePath": str(image_path),
            "assessment": dict(assessment),
            "stateSnapshot": {
                "blueprintId": self._state.get("blueprintId"),
                "sensor": self._state.get("sensor"),
                "crop": self._state.get("crop"),
                "kpi": self._state.get("kpi"),
            },
        }
        sidecar_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return sidecar_path

    def _write_planning_trace_sidecar(self) -> Path | None:
        planning_run = self._state.get("planningRun") or {}
        if not planning_run:
            return None
        try:
            PLANNING_TRACE_DIR.mkdir(parents=True, exist_ok=True)
            run_id = str(planning_run.get("runId") or "planning-run").replace("/", "_")
            timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
            sidecar_path = PLANNING_TRACE_DIR / f"{timestamp}_{run_id}.json"
            payload = {
                "createdAt": timestamp,
                "planningRun": planning_run,
                "ragAdvice": self._state.get("ragAdvice") or planning_run.get("ragAdvice") or {},
                "gapAnalysis": self._state.get("gapAnalysis") or planning_run.get("gapAnalysis") or {},
                "generationCriteria": self._state.get("generationCriteria") or planning_run.get("generationCriteria") or {},
                "ranked": self._state.get("ranked") or [],
                "visionAssessmentUsed": self._latest_vision_assessment or {},
                "stateSnapshot": {
                    "blueprintId": self._state.get("blueprintId"),
                    "sensor": self._state.get("sensor"),
                    "crop": self._state.get("crop"),
                    "kpi": self._state.get("kpi"),
                },
            }
            sidecar_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            return sidecar_path
        except Exception as exc:
            print(f"[joon.smartfarm.omniops] planning trace write failed: {exc}")
            return None

    def _planning_trace_summary_lines(
        self,
        planning_run: Mapping[str, Any],
        rag_advice: Mapping[str, Any],
        gap_analysis: Mapping[str, Any],
        trace_path: Path | None,
    ) -> list[str]:
        """Compact, UI-safe proof lines for classroom/demo RAG verification."""

        lines: list[str] = []
        request_trace = planning_run.get("ragRequestTrace") if isinstance(planning_run, Mapping) else {}
        request_trace = request_trace if isinstance(request_trace, Mapping) else {}
        if request_trace:
            ok = request_trace.get("ok")
            status_code = request_trace.get("statusCode")
            status = "ok" if ok is True else "failed" if ok is False else "sent"
            if status_code is not None:
                status = f"{status} HTTP {status_code}"
            lines.append(
                "RAG API "
                f"{request_trace.get('method', '-')} {request_trace.get('path', '-')} -> {status}; "
                f"url={request_trace.get('url', '-')}"
            )
            body = request_trace.get("bodySummary") if isinstance(request_trace.get("bodySummary"), Mapping) else {}
            lines.append(
                "Request context: "
                f"objective={body.get('objective', '-')}, candidates={body.get('candidateCount', '-')}, "
                f"day={body.get('currentDay', '-')}, planting={body.get('plantingDate', '-')}, "
                f"date={body.get('date', '-')}, vision={'yes' if body.get('hasVisionAssessment') else 'no'}, "
                f"no_llm={body.get('noLlm', '-')}"
            )
            sensor = body.get("sensor") if isinstance(body.get("sensor"), Mapping) else {}
            if sensor:
                lines.append(
                    "Sensor sent: "
                    f"DLI={sensor.get('dli_mol_m2_day', '-')}, humidity={sensor.get('humidity_percent', '-')}%, "
                    f"substrate={sensor.get('substrate_moisture_percent', '-')}%, "
                    f"temp={sensor.get('temperature_c', '-')}C, CO2={sensor.get('co2_ppm', '-')}ppm"
                )
            if request_trace.get("error"):
                lines.append(f"RAG API error: {request_trace.get('error')}")
        else:
            lines.append("RAG API trace not returned by Twin yet; reload Twin extension if this stays empty after Generate.")

        provider = rag_advice.get("provider") or planning_run.get("source") or "Gemma/RAG"
        model = rag_advice.get("model") or "-"
        status = planning_run.get("gemmaRagStatus") or planning_run.get("source") or "-"
        sources = list(rag_advice.get("evidence") or [])
        lines.append(f"Gemma status: {self._planner_status_short(str(status), str(provider))}; provider={provider}; model={model}; sources={len(sources)}")
        criteria = planning_run.get("generationCriteria") if isinstance(planning_run.get("generationCriteria"), Mapping) else {}
        if criteria:
            weights = criteria.get("objectiveWeights") if isinstance(criteria.get("objectiveWeights"), Mapping) else {}
            weight_text = ", ".join(
                f"{label}={self._as_float(weights.get(key), 0.0) * 100:.0f}%"
                for key, label in (
                    ("earliestShipment", "ship"),
                    ("yield", "yield"),
                    ("diseaseControl", "disease"),
                    ("opex", "opex"),
                    ("actuatorSafety", "safe"),
                )
                if key in weights
            )
            validation = criteria.get("twinValidation") if isinstance(criteria.get("twinValidation"), Mapping) else {}
            lines.append(
                "Generation criteria: "
                f"weights[{weight_text or '-'}], RAG docs={criteria.get('ragDocsCount', len(sources))}, "
                f"Twin floor=maturity>={validation.get('harvestMaturityThresholdPercent', '-')}%, "
                f"yield>={validation.get('minYieldScore', '-')}, disease<={validation.get('diseasePressureLimitPercent', '-')}%"
            )
            vision = criteria.get("usedVisionState") if isinstance(criteria.get("usedVisionState"), Mapping) else {}
            sensor = criteria.get("usedSensorState") if isinstance(criteria.get("usedSensorState"), Mapping) else {}
            lines.append(
                "Used state: "
                f"DLI={sensor.get('dliMolM2Day', '-')}, RH={sensor.get('humidityPercent', '-')}%, "
                f"CO2={sensor.get('co2Ppm', '-')}ppm, "
                f"vision={'yes' if vision.get('attached') else 'no'}"
            )
        quality_gate = planning_run.get("qualityGate") if isinstance(planning_run, Mapping) else {}
        quality_gate = quality_gate if isinstance(quality_gate, Mapping) else {}
        repaired_count = int(self._as_float(quality_gate.get("repairedCount"), 0.0)) if quality_gate else 0
        if repaired_count:
            lines.append(
                f"Twin quality gate: repaired {repaired_count} infeasible Gemma candidate(s); "
                "original scores and actuator targets are in the JSON trace."
            )

        limiting = list(gap_analysis.get("limitingFactors") or [])
        if limiting:
            lines.append(
                "Gap factors: "
                + self._ui_safe_text(", ".join(str(item) for item in limiting[:4]), "current sensor/crop gap factors available in JSON trace")
            )
        if self._is_present(gap_analysis.get("deviationScore")):
            lines.append(f"Gap score: {self._as_float(gap_analysis.get('deviationScore'), 0.0):.1f}")

        for row in self._ordered_plan_rows(include_fallback=False):
            score = self._score_value(row)
            score_text = self._format_score(score)
            validation_note = self._plan_validation_note(row)
            lines.append(
                f"{self._plan_label(row)}: {score_text}, {self._format_ship_delta(row)}, "
                f"{self._plan_controls(row).replace('Controls: ', '')}"
                + (f", validation={validation_note}" if validation_note else "")
            )

        if sources:
            first = sources[0] if isinstance(sources[0], Mapping) else {"source": sources[0]}
            summary = first.get("summary") or first.get("source") or "-"
            lines.append(
                "First RAG source: "
                + self._ui_safe_text(f"{first.get('source', '-')}: {summary}", "RAG source metadata is available in JSON trace")
            )
        if trace_path is not None:
            lines.append(f"Saved JSON trace: {trace_path}")
        lines.append(f"Recommended: {planning_run.get('recommendedBlueprintId', '-')}")
        return lines

    def _run_daily_planning(self):
        try:
            payload = self._twin_payload("planning", reason="omniops")
            self._state = self._normalize_api_state(payload)
            recommended = self._state.get("ranked", [{}])[0]
            self._refresh_ui()
            self._ensure_growth_camera_for_dashboard()
            rec_id = str(recommended.get("blueprintId") or recommended.get("id") or "")
            rec_name = self._short_plan_name(recommended.get("name", recommended.get("blueprintName", "-")), rec_id)
            self._set_status(f"Daily planning completed. Recommended: {rec_name}.")
        except Exception as exc:
            self._set_status(f"Daily planning API failed; keeping local panel state. {exc}")

    def _generate_rag_blueprints(self):
        self._append_rag_trace(
            "Generate clicked: POST Twin /smartfarm/blueprint/generate -> Twin calls TwinX Gemma/RAG if configured",
            f"Vision assessment attached: {'yes' if self._latest_vision_assessment else 'no'}",
        )
        try:
            payload = self._twin_payload(
                "generate_blueprints",
                goal="balanced",
                constraints={"maxOpexIncreasePct": 18, "diseaseRiskMax": "controlled"},
                vision_assessment=self._latest_vision_assessment,
            )
            self._state = self._normalize_api_state(payload)
            recommended = self._state.get("ranked", [{}])[0]
            self._actuator_dirty = False
            planning_run = self._state.get("planningRun") or {}
            rag_advice = self._state.get("ragAdvice") or planning_run.get("ragAdvice") or {}
            status = str(planning_run.get("gemmaRagStatus") or planning_run.get("source") or "planning-run")
            provider = str(rag_advice.get("provider") or planning_run.get("source") or "Gemma/RAG")
            sources = list(rag_advice.get("evidence") or [])
            candidates = list(planning_run.get("candidates") or [])
            self._record_blueprint_generation(planning_run)
            self._refresh_ui()
            self._sync_actuator_controls(self._state["actuator"], force=True)
            self._ensure_growth_camera_for_dashboard()
            trace_path = self._write_planning_trace_sidecar()
            self._append_rag_trace(
                *self._planning_trace_summary_lines(
                    planning_run,
                    rag_advice,
                    self._state.get("gapAnalysis") or planning_run.get("gapAnalysis") or {},
                    trace_path,
                )
            )
            self._set_status(
                f"{self._planner_status_short(status, provider)} blueprint generation completed "
                f"({planning_run.get('runId', 'run')}, {len(candidates)} plans, {len(sources)} RAG sources). Recommended: "
                f"{self._short_plan_name(recommended.get('name', recommended.get('blueprintName', '-')), str(recommended.get('blueprintId') or recommended.get('id') or ''))}. "
                f"Trace: {trace_path.name if trace_path else 'not available'}."
            )
        except Exception as exc:
            self._append_rag_trace(f"Generate failed: {type(exc).__name__}: {exc}")
            self._set_status(f"Gemma/RAG blueprint generation failed; keeping current state. {exc}")

    def _apply_recommended_blueprint(self):
        ranked = self._state.get("ranked") or []
        if not ranked:
            self._set_status("No recommended blueprint is available. Run planning or Generate Gemma/RAG Blueprints first.")
            return
        blueprint_id = ranked[0].get("blueprintId") or ranked[0].get("id")
        if not blueprint_id:
            self._set_status("Recommended blueprint row has no id.")
            return
        self._apply_blueprint(str(blueprint_id))

    def _reset_demo_baseline(self):
        """Return the operator UI to the first-screen demo state.

        Reset Baseline should be stronger than a USD timeline reset: it clears
        generated Blueprint evidence, selected branch history, RAG trace lines,
        and the latest vision assessment so the next demo starts from a clean
        Baseline -> Generate -> Apply story. Runtime trace files are preserved
        on disk for auditability, but the visible panels become fresh.
        """
        self._post_scene("reset", reset_demo_state=True)

    def _clear_demo_runtime_state(self):
        self._selected_blueprint = "baseline"
        self._active_generation_run_id = None
        self._blueprint_decision_history = []
        self._blueprint_generation_history = []
        self._latest_vision_assessment = None
        self._capture_seq = 0
        self._sensor_history = {}
        self._decision_graph_plot_error_reported = False
        self._rag_trace_lines = [
            "SmartFarm RAG Trace ready. Click Generate Gemma/RAG Blueprints to capture live API evidence."
        ]
        self._logs = ["Demo reset: Baseline/current Twin state is ready for the first Generate step."]
        if isinstance(self._state, dict):
            self._state["blueprintId"] = "baseline"
            self._state["name"] = BLUEPRINTS.get("baseline", {}).get("name", "Baseline")
            self._state["ranked"] = []
            self._state["ragAdvice"] = {}
            self._state["gapAnalysis"] = {}
            self._state["generationCriteria"] = {}
            self._state["planningRun"] = {}

    def _post_scene(self, scene: str, *, reset_demo_state: bool = False):
        try:
            payload = self._twin_payload("scene", scene=scene)
            self._state = self._normalize_api_state(payload)
            if reset_demo_state or scene in {"reset", "growth"}:
                self._clear_demo_runtime_state()
            self._actuator_dirty = False
            self._refresh_ui()
            self._sync_actuator_controls(self._state["actuator"], force=True)
            self._ensure_growth_camera_for_dashboard()
            if reset_demo_state or scene == "reset":
                self._set_status("Demo reset complete: Baseline/current Twin is clean; Generate starts a fresh A/B/C run.")
            else:
                self._set_status(f"SmartFarm Twin scene/{scene} applied to existing farm scene.")
        except Exception as exc:
            if reset_demo_state:
                self._state = self._fallback_state("baseline")
                self._clear_demo_runtime_state()
                self._actuator_dirty = False
                self._refresh_ui()
                self._set_status(f"Demo reset fell back to local Baseline state. Twin API unavailable: {exc}")
            else:
                self._set_status(f"scene/{scene} API failed. Ensure joon.smartfarm.twin service is loaded. {exc}")

    def _apply_blueprint(self, blueprint_id: str):
        self._selected_blueprint = blueprint_id
        current_planning_run = self._state.get("planningRun") if isinstance(self._state.get("planningRun"), Mapping) else {}
        selection_run_id = self._active_generation_run_id or str(current_planning_run.get("runId") or "")
        try:
            payload = self._twin_payload("blueprint", blueprint_id=blueprint_id)
            self._state = self._normalize_api_state(payload)
            self._actuator_dirty = False
            self._record_blueprint_selection(blueprint_id, status="applied", run_id=selection_run_id)
            self._refresh_ui()
            self._sync_actuator_controls(self._state["actuator"], force=True)
            self._ensure_growth_camera_for_dashboard()
            self._set_status(f"Applied {self._state.get('name', blueprint_id)} through existing SmartFarm Twin scene.")
        except Exception as exc:
            self._state = self._fallback_state(blueprint_id)
            self._record_blueprint_selection(blueprint_id, status="fallback-preview", run_id=selection_run_id)
            self._refresh_ui()
            self._set_status(f"Blueprint API failed; panel shows fallback model only. Existing scene not mutated. {exc}")

    def _record_blueprint_generation(self, planning_run: Mapping[str, Any]):
        if not isinstance(planning_run, Mapping) or not planning_run:
            return
        run_id = str(planning_run.get("runId") or "").strip()
        if not run_id:
            return
        rows = self._ordered_plan_rows(include_fallback=False)
        candidates = []
        for row in rows[:3]:
            row_id = str(row.get("blueprintId") or row.get("id") or "")
            candidates.append(
                {
                    "blueprintId": row_id,
                    "label": self._plan_label(row),
                    "score": self._score_value(row),
                    "ship": self._format_ship_delta(row),
                    "opex": self._format_opex(row),
                    "recommended": row_id == str(planning_run.get("recommendedBlueprintId") or ""),
                }
            )
        existing = next((item for item in self._blueprint_generation_history if item.get("runId") == run_id), None)
        if existing is not None:
            existing["candidates"] = candidates
            existing["time"] = existing.get("time") or datetime.now().strftime("%H:%M:%S")
            self._active_generation_run_id = run_id
            return
        previous_selected = self._last_selected_generation()
        entry = {
            "index": len(self._blueprint_generation_history) + 1,
            "runId": run_id,
            "time": datetime.now().strftime("%H:%M:%S"),
            "candidates": candidates,
            "recommendedBlueprintId": planning_run.get("recommendedBlueprintId"),
            "selectedBlueprintId": None,
            "selectedLabel": None,
            "selectedScore": None,
            "selectedShip": None,
            "status": "generated",
            "previousSelectedRunId": previous_selected.get("runId") if previous_selected else None,
            "previousSelectedLabel": previous_selected.get("selectedLabel") if previous_selected else None,
        }
        self._blueprint_generation_history.append(entry)
        self._blueprint_generation_history = self._blueprint_generation_history[-6:]
        self._active_generation_run_id = run_id
        self._append_rag_trace(
            f"Generate history: {run_id} created {len(candidates)} branch candidates; "
            f"previous selection={entry.get('previousSelectedLabel') or 'none'}"
        )

    def _record_blueprint_selection(self, blueprint_id: str, *, status: str, run_id: str | None = None):
        planning_run = self._state.get("planningRun") if isinstance(self._state.get("planningRun"), Mapping) else {}
        row = self._plan_row_by_id(blueprint_id)
        previous = self._blueprint_decision_history[-1] if self._blueprint_decision_history else {}
        run_id = str(run_id or planning_run.get("runId") or self._active_generation_run_id or "").strip()
        generation = self._generation_record_for_selection(run_id)
        entry = {
            "index": len(self._blueprint_decision_history) + 1,
            "blueprintId": blueprint_id,
            "label": self._plan_label(row) if row else _plain_plan_name(None, blueprint_id),
            "runId": run_id or "-",
            "score": self._score_value(row) if row else None,
            "ship": self._format_ship_delta(row) if row else "-",
            "status": status,
            "previousBlueprintId": previous.get("blueprintId"),
            "previousLabel": previous.get("label"),
            "time": datetime.now().strftime("%H:%M:%S"),
        }
        if generation is not None:
            generation["selectedBlueprintId"] = blueprint_id
            generation["selectedLabel"] = entry["label"]
            generation["selectedScore"] = entry["score"]
            generation["selectedShip"] = entry["ship"]
            generation["selectedAt"] = entry["time"]
            generation["status"] = status
        self._blueprint_decision_history.append(entry)
        self._blueprint_decision_history = self._blueprint_decision_history[-8:]
        self._append_rag_trace(
            f"Generate selection: run {entry.get('runId', '-')} selected {entry['label']}; "
            f"previous selected={entry.get('previousLabel') or 'none'} "
            f"({entry['status']}, {entry.get('runId', '-')}, {self._format_score(entry.get('score'))})"
        )
        try:
            self._refresh_blueprint_dag()
        except Exception as exc:
            print(f"[joon.smartfarm.omniops] decision history DAG refresh failed: {exc}")

    def _plan_row_by_id(self, blueprint_id: str) -> Mapping[str, Any]:
        for row in self._ordered_plan_rows(include_fallback=True):
            row_id = str(row.get("blueprintId") or row.get("id") or "")
            if row_id == blueprint_id:
                return row
        return {"blueprintId": blueprint_id, "name": _plain_plan_name(None, blueprint_id)}

    def _last_selected_generation(self) -> Mapping[str, Any]:
        for entry in reversed(self._blueprint_generation_history):
            if entry.get("selectedBlueprintId"):
                return entry
        return {}

    def _generation_record_for_selection(self, run_id: str | None) -> Dict[str, Any] | None:
        if run_id:
            for entry in reversed(self._blueprint_generation_history):
                if entry.get("runId") == run_id:
                    return entry
        if self._blueprint_generation_history:
            return self._blueprint_generation_history[-1]
        pseudo_run_id = run_id or f"manual-{len(self._blueprint_generation_history) + 1:02d}"
        entry = {
            "index": len(self._blueprint_generation_history) + 1,
            "runId": pseudo_run_id,
            "time": datetime.now().strftime("%H:%M:%S"),
            "candidates": [],
            "recommendedBlueprintId": None,
            "selectedBlueprintId": None,
            "selectedLabel": None,
            "selectedScore": None,
            "selectedShip": None,
            "status": "manual",
            "previousSelectedRunId": None,
            "previousSelectedLabel": None,
        }
        self._blueprint_generation_history.append(entry)
        return entry

    def _apply_manual_actuators(self):
        try:
            payload = self._twin_payload("actuator", payload=self._actuator_payload_from_controls())
            self._state = self._normalize_api_state(payload)
            self._actuator_dirty = False
            self._refresh_ui()
            self._sync_actuator_controls(self._state["actuator"], force=True)
            self._ensure_growth_camera_for_dashboard()
            self._set_status("Manual actuator controls applied to the twin.")
        except Exception as exc:
            self._set_status(f"Manual actuator API failed. {exc}")

    def _load_state_from_api(self):
        try:
            payload = self._twin_payload("state")
            self._state = self._normalize_api_state(payload)
            self._actuator_dirty = False
            self._refresh_ui()
            self._sync_actuator_controls(self._state["actuator"], force=True)
            self._ensure_growth_camera_for_dashboard()
            self._set_status("Loaded state from existing SmartFarm Twin API.")
        except Exception as exc:
            self._set_status(f"State API unavailable; using fallback model state. {exc}")

    def _poll_state_from_api(self):
        if self._actuator_dirty:
            return
        try:
            payload = self._twin_payload("state", timeout=2)
            self._state = self._normalize_api_state(payload)
            self._refresh_ui()
            if not self._stage_has_growth_camera():
                self._ensure_growth_camera_for_dashboard()
        except Exception:
            pass

    # -------------------------------------------------------------- API data --

    def _active_twin(self):
        if get_active_extension is None:
            return None
        try:
            return get_active_extension()
        except Exception:
            return None

    def _twin_payload(self, action: str, **kwargs) -> Dict[str, Any]:
        twin = self._active_twin()
        if twin is not None:
            if action == "state":
                return twin.get_state_payload()
            if action == "planning":
                return twin.run_daily_planning_payload(kwargs.get("reason", "omniops"))
            if action == "generate_blueprints":
                return twin.generate_blueprint_payload(
                    goal=kwargs.get("goal", "balanced"),
                    constraints=kwargs.get("constraints") or {},
                    vision_assessment=kwargs.get("vision_assessment"),
                )
            if action == "scene":
                return twin.create_scene_payload(kwargs.get("scene", "growth"))
            if action == "blueprint":
                return twin.apply_blueprint_payload(kwargs.get("blueprint_id", "baseline"))
            if action == "actuator":
                return twin.apply_actuator_payload(kwargs.get("payload", {}))
            raise ValueError(f"Unknown twin action: {action}")

        if action == "state":
            return self._request_json("GET", f"{TWIN_API_BASE}/state", timeout=kwargs.get("timeout", 12))
        if action == "planning":
            return self._request_json("POST", f"{TWIN_API_BASE}/planning/run", {"reason": kwargs.get("reason", "omniops")})
        if action == "generate_blueprints":
            return self._request_json(
                "POST",
                f"{TWIN_API_BASE}/blueprint/generate",
                {
                    "reason": kwargs.get("reason", "omniops"),
                    "goal": kwargs.get("goal", "balanced"),
                    "constraints": kwargs.get("constraints") or {},
                    "visionAssessment": kwargs.get("vision_assessment"),
                },
                timeout=kwargs.get("timeout", 40),
            )
        if action == "scene":
            return self._request_json("POST", f"{TWIN_API_BASE}/scene/{kwargs.get('scene', 'growth')}", {})
        if action == "blueprint":
            return self._request_json("POST", f"{TWIN_API_BASE}/blueprint/apply", {"blueprintId": kwargs.get("blueprint_id", "baseline")})
        if action == "actuator":
            return self._request_json("POST", f"{TWIN_API_BASE}/actuator/apply", kwargs.get("payload", {}))
        raise ValueError(f"Unknown twin action: {action}")

    def _request_json(
        self, method: str, url: str, body: Mapping[str, Any] | None = None, timeout: float = 12
    ) -> Dict[str, Any]:
        data = None if method == "GET" else json.dumps(body or {}).encode("utf-8")
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return json.loads(res.read().decode("utf-8"))

    def _normalize_api_state(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        blueprint_id = payload.get("appliedBlueprintId") or "baseline"
        fallback = self._fallback_state(str(blueprint_id))
        sensor_api = payload.get("sensorState") or {}
        actuator_api = payload.get("actuatorState") or {}
        crop = payload.get("cropState") or fallback["crop"]
        kpi = payload.get("growthKpi") or fallback["kpi"]
        result = payload.get("result") or {}
        recommendation = payload.get("recommendation") or {}
        scores = recommendation.get("scores") or fallback["ranked"]
        planning_run = payload.get("planningRun") or {}
        rag_advice = payload.get("ragAdvice") or planning_run.get("ragAdvice") or {}
        gap_analysis = payload.get("gapAnalysis") or planning_run.get("gapAnalysis") or {}
        generation_criteria = payload.get("generationCriteria") or planning_run.get("generationCriteria") or {}
        sensor = {
            "scenario_seed": sensor_api.get("scenarioSeed", fallback["sensor"]["scenario_seed"]),
            "twin_day": sensor_api.get("twinDay", fallback["sensor"]["twin_day"]),
            "crop_stage": sensor_api.get("cropStage", fallback["sensor"]["crop_stage"]),
            "growth_index": sensor_api.get("growthIndex", fallback["sensor"]["growth_index"]),
            "dli_mol_m2_day": sensor_api.get("dliMolM2Day", fallback["sensor"]["dli_mol_m2_day"]),
            "substrate_moisture_percent": sensor_api.get("soilMoisturePercent", fallback["sensor"]["substrate_moisture_percent"]),
            "humidity_percent": sensor_api.get("humidityPercent", fallback["sensor"]["humidity_percent"]),
            "temperature_c": sensor_api.get("temperatureC", fallback["sensor"]["temperature_c"]),
            "co2_ppm": sensor_api.get("co2Ppm", fallback["sensor"]["co2_ppm"]),
            "disease_risk": sensor_api.get("diseaseRisk", fallback["sensor"]["disease_risk"]),
        }
        actuator = {
            "led_intensity_percent": actuator_api.get("ledIntensityPercent", fallback["actuator"]["led_intensity_percent"]),
            "photoperiod_hours": actuator_api.get("photoperiodHours", fallback["actuator"]["photoperiod_hours"]),
            "water_valve_open": actuator_api.get("waterValveOpen", fallback["actuator"]["water_valve_open"]),
            "irrigation_pulses_per_day": actuator_api.get("irrigationPulsesPerDay", fallback["actuator"]["irrigation_pulses_per_day"]),
            "fan_duty_percent": actuator_api.get("fanDutyPercent", fallback["actuator"]["fan_duty_percent"]),
            "co2_ppm": actuator_api.get("co2Ppm", fallback["actuator"]["co2_ppm"]),
        }
        normalized_crop = {
            "day": crop.get("day", fallback["crop"]["day"]),
            "vegetativeGrowth": crop.get("vegetativeGrowth", fallback["crop"]["vegetativeGrowth"]),
            "flowering": crop.get("flowering", fallback["crop"]["flowering"]),
            "fruitSet": crop.get("fruitSet", fallback["crop"]["fruitSet"]),
            "fruitMaturity": crop.get("fruitMaturity", fallback["crop"]["fruitMaturity"]),
            "diseasePressure": crop.get("diseasePressure", fallback["crop"]["diseasePressure"]),
            "estimatedYield": crop.get("estimatedYield", fallback["crop"]["estimatedYield"]),
        }
        timeline = payload.get("timeline") or project_days(sensor, actuator, range(0, 22, 3))
        evidence = list(kpi.get("evidence", []))
        if rag_advice:
            stage = rag_advice.get("growthStage", "-")
            evidence.insert(0, f"Gemma/RAG provider {rag_advice.get('provider', '-')} · growth stage {stage}")
            sources = rag_advice.get("evidence") or []
            if sources:
                evidence.insert(1, f"RAG sources: {len(sources)} document chunks; first: {sources[0].get('summary', sources[0])}")
        if gap_analysis:
            for factor in list(gap_analysis.get("limitingFactors") or [])[:2]:
                evidence.append(f"Gap: {factor}")
        return {
            **fallback,
            "blueprintId": blueprint_id,
            "name": result.get("blueprintName") or fallback["name"],
            "sceneMode": payload.get("sceneMode", "unknown"),
            "smartFarmPath": payload.get("smartFarmPath", SMART_FARM_PATH),
            "sensor": sensor,
            "actuator": actuator,
            "crop": normalized_crop,
            "kpi": kpi,
            "evidence": evidence,
            "ranked": scores,
            "timeline": timeline,
            "ragAdvice": rag_advice,
            "gapAnalysis": gap_analysis,
            "generationCriteria": generation_criteria,
            "planningRun": planning_run,
        }

    def _fallback_state(self, blueprint_id: str) -> Dict[str, Any]:
        if blueprint_id not in BLUEPRINTS:
            blueprint_id = "baseline"
        state = state_for_blueprint(blueprint_id)
        return {**state, "sceneMode": "fallback", "smartFarmPath": SMART_FARM_PATH}

    def _stage_has_existing_farm(self) -> bool:
        stage = omni.usd.get_context().get_stage()
        return bool(stage and stage.GetPrimAtPath(SMART_FARM_PATH))

    def _stage_has_growth_camera(self) -> bool:
        stage = omni.usd.get_context().get_stage()
        return bool(stage and stage.GetPrimAtPath(GROWTH_CAMERA_PATH))
