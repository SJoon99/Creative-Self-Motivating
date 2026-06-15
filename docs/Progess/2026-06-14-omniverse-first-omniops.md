# 2026-06-14 SmartFarm OmniOps: Omniverse-first 새 프로젝트

## 결정

교수 평가/시연 관점에서는 Web portal을 주 제품 UI로 설명하지 않는다. Web은 원격 화면 전달용 WebRTC viewer로만 둔다. 실제 기능은 Omniverse Kit extension 내부 패널과 기존 SmartFarm USD scene에 구현한다.

중요한 수정 원칙:

> 새 프로젝트여도 딸기농장 환경은 새로 만들지 않는다. 기존 `joon.smartfarm.twin`이 만드는 `/World/SmartFarm` 환경을 그대로 사용한다. `joon.smartfarm.omniops`는 그 위에 운영 패널만 추가한다.

기존 구현은 유지한다.

- 기존 scene/logic extension: `joon.smartfarm.twin`
- 기존 Web/K8S/TwinX 배포: 유지
- 신규 operator UI extension: `joon.smartfarm.omniops`

## 환경 구분

### 1번 개발/테스트 환경

- 대상: NUC/node + Sandbox-Infra
- 목적: 새 Omniverse 패널 개발, 기존 딸기농장 scene behavior 테스트
- 원칙: 기능 검증은 이 환경에서 먼저 한다.

### 2번 프로토타입/시연 환경

- 대상: ARM DGX Spark + TwinX
- 목적: 검증된 결과 적용 및 시연
- 원칙: 1번에서 검증된 app/extension만 포팅한다.

## 추가된 파일

```txt
source/extensions/joon.smartfarm.omniops/
source/apps/joon.smartfarm_omniops.kit
source/apps/joon.smartfarm_omniops_streaming.kit
scripts/smartfarm-omniops-smoke.sh
scripts/smartfarm-omniops-dev.sh
scripts/smartfarm-omniops-streaming.sh
```

## 구조

```txt
joon.smartfarm_omniops.kit
  ├─ joon.smartfarm.twin       # 기존 딸기농장 scene/API/Blueprint/actuator 로직
  └─ joon.smartfarm.omniops    # 신규 Omniverse-first right-docked operator panel
```

신규 `omniops`는 자체 농장 scene을 만들지 않는다. Scene root는 항상 기존 twin의 다음 경로다.

```txt
/World/SmartFarm
```

같은 Kit 프로세스 안에서는 `omniops`가 `joon.smartfarm.twin.get_active_extension()` 브릿지로 직접 호출한다. 이유는 Kit update loop 안에서 `127.0.0.1:8011`로 자기 자신에게 HTTP 호출을 걸면 service callback 처리와 update thread가 서로 기다리는 self-call deadlock이 날 수 있기 때문이다.

외부 클라이언트/검증용 HTTP API는 그대로 유지한다.

```txt
GET  http://127.0.0.1:8011/smartfarm/state
POST http://127.0.0.1:8011/smartfarm/scene/growth
POST http://127.0.0.1:8011/smartfarm/scene/reset
POST http://127.0.0.1:8011/smartfarm/planning/run
POST http://127.0.0.1:8011/smartfarm/blueprint/apply
POST http://127.0.0.1:8011/smartfarm/actuator/apply
```

## 구현 범위

### Omniverse Right Panel

Window: `SmartFarm OmniOps Dock`

구현됨:

- 시작 시 popup처럼 띄우지 않고 `Layer` 패널과 같은 dock stack에 선택 가능한 tab으로 붙임
- docking은 `Layer` SAME-tab을 우선 사용하고, target이 준비되지 않은 frame에서는 OmniOps window를 다시 숨겨 floating popup layout이 저장되지 않게 함
- dock 완료 후 tab bar를 유지해서 `Layer`와 `SmartFarm OmniOps Dock`을 서로 선택할 수 있게 함
- 기본 Property/Details pane만 fallback target이 아닐 때 숨김

- Twin Source
  - Scene Root
  - Scene Mode
  - Active Blueprint
- Growth Status
  - Health / Maturity / Ready KPI cards with progress bars; health card omits the long model-estimated confidence text to avoid overflow
  - Expected Ship
  - Disease Risk
  - Main Limiter
- Virtual Sensors rolling graphs
  - DLI
  - Substrate moisture
  - Humidity
  - Temperature
  - CO2
- Actuator controls
  - LED intensity slider
  - Photoperiod slider
  - Irrigation pulses slider
  - Fan duty slider
  - CO2 setpoint slider
  - Water valve toggle
  - Apply Manual Controls
- Blueprint Apply
  - Plan A
  - Plan B
  - Plan C
  - Baseline is kept as the fixed current-state twin and is reached through Reset Baseline
- Create Current Twin
- Reset Baseline
- Run Daily Planning
- Refresh State

### Growth Camera

- Camera guide/frustum scale is intentionally very small (`GROWTH_CAMERA_VISUAL_SCALE=0.006`) so the camera object/gizmo does not dominate the farm view.
- Camera FOV is moderately zoomed for the bottom-right live view (`focalLength=38.0`, aperture `32.0 x 18.0`) while keeping the same plant-crown target so pre-fruit leaf/canopy states remain visible.
- The bottom-right live camera remains bound to `GrowthPhenotypeCamera`, but is docked as a 30% split so the plan dashboard remains primary while the live camera is large enough to inspect and the accepted camera framing is preserved.

### Evidence Dashboard / Scoreboard / Log

오른쪽 `SmartFarm OmniOps Dock`은 실제 클릭/터치 가능한 운영 cockpit으로 줄였다. Growth Status는 오른쪽 dock의 KPI card로만 유지하고, 하단 `SmartFarm Evidence` panel은 Generate 이후 갱신되는 Plan A/B/C 설명, Operator Log, 우측 Growth Camera live viewport 중심으로 분리해서 중복을 줄인다.

의도:

- 오른쪽: Growth Summary, Virtual Sensor, Actuator, Blueprint Apply, Growth Camera 같은 즉시 조작 요소
- 아래쪽: Simulation Evidence, Blueprint Scoreboard, Vision Assessment, Operator Log 같은 설명/감사/검증 요소

`SmartFarm Evidence`는 Console/Content가 있는 하단 dock stack에 붙는 것을 우선한다. popup으로 떠야 하는 제품 UI가 아니라, Omniverse 내부 explainability panel이다.

현재 하단 패널은 단순 텍스트 나열이 아니라 `Evidence Dashboard` 형태로 구성한다.

2026-06-15 clarification:

- Recommended top card는 “추천 Plan의 twin simulation score /100”이다. 생육 진행률이 아니다.
- Applied top card는 “현재 적용된 Twin 상태의 healthScore /100”이다.
- Gemma/RAG Run top card는 Gemma/RAG endpoint가 실제 응답했는지(`Gemma live`, `Gemma legacy`, `Gemma + fallback`, `Twin fallback`, `Offline fallback`)와 생성 plan/source 개수를 보여준다.
- Growth Camera top card는 “카메라 기반 whole-cycle growthProgressPercent”이다.
- Plan A/B/C row의 score는 Gemma/RAG 후보를 Twin이 harvest horizon까지 시뮬레이션한 ranking score이다.
- Plan A/B/C는 고정 전략 클래스가 아니라 neutral display slot이다. Generate마다 후보를 먼저 score rank로 정렬한 뒤, rank가 A/B/C에 순환 배정되므로 특정 글자만 항상 0점으로 보이지 않는다.
- Twin quality gate는 Gemma/RAG 후보가 Twin 시뮬레이션에서 0점/고질병위험/harvest horizon 실패로 판정될 때만 airflow/light/CO2를 1회 보정하고 다시 시뮬레이션한다. 원본 Gemma 후보의 score/actuator는 `qualityGate` 및 `original*` trace에 남긴다.
- `ship -Nd`는 현재 Baseline 예상 출하일 대비 N일 빨라짐을 뜻한다. 값이 없으면 `--d`가 아니라 `ship n/a`로 표시한다.
- Vision provider는 실제 Gemma/RAG vision endpoint 성공 시에만 `Gemma vision`으로 표시하고, endpoint 미설정/실패 시에는 `Local fallback`으로 표시한다.
- Omniverse UI font가 한글/비ASCII 설명을 `?`로 렌더링할 수 있으므로 Gemma/RAG 요청에는 English ASCII UI text contract를 포함하고, 그래도 비ASCII 설명이 오면 Plan row에서는 영어 fallback 문구로 대체한다.
- Generate 실행마다 `logs/smartfarm-blueprints/<timestamp>_<runId>.json` trace를 저장해 Gemma/RAG 응답, RAG source, gap analysis, Twin simulation ranking, 사용된 vision input을 재검증할 수 있게 한다.

- 상단 decision summary cards
  - Recommended
  - Applied
  - Growth Health
  - Fruit Maturity
  - Disease Risk
  - Vision Check
- Simulation Timeline
  - projected maturity progress bar
  - DLI / disease pressure / yield context
- Blueprint Scoreboard
  - score bar
  - lead time, OpEx, disease-risk explanation
  - recommended marker와 applied marker
  - Plan A/B/C별 operator intent, control focus, tradeoff 설명
- Vision Assessment
  - Growth Camera POC card
  - source/provider/confidence
  - phenotype traits
- Operator Log
  - 최근 조작/API/camera event audit trail

### Manual actuator -> sensor projection

수동 actuator 조작은 단순히 슬라이더 값만 바꾸는 것이 아니라 synthetic sensor/crop state로 투영한다.

규칙:

- LED intensity + photoperiod 증가 → DLI 증가, 온도 약간 증가
- irrigation pulse + water valve → substrate moisture 증가, humidity 일부 증가
- fan duty 증가 → humidity/disease pressure 감소, 온도 약간 감소
- CO₂ setpoint 증가 → synthetic CO₂ sensor 증가, growth index 일부 개선

OmniOps 오른쪽 패널에서는 slider를 움직이는 즉시 `manual-actuator-preview` 상태로 sensor graph/KPI가 바뀐다. `Apply Manual Controls`를 누르면 같은 actuator recipe가 live SmartFarm Twin으로 전달되어 USD scene visual과 service state가 함께 바뀐다.

### Growth Camera / Vision POC

초기 시연 카메라 framing 기록:

```txt
Camera path: /World/SmartFarm/Cameras/GrowthPhenotypeCamera
Focal length: 18.0
Aperture: 24.0 x 13.5
Clip range: 0.05 - 12.0
Position: (-43.0, 2.18, -14.6)
Rotation: (-20.0, -115.0, 0.0)
Visual scale: 0.16
Soft fill: /World/SmartFarm/Cameras/GrowthPhenotypeFillLight, intensity 180.0
```

2026-06-15 update:

```txt
Focal length: 38.0
Aperture: 32.0 x 18.0
Clip range: 0.05 - 9.0
Position: (-26.2, 1.75, -17.5)
Look-at target: (-29.0, 1.50, -15.2)
Visual scale: 0.006
Soft fill: /World/SmartFarm/Cameras/GrowthPhenotypeFillLight, intensity 90.0
Bottom layout: SmartFarm Evidence dashboard 7 + SmartFarm Strawberry Live View 3
```


실제 딸기 생육 상태를 어떻게 확인하느냐는 질문에 대응하기 위해 1차 범위는 “실제 환경 보정”이 아니라 “트윈 내부에서 카메라 기반 생육 확인 흐름을 구현”하는 것으로 제한한다.

구현됨:

- `/World/SmartFarm/Cameras/GrowthPhenotypeCamera` virtual crop camera 생성
- 오른쪽 Dock에 `Focus Growth Camera`, `Capture & Analyze Growth` 추가
- capture 요청 및 `logs/smartfarm-vision/` PNG/metadata sidecar 기록
- `SMARTFARM_VISION_BASE_URL` 또는 `SMARTFARM_RAG_BASE_URL` 설정 시 캡처 PNG를 Gemma/RAG vision endpoint로 전송
- endpoint 미설정/실패 시 deterministic phenotype estimator fallback
  - source: `virtual-camera-observed` 또는 `virtual-camera-gemma-observed`
  - provider: `foundation-model-adapter/mock` 또는 `twinx-gemma-vision`
  - confidence: provider 응답 또는 `poc-heuristic`
  - whole-cycle growth progress %, health, maturity, fruit set, canopy vigor, disease risk 표시

명시적 제외:

- 실제 IP camera 연결
- 실제 환경과 Twin 예측값의 divergence 계산 및 보정

따라서 시연 설명은 다음과 같이 한다.

```txt
현재 POC는 실제 농장 카메라 대신 Omniverse 내부 Growth Camera로 phenotype 관측 흐름을 검증합니다.
SMARTFARM_VISION_BASE_URL/SMARTFARM_RAG_BASE_URL이 설정되어 있으면 캡처 PNG를 Gemma/RAG vision adapter로 보내고,
설정이 없거나 실패하면 deterministic fallback으로 전체 생육 진행률을 산출합니다.
현 단계에서는 실제 IP camera ingestion과 실제 환경 assimilation은 범위 밖입니다.
```

## 테스트 방법

### 0. 기존 구현 보존 확인

기존 `joon.smartfarm.twin` / Web / TwinX 배포를 직접 수정하지 않는다. 신규 파일은 별도 app/extension으로만 추가한다.

```bash
cd /home/joon/kit-app-template
git status --short -- source/extensions/joon.smartfarm.omniops source/apps/joon.smartfarm_omniops.kit source/apps/joon.smartfarm_omniops_streaming.kit scripts/smartfarm-omniops-*.sh docs/Progess/2026-06-14-omniverse-first-omniops.md
```

### 1. 순수 모델 smoke test

Omniverse를 띄우지 않고 crop model / KPI / blueprint ranking fallback을 검증한다.

```bash
cd /home/joon/kit-app-template
./scripts/smartfarm-omniops-smoke.sh
```

기대 결과:

```txt
Ran 9 RAG adapter tests ... OK
Ran 5 OmniOps model tests ... OK
SmartFarm OmniOps smoke passed.
```

### 2. 1번 개발환경 GUI 테스트

NUC/node의 GUI 가능한 환경에서 실행한다.

```bash
cd /home/joon/kit-app-template
./scripts/smartfarm-omniops-dev.sh
```

확인할 것:

1. 기존 딸기농장 환경이 열린다. 새 단순 농장이 아니라 `/World/SmartFarm`이어야 한다.
2. `SmartFarm OmniOps Dock` 패널이 popup이 아니라 `Layer` 옆 선택 가능한 dock tab으로 붙어 있다.
3. `Layer` tab과 OmniOps tab을 전환하면서 센서/액추에이터/Blueprint/evidence/log를 모두 조작할 수 있다.
4. Stage에 `/World/SmartFarm`가 존재한다.
5. `Virtual Sensors`가 rolling line graph로 갱신된다.
6. `Apply Manual Controls`를 누르면 기존 SmartFarm scene의 actuator visual/sensor state가 바뀐다.
7. `Create Current Twin`을 누르면 기존 SmartFarm Twin의 `/scene/growth`가 호출된다.
8. `Plan B`를 누르면 기존 SmartFarm scene에서:
   - Health / maturity / readiness 값이 바뀐다.
   - 기존 LED/Fan/Irrigation/CO2 visual이 바뀐다.
   - 기존 딸기 crop visual이 바뀐다.
   - 오른쪽 panel의 evidence/log가 갱신된다.
9. `Plan C`를 누르면 기존 SmartFarm scene에서 disease-safe 상태가 반영된다.
10. `Reset Baseline`으로 현재 baseline 상태로 복귀한다.

### 3. WebRTC 화면 전달 테스트

이건 Web dashboard가 아니라 **Omniverse 화면 viewer용**이다.

Spark/NUC에서:

```bash
cd /home/joon/kit-app-template
./scripts/smartfarm-omniops-streaming.sh
```

다른 터미널에서 포트 확인:

```bash
ss -ltnup | grep -E '49100|47998|8011'
```

시연 PC에서는 같은 내부망에서 WebRTC viewer로:

```txt
signaling: <host-ip>:49100
media UDP: <host-ip>:47998
```

평가 설명:

```txt
브라우저는 UI가 아니라 Omniverse 화면을 원격으로 보는 viewer입니다.
운영 패널, 시뮬레이션, Blueprint 적용 로직은 모두 Omniverse extension 내부에 있고, 기존 딸기농장 Twin scene과 직접 연결되어 있습니다.
```

### 4. 2번 환경 포팅 전 확인

2번 ARM Spark + TwinX로 옮기기 전에는 1번에서 다음을 완료해야 한다.

- smoke test 통과
- GUI에서 기존 `/World/SmartFarm`가 열리는지 확인
- 모든 Blueprint apply가 기존 scene에 반영되는지 확인
- WebRTC streaming으로 Omniverse panel이 보이는지 확인
- 기존 `joon.smartfarm.twin` / TwinX Web 배포 영향 없음 확인

## 다음 개발 단계

1. 하단 Evidence의 Growth Camera live viewport를 시연 화면에서 육안 확인하고 필요 시 해상도/카메라 앵글 추가 조정
2. sensor graph를 현재 단순 rolling line에서 더 명확한 chart/threshold 스타일로 개선
3. 기존 scene 내부 sensor/actuator label 강화
4. 기존 `joon.smartfarm.twin`의 UI는 숨기고 `omniops` 패널을 평가용 primary UI로 사용
5. 검증 후 2번 Spark/TwinX에는 `joon.smartfarm_omniops_streaming.kit`를 배포
