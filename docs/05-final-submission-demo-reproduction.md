# 최종 데모 재현 가이드

이 문서는 제출 영상 기준으로 제3자가 같은 Omniverse/Kit 환경에서 SmartFarm OmniOps 데모를 따라 하기 위한 최소 절차만 정리한다.

- 프로젝트 ZIP: `2026-C&S Project_Final_project_Team-Code.zip`
- 데모 영상: `2026-C&S Project_Final_demo_Team-Code.mp4`
- 기준 Kit/App: Kit `110.1.1`, SmartFarm app `0.1.0`

---

## 1. 준비

```bash
unzip 2026-C\&S\ Project_Final_project_Team-Code.zip -d smartfarm-final
cd smartfarm-final
```

build 결과가 포함되어 있으면 바로 실행한다.

```bash
./scripts/smartfarm-omniops-dev.sh
```

build 결과가 없으면 같은 Kit SDK 환경에서 먼저 build한다.

```bash
./repo.sh build
./scripts/smartfarm-omniops-dev.sh
```

정상 상태 확인:

```bash
./scripts/smartfarm-twin-status.sh
curl -fsS http://127.0.0.1:8011/smartfarm/state | python3 -m json.tool | head -80
```

---

## 2. 데모에서 확인할 화면

Omniverse가 열리면 다음을 확인한다.

1. 상단 Viewport에 딸기 스마트팜 Twin scene 표시
2. 우측 `SmartFarm OmniOps Dock` 표시
3. 하단 `SmartFarm Evidence` 표시
4. 하단 `SmartFarm RAG Trace` 표시
5. 하단 `SmartFarm Blueprint DAG` 표시
6. 하단 `SmartFarm Strawberry Live View` 표시

Baseline은 현재 스마트팜 상태를 Twin에 보여주는 고정 기준이다. Plan A/B/C는 Baseline이 아니라 Generate 버튼을 누를 때마다 생성되는 Blueprint 후보이다.

---

## 3. 핵심 시연 순서

### 3.1 현재 상태 확인

우측 Dock에서 LED, 관수, 팬, CO2, water valve, Growth Camera 상태를 확인한다.
필요하면 아래 버튼을 누른다.

```text
Refresh State
Create Current Twin
```

### 3.2 Blueprint 생성

우측 Dock에서 다음 버튼을 누른다.

```text
Generate Gemma/RAG Blueprints
```

정상 결과:

- Plan A/B/C 3개 후보가 생성된다.
- Recommended Plan이 표시된다.
- 각 Plan에 score, 예상 출하일, actuator 조합, 설명, risk가 표시된다.
- `SmartFarm RAG Trace`에 Gemma/RAG 호출 또는 fallback trace가 표시된다.
- `SmartFarm Blueprint DAG`에 Generate → Plan A/B/C → Twin Validation → Recommended 흐름이 표시된다.

로그 확인:

```bash
find logs/smartfarm-blueprints -maxdepth 3 -type f | sort | tail -20
```

### 3.3 Plan 적용

우측 Dock에서 아래 중 하나를 누른다.

```text
Plan A
Plan B
Plan C
Apply Recommended
```

정상 결과:

- Applied Plan이 갱신된다.
- Twin 상태와 Evidence Dashboard가 선택한 Plan 기준으로 바뀐다.
- DAG 하단 selection chain에 선택 기록이 추가된다.

### 3.4 다시 Generate해서 branch 흐름 확인

Plan 적용 후 다시 누른다.

```text
Generate Gemma/RAG Blueprints
```

확인할 것:

- 새 Plan A/B/C가 현재 Twin state 기준으로 다시 생성된다.
- DAG 하단에 이전 Generate에서 선택한 Plan과 다음 Generate가 이어져 보인다.
- 이 흐름이 “후보 선택 → 결과 확인 → 다시 계획 생성” 구조를 보여준다.

### 3.5 딸기 상태 캡처/분석

우측 Dock에서 누른다.

```text
Capture & Analyze Growth
```

정상 결과:

- Growth Camera 이미지가 저장된다.
- 생육 progress, health, risk가 UI에 표시된다.
- image-capable Gemma endpoint가 없으면 deterministic fallback 분석이 사용된다.

결과 확인:

```bash
find logs/smartfarm-vision -maxdepth 1 -type f | sort | tail -20
```

---

## 4. 점수 의미

Plan score는 Gemma confidence가 아니라 Twin validation score이다.

주요 기준:

- 조기 출하 가능성
- 예상 수확 readiness/yield
- 병해 위험
- 운영 비용 증가
- actuator 조합 안전성

기본 가중치:

| 항목 | 가중치 |
|---|---:|
| earliestShipment | 0.36 |
| yield | 0.24 |
| diseaseControl | 0.22 |
| opex | 0.10 |
| actuatorSafety | 0.08 |

0점에 가까운 Plan은 UI 오류가 아니라 현재 Twin 조건에서 위험하거나 수확 조건을 만족하지 못한 후보라는 의미이다.

---

## 5. Live Gemma/RAG 연결이 필요한 경우

내부망의 실제 RAG/Gemma endpoint를 사용할 때만 환경 변수를 지정한다.

```bash
export SMARTFARM_RAG_BASE_URL="http://<RAG_OR_GEMMA_ENDPOINT>"
export SMARTFARM_RAG_TOKEN_FILE="$HOME/.smartfarm-rag-token"   # 필요할 때만
export SMARTFARM_RAG_TIMEOUT=30
./scripts/smartfarm-omniops-dev.sh
```

연결이 안 되어도 fallback으로 Plan 생성, Twin validation, DAG, capture flow는 재현 가능하다.

---

## 6. WebRTC로 보는 경우

브라우저에서 Omniverse stream을 확인해야 하면 streaming app을 실행한다.

```bash
export SMARTFARM_PUBLIC_HOST="<브라우저에서 접근 가능한 IP>"
./scripts/smartfarm-omniops-streaming.sh
```

기본 포트:

| 용도 | 포트 |
|---|---:|
| SmartFarm API | 8011 |
| WebRTC signaling | 49100 |
| WebRTC media UDP | 47998 |

문제가 있으면:

```bash
./scripts/smartfarm-twin-status.sh
ss -lntup | egrep '(:8011|:49100)' || true
ss -lunp | egrep '(:47998)' || true
```

---

## 7. 제출 ZIP 생성

tracked source 기준으로 제출 ZIP을 만들 때:

```bash
git archive --format=zip --output "2026-C&S Project_Final_project_Team-Code.zip" HEAD
```

실행 중 생성된 로그와 스크린샷을 제외하려면:

```bash
git ls-files | grep -v '^logs/' | grep -v '^figure/' > /tmp/smartfarm-submit-files.txt
git archive --format=zip --output "2026-C&S Project_Final_project_Team-Code.zip" HEAD -- $(cat /tmp/smartfarm-submit-files.txt)
```

---

## 8. 데모 성공 체크리스트

- [ ] SmartFarm OmniOps Composer 실행
- [ ] 딸기 스마트팜 Twin scene 표시
- [ ] `Generate Gemma/RAG Blueprints` 클릭 시 Plan A/B/C 생성
- [ ] Evidence Dashboard에 Plan 설명과 score 표시
- [ ] RAG Trace에 호출/근거/fallback 상태 표시
- [ ] Blueprint DAG에 branch graph 표시
- [ ] Plan 적용 후 Applied Plan 갱신
- [ ] 다시 Generate했을 때 선택 흐름이 이어짐
- [ ] `Capture & Analyze Growth` 결과가 생성됨
