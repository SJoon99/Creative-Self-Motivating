# Design

## Source of truth
- Status: Active
- Last refreshed: 2026-06-14
- Primary product surfaces:
  - Omniverse-first SmartFarm operator experience in `joon.smartfarm.omniops`.
  - Existing SmartFarm twin scene under `/World/SmartFarm` from `joon.smartfarm.twin`.
  - WebRTC/browser surface is a remote screen viewer, not the primary product UI.
- Evidence reviewed:
  - `source/extensions/joon.smartfarm.omniops/docs/README.md`
  - `docs/Progess/2026-06-14-omniverse-first-omniops.md`
  - `docs/Progess/2026-06-02-growth-status-kpi.md`
  - `source/extensions/joon.smartfarm.omniops/joon/smartfarm/omniops/extension.py`

## Brand
- Personality: technical, trustworthy, operator-grade, demo-friendly.
- Trust signals: clear provenance labels, current twin state, confidence, evidence trail, visible actuation results in the 3D scene.
- Avoid: web-dashboard justification as the main story, over-packed panels, unlabelled AI conclusions, decorative-only metrics.

## Product goals
- Goals:
  - Let an evaluator operate the SmartFarm twin inside Omniverse without needing a separate web product.
  - Show what the farm is doing now, what blueprint is recommended, and what changes when the operator applies it.
  - Make Plan A/B/C self-explanatory: each row should state intent, control focus, and tradeoff, not only a score.
  - Explain strawberry growth state with a defensible chain: environment sensors -> crop model -> visual/phenotype observation -> planner forecast.
- Non-goals:
  - Replace the existing Web/K8S deployment path.
  - Build a full commercial crop-vision model during the POC.
  - Claim real plant measurement when the signal is synthetic or virtual-camera based.
- Success signals:
  - Main operator tasks are reachable from the Layer-side OmniOps tab without scrolling through audit logs.
  - Evidence, scoreboard, and logs are available but separated from touch-first controls.
  - Growth state is explained as model-estimated or virtual-camera-observed with confidence; real-world divergence correction is a later phase.

## Personas and jobs
- Primary personas:
  - Professor/evaluator watching a live POC demonstration.
  - Farm operator controlling recipes and blueprints in the twin.
  - Developer migrating validated features from NUC/Sandbox-Infra to Spark/TwinX.
- User jobs:
  - Inspect current crop condition.
  - Apply or compare blueprints.
  - Manually adjust actuator setpoints.
  - Verify why a blueprint or growth assessment was selected.
  - Capture a strawberry camera view and infer phenotype status inside the twin.
- Key contexts of use:
  - Same-LAN WebRTC/Kit stream during demo.
  - Direct Omniverse GUI on the development node.

## Information architecture
- Primary navigation:
  - `Layer` dock stack: selectable `SmartFarm OmniOps Dock` tab for touch/click operational controls.
  - Bottom dock stack near Console/Content: `SmartFarm Evidence` dashboard for explanations, scoreboards, histories, and logs.
- Core routes/screens:
  - Scene: `/World/SmartFarm` remains the visual source of truth.
  - Right-side OmniOps control tab.
  - Bottom evidence/evaluation tab.
- Content hierarchy:
  1. Current growth/health summary.
  2. Actionable sensor and actuator controls.
  3. Blueprint apply buttons.
  4. Camera capture / growth assessment action.
  5. Evidence, rankings, simulation traces, and operator log in the bottom panel.

## Design principles
- Principle 1: Right panel is for actions, not archives. Keep only information that changes the next operator click.
- Principle 2: Bottom panel is for explainability. Put details there when they answer “why did the system decide this?” rather than “what should I touch now?”
- Principle 3: Plant phenotype and environment are different evidence classes. Sensors infer conditions; camera/vision observes the crop. Show both and reconcile them.
- Tradeoffs:
  - A single scroll panel is faster to build but weak for evaluator comprehension.
  - A split cockpit/evidence layout costs more implementation work but better matches Omniverse-native operation and professor feedback.

## Visual language
- Color: use severity/status colors sparingly: green for healthy/on-track, amber for caution, red for disease/high-risk/divergence.
- Typography: compact labels with larger numeric KPIs for touch-friendly reading through WebRTC.
- Spacing/layout rhythm: right dock should use short cards and large buttons; bottom panel can use denser tables/tabs.
- Shape/radius/elevation: follow Kit native UI components; use compact cards, progress bars, and section grouping rather than a web-like custom design system.
- Motion: sensor charts can update live; blueprint/growth simulations should avoid sudden visual jumps unless explicitly indicating a forecast transition.
- Imagery/iconography: strawberry camera captures should be visible as thumbnails with timestamp/confidence, not only as text.

## Components
- Existing components to reuse:
  - `SmartFarm OmniOps Dock` window and Layer-tab docking behavior.
  - Existing virtual sensor rolling graphs.
  - Existing actuator sliders/toggles.
  - Existing blueprint apply buttons and twin bridge calls.
- New/changed components:
  - Compact `Growth Summary` card in the right panel.
  - `SmartFarm Evidence` bottom dock dashboard with decision summary cards, simulation timeline bars, blueprint score/description rows, vision card, and operator log.
  - `Growth Camera` capture button and latest assessment card.
  - Future: `Twin vs real camera` divergence indicator after real farm data exists.
- Variants and states:
  - Baseline / Plan A / Plan B / Plan C active states.
  - Sensor normal/caution/risk states.
  - Vision assessment states: not captured, analyzing, observed, low-confidence, stale.
- Token/component ownership:
  - Use repo-native Kit UI code inside `source/extensions/joon.smartfarm.omniops`.
  - Do not add a separate frontend design-system dependency for this Omniverse-first surface.

## Accessibility
- Target standard: demo/operator readability and touch usability; no formal WCAG claim for Kit-native panels yet.
- Keyboard/focus behavior: buttons and sliders should be reachable without floating popup windows.
- Contrast/readability: streaming viewers must read KPI labels and buttons at demo resolution.
- Screen-reader semantics: not currently supported by Kit extension; document as future gap.
- Reduced motion and sensory considerations: use bounded chart updates and avoid flashing growth-state transitions.

## Responsive behavior
- Supported breakpoints/devices:
  - Primary: Omniverse desktop window streamed over WebRTC.
  - Secondary: direct local GUI on NUC/Spark.
- Layout adaptations:
  - Right panel width should support one-column controls.
  - Bottom evidence panel should support a wide card grid with scrolling, keeping dense content inspectable without turning the right operator panel into an archive.
- Touch/hover differences:
  - Right-panel buttons/sliders must be large enough for remote/touch operation.
  - Bottom panel can prioritize inspection over touch-first action.

## Interaction states
- Loading: show “connecting/loading twin state” rather than empty panels.
- Empty: if no camera capture exists, show “No vision assessment yet; capture crop image.”
- Error: show failed API/bridge/capture provider errors in the bottom log and a compact right-panel warning.
- Success: after blueprint/camera action, show short right-panel confirmation and detailed evidence in bottom panel.
- Manual preview: actuator slider movement may update local projected sensors immediately, but copy must say it is a preview until `Apply Manual Controls` mutates the live USD twin.
- Disabled: disable apply/capture actions while scene bridge is unavailable or an action is already running.
- Offline/slow network, if applicable: WebRTC is only screen transport; internal state should indicate if the twin API/bridge is stale.

## Content voice
- Tone: confident but transparent about POC assumptions.
- Terminology:
  - Use “model-estimated” for synthetic sensor/crop-model output.
  - Use “virtual-camera-observed” for current twin-camera output and reserve “real-camera-observed” for a later physical camera integration.
  - Use “planner-forecast” for future blueprint simulation projections.
- Microcopy rules:
  - Do not say a strawberry was “measured” unless the source is a real sensor/camera.
  - Always show confidence and evidence class for growth assessments.

## Implementation constraints
- Framework/styling system: NVIDIA Omniverse Kit UI in Python; preserve existing `/World/SmartFarm` scene and existing Web/K8S path.
- Design-token constraints: follow Kit UI primitives; no new web CSS/token layer for OmniOps.
- Performance constraints: camera capture/vision analysis should be on-demand first, not continuous, to avoid blocking Kit UI.
- Compatibility constraints:
  - Development/test environment: NUC/node + Sandbox-Infra.
  - Demo/prototype environment: ARM Spark + TwinX.
  - Stable features are validated in environment 1 before porting to environment 2.
- Test/screenshot expectations:
  - Smoke test must still pass with `./scripts/smartfarm-omniops-smoke.sh`.
  - GUI check must confirm no floating OmniOps popup and that the bottom evidence panel docks beside Console/Content.

## Open questions
- [ ] Which foundation/vision model provider will be used for the first real image-analysis adapter? Owner: Gemma/RAG integration team or local POC implementer. Impact: dependency and latency.
- [ ] Should virtual-camera captures be persisted as image artifacts in repo-local logs, DB, or external object storage? Owner: implementation. Impact: demo repeatability and audit trail.
- [ ] What minimum camera-derived traits are required for the professor demo: fruit count, redness/maturity, leaf health, disease spots, canopy density, or all of them? Owner: product/demo. Impact: scope.
- [ ] When real farm data exists, define the threshold and policy for Twin-vs-real-camera divergence correction. Owner: later product/research phase. Impact: assimilation logic.
