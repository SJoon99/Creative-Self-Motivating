# SmartFarm / TwinX Gemma-RAG POC Agent Handoff

_Last updated: 2026-06-15 KST_

This document is a shareable handoff for people or agents who have never seen this project.  It explains what has been implemented, what the demo currently proves, how the TwinX/GitOps/Gemma/RAG environment is wired, what every major sensor/actuator/plan field means, and how the scoring/ranking logic works.

> **Do not confuse this file with `AGENTS.md`.**  `AGENTS.md` is the runtime instruction file for coding agents.  This `Agent.md` is a human/agent project handoff for the SmartFarm POC.

> **Distribution classification:** shareable technical handoff.  Concrete internal hosts, SSH users, Kubernetes namespaces, LoadBalancer IPs, token file paths, and private GitOps paths are intentionally redacted as placeholders.  Operators should resolve placeholders from the secured runbook, environment variables, or cluster inventory.

---

## Table of contents

1. [One-sentence product concept](#1-one-sentence-product-concept)
2. [Current implementation status](#2-current-implementation-status)
3. [Mental model](#3-mental-model)
4. [Repositories, machines, and services](#4-repositories-machines-and-services)
5. [Key local files and responsibilities](#5-key-local-files-and-responsibilities)
6. [User-facing Omniverse UI](#6-user-facing-omniverse-ui)
7. [Baseline vs Plan A/B/C](#7-baseline-vs-plan-abc)
8. [Baseline sensor/crop/actuator data](#8-baseline-sensorcropactuator-data)
9. [Static legacy Plan A/B/C presets](#9-static-legacy-plan-abc-presets)
10. [State response contract](#10-state-response-contract)
11. [Growth KPI meanings and formulas](#11-growth-kpi-meanings-and-formulas)
12. [Synthetic sensor/crop model](#12-synthetic-sensorcrop-model)
13. [Gemma/RAG Blueprint generation contract](#13-gemmarag-blueprint-generation-contract)
14. [Gap analysis](#14-gap-analysis)
15. [Candidate generation fallback paths](#15-candidate-generation-fallback-paths)
16. [Rolling-horizon twin simulation](#16-rolling-horizon-twin-simulation)
17. [Candidate score meaning](#17-candidate-score-meaning)
18. [Static fallback score formula](#18-static-fallback-score-formula)
19. [Applying plans](#19-applying-plans)
20. [Growth camera and blue-sky scene settings](#20-growth-camera-and-blue-sky-scene-settings)
21. [Capture & Analyze Growth](#21-capture--analyze-growth)
22. [What `Gemma live` proves](#22-what-gemma-live-proves)
23. [Logs and evidence files](#23-logs-and-evidence-files)
24. [Direct Omniverse browser viewer](#24-direct-omniverse-browser-viewer)
25. [How to run and verify locally](#25-how-to-run-and-verify-locally)
26. [Demo script for class or stakeholder review](#26-demo-script-for-class-or-stakeholder-review)
27. [Troubleshooting](#27-troubleshooting)
28. [Known risks and next steps](#28-known-risks-and-next-steps)
29. [Glossary](#29-glossary)
30. [Minimal command reference](#30-minimal-command-reference)

## 1. One-sentence product concept

The service shows the **current strawberry farm state as a fixed Baseline inside an Omniverse digital twin**, asks a **Gemma + RAG foundation-model service** to generate three alternative control Blueprints (`Plan A`, `Plan B`, `Plan C`) from the current sensor/crop/camera context, then validates those Blueprints through the local twin simulator to choose the plan that can ship strawberries earliest while keeping yield, cost, and disease risk acceptable.

---

## 2. Current implementation status

### Working now

- Omniverse SmartFarm scene exists at `/World/SmartFarm`.
- Baseline/current state is fixed as the current twin state, not a generated plan.
- `Generate Gemma/RAG Blueprints` now calls the real TwinX RAG API when the streaming app is launched with the project scripts.
- TwinX RAG API returns three Gemma/RAG-generated candidates; the local Twin maps them into neutral UI slots `Plan A`, `Plan B`, `Plan C`.
- Local twin validates and scores the returned candidates using a rolling-horizon growth/disease/cost simulation.
- If a generated candidate is clearly infeasible, the Twin quality gate repairs airflow/light/CO2 once, re-simulates the repaired candidate, and preserves the original Gemma score/actuators in the JSON trace.
- Dashboard shows:
  - recommended plan,
  - applied plan,
  - Gemma/RAG run status,
  - plan explanations,
  - a live Growth Camera viewport,
  - a selectable RAG Trace panel for classroom/demo proof.
- Growth camera capture writes PNG/JSON sidecars and sends image bytes to the TwinX vision endpoint when `SMARTFARM_RAG_BASE_URL` or `SMARTFARM_VISION_BASE_URL` is configured.
- TwinX GitOps includes the RAG trace and vision endpoints.
- The local streaming process currently has the RAG environment configured.

### Important POC limitation

- **True Gemma image understanding is not active yet.**  The Twinx `/vision/analyze` endpoint receives the PNG and attempts a Gemma vision call, but the current `gemma4` vLLM deployment rejects image prompts with an error equivalent to `At most 0 image(s) may be provided in one prompt.`  Therefore the vision endpoint returns `analysisMode=gemma_vision_fallback` and preserves the deterministic virtual-camera phenotype estimate.
- This is intentionally exposed in the UI/logs as `Gemma request + fallback`, not hidden.

---

## 3. Mental model

```text
User clicks Generate
        |
        v
OmniOps UI extension
source/extensions/joon.smartfarm.omniops/...
        |
        | local in-process call or HTTP POST
        v
SmartFarm Twin extension API
127.0.0.1:8011/smartfarm/blueprint/generate
source/extensions/joon.smartfarm.twin/...
        |
        | builds Baseline snapshot:
        | sensor + crop + actuator + growth KPI + optional camera analysis
        v
TwinX RAG service
http://<TWINX_RAG_LB>:<RAG_PORT>/blueprints/generate
K8s namespace: <K8S_NAMESPACE>, deployment: <RAG_SERVICE_NAME>
        |
        | retrieves strawberry docs from ChromaDB,
        | calls Gemma/vLLM, returns 3 Blueprint candidates
        v
Local Twin simulator
- applies actuator bounds
- simulates daily fruit maturity / disease / yield / cost
- scores Plan A/B/C
        |
        v
OmniOps Dashboard + RAG Trace
- Plan cards
- explanation
- request/response proof
- saved JSON sidecar
```

Vision/camera flow:

```text
User clicks Capture & Analyze Growth
        |
        v
Omniverse GrowthPhenotypeCamera captures PNG
logs/smartfarm-vision/*.png
        |
        v
OmniOps sends base64 image + sensor/crop context
TwinX /vision/analyze, /analyze/growth, /phenotype/analyze, or /analyze
        |
        v
Current state: Gemma image call fails because deployed model is text-only.
TwinX returns gemma_vision_fallback + deterministic fallback assessment.
        |
        v
UI shows health/progress/risk and trace shows endpoint/http/auth/image bytes/fallback reason.
```

---

## 4. Repositories, machines, and services

### Local SmartFarm / Omniverse repo

| Item | Value |
| --- | --- |
| Local repo | `/home/user/kit-app-template` |
| Main app family | NVIDIA Omniverse Kit app template customized with SmartFarm extensions |
| OmniOps extension | `source/extensions/joon.smartfarm.omniops` |
| Twin/service extension | `source/extensions/joon.smartfarm.twin` |
| Streaming launcher | `scripts/smartfarm-omniops-streaming.sh` |
| Common SmartFarm env launcher | `scripts/smartfarm-twin-common.sh` |
| Local SmartFarm API | `http://127.0.0.1:8011/smartfarm` |
| Local WebRTC signaling | `49100/TCP` |
| Local WebRTC media | `47998/UDP` |
| Live tmux session observed | `smartfarm_streaming` |

Current streaming process environment was verified with `/proc/<kit-pid>/environ`:

```text
SMARTFARM_APP_HOME=/home/user/kit-app-template
SMARTFARM_RAG_BASE_URL=http://<TWINX_RAG_LB>:<RAG_PORT>
SMARTFARM_RAG_TIMEOUT=30
SMARTFARM_RAG_TOKEN_FILE=<SMARTFARM_RAG_TOKEN_FILE>
```

The key fix was that `scripts/smartfarm-omniops-streaming.sh` now sources `scripts/smartfarm-twin-common.sh`.  Without that, the streaming app could start without `SMARTFARM_RAG_BASE_URL` and `Generate` would use offline deterministic fallback.

### TwinX / GitOps environment

| Item | Value |
| --- | --- |
| SSH host | `ssh <TWINX_SSH_USER>@<TWINX_OPS_HOST>` |
| GitOps repo on host | `<TWINX_OPS_REPO>` |
| K8s namespace | `<K8S_NAMESPACE>` |
| RAG service | `<RAG_SERVICE_NAME>` |
| RAG service LB | `<TWINX_RAG_LB>:<RAG_PORT>` |
| Gemma service | `<GEMMA_VLLM_SERVICE>` |
| Gemma internal service | `<GEMMA_VLLM_SERVICE>.<K8S_NAMESPACE>.svc.cluster.local:<GEMMA_PORT>/v1` |
| Omniverse direct viewer | `<OMNIVERSE_VIEWER_SERVICE>` |
| Viewer LB observed | `<OMNIVERSE_VIEWER_LB>:<VIEWER_PORT>` |

Observed K8s status on 2026-06-15:

```text
deployment.apps/<GEMMA_VLLM_SERVICE>        1/1
deployment.apps/<GEMMA_AUTH_PROXY_DEPLOYMENT> 1/1
deployment.apps/<OMNIVERSE_VIEWER_SERVICE>  1/1
deployment.apps/<RAG_SERVICE_NAME>          1/1
service/<GEMMA_VLLM_SERVICE>        ClusterIP      <GEMMA_PORT>/TCP
service/<GEMMA_BACKEND_SERVICE>     ClusterIP      <GEMMA_PORT>/TCP
service/<OMNIVERSE_VIEWER_SERVICE>  LoadBalancer   <OMNIVERSE_VIEWER_LB>   <VIEWER_PORT>/TCP
service/<RAG_SERVICE_NAME>          LoadBalancer   <TWINX_RAG_LB>   <RAG_PORT>/TCP
```

Recent GitOps changes relevant to this POC include:

- RAG call trace exposure for SmartFarm demos.
- SmartFarm Gemma vision-analysis endpoint aliases.
- Direct Omniverse viewer deployment under the project GitOps app tree.
- Direct viewer configuration pointing at the SmartFarm twin stream.

Concrete commit hashes belong in the secured operator runbook, not this shareable handoff.

### TwinX RAG server source

Remote file:

```text
<TWINX_OPS_REPO>/argocd/multi-tenancy/apps/<K8S_NAMESPACE>/apps/<RAG_SERVICE_NAME>/files/rag_server.py
```

Important RAG server environment defaults:

| Env | Default / role |
| --- | --- |
| `RAG_REPO_DIR` | `/data/repo` |
| `DB_DIR` | `/data/repo/chroma_db` |
| `TABLE_PATH` | `/data/repo/setpoints_table.json` |
| `COLLECTION_NAME` | `strawberry_manual` |
| `EMBEDDING_MODEL` | `BAAI/bge-m3` |
| `LLM_MODEL` | `gemma4` |
| `OPENAI_BASE_URL` | `http://<GEMMA_VLLM_SERVICE>.<K8S_NAMESPACE>.svc.cluster.local:<GEMMA_PORT>/v1` |
| `RAG_API_TOKEN` | bearer token expected unless `RAG_ALLOW_NO_AUTH=true` |
| `TOP_K` | default `5` |

Important RAG endpoints:

| Endpoint | Role |
| --- | --- |
| `GET /livez` | liveness |
| `GET /healthz` | readiness, model and Chroma collection count |
| `POST /ask` | free-form RAG QA |
| `POST /recommend` | legacy date/stage setpoint recommendation |
| `POST /blueprints/generate` | state-aware Blueprint A/B/C generation |
| `POST /vision/analyze` | growth-camera image analysis contract |
| `POST /analyze/growth` | alias for vision analysis |
| `POST /phenotype/analyze` | alias for vision analysis |
| `POST /analyze` | alias for vision analysis |

---

## 5. Key local files and responsibilities

| File | Responsibility |
| --- | --- |
| `source/extensions/joon.smartfarm.omniops/joon/smartfarm/omniops/extension.py` | Omniverse UI, dock panels, dashboard, RAG trace, growth camera, capture button, calls into Twin API. |
| `source/extensions/joon.smartfarm.omniops/joon/smartfarm/omniops/model.py` | UI-side fallback/static POC model for Baseline, static Plan A/B/C, synthetic sensor/crop/KPI formulas, virtual-camera fallback estimator. |
| `source/extensions/joon.smartfarm.twin/joon/smartfarm/twin/extension.py` | Digital twin scene authoring, SmartFarm HTTP API, Baseline/current state, Generate flow, Apply flow, daily simulation, scoring, candidate publication. |
| `source/extensions/joon.smartfarm.twin/joon/smartfarm/twin/rag_adapter.py` | Pure-Python TwinX RAG client, request body contract, response normalization, gap analysis, legacy candidate fallback generation. |
| `scripts/smartfarm-twin-common.sh` | Shared launch defaults, including RAG API URL/token file/timeouts and ports. |
| `scripts/smartfarm-omniops-streaming.sh` | Headless streaming OmniOps launcher; now sources the common env. |
| `web/omniverse-direct-viewer` | Minimal browser page that only connects to the Omniverse WebRTC stream. |
| `logs/smartfarm-blueprints` | Generated planning/RAG trace JSON files and `rag-trace.log`. |
| `logs/smartfarm-vision` | Captured growth-camera PNG files and vision sidecar JSON. |

---

## 6. User-facing Omniverse UI

### Right dock: `SmartFarm OmniOps Dock`

Main controls and readouts:

- Scene mode and active Blueprint.
- Growth Status cards:
  - `Health`
  - `Maturity`
  - `Ready`
  - expected ship date
  - disease risk
  - main limiting factor
- Virtual sensor trend graphs.
- Actuator controls:
  - LED intensity
  - photoperiod
  - irrigation pulses
  - fan duty
  - CO2 setpoint
  - water valve
- Blueprint buttons:
  - `Plan A`
  - `Plan B`
  - `Plan C`
- Control buttons:
  - `Create Current Twin`
  - `Reset Baseline`
  - `Run Daily Planning`
  - `Refresh State`
  - `Generate Gemma/RAG Blueprints`
  - `Apply Recommended`
- Growth Camera section:
  - camera path
  - last capture
  - vision health
  - growth progress
  - vision risk
  - `Focus Growth Camera`
  - `Capture & Analyze Growth`

### Bottom dock: `SmartFarm Evidence`

The Kit window title is `SmartFarm Evidence`; the header text inside the panel is `SmartFarm Evidence Dashboard`.  This is the main demonstration panel.

- Top metric cards:
  - Recommended Plan
  - Applied Plan
  - Gemma/RAG Run
  - Growth Camera
- Plan explanation area:
  - all generated Plan A/B/C cards shown side by side,
  - score,
  - ship delta,
  - controls,
  - rationale/tradeoff text.
- Embedded Growth Camera live viewport on the right/lower side.

### Bottom neighboring tab: `SmartFarm RAG Trace`

This panel is for class/demo verification.  It shows proof lines such as:

- which Twin API was called,
- whether a vision assessment was attached,
- TwinX RAG endpoint path,
- HTTP status,
- URL,
- auth configured yes/no,
- request sensor values,
- provider/model/source count,
- gap factors and gap score,
- each plan's score/ship/control summary,
- saved JSON trace path,
- recommended plan id.

It also appends to:

```text
logs/smartfarm-blueprints/rag-trace.log
```

---

## 7. Baseline vs Plan A/B/C

### Baseline meaning

**Baseline is the current twin state.  It is fixed as the representation of the current farm, not a generated plan candidate.**

This matters because the service goal is:

1. Show the current state in the twin.
2. Use current sensor/crop/camera evidence to reduce the gap between real farm and AI assumptions.
3. Ask Gemma/RAG for alternative Blueprints.
4. Validate those Blueprints by simulation.

Baseline should not be remapped to labels like `gemma-rag-balanced`, and it should not be selected as Plan A/B/C.

### Generated plan meaning

`Plan A`, `Plan B`, and `Plan C` are neutral display slots for the three candidate Blueprints generated from the current Baseline.  The labels are intentionally plain in the UI; suffixes such as `low cost`, `early shipment`, or `disease safe` are hidden from the button labels.

The letters are **not fixed strategy classes**.  After generation, the Twin scores the candidates, then rotates score ranks through Plan A/B/C on successive Generate clicks.  This prevents one letter from always looking like the bad plan while still keeping the real score and source-candidate id in the trace.

Internally the IDs may be one of:

| UI label | Static legacy id | Generated id |
| --- | --- | --- |
| Plan A | `plan-a-low-cost` | `blueprint-a` |
| Plan B | `plan-b-early-shipment` | `blueprint-b` |
| Plan C | `plan-c-disease-safe` | `blueprint-c` |

The generated IDs are runtime candidates from Gemma/RAG plus local Twin validation.  After generation and optional quality-gate repair, the Twin publishes them into the same runtime registry used by Apply, so clicking Plan A/B/C applies the generated candidate state rather than only the old static preset.

### State taxonomy

| Category | Baseline / current state | Static legacy fallback | Generated runtime candidate |
| --- | --- | --- | --- |
| Owner | SmartFarm Twin current-state service | Local deterministic POC model | TwinX Gemma/RAG + local Twin validator |
| Mutability | Fixed anchor for the current run; reset returns here | Code-defined presets used only when no live run exists | Recreated each Generate click from current snapshot |
| Source of truth | Current sensor/crop/actuator snapshot in the Twin | `model.py` and legacy service summary tables | `planningRun.candidates[]` from `/blueprints/generate`, then normalized by `rag_adapter.py` |
| UI label | `Baseline` / active current twin | `Plan A/B/C` fallback labels | `Plan A/B/C` live labels |
| Apply path | Reset/current-state representation, not a generated candidate | Apply buttons before a live run | Apply buttons after `_publish_planning_candidates(...)` |
| Product meaning | What the farm looks like now | Demo-safe fallback if AI/RAG is unavailable | The actual AI-proposed Blueprint alternatives to simulate and compare |

When sharing screenshots, always identify the mode: `current Baseline`, `static fallback`, `live Gemma/RAG`, or `vision fallback`.  The same visible labels `Plan A/B/C` can refer to static fallback rows or generated runtime candidates depending on whether a live planning run exists.

---

## 8. Baseline sensor/crop/actuator data

The initial Baseline sensor state is defined in `model.py` and mirrored by the Twin extension.

| Field | Baseline value | Meaning |
| --- | ---: | --- |
| `scenario_seed` | `cloudy-winter-low-light` | Synthetic scenario identifier. |
| `twin_day` | `34` | Crop day used by the POC. |
| `crop_stage` | `flowering_delayed_fruit_set` | Current stage label. |
| `growth_index` | `0.42` | Synthetic compact growth indicator. |
| `dli_mol_m2_day` | `11.2` | Daily light integral. Low for fast strawberry forcing. |
| `substrate_moisture_percent` | `31` | Root-zone/substrate moisture. Low. |
| `humidity_percent` | `82` | Relative humidity. High disease pressure. |
| `temperature_c` | `24.8` | Greenhouse temperature. |
| `co2_ppm` | `420` | Ambient-ish CO2. Low for enriched forcing. |
| `disease_risk` | `high` | Derived disease risk label. |

Baseline actuator state:

| Field | Baseline value | Meaning |
| --- | ---: | --- |
| `led_intensity_percent` | `40` | LED output. |
| `photoperiod_hours` | `12` | Light hours/day. |
| `water_valve_open` | `false` | Irrigation valve state. |
| `irrigation_pulses_per_day` | `1` | Irrigation events/day. |
| `fan_duty_percent` | `20` | Airflow/fan duty. |
| `co2_ppm` | `420` | CO2 setpoint. |

Baseline forecast summary:

| Field | Value |
| --- | --- |
| expected ship | `2027-01-06` in the static UI model; rolling-horizon Twin can project later if harvest criteria fail. |
| yield score | `72` static fallback value |
| OpEx delta | `0%` |
| operator meaning | current operation projected from today's sensor state |

---

## 9. Static legacy Plan A/B/C presets

These still exist as fallback/defaults when no live generated planning run exists.

| Field | Plan A | Plan B | Plan C |
| --- | --- | --- | --- |
| Internal id | `plan-a-low-cost` | `plan-b-early-shipment` | `plan-c-disease-safe` |
| UI label | `Plan A` | `Plan B` | `Plan C` |
| Legacy intent | cost-sensitive recovery | earliest shipment push | disease safety margin |
| DLI | `13.5` | `17.8` | `15.4` |
| moisture | `42%` | `48%` | `45%` |
| humidity | `72%` | `68%` | `62%` |
| temperature | `23.2C` | `23.6C` | `22.8C` |
| CO2 | `500 ppm` | `650 ppm` | `580 ppm` |
| disease risk | controlled | controlled | low |
| LED | `55%` | `80%` | `70%` |
| photoperiod | `13h` | `16h` | `15h` |
| irrigation | `3/day` | `3/day` | `4/day` |
| fan | `35%` | `55%` | `70%` |
| expected ship | `2027-01-01` | `2026-12-22` | `2026-12-28` |
| yield score | `79` | `87` | `83` |
| OpEx delta | `-6%` | `+18%` | `+9%` |

Again: when live Gemma/RAG generation succeeds, generated candidates replace the static strategy meaning for that run while keeping only the visible labels `Plan A/B/C`.

---

## 10. State response contract

The SmartFarm Twin API returns this high-level shape from `/smartfarm/state`, `/smartfarm/blueprint/generate`, `/smartfarm/planning/run`, and apply endpoints:

```jsonc
{
  "ok": true,
  "message": "...",
  "sceneMode": "...",
  "hasStage": true,
  "smartFarmPath": "/World/SmartFarm",
  "appliedBlueprintId": "baseline | blueprint-a | ...",
  "view": {
    "defaultCameraPath": "...",
    "serviceUiVisible": true
  },
  "simulation": {
    "fastPlaybackSeconds": 7,
    "timelineStartDay": 0,
    "timelineEndDay": 60
  },
  "rendering": {
    "fixedExposure": "..."
  },
  "sensorState": {},
  "cropState": {},
  "growthKpi": {},
  "actuatorState": {},
  "result": {},
  "recommendation": {
    "recommendedBlueprintId": "blueprint-b",
    "rationale": "...",
    "scores": []
  },
  "ragAdvice": {},
  "gapAnalysis": {},
  "planningRun": {}
}
```

### Sensor fields

| API field | Internal field | Meaning |
| --- | --- | --- |
| `scenarioSeed` | `scenario_seed` | Synthetic scenario/source marker. |
| `twinDay` | `twin_day` | Current crop day. |
| `cropStage` | `crop_stage` | Human stage label. |
| `growthIndex` | `growth_index` | Compact synthetic growth indicator. |
| `dliMolM2Day` | `dli_mol_m2_day` | Daily light integral. |
| `soilMoisturePercent` | `substrate_moisture_percent` | Substrate/root-zone moisture. |
| `humidityPercent` | `humidity_percent` | Relative humidity. |
| `temperatureC` | `temperature_c` | Temperature in Celsius. |
| `co2Ppm` | `co2_ppm` | CO2 ppm. |
| `diseaseRisk` | `disease_risk` | `low`, `controlled`, or `high`. |

### Crop fields

| Field | Range | Meaning |
| --- | ---: | --- |
| `day` | integer | Crop day. |
| `vegetativeGrowth` | `0..1` | Canopy/leaf development. |
| `flowering` | `0..1` | Flowering progress. |
| `fruitSet` | `0..1` | Fruit-set density/progress. |
| `fruitMaturity` | `0..1` | Fruit maturity/ripeness progress. Harvest threshold is `0.92`. |
| `diseasePressure` | `0..1` | Disease risk pressure. Acceptable harvest limit is `<=0.62`. |
| `estimatedYield` | `0..100` | Model-estimated yield score. Acceptable harvest limit is `>=70`. |

### Actuator fields

| API field | Internal field | Bounds | Meaning |
| --- | --- | ---: | --- |
| `ledIntensityPercent` | `led_intensity_percent` | `0..100` | LED power. |
| `photoperiodHours` | `photoperiod_hours` | `8..18` | Light hours/day. |
| `waterValveOpen` | `water_valve_open` | boolean | Irrigation valve. |
| `irrigationPulsesPerDay` | `irrigation_pulses_per_day` | `0..8` | Irrigation pulses/day. |
| `fanDutyPercent` | `fan_duty_percent` | `0..100` | Fan/airflow duty. |
| `co2Ppm` | `co2_ppm` | `380..900` | CO2 target. |

---

## 11. Growth KPI meanings and formulas

`growthKpi` is an operator-facing summary, not a raw sensor echo.

### Sensor band scores

Each sensor is scored `0..1` against an optimal and hard range:

| Sensor | Optimal range | Hard range | Weight in environment score |
| --- | --- | --- | ---: |
| DLI | `16..20` | `8..24` | `0.28` |
| moisture | `42..55` | `24..65` | `0.22` |
| humidity | `60..72` | `48..90` | `0.20` |
| temperature | `21.5..24.5` | `17..29` | `0.15` |
| CO2 | `550..750` | `380..900` | `0.15` |

If value is inside the optimal band, score is `1.0`.  If outside, score linearly falls toward `0.0` at the hard limit.

### Environment score

```text
environment_score =
  dli_score      * 0.28 +
  moisture_score * 0.22 +
  humidity_score * 0.20 +
  temp_score     * 0.15 +
  co2_score      * 0.15
```

### Crop score

```text
crop_score =
  vegetativeGrowth       * 0.18 +
  flowering              * 0.14 +
  fruitSet               * 0.18 +
  fruitMaturity          * 0.28 +
  (1 - diseasePressure)  * 0.22
```

### Health score

```text
healthScore = clamp((environment_score * 0.44 + crop_score * 0.56) * 100, 0, 100)
```

### Fruit maturity percent

```text
fruitMaturityPercent = fruitMaturity * 100
```

### Harvest readiness percent

```text
harvestReadinessPercent =
  (fruitMaturity * 0.62 + estimatedYield/100 * 0.22 + (1 - diseasePressure) * 0.16) * 100
```

### Main limiting factor

The largest of these pressure terms is chosen:

- low DLI,
- low substrate moisture,
- high humidity,
- low temperature,
- high temperature,
- low CO2.

If all severities are non-positive, the message is `No severe limiter; maintain current climate balance`.

---

## 12. Synthetic sensor/crop model

The POC currently does not read physical sensors.  It maps actuator changes to synthetic greenhouse responses.

### Sensor from actuator model

Given a base state, actuator setpoints are translated as follows:

```text
dli = base_dli + (LED - 40) * 0.105 + (photoperiod - 12) * 0.75
moisture = base_moisture + (irrigation_pulses - 1) * 4.5 + (2.5 if water valve open)
humidity = base_humidity + (irrigation_pulses - 1) * 1.8 - (fan - 20) * 0.32 - (LED - 40) * 0.035
temperature = base_temperature + (LED - 40) * 0.025 + (photoperiod - 12) * 0.05 - (fan - 20) * 0.018
CO2 = actuator CO2 target
```

Clamps:

| Field | Clamp |
| --- | --- |
| DLI | `7.5..23.5` |
| moisture | `24..65` |
| humidity | `48..90` |
| temperature | `18..29` |
| CO2 | `380..900` |

Disease pressure:

```text
moisture_stress = max(0, 38 - moisture) * 0.010 + max(0, moisture - 58) * 0.006

disease_pressure = clamp(
  0.70
  + (humidity - 82) * 0.018
  + moisture_stress
  - (fan - 20) * 0.0040
  - (dli - 11.2) * 0.0060,
  0.12,
  0.84
)
```

Growth index:

```text
growth_index = clamp(
  0.42
  + (dli - 11.2) * 0.018
  + (moisture - 31) * 0.0035
  + max(0, CO2 - 420) * 0.00010
  - max(0, disease_pressure - 0.42) * 0.08
  + max(0, 0.42 - disease_pressure) * 0.04,
  0.28,
  0.78
)
```

Disease label mapping:

| pressure | label |
| ---: | --- |
| `>=0.66` | `high` |
| `>=0.38` and `<0.66` | `controlled` |
| `<0.38` | `low` |

### Crop from sensor model

```text
risk = high -> 0.70, controlled -> 0.42, low -> 0.24
fruitMaturity = clamp(0.18 + growth_index * 0.62 + max(0, twin_day - 34) * 0.006, 0.12, 0.88)
vegetativeGrowth = clamp(0.52 + growth_index * 0.38, 0, 1)
flowering = clamp(0.45 + growth_index * 0.46, 0, 1)
fruitSet = clamp(0.25 + growth_index * 0.58, 0, 1)
diseasePressure = risk
estimatedYield = clamp(58 + growth_index * 42 - risk * 12, 0, 100)
```

---

## 13. Gemma/RAG Blueprint generation contract

### Local request builder

The Twin extension builds a snapshot using `build_state_snapshot(...)` in `rag_adapter.py`:

```jsonc
{
  "facilityId": "smartfarm-spark-a7ce",
  "goal": "balanced",
  "referenceDate": "2026-10-23",
  "plantingDate": "2026-09-19",
  "currentDay": 34,
  "sensorState": {},
  "cropState": {},
  "actuatorState": {},
  "growthKpi": {},
  "visionAssessment": {},
  "constraints": {
    "maxOpexIncreasePct": 18,
    "diseaseRiskMax": "controlled"
  }
}
```

Then it calls:

```http
POST http://<TWINX_RAG_LB>:<RAG_PORT>/blueprints/generate
Authorization: Bearer <contents of SMARTFARM_RAG_TOKEN_FILE>
Content-Type: application/json
```

Request body includes:

```jsonc
{
  "facilityId": "smartfarm-spark-a7ce",
  "objective": "balanced",
  "responseLanguage": "en-US",
  "uiTextContract": "Return every human-facing label... in concise English ASCII only...",
  "candidateCount": 3,
  "referenceDate": "2026-10-23",
  "plantingDate": "2026-09-19",
  "currentDay": 34,
  "constraints": {},
  "baseline": {
    "sensorState": {},
    "cropState": {},
    "actuatorState": {},
    "growthKpi": {},
    "visionAssessment": {}
  },
  "no_llm": false
}
```

### Why the English ASCII contract exists

The Omniverse UI used in this demo renders unsupported Korean glyphs as `?`.  The adapter therefore asks TwinX/Gemma to return UI-facing labels, summaries, rationale, intent, tradeoff, and evidence summaries in English ASCII.  If returned text still contains unsupported characters or many question marks, the UI normalizer falls back to safe English default text.

### TwinX `/blueprints/generate` behavior

The remote `rag_server.py`:

1. Checks bearer auth.
2. Determines current day / planting date.
3. Picks the strawberry growth stage from `setpoints_table.json`.
4. Applies seasonal overrides.
5. Retrieves relevant RAG contexts from ChromaDB.
6. Calls Gemma through the OpenAI-compatible vLLM endpoint unless `no_llm=true`.
7. If Gemma JSON generation fails, uses deterministic fallback candidates and records warnings.
8. Logs a line such as:

```text
blueprints.generate facility=smartfarm-spark-a7ce objective=balanced mode=gemma_json candidates=3 warnings=0 evidence=8
```

Response includes:

| Field | Meaning |
| --- | --- |
| `provider` | Usually `twinx-gemma-rag`. |
| `model` | Current `LLM_MODEL`, e.g. `gemma4`. |
| `objective` | Current objective, e.g. `balanced`. |
| `referenceDate`, `plantingDate`, `currentDay` | Time context. |
| `growthStage` | Stage selected from table. |
| `seasonalAdjustment` | Seasonal override name if applied. |
| `generationMode` | `gemma_json`, `deterministic_no_llm`, or `deterministic_fallback`. |
| `warnings` | Gemma/fallback warnings. |
| `baselineSummary` | Summary of current state. |
| `setpoints` | RAG-backed setpoint recommendation. |
| `constraints` | Echoed constraints. |
| `evidence` | Up to 8 RAG evidence items. |
| `candidates` | The three Blueprint candidates. |

### Local response normalization

The local adapter normalizes any returned candidate labels to exactly:

```text
Plan A
Plan B
Plan C
```

It also bounds actuator targets:

| Actuator | Bounds |
| --- | --- |
| LED | `0..100` |
| photoperiod | `8..18` |
| irrigation pulses/day | `0..8` |
| fan duty | `0..100` |
| CO2 | `380..900` |

Human-facing text is sanitized for Omniverse UI safety.

---

## 14. Gap analysis

If TwinX returns RAG advice, the local twin compares the current Baseline against RAG setpoints.

Targets:

```text
target_dli = clamp(14 + supplementalLight.hoursPerDay * 0.75, 14, 20)
target_moisture = 46
target_humidity = RAG humidityPct.target, default 66
target_temperature = RAG temperatureDayC.target, default 22
target_co2 = min(RAG co2Ppm.target, 900)
```

Weighted deviations:

| Factor | Weight | Denominator | Correction text |
| --- | ---: | ---: | --- |
| DLI | `1.20` | `8.0` | increase LED intensity/photoperiod |
| Humidity | `1.10` | `20.0` | increase airflow and avoid excess irrigation |
| CO2 | `0.95` | `520.0` | raise CO2 enrichment setpoint |
| Substrate moisture | `0.85` | `28.0` | normalize irrigation pulses |
| Temperature | `0.65` | `7.0` | balance LED heat with ventilation |

Additional deviations:

- If `diseasePressure >= 0.62`, add disease pressure severity `0.95` with target `0.42`.
- If `fruitMaturity < 0.55`, add fruit maturity severity `0.72` with target `0.72`.

Final gap score:

```text
deviationScore = clamp(total_severity / 5.0, 0, 1) * 100
```

The top factors are shown in the RAG Trace panel.

---

## 15. Candidate generation fallback paths

There are three planning paths, in priority order:

1. **Live `/blueprints/generate` path**
   - Preferred current path.
   - TwinX Gemma/RAG directly returns 3 candidates.
   - Local twin simulates and scores them.

2. **Legacy `/recommend` fallback path**
   - Only used if `/blueprints/generate` returns `404`, `405`, or `501`.
   - TwinX returns stage/date setpoints.
   - Local `generate_blueprint_candidates(...)` creates three candidate recipes from the setpoints and gap analysis.

3. **Offline deterministic planner**
   - Used if RAG URL is missing or the RAG request fails with a real error.
   - Status becomes `unavailable: ...` or `pending_external_pipeline`.
   - Source is `synthetic-deterministic-planner-v2`.

### Legacy local candidate recipes

If legacy `/recommend` fallback is used:

- Plan A (`blueprint-a`, early shipment):
  - LED at least `72`, increased by DLI gap,
  - photoperiod at least `15`,
  - irrigation at least `3`,
  - fan at least `48`,
  - CO2 at least `740`.
- Plan B (`blueprint-b`, balanced):
  - moderate DLI/CO2/moisture correction,
  - fan based on humidity and temperature excess,
  - CO2 capped near `760`.
- Plan C (`blueprint-c`, disease safe):
  - fan at least `66`,
  - LED at least `62`,
  - photoperiod at least `14`,
  - irrigation constrained roughly `2..4`,
  - CO2 at least `620`.

---

## 16. Rolling-horizon twin simulation

After candidate generation, the local Twin remains the validator.  It simulates each candidate daily from the current crop day until harvest criteria pass or the planning horizon ends.

Constants:

| Constant | Value | Meaning |
| --- | ---: | --- |
| `PLANNING_REFERENCE_DATE` | `2026-10-23` | Date anchor for shipment date math. |
| `BASELINE_HARVEST_DAY` | `75` | Baseline target day used for ship delta. |
| `PLANNING_MAX_HORIZON_DAYS` | `90` | Maximum simulation day. |
| `HARVEST_MATURITY_THRESHOLD` | `0.92` | Fruit maturity required for harvest. |
| `MIN_ACCEPTABLE_YIELD_SCORE` | `70` | Minimum yield score for valid harvest. |
| `DISEASE_PRESSURE_LIMIT` | `0.62` | Maximum acceptable disease pressure for harvest. |

Each simulated day:

1. Builds a virtual sensor from actuator/crop state.
2. Computes factors:

```text
dli_factor = clamp((DLI - 9) / 10, 0, 1.35)
moisture_factor = 1 - abs(moisture - 46) / 42
temp_factor = 1 - abs(temp - 23.3) / 8
co2_factor = clamp((CO2 - 390) / 360, 0, 1)
humidity_penalty = max(0, (humidity - 72) / 28)
dry_penalty = max(0, (38 - moisture) / 28)
```

3. Computes maturity gain:

```text
maturity_gain = 0.010
              + 0.014 * dli_factor
              + 0.005 * moisture_factor
              + 0.004 * temp_factor
              + 0.004 * co2_factor

maturity_gain *= clamp(1 - diseasePressure * 0.22, 0.72, 1.05)
```

4. Updates crop:

```text
fruitMaturity += maturity_gain
fruitSet       += maturity_gain * 0.42
flowering      += maturity_gain * 0.18
vegetative     += maturity_gain * 0.10
```

5. Updates disease pressure:

```text
disease_control = max(0, fan - 35) * 0.00045
                + max(0, 70 - humidity) * 0.0012
```

Extra disease strategy handling:

- disease-safe plans get extra disease control when base disease is high,
- early-shipment plans get small extra disease control,
- low-cost plans reduce disease control when base disease is high.

Disease update:

```text
diseasePressure = clamp(
  diseasePressure + humidity_penalty * 0.014 + dry_penalty * 0.008 - disease_control,
  0.04,
  0.95
)
```

6. Updates yield:

```text
estimatedYield = clamp(55 + fruitSet * 32 + fruitMaturity * 18 - diseasePressure * 18, 0, 100)
```

7. Accumulates daily OpEx:

```text
daily_opex = LED * photoperiod / 1250 + fan / 180 + irrigation_pulses * 0.10
```

Final OpEx delta:

```text
opexDeltaPercent = round((average_daily_opex - 1.00) * 18)
```

### Harvest condition

A candidate is considered harvest-valid when all are true:

```text
fruitMaturity >= 0.92
diseasePressure <= 0.62
estimatedYield >= 70
```

If this never happens before day 90, the candidate receives an unsafe harvest penalty.

---

## 17. Candidate score meaning

The Plan score is **not a Gemma confidence score**.  It is the local Twin validation score after a Gemma/RAG candidate has been simulated.

### Rolling-horizon score formula

```text
days_earlier = BASELINE_HARVEST_DAY - harvest_day

disease_penalty =
  high       -> 42
  controlled -> 10
  low        -> 0
  plus diseasePressure * 30

unsafe_harvest_penalty = 22 if harvest_day >= PLANNING_MAX_HORIZON_DAYS else 0
cost_saving_bonus = min(max(0, -opexDeltaPercent), 8) * 0.30

score =
  days_earlier * 1.4
  + yieldScore * 0.65
  + cost_saving_bonus
  - max(0, opexDeltaPercent) * 0.40
  - disease_penalty
  - unsafe_harvest_penalty
```

If the Baseline disease pressure is high (`>=0.62`), strategy adjustments apply:

- disease-safe candidate: `+18`
- low-cost candidate: `-20`
- near-harvest early-shipment candidate under high disease: `-8`

Then:

```text
score = clamp(score, 0, 100)
```

### Why a Plan can show `0/100`, and what changed

A `0/100` plan is not necessarily a UI bug.  It means the candidate was generated and simulated, but the Twin validation found it unacceptable after penalties.  Typical reasons:

- disease pressure remained high,
- harvest criteria were not reached before the planning horizon,
- shipment was not earlier than Baseline,
- OpEx or actuator stress did not compensate for weak maturity/disease results.

Current behavior adds a **Twin quality gate** before A/B/C slot assignment:

1. If candidate score is below `20`, disease risk is `high`, harvest reaches the max horizon, or final disease pressure exceeds `0.62`, it is marked infeasible.
2. The original Gemma/RAG candidate is not hidden; its score, actuator target, prediction, and simulation are saved under `qualityGate` / `original*` fields in the JSON trace.
3. The Twin tries one transparent repair pass using safer airflow/light/CO2 profiles.
4. The repaired candidate is re-simulated by the same rolling-horizon model.
5. Only an improving repaired candidate replaces the infeasible one for ranking and Apply.

Older example live verified run before the quality gate on 2026-06-15 (`mode=live Gemma/RAG`):

```text
runId: ragrun-0004-7bdae0f8
status: live_blueprint_generator
source: twinx-gemma-rag-adapter-v1
TwinX trace: POST /blueprints/generate -> HTTP 200, auth=true
RAG sources: 8
recommended: blueprint-b

Plan A / blueprint-a: 0.0
  shipmentDate: 2027-01-21
  yieldScore: 87
  opexDeltaPercent: -1
  diseaseRisk: high
  actuator: LED 50%, 12h, irrigation 3/day, fan 30%, CO2 850

Plan B / blueprint-b: 58.0
  shipmentDate: 2026-12-20
  yieldScore: 87
  opexDeltaPercent: -1
  diseaseRisk: controlled
  actuator: LED 40%, 12h, irrigation 2/day, fan 60%, CO2 600

Plan C / blueprint-c: 0.0
  shipmentDate: 2027-01-21
  yieldScore: 88
  opexDeltaPercent: -3
  diseaseRisk: high
  actuator: LED 40%, 12h, irrigation 2/day, fan 40%, CO2 500
```

In that older run, Plan B was recommended because the local Twin considered it the only candidate that controlled disease enough while still shipping earlier.  With the current quality gate, the same kind of 0-score candidates are expected to appear as repaired candidates with `provider=...+twin-quality-gate` and a trace line explaining the repair.

### Ship delta display

The dashboard ship delta compares candidate shipment date to the fixed Baseline shipment date.  For example:

- `ship -29d`: candidate ships 29 days earlier than Baseline.
- `ship ±0d`: no earlier shipment advantage.
- If an old UI showed `ship --d`, it meant missing/invalid shipment date formatting in the displayed row; current logic formats missing values safely and should use the trace JSON for exact dates.

---

## 18. Static fallback score formula

When no planning run exists, static Plan A/B/C can be ranked by the older score:

```text
score = yield_score
      + daysEarlier * 0.80
      + max(0, -opex) * 0.20
      - max(0, opex) * 0.25
      - disease_penalty
      - actuator_stress_penalty
```

Disease penalty:

| disease risk | penalty |
| --- | ---: |
| high | `18` |
| controlled | `3` |
| low | `0` |

Actuator stress penalty:

```text
max(0, LED - 80) * 0.08
```

This older formula is mainly for fallback/static dashboard behavior; live generated Blueprints use the rolling-horizon simulation score above.

---

## 19. Applying plans

After `Generate`, the Twin calls `_publish_planning_candidates(candidates)`.  For every candidate except Baseline, it updates runtime registries:

- `BLUEPRINT_SENSOR_STATES[blueprint_id]`
- `BLUEPRINT_ACTUATOR_STATES[blueprint_id]`
- `BLUEPRINT_SERVICE_SUMMARY[blueprint_id]`

Therefore:

- clicking `Plan A`, `Plan B`, or `Plan C` applies the latest generated runtime candidate if present;
- Baseline remains immutable and is not overwritten by simulated future-harvest state;
- `Apply Recommended` applies the current highest-scoring plan from the latest run.

---

## 20. Growth camera and blue-sky scene settings

### Camera

Growth camera path:

```text
/World/SmartFarm/Cameras/GrowthPhenotypeCamera
```

Purpose:

- close crop/phenotype camera,
- view should include crown/leaves/fruit area,
- should still be useful before fruit appears.

Current authored properties:

| Property | Value |
| --- | ---: |
| focal length | `38.0` |
| horizontal aperture | `32.0` |
| vertical aperture | `18.0` |
| clipping range | `0.05..9.0` |
| visual scale | `0.006` |
| eye | `(-26.2, 1.75, -17.5)` |
| target | `(-29.0, 1.50, -15.2)` |

The camera is positioned inside House_01_01 and aimed around Plant_06 / Bed_01 crown area rather than only a fruit, so it remains meaningful when strawberries have not appeared yet.

### Blue sky

Both Twin and OmniOps ensure a consistent blue-sky environment.

| Element | Path | Value |
| --- | --- | --- |
| Dome light | `/World/SmartFarm/Lighting/SoftSky` | color `(0.42, 0.68, 1.00)`, intensity `260` |
| Sun | `/World/SmartFarm/Lighting/Sun` | color `(1.00, 0.93, 0.78)`, intensity `520`, angle `1.2`, rotation roughly `(-45, 35, 0)` |

---

## 21. Capture & Analyze Growth

### What the button does

`Capture & Analyze Growth` performs this sequence:

1. Ensure `/World/SmartFarm/Cameras/GrowthPhenotypeCamera` exists.
2. Set the active viewport camera to the Growth Camera.
3. Capture a PNG to:

```text
logs/smartfarm-vision/<timestamp>_<seq>_<blueprint>.png
```

4. Build a deterministic fallback phenotype assessment from current sensor/crop state.
5. Send the image and context to the configured vision endpoint.
6. Normalize the returned assessment.
7. Write a sidecar JSON:

```text
logs/smartfarm-vision/<timestamp>_<seq>_<blueprint>.json
```

8. Update UI vision fields and append RAG Trace lines.

### Vision request body

```jsonc
{
  "facilityId": "smartfarm-spark-a7ce",
  "cameraPath": "/World/SmartFarm/Cameras/GrowthPhenotypeCamera",
  "capturePath": "logs/smartfarm-vision/....png",
  "observedAt": "...Z",
  "imageMimeType": "image/png",
  "imageBase64": "...",
  "objective": "Analyze the strawberry crop image...",
  "sensorContext": {},
  "cropContext": {},
  "kpiContext": {},
  "fallbackAssessment": {}
}
```

Endpoint selection order:

1. If `SMARTFARM_VISION_ANALYZE_PATH` is set, use it.
2. Otherwise try:
   - `/vision/analyze`
   - `/analyze/growth`
   - `/phenotype/analyze`
   - `/analyze`

Base URL:

```text
SMARTFARM_VISION_BASE_URL or SMARTFARM_RAG_BASE_URL
```

Token:

```text
SMARTFARM_VISION_TOKEN or SMARTFARM_RAG_TOKEN
or token file from SMARTFARM_VISION_TOKEN_FILE / SMARTFARM_RAG_TOKEN_FILE
```

### Current verified vision state

A direct TwinX call with the latest captured PNG returned:

```text
provider: twinx-gemma-vision
analysisMode: gemma_vision_fallback
confidence: gemma-text-fallback
imageBytes: 1459731
growthProgressPercent: 85
healthScore: 82
diseaseRisk: low
traits[0]: Image received from /World/SmartFarm/Cameras/GrowthPhenotypeCamera (image/png).
```

Meaning:

- The image reaches TwinX.
- Auth and endpoint path work.
- The response is not true visual Gemma reasoning yet; it is fallback because current `gemma4` cannot accept images.

### Local fallback vision formulas

The local deterministic fallback computes:

```text
health = vegetativeGrowth * 0.25
       + fruitSet * 0.20
       + fruitMaturity * 0.25
       + (1 - diseasePressure) * 0.30

readiness = fruitMaturity * 0.70
          + estimatedYield/100 * 0.20
          + (1 - diseasePressure) * 0.10

growthProgress = vegetativeGrowth * 0.20
               + flowering * 0.20
               + fruitSet * 0.25
               + fruitMaturity * 0.35
```

The fallback source/provider labels are intentionally explicit:

```text
source: virtual-camera-observed
provider: foundation-model-adapter/mock
confidence: poc-heuristic
```

When the TwinX endpoint was contacted but fell back, the UI provider label becomes:

```text
Gemma request + fallback
```

---

## 22. What `Gemma live` proves

When the Gemma/RAG path is live, the UI/trace can prove:

- exact API path: `POST /blueprints/generate`,
- exact URL: `http://<TWINX_RAG_LB>:<RAG_PORT>/blueprints/generate`,
- HTTP status: `200`,
- auth configured: `true`,
- run id: `ragrun-####-xxxxxxxx`,
- provider: `twinx-gemma-rag`,
- model: `gemma4`,
- source: `twinx-gemma-rag-adapter-v1`,
- generation mode: usually `gemma_json`,
- number of RAG sources, e.g. `8`,
- current sensor values sent in the request,
- whether vision assessment was attached,
- each Plan candidate's actuator recipe,
- each Plan candidate's Twin validation score,
- whether the Twin quality gate repaired any infeasible candidates, including original and repaired actuator targets in JSON,
- recommended candidate id.

It does **not** by itself prove that every click must produce a different answer.  If the Baseline state, constraints, RAG documents, and objective are the same, Gemma can reasonably return similar or identical candidate structures.  Variation should come from changed current state, changed vision assessment, changed constraints/objective, or stochastic generation settings.

---

## 23. Logs and evidence files

### Planning/RAG traces

Directory:

```text
logs/smartfarm-blueprints/
```

Files:

```text
rag-trace.log
<timestamp>_<runId>.json
```

The JSON sidecar includes:

- `planningRun`,
- `ragAdvice`,
- `gapAnalysis`,
- `ranked`,
- `visionAssessmentUsed`,
- `stateSnapshot`.

### Vision captures

Directory:

```text
logs/smartfarm-vision/
```

Files:

```text
<timestamp>_<seq>_<blueprint>.png
<timestamp>_<seq>_<blueprint>.json
```

The JSON sidecar includes:

- image file name/path/size,
- normalized assessment,
- endpoint/http/auth/fallback metadata if returned,
- state snapshot at capture time.

### TwinX pod logs

Useful command:

```bash
ssh <TWINX_SSH_USER>@<TWINX_OPS_HOST> \
  'kubectl -n <K8S_NAMESPACE> logs deploy/<RAG_SERVICE_NAME> --tail=100 | grep -E "blueprints.generate|vision.analyze"'
```

Expected examples:

```text
INFO:<RAG_LOGGER_NAME>:blueprints.generate facility=smartfarm-spark-a7ce objective=balanced mode=gemma_json candidates=3 warnings=0 evidence=8
INFO:<RAG_LOGGER_NAME>:vision.analyze facility=smartfarm-spark-a7ce camera=/World/SmartFarm/Cameras/GrowthPhenotypeCamera mode=gemma_vision_fallback confidence=gemma-text-fallback imageBytes=1459731 fallback=yes
```

---

## 24. Direct Omniverse browser viewer

A minimal web page exists under:

```text
web/omniverse-direct-viewer
```

Purpose:

- no portal features,
- only a `Connect Stream` action,
- shows the Omniverse WebRTC stream full-screen in the browser.

Local package:

```text
@ nvidia/omniverse-webrtc-streaming-library 5.6.0
Vite + TypeScript
```

Current/default config file:

```json
{
  "stream": {
    "server": "<OMNIVERSE_STREAM_HOST>",
    "signalingPort": 49100,
    "mediaPort": 47998,
    "width": 1920,
    "height": 1080,
    "fps": 60,
    "authenticate": true,
    "fullscreenOnConnect": true,
    "maxReconnects": 3,
    "connectTimeoutMs": 15000
  }
}
```

GitOps/K8s observed service:

```text
<OMNIVERSE_VIEWER_SERVICE> LoadBalancer <OMNIVERSE_VIEWER_LB>:<VIEWER_PORT>
```

If the browser page opens but does not connect to the desired SmartFarm twin, verify that `/config.json` points at the host actually running `scripts/smartfarm-omniops-streaming.sh` and that `49100/TCP` and `47998/UDP` are reachable from the client network.

---

## 25. How to run and verify locally

### Start/restart streaming app

```bash
tmux new -d -s smartfarm_streaming 'cd /home/user/kit-app-template && scripts/smartfarm-omniops-streaming.sh'
```

or restart an existing session manually after killing the old Kit process.

Verify the Kit process has RAG env:

```bash
pid=$(pgrep -f 'joon.smartfarm_omniops_streaming.kit' | head -1)
tr '\0' '\n' < /proc/$pid/environ | grep '^SMARTFARM_RAG'
```

Expected:

```text
SMARTFARM_RAG_BASE_URL=http://<TWINX_RAG_LB>:<RAG_PORT>
SMARTFARM_RAG_TIMEOUT=30
SMARTFARM_RAG_TOKEN_FILE=<SMARTFARM_RAG_TOKEN_FILE>
```

### Verify live Blueprint generation without UI

```bash
python3 - <<'PY'
import json, urllib.request
url='http://127.0.0.1:8011/smartfarm/blueprint/generate'
body={"goal":"balanced","constraints":{"maxOpexIncreasePct":18,"diseaseRiskMax":"controlled"}}
req=urllib.request.Request(url,data=json.dumps(body).encode(),method='POST',headers={'Content-Type':'application/json','Accept':'application/json'})
with urllib.request.urlopen(req,timeout=45) as r:
    data=json.load(r)
pr=data.get('planningRun') or {}
print(data.get('ok'), data.get('message'))
print(pr.get('runId'), pr.get('gemmaRagStatus'), pr.get('source'))
print(pr.get('ragRequestTrace'))
print('recommended', pr.get('recommendedBlueprintId'))
for c in pr.get('candidates',[]):
    print(c.get('name'), c.get('id'), c.get('score'), c.get('provider'), c.get('predicted'), c.get('actuatorTarget'))
PY
```

A verified live result on 2026-06-15 returned (`mode=live Gemma/RAG`):

```text
ok=True
runId=ragrun-0004-7bdae0f8
gemmaRagStatus=live_blueprint_generator
source=twinx-gemma-rag-adapter-v1
trace=POST /blueprints/generate HTTP 200 ok=True auth=True
recommended=blueprint-b
sources=8
```

### Verify Twinx vision endpoint with a captured PNG

```bash
python3 - <<'PY'
import base64,json,os,urllib.request
from pathlib import Path
img=Path(sorted(Path('logs/smartfarm-vision').glob('*.png'), key=lambda p:p.stat().st_mtime)[-1])
tok=Path(os.path.expanduser(os.getenv('SMARTFARM_RAG_TOKEN_FILE', '<SMARTFARM_RAG_TOKEN_FILE>'))).read_text().strip()
body={
  "facilityId":"smartfarm-spark-a7ce",
  "cameraPath":"/World/SmartFarm/Cameras/GrowthPhenotypeCamera",
  "capturePath":str(img),
  "observedAt":"2026-06-15T00:00:00Z",
  "imageMimeType":"image/png",
  "imageBase64":base64.b64encode(img.read_bytes()).decode(),
  "fallbackAssessment":{"source":"virtual-camera-observed","healthScore":82,"growthProgressPercent":85,"diseaseRisk":"low"}
}
req=urllib.request.Request(
  'http://<TWINX_RAG_LB>:<RAG_PORT>/vision/analyze',
  data=json.dumps(body).encode(),
  method='POST',
  headers={'Content-Type':'application/json','Accept':'application/json','Authorization':f'Bearer {tok}'}
)
with urllib.request.urlopen(req, timeout=45) as r:
  data=json.load(r)
a=data.get('assessment',data)
print(data.get('provider'), a.get('analysisMode'), a.get('confidence'), a.get('imageBytes'))
PY
```

Current expected POC result (`mode=vision fallback`):

```text
twinx-gemma-vision gemma_vision_fallback gemma-text-fallback <image-bytes>
```

### Python syntax/unit tests

```bash
python3 -m py_compile \
  source/extensions/joon.smartfarm.omniops/joon/smartfarm/omniops/extension.py

bash -n scripts/smartfarm-omniops-streaming.sh scripts/smartfarm-twin-common.sh

export PYTHONPATH="/home/user/kit-app-template/source/extensions/joon.smartfarm.omniops:/home/user/kit-app-template/source/extensions/joon.smartfarm.twin:${PYTHONPATH:-}"
python3 -m unittest discover -s source/extensions/joon.smartfarm.omniops/joon/smartfarm/omniops/tests -p 'test_model.py'
python3 -m unittest discover -s source/extensions/joon.smartfarm.twin/joon/smartfarm/twin/tests -p 'test_rag_adapter.py'
```

Verified counts:

```text
omniops test_model.py: 5 tests OK
twin test_rag_adapter.py: 10 tests OK
```

`test_hello_world.py` requires `omni.kit.test` and should be treated as a Kit integration test, not a generic Python unit test.

---

## 26. Demo script for class or stakeholder review

1. Open the Omniverse stream or local app.
2. Confirm Baseline/current twin is visible.
3. Point out that Baseline is not Plan A/B/C; it is the current farm state.
4. Open bottom `SmartFarm Evidence Dashboard`.
5. Open/select `SmartFarm RAG Trace` tab beside Evidence.
6. Click `Generate Gemma/RAG Blueprints`.
7. In RAG Trace, show:
   - `POST /blueprints/generate`,
   - HTTP `200`,
   - provider/model/source count,
   - sensor values sent,
   - Plan A/B/C scores and controls,
   - saved JSON trace path.
8. Explain that a 0 score means the Twin rejected that plan after simulation, not that the button failed.
9. Click `Apply Recommended` or click the recommended Plan button.
10. Click `Capture & Analyze Growth`.
11. Show the captured PNG/JSON in `logs/smartfarm-vision` and RAG Trace vision lines.
12. Explicitly state the current vision limitation: image reaches TwinX but current Gemma deployment returns fallback because it is not configured as a multimodal image model.

---

## 27. Troubleshooting

### Generate always uses offline fallback

Symptoms:

```text
Gemma status: Offline fallback
source=synthetic-deterministic-planner-v2
RAG API trace not returned
unavailable: SMARTFARM_RAG_BASE_URL is not configured
```

Check:

```bash
pid=$(pgrep -f 'joon.smartfarm_omniops_streaming.kit' | head -1)
tr '\0' '\n' < /proc/$pid/environ | grep SMARTFARM_RAG
```

Fix:

- Start with `scripts/smartfarm-omniops-streaming.sh`, not a raw Kit command.
- Ensure `scripts/smartfarm-omniops-streaming.sh` sources `scripts/smartfarm-twin-common.sh`.
- Ensure token file exists at `<SMARTFARM_RAG_TOKEN_FILE>`.

### Generate works but answers do not change

Likely causes:

- Baseline sensor/crop state is unchanged.
- Objective is always `balanced`.
- Constraints are unchanged.
- RAG documents and stage are unchanged.
- Gemma may return deterministic/similar JSON under the current prompt.

To force meaningful changes, change current actuator/state, attach a different vision assessment, or add explicit objective/constraint variants.

### UI shows question marks (`???`)

Cause:

- Omniverse UI font/rendering path does not support some Korean or special glyphs.

Mitigations already implemented:

- RAG prompt requests English ASCII for UI text.
- Adapter replaces unsupported text with safe English fallback.
- `CO₂` is normalized to `CO2` in UI text.

### Plan shows `0/100`

This means the Twin simulation scored it as invalid/unsafe/late after penalties.  Inspect candidate fields:

- `predicted.diseaseRisk`,
- `predicted.riskNote`,
- `simulation.harvestDay`,
- `simulation.dailyStates`,
- `predicted.opexDeltaPercent`.

### Capture says fallback

Current expected state if using `gemma4` text-only vLLM.  The image did reach TwinX if trace contains:

- endpoint path `/vision/analyze`,
- HTTP 200,
- image byte count,
- `analysisMode=gemma_vision_fallback`.

To enable real vision, deploy/configure a multimodal Gemma-compatible model behind the OpenAI-compatible endpoint and update `LLM_MODEL` / `OPENAI_BASE_URL` as needed.

### Direct viewer page opens but does not connect

Check:

- `web/omniverse-direct-viewer/public/config.json` or deployed `/config.json`,
- target `stream.server`,
- `49100/TCP` signaling reachability,
- `47998/UDP` media reachability,
- the SmartFarm streaming Kit process is alive.

---

## 28. Known risks and next steps

### High-priority next steps

1. **Real multimodal vision model**
   - Replace or add a Gemma/vLLM model that accepts image input.
   - Keep the same `/vision/analyze` contract.
   - Validate that `analysisMode` becomes true vision, not fallback.

2. **Persist planning and logs in DB**
   - Current POC writes local JSON/log sidecars.
   - RAG documents live in ChromaDB, but planning run audit persistence should move to a durable DB if this becomes productized.

3. **Real sensor ingestion**
   - Current sensors are synthetic and deterministic.
   - Replace `BASELINE_SENSOR` / virtual state updates with actual sensor streams.

4. **Objective variants**
   - Current Generate objective is `balanced`.
   - Product may need explicit objectives such as earliest shipment, lowest OpEx, disease-safe, or operator-defined constraints.

5. **Remote/source Git hygiene**
   - Local repo origin observed as NVIDIA kit app template upstream, not a project-owned remote.
   - Do not push local source changes to the wrong upstream.
   - Twinx GitOps commits were pushed in `<TWINX_OPS_REPO>`.

### Current design choices to preserve

- Baseline remains current state and fixed.
- Plan A/B/C are generated alternatives, not static business categories in the product story.
- Gemma/RAG proposes candidate controls; the Twin validates and ranks them.
- The UI should expose whether Gemma/RAG/vision is live or fallback.
- Evidence/trace visibility is required for class/demo validation.

---

## 29. Glossary

| Term | Meaning |
| --- | --- |
| Baseline | Current farm/twin state. Fixed anchor for generation and comparison. |
| Blueprint | A candidate actuator/control recipe proposed for the twin. |
| Plan A/B/C | UI labels for the three generated Blueprint candidates. |
| Gemma/RAG | TwinX service that uses strawberry docs/ChromaDB + Gemma/vLLM to produce advice/candidates. |
| Twin validation | Local simulation of candidate controls to harvest, disease, yield, and cost. |
| Score | Twin validation score, not Gemma confidence. |
| DLI | Daily Light Integral, mol/m2/day. |
| OpEx delta | Relative operating-cost estimate based on LED, photoperiod, fan, and irrigation use. |
| Disease pressure | Numeric disease risk proxy used by crop model and harvest criteria. |
| Growth Camera | Omniverse virtual camera used for phenotype/camera workflow. |
| Vision fallback | Current state where image is sent but text-only Gemma cannot analyze it, so deterministic fallback assessment is used. |

---

## 30. Minimal command reference

```bash
# Local state
curl -s http://127.0.0.1:8011/smartfarm/state | python3 -m json.tool | head

# Generate live Gemma/RAG blueprints
curl -s -X POST http://127.0.0.1:8011/smartfarm/blueprint/generate \
  -H 'Content-Type: application/json' \
  -d '{"goal":"balanced","constraints":{"maxOpexIncreasePct":18,"diseaseRiskMax":"controlled"}}' \
  | python3 -m json.tool

# Twinx RAG health
TOKEN=$(cat <SMARTFARM_RAG_TOKEN_FILE>)
curl -s -H "Authorization: Bearer $TOKEN" http://<TWINX_RAG_LB>:<RAG_PORT>/healthz | python3 -m json.tool

# Twinx K8s status
ssh <TWINX_SSH_USER>@<TWINX_OPS_HOST> 'kubectl -n <K8S_NAMESPACE> get deploy,svc,pod | grep -E "<RAG_SERVICE_NAME>|<GEMMA_VLLM_SERVICE>|<OMNIVERSE_VIEWER_SERVICE>"'

# RAG server logs
ssh <TWINX_SSH_USER>@<TWINX_OPS_HOST> 'kubectl -n <K8S_NAMESPACE> logs deploy/<RAG_SERVICE_NAME> --tail=100'

# Local unit tests
export PYTHONPATH="/home/user/kit-app-template/source/extensions/joon.smartfarm.omniops:/home/user/kit-app-template/source/extensions/joon.smartfarm.twin:${PYTHONPATH:-}"
python3 -m unittest discover -s source/extensions/joon.smartfarm.omniops/joon/smartfarm/omniops/tests -p 'test_model.py'
python3 -m unittest discover -s source/extensions/joon.smartfarm.twin/joon/smartfarm/twin/tests -p 'test_rag_adapter.py'
```
