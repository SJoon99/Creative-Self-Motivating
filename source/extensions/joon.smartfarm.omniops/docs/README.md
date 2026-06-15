# Smart Farm OmniOps

Omniverse-first operator UI for the existing strawberry smart farm digital twin.

This extension intentionally keeps the previous Web/K8S implementation intact and does **not** create a replacement farm scene. It loads alongside `joon.smartfarm.twin` and controls the existing `/World/SmartFarm` scene. WebRTC is only the remote screen transport.

## Evaluator/demo UX

- **Layer-tab operator panel from startup**: `SmartFarm OmniOps Dock` is docked as a selectable tab beside the existing `Layer` panel, so the evaluator can switch between scene Layer and OmniOps controls.
- **Existing SmartFarm twin scene**: all visual changes still happen under `/World/SmartFarm` from `joon.smartfarm.twin`.
- **Virtual Sensors live trend**: DLI, substrate moisture, humidity, temperature, and CO₂ are plotted as rolling line graphs.
- **Actuator controls**: LED intensity, photoperiod, irrigation pulses, fan duty, CO₂ setpoint, and water valve are controllable from the same right panel.
- **Blueprint operations**: Baseline is the fixed current-state twin. Plan A / Plan B / Plan C are neutral generated-plan display slots, not fixed strategy classes.
- **Touch-first operator cockpit**: the right `SmartFarm OmniOps Dock` keeps only information and controls the operator is expected to click/touch during the demo.
- **Bottom 7:3 evidence layout**: `SmartFarm Evidence` is the dominant dashboard split and `SmartFarm Strawberry Live View` is a separate right-side live viewport split. The intended bottom ratio is dashboard 7 : live strawberry camera 3, while preserving the accepted camera framing.
- **Growth Camera / Gemma vision**: `Capture & Analyze Growth` creates/uses a virtual strawberry phenotype camera, captures a PNG, and sends it to a configured Gemma/RAG vision endpoint. If the endpoint is not configured or fails, it falls back to a deterministic provider-ready assessment and records that fallback in the sidecar metadata.
- **WebRTC**: browser viewing is a stream of the Omniverse app, not a separate product UI.

## Docking note

The OmniOps window starts hidden and is made visible only after Kit can immediately dock it into the existing `Layer` dock stack. If the target is not ready, the extension hides the window again before the next draw frame, preventing the previous floating popup layout from being persisted. After docking, OmniOps keeps the dock tab bar visible/enabled so it appears as a normal selectable neighbor tab next to `Layer`; only stock Property/Details panes are hidden when they are not used as a fallback target.

`SmartFarm Evidence` follows the same no-popup rule and attempts to dock into the bottom Console/Content stack. The intended information architecture is:

- right side: operator actions and compact growth state
- bottom side: explanation/ranking dashboard plus a separate live strawberry camera viewport

The evidence dashboard is intentionally visual:

- top cards: recommended blueprint score, applied twin health, Gemma/RAG run status, and latest growth-camera progress
- simulation timeline: projected maturity bars with DLI, disease pressure, and yield context
- blueprint scoreboard: Plan A/B/C rows show `score /100` from twin simulation ranking, `ship -Nd` vs the current Baseline harvest date, OpEx, yield, and risk explanation
- generated candidates are scored first, then the score ranks rotate through Plan A/B/C on successive Generate clicks so one letter does not permanently look like the bad plan
- if a generated candidate is clearly infeasible in the Twin (`0`/very low score, high disease risk, or no harvest inside the horizon), a transparent one-pass Twin quality gate repairs airflow/light/CO2, re-simulates it, and preserves the original score/actuators in the JSON trace
- each Plan A/B/C row includes operator intent, control focus, AI source (`Gemma/RAG`, `Twin simulator`, or fallback), and tradeoff text so the evaluator can understand why the plan exists instead of seeing only a score
- human-facing Gemma/RAG text is requested as English ASCII and non-ASCII fallback text is replaced before rendering, because the current Omniverse UI can display unsupported glyphs as `?`.
- vision assessment: crop-camera assessment with source/confidence, whole-cycle growth progress %, and phenotype traits. The UI says `Gemma vision` only for a successful Gemma/RAG vision response; otherwise it says `Local fallback`.
- blueprint trace: every Generate Gemma/RAG Blueprints run writes `logs/smartfarm-blueprints/<timestamp>_<runId>.json` with `planningRun`, `ragAdvice`, `gapAnalysis`, ranked candidates, the RAG request trace, and the vision assessment used as input.
- `SmartFarm RAG Trace` selectable bottom tab: compact terminal-style proof lines for the last Generate click, including endpoint path/status, request context, sensor values sent, RAG source count, gap factors, Plan A/B/C simulation scores, and the saved JSON trace path. The same lines append to `logs/smartfarm-blueprints/rag-trace.log` for a separate terminal view.
- operator log: compact event timeline for demo auditability

## Manual actuator projection

Manual actuator changes are no longer only visual setpoint edits. The OmniOps panel now derives a plausible synthetic sensor/crop projection from the current actuator values:

- LED + photoperiod increase DLI and can raise temperature.
- Irrigation pulses and valve state raise substrate moisture and can raise humidity.
- Fan duty lowers humidity/disease pressure and slightly cools the crop zone.
- CO₂ setpoint changes the synthetic CO₂ sensor and contributes to growth index.

While moving sliders, OmniOps shows a local `manual-actuator-preview` so the sensor graphs and KPI cards react immediately. Pressing `Apply Manual Controls` sends the same actuator recipe to the live SmartFarm Twin, mutates the USD scene, and returns the applied sensor/crop state from the twin service.

## Architecture note

`joon.smartfarm.omniops` prefers an in-process bridge to the live `joon.smartfarm.twin` extension when both extensions are loaded in the same Kit process. This avoids same-process HTTP self-call deadlocks from the Kit update loop.

The HTTP API remains available for external clients and smoke checks:

```txt
GET  http://127.0.0.1:8011/smartfarm/state
POST http://127.0.0.1:8011/smartfarm/scene/growth
POST http://127.0.0.1:8011/smartfarm/scene/reset
POST http://127.0.0.1:8011/smartfarm/planning/run
POST http://127.0.0.1:8011/smartfarm/blueprint/apply
POST http://127.0.0.1:8011/smartfarm/actuator/apply
```

## Target workflow

1. Develop and test in environment 1: NUC/node + Sandbox-Infra.
2. After validation, port stable app/extension to environment 2: ARM Spark + TwinX.

## Run

GUI development run:

```bash
cd /home/joon/kit-app-template
./scripts/smartfarm-omniops-dev.sh
```

WebRTC stream run:

```bash
cd /home/joon/kit-app-template
./scripts/smartfarm-omniops-streaming.sh
```

Smoke test:

```bash
cd /home/joon/kit-app-template
./scripts/smartfarm-omniops-smoke.sh
```

## Expected startup state

- Main window: `SmartFarm OmniOps Composer`
- Scene root: `/World/SmartFarm`
- Right-side tab: `SmartFarm OmniOps Dock`, selectable beside `Layer`
- Bottom tab: `SmartFarm Evidence`, selectable beside Console/Content
- Initial twin state: current/growth Baseline, not a fully mature final-only view
- Stock Property panel: hidden unless needed as a fallback dock target

## Growth Camera scope

The current POC implements steps 1-4 of the camera story only:

1. Keep the right Dock action-focused.
2. Move evidence/score/log content to the bottom evidence panel.
3. Add a virtual crop-facing camera at `/World/SmartFarm/Cameras/GrowthPhenotypeCamera`.
4. Provide `Capture & Analyze Growth` that writes capture metadata under `logs/smartfarm-vision/` and calls the configured Gemma/RAG vision endpoint when available.

Configuration:

- `SMARTFARM_VISION_BASE_URL` or `SMARTFARM_RAG_BASE_URL`
- optional `SMARTFARM_VISION_ANALYZE_PATH` (default tries `/vision/analyze`, `/analyze/growth`, `/phenotype/analyze`, `/analyze`)
- optional `SMARTFARM_VISION_TOKEN` / `SMARTFARM_RAG_TOKEN`

Out of scope for this phase:

- real farm IP camera ingestion
- Twin-vs-real-world divergence correction/assimilation
## Locked Growth Camera view

Current demo view is locked as the accepted crop phenotype camera baseline:

```txt
Camera path: /World/SmartFarm/Cameras/GrowthPhenotypeCamera
Focal length: 38.0
Aperture: 32.0 x 18.0
Clip range: 0.05 - 9.0
Position: (-26.2, 1.75, -17.5)
Look-at target: (-29.0, 1.50, -15.2)
Visual scale: 0.006
Soft fill: /World/SmartFarm/Cameras/GrowthPhenotypeFillLight, intensity 90.0
Bottom layout: SmartFarm Evidence dashboard 7 + SmartFarm Strawberry Live View 3
```

Do not keep tuning this view unless the evaluator/demo camera framing changes.
