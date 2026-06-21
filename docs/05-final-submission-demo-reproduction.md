# 최종 제출용 데모 재현 가이드

> 제출 프로젝트 파일명: `2026-C&S Project_Final_project_Team-Code.zip`
> 제출 데모 영상 파일명: `2026-C&S Project_Final_demo_Team-Code.mp4`
> 프로젝트 제출 위치: <https://drive.google.com/drive/u/2/folders/1VyvHmygcX_YTKeGApbbq0USLZdnFr0-X>
> 데모 영상 제출 위치: <https://drive.google.com/drive/u/2/folders/1_APMYRWEw0t4Ccbcvt4UPyh4amfMo8qz>

이 문서는 과제 검증 요구사항인 **“제3자가 직접 녹화된 데모 비디오를 기준으로 동일한 Omniverse app 버전에서 똑같이 따라 할 수 있어야 한다”**를 만족하기 위한 실행/시연 절차서이다.
데모 영상 자체의 내레이션과 편집은 제출자가 별도로 작성하되, 영상에서 보여주는 조작 순서는 아래 절차와 맞추면 된다.

---

## 1. 프로젝트 개요

이 프로젝트는 NVIDIA Omniverse Kit 기반의 **딸기 스마트팜 Digital Twin + Gemma/RAG Blueprint 검증 POC**이다.

핵심 흐름은 다음과 같다.

1. 현재 스마트팜 상태를 Omniverse Twin 안에 **Baseline**으로 표현한다.
2. 센서값, 현재 crop state, Growth Camera 관측값을 Gemma/RAG 요청 context로 사용한다.
3. `Generate Gemma/RAG Blueprints` 버튼을 누르면 Plan A/B/C 형태의 Blueprint 후보 3개를 생성한다.
4. 각 후보는 바로 적용되지 않고, Twin rolling-horizon simulation으로 먼저 검증된다.
5. UI는 추천 Plan, score, score 산정 근거, RAG trace, DAG branch graph를 함께 보여준다.
6. 운영자가 Plan을 적용하거나 다시 Generate하여 branch/replan 과정을 이어간다.

### Baseline과 Plan의 의미

- **Baseline**: 현재 상태를 Twin에 표현한 고정 기준이다. Gemma/RAG 후보와 매핑되는 전략명이 아니다.
- **Plan A/B/C**: Gemma/RAG가 현재 상태를 보고 생성한 중립적인 후보 slot이다. A가 항상 저비용, B가 항상 조기출하 같은 고정 의미를 갖지 않는다.
- **Recommended Plan**: Twin simulation score가 가장 좋은 후보이다.
- **Applied Plan**: 운영자가 실제로 적용한 후보이다.

---

## 2. 검증자가 준비해야 하는 환경

### 2.1 필수 환경

| 항목 | 값 / 설명 |
|---|---|
| OS | Linux 환경 권장. 현재 개발/시연은 `linux-aarch64` 또는 `linux-x86_64` Kit build layout을 자동 감지하도록 구성됨 |
| GPU | Omniverse Kit 실행 가능 GPU |
| Omniverse/Kit | 이 저장소의 Kit App Template 기반 build. `tools/VERSION.md` 기준 `110.1.1`, SmartFarm app version `0.1.0` |
| Python | Omniverse Kit 포함 Python + 로컬 테스트용 Python 3 |
| 네트워크 | 로컬 GUI만 검증하면 외부 네트워크 불필요. TwinX live Gemma/RAG 검증은 동일 내부망과 RAG endpoint 접근 권한 필요 |

### 2.2 포함된 주요 앱

| 앱 파일 | 용도 |
|---|---|
| `source/apps/joon.smartfarm_omniops.kit` | 로컬 GUI 데모용 SmartFarm OmniOps Composer |
| `source/apps/joon.smartfarm_omniops_streaming.kit` | WebRTC/브라우저 스트리밍용 headless OmniOps app |
| `source/extensions/joon.smartfarm.twin/` | Twin scene, sensor/actuator model, planning/RAG adapter |
| `source/extensions/joon.smartfarm.omniops/` | 오른쪽 Dock, 하단 Evidence Dashboard, RAG Trace, Blueprint DAG UI |

### 2.3 Live Gemma/RAG와 Offline POC 모드

프로젝트는 두 방식으로 재현 가능하다.

| 모드 | 설명 | 검증 포인트 |
|---|---|---|
| Live Gemma/RAG | `SMARTFARM_RAG_BASE_URL`이 실제 RAG/Gemma endpoint를 가리키고, 필요 시 token file을 사용 | RAG Trace에 live call, source count, model adapter 상태 표시 |
| Offline/Fallback POC | endpoint 접근이 안 되거나 vision-capable model이 없으면 deterministic fallback 사용 | UI 흐름, Plan 생성, Twin score, DAG graph, capture sidecar JSON 재현 가능 |

제출 ZIP에는 보안상 내부 credential을 포함하지 않는다. Live endpoint는 실행 환경 변수로 주입한다.

---

## 3. 압축 해제 후 빠른 실행

검증자가 제출 ZIP을 받은 뒤 아래 순서대로 실행한다.

```bash
unzip 2026-C\&S\ Project_Final_project_Team-Code.zip -d smartfarm-final
cd smartfarm-final
```

### 3.1 build 결과가 포함된 경우

```bash
./scripts/smartfarm-omniops-dev.sh
```

스크립트는 다음 중 존재하는 Kit binary를 자동 사용한다.

```text
_build/linux-aarch64/release/kit/kit
_build/linux-x86_64/release/kit/kit
```

### 3.2 build 결과가 없는 경우

동일 Omniverse/Kit SDK가 설치되어 있고 네트워크로 extension cache를 받을 수 있는 환경에서:

```bash
./repo.sh build
./scripts/smartfarm-omniops-dev.sh
```

> 참고: 과제 검증은 “동일한 Omniverse app 버전” 기준이므로, 제출 ZIP에 build 결과를 포함하지 않는 경우 검증자도 동일 Kit SDK/extension cache 환경을 맞춰야 한다.

### 3.3 실행 상태 확인

다른 터미널에서:

```bash
./scripts/smartfarm-twin-status.sh
```

정상이라면 다음 항목이 확인된다.

- SmartFarm Kit process 실행 중
- API port `8011` listening
- WebRTC signaling port `49100` listening 또는 streaming app 실행 가능
- `/smartfarm/state` API 응답

직접 API 확인:

```bash
curl -fsS http://127.0.0.1:8011/smartfarm/state | python3 -m json.tool | head -80
```

---

## 4. 데모 영상과 동일하게 따라 하는 조작 순서

아래 순서는 데모 영상의 체크포인트로 그대로 사용할 수 있다.

### Step 1. SmartFarm OmniOps Composer 실행 확인

1. `./scripts/smartfarm-omniops-dev.sh` 실행.
2. Omniverse 창 제목 또는 앱 제목이 `SmartFarm OmniOps Composer 0.1.0`인지 확인.
3. Viewport에 딸기 스마트팜 scene이 보이는지 확인.
4. 우측 패널에서 `SmartFarm OmniOps Dock` 탭을 확인.
5. 하단 패널에서 다음 탭을 확인.
   - `SmartFarm Evidence`
   - `SmartFarm RAG Trace`
   - `SmartFarm Blueprint DAG`
   - `SmartFarm Strawberry Live View`

정상 화면의 의미:

- 상단 Viewport: 현재 Twin scene.
- 우측 Dock: 운영자가 누르는 control panel.
- 하단 Evidence: AI/Twin 검증 결과와 Plan 설명.
- 하단 Live View: Growth camera로 보는 딸기 상태.

### Step 2. Baseline/current state 확인

우측 Dock에서 현재 actuator/sensor 값을 확인한다.

| UI 항목 | 의미 |
|---|---|
| LED / DLI 관련 slider | 조명 강도와 광주기 입력 |
| Irrigation pulses | 하루 관수 횟수 |
| Fan duty | 환기/팬 duty 비율 |
| CO2 setpoint | CO2 목표 농도 |
| Water valve | 현재 관수 valve 상태 |
| Growth Camera | 딸기 생육 관측용 가상 카메라 경로 |

Baseline은 “현재 상태”를 표시하는 역할이다. Plan A/B/C 중 하나가 Baseline이 되는 구조가 아니다.

### Step 3. 현재 Twin 상태 동기화

필요하면 우측 Dock에서 다음 버튼을 누른다.

1. `Refresh State`
2. `Create Current Twin`

이 단계는 시연자가 “현재 상태를 먼저 Twin에 고정한다”는 의미로 보여주면 된다.

### Step 4. Gemma/RAG Blueprint 생성

우측 Dock에서:

```text
Generate Gemma/RAG Blueprints
```

버튼을 누른다.

예상 결과:

1. 하단 `SmartFarm Evidence`에 Recommended Plan과 Plan A/B/C card가 갱신된다.
2. 각 plan card에는 score, 예상 ship day, actuator recipe, AI rationale, risk가 표시된다.
3. `SmartFarm RAG Trace` 탭에는 RAG/Gemma 호출 상태, source count, fallback 여부, trace 요약이 표시된다.
4. `SmartFarm Blueprint DAG` 탭에는 branch graph PNG가 표시된다.
5. `logs/smartfarm-blueprints/` 아래에 trace JSON이 생성된다.

정상 동작 확인용 로그:

```bash
find logs/smartfarm-blueprints -maxdepth 3 -type f | sort | tail -20
```

### Step 5. Score와 생성 기준 설명

Evidence Dashboard에서 다음 정보를 보여준다.

| 영역 | 의미 |
|---|---|
| Recommended Plan | Twin simulation 기준 가장 높은 점수를 받은 후보 |
| Applied Plan | 운영자가 실제 적용한 후보 |
| Gemma/RAG Run | 이번 Generate가 live Gemma/RAG인지 fallback인지, source가 몇 개인지 |
| Growth Camera | 최근 capture/vision 분석 상태 |
| Blueprint Trajectory & Score Basis | score 가중치, 사용된 sensor/vision/RAG context, trajectory preview |
| Blueprint Branch Candidates | Plan A/B/C 각각의 actuator 조합과 생성 이유 |

현재 score는 Gemma confidence가 아니라 **Twin validation score**이다.

기본 가중치:

| 항목 | 가중치 | 설명 |
|---|---:|---|
| earliestShipment | 0.36 | Baseline보다 얼마나 빨리 출하 가능한지 |
| yield | 0.24 | 예상 수량/수확 readiness |
| diseaseControl | 0.22 | 병해 위험을 얼마나 낮게 유지하는지 |
| opex | 0.10 | 운영 비용 증가를 얼마나 억제하는지 |
| actuatorSafety | 0.08 | LED/관수/팬/CO2 조합이 안전 범위에 있는지 |

따라서 score가 0에 가까우면 “AI가 실패했다”라기보다, 해당 candidate가 현재 Twin 조건에서 harvest horizon, disease risk, opex, actuator safety 조건을 만족하지 못했다는 의미이다.

### Step 6. Blueprint DAG / branch graph 확인

`SmartFarm Blueprint DAG` 탭을 선택한다.

이 패널은 feedback에서 요구된 “Plan들이 그냥 3개 카드로만 보이는 것이 아니라, branch 후보와 replan 흐름으로 보이게 하는 시각화”를 위해 추가된 패널이다.

표시되는 구조:

```text
Current State
   ↓
Generate Gemma/RAG
   ↓
Plan A ┐
Plan B ├─ Twin Validation / Quality Gate ─ Recommended ─ Apply
Plan C ┘
   ↘ 실패/부적합 시 Replan feedback edge
```

추가로 하단에는 generate-run selection chain이 표시된다.

예시:

```text
Generate #1 selected Plan B  ->  Generate #2 selected Plan C  ->  Generate #3 pending
```

이것은 git branch처럼 **각 Generate 결과와 그중 선택한 branch의 연결**을 보여주기 위한 POC 시각화이다.
완전한 자동 강화학습/rollback optimizer가 아니라, 현재 데모 범위에서는 다음을 보장한다.

- Generate할 때마다 run id와 Plan A/B/C 후보가 기록된다.
- 사용자가 Plan을 적용하면 해당 run의 selected branch가 기록된다.
- 다음 Generate는 현재 Twin state와 최근 선택 이력을 context로 삼아 다시 후보를 만든다.
- DAG panel은 선택 이력과 replan feedback edge를 시각적으로 보여준다.

DAG 이미지 파일은 아래에 저장된다.

```bash
ls -lh logs/smartfarm-blueprints/dag/
```

### Step 7. Plan 적용

우측 Dock에서 직접 `Plan A`, `Plan B`, `Plan C` 중 하나를 누르거나:

```text
Apply Recommended
```

버튼을 누른다.

예상 결과:

- Applied Plan이 갱신된다.
- Twin 내부 actuator/crop state가 해당 plan 기준으로 업데이트된다.
- Evidence Dashboard의 Applied Plan score가 바뀐다.
- DAG selection chain에 선택 결과가 반영된다.

### Step 8. 다시 Generate하여 branch/replan 흐름 확인

Plan 적용 후 다시:

```text
Generate Gemma/RAG Blueprints
```

를 누른다.

확인할 것:

- Plan A/B/C가 이전 Generate와 다른 후보로 갱신된다.
- Score와 trajectory가 현재 state 기준으로 다시 계산된다.
- `SmartFarm Blueprint DAG` 하단에 이전 선택과 다음 Generate가 이어진 형태로 표시된다.
- `SmartFarm RAG Trace`에는 새로운 run trace가 추가된다.

### Step 9. Growth Camera capture & analyze

우측 Dock에서:

```text
Capture & Analyze Growth
```

버튼을 누른다.

예상 결과:

- 현재 Growth camera 화면이 PNG로 저장된다.
- sidecar JSON에 growth progress, health, risk, analysis mode가 저장된다.
- image-capable Gemma endpoint가 가능하면 실제 이미지 분석 요청이 들어간다.
- 현재 배포가 text-only Gemma이거나 vision endpoint가 없으면 deterministic fallback 분석을 사용하고, UI/JSON에 fallback 여부가 표시된다.

확인 명령:

```bash
find logs/smartfarm-vision -maxdepth 1 -type f | sort | tail -20
```

---

## 5. Live Gemma/RAG 연결 설정

Live endpoint가 있는 환경에서는 실행 전에 아래 환경 변수를 지정한다.

```bash
export SMARTFARM_RAG_BASE_URL="http://<TWINX_RAG_LB_HOST>:<PORT>"
export SMARTFARM_RAG_TOKEN_FILE="$HOME/.smartfarm-rag-token"   # 필요 시
export SMARTFARM_RAG_TIMEOUT=30
./scripts/smartfarm-omniops-dev.sh
```

스트리밍 앱도 동일한 환경 변수를 사용한다.

```bash
export SMARTFARM_PUBLIC_HOST="<BROWSER에서_접근할_HOST_OR_IP>"
export SMARTFARM_RAG_BASE_URL="http://<TWINX_RAG_LB_HOST>:<PORT>"
./scripts/smartfarm-omniops-streaming.sh
```

Live 호출 여부는 다음에서 확인한다.

1. `SmartFarm RAG Trace` 패널
2. `logs/smartfarm-blueprints/*.json`
3. Kit stdout 또는 `logs/smartfarm-omniops-streaming.log`

Trace JSON에서 확인할 대표 필드:

| 필드 | 의미 |
|---|---|
| `runId` | Generate 실행 id |
| `model` / `adapter` | Gemma/RAG adapter 정보 |
| `sourceCount` | 사용된 RAG source 수 |
| `generationCriteria` | 어떤 sensor/vision/context로 만들었는지 |
| `candidates` | Plan A/B/C 후보 |
| `scoreBreakdown` | Twin validation score 세부 항목 |
| `qualityGate` | 위험 후보 보정 여부 |
| `trajectory` | readiness/disease/opex 미래 preview |

---

## 6. WebRTC / 브라우저 스트리밍 실행

로컬 GUI가 아니라 브라우저에서 Omniverse 화면만 보이게 할 때 사용한다.

```bash
export SMARTFARM_PUBLIC_HOST="<검증자가_브라우저에서_접근할_HOST_OR_IP>"
./scripts/smartfarm-omniops-streaming.sh
```

다른 터미널에서:

```bash
./scripts/smartfarm-twin-status.sh
```

기본 port:

| 용도 | 기본값 |
|---|---:|
| SmartFarm local API | `127.0.0.1:8011` |
| WebRTC signaling | `<SMARTFARM_PUBLIC_HOST>:49100` |
| WebRTC media UDP | `<SMARTFARM_PUBLIC_HOST>:47998` |

브라우저 viewer를 별도로 사용하는 경우 `web/omniverse-direct-viewer/`의 설정에서 signaling host/port를 위 값으로 맞춘다.
검증 환경에서 WebRTC가 막히면 local GUI app으로 동일 기능을 검증할 수 있다.

---

## 7. 제출 ZIP에 포함되어야 하는 파일

최소 포함 권장 항목:

```text
README.md
Agent.md
docs/
scripts/
source/apps/
source/extensions/joon.smartfarm.twin/
source/extensions/joon.smartfarm.omniops/
source/OwnType/
web/omniverse-direct-viewer/
web/smartfarm-web/
services/smartfarm-service/
repo.toml
premake5.lua
tools/VERSION.md
```

보통 제외해도 되는 항목:

```text
_build/        # build 결과를 별도로 제공하지 않는 경우 제외 가능
logs/          # 실행 중 생성되는 trace/capture 파일
figure/        # 로컬 스크린샷
.cache/
.local/
```

현재 repository에는 scene 재현을 위한 일부 대형 USD/asset이 포함되어 있으므로 ZIP 크기가 커질 수 있다. Git에 올라간 tracked 파일 기준으로 ZIP을 만들려면:

```bash
git archive --format=zip --output "2026-C&S Project_Final_project_Team-Code.zip" HEAD
```

실행 중 생성되는 `logs/`, `figure/` 같은 로컬 산출물을 확실히 제외한 제출 ZIP을 만들려면 아래처럼 tracked 파일 중 runtime artifact만 제외한다.

```bash
git ls-files | grep -v "^logs/" | grep -v "^figure/" > /tmp/smartfarm-submit-files.txt
git archive --format=zip --output "2026-C&S Project_Final_project_Team-Code.zip" HEAD -- $(cat /tmp/smartfarm-submit-files.txt)
```

build 결과까지 함께 제출해야 하는 수업 운영 방식이면 `_build/` 포함 여부를 별도로 확인한다.

---

## 8. 검증자가 성공으로 판단할 체크리스트

아래 항목이 모두 보이면 데모 재현 성공으로 볼 수 있다.

- [ ] `SmartFarm OmniOps Composer 0.1.0` 실행
- [ ] Viewport에 딸기 스마트팜 Twin scene 표시
- [ ] 우측 `SmartFarm OmniOps Dock` 표시
- [ ] 하단 `SmartFarm Evidence` 표시
- [ ] 하단 `SmartFarm RAG Trace` 표시
- [ ] 하단 `SmartFarm Blueprint DAG` 표시
- [ ] 하단 `SmartFarm Strawberry Live View` 표시
- [ ] `Generate Gemma/RAG Blueprints` 클릭 시 Plan A/B/C 생성
- [ ] 각 Plan에 score, actuator controls, rationale/risk 표시
- [ ] score basis/weights 표시
- [ ] DAG graph에 Plan branch와 Recommended/Apply 흐름 표시
- [ ] Plan 적용 후 Applied Plan 갱신
- [ ] 다시 Generate 시 run/selection chain이 이어짐
- [ ] `Capture & Analyze Growth` 클릭 시 PNG/JSON 결과 생성
- [ ] `logs/smartfarm-blueprints/`와 `logs/smartfarm-vision/`에 재현 가능한 산출물 생성

---

## 9. 문제 해결

### 9.1 앱이 실행되지 않음

```bash
ls -lh _build/linux-aarch64/release/kit/kit _build/linux-x86_64/release/kit/kit 2>/dev/null
```

Kit binary가 없으면:

```bash
./repo.sh build
```

### 9.2 port가 이미 사용 중

기본 launcher는 기존 SmartFarm Kit process를 정리하려고 시도한다. 그래도 충돌하면:

```bash
./scripts/smartfarm-twin-status.sh
ps -ef | grep 'joon.smartfarm' | grep -v grep
```

필요한 경우 해당 Kit process를 종료하고 다시 실행한다.

### 9.3 Generate를 눌러도 live Gemma 호출이 안 보임

확인할 것:

```bash
echo "$SMARTFARM_RAG_BASE_URL"
ls -l "$SMARTFARM_RAG_TOKEN_FILE"
curl -fsS "$SMARTFARM_RAG_BASE_URL/health" || true
```

Live endpoint 접근이 안 되면 fallback 후보가 생성된다. 이 경우에도 UI/score/DAG 흐름 검증은 가능하다.

### 9.4 `Capture & Analyze Growth`가 실제 image Gemma로 가지 않음

현재 배포된 Gemma가 image-capable endpoint를 제공하지 않으면 fallback 분석이 정상 경로이다.
이때 sidecar JSON의 `analysisMode` 또는 trace에 fallback 표시가 남는다.

### 9.5 WebRTC cannot connect

확인 순서:

```bash
./scripts/smartfarm-twin-status.sh
ss -lntup | egrep '(:8011|:49100)' || true
ss -lunp | egrep '(:47998)' || true
```

- `SMARTFARM_PUBLIC_HOST`가 브라우저에서 접근 가능한 IP인지 확인한다.
- 방화벽/NAT가 `49100/tcp`, `47998/udp`를 막지 않는지 확인한다.
- WebRTC가 막힌 환경이면 로컬 GUI app으로 동일 데모를 검증한다.

---

## 10. 개발자용 검증 명령

문서/코드 변경 후 최소 검증:

```bash
python3 -m py_compile \
  source/extensions/joon.smartfarm.omniops/joon/smartfarm/omniops/extension.py \
  source/extensions/joon.smartfarm.twin/joon/smartfarm/twin/extension.py

PYTHONPATH=source/extensions/joon.smartfarm.omniops \
python3 -m unittest joon.smartfarm.omniops.tests.test_model

PYTHONPATH=source/extensions/joon.smartfarm.twin \
python3 -m unittest joon.smartfarm.twin.tests.test_rag_adapter

git diff --check
```

---

## 11. 데모 영상 녹화 체크포인트

제출자가 데모 영상을 만들 때 아래 장면을 순서대로 담으면, 검증자는 이 문서를 따라 같은 흐름을 재현할 수 있다.

1. 프로젝트 폴더와 실행 명령 표시
2. Omniverse app 실행 화면 표시
3. SmartFarm scene과 Growth camera view 표시
4. Baseline/current state 의미 설명
5. `Generate Gemma/RAG Blueprints` 클릭
6. Plan A/B/C 생성 결과 표시
7. score weight와 generation criteria 표시
8. `SmartFarm RAG Trace` 탭 표시
9. `SmartFarm Blueprint DAG` 탭에서 branch graph 표시
10. Recommended Plan 또는 특정 Plan 적용
11. 다시 Generate하여 branch chain이 이어지는 모습 표시
12. `Capture & Analyze Growth` 실행 및 capture 결과 표시
13. 로그/JSON 파일 위치 표시

