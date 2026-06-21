# Creative-Self-Motivating

Omniverse 기반 SmartFarm Digital Twin POC.
현재 딸기 스마트팜 상태를 Twin 환경에 Baseline으로 표현하고, Gemma/RAG가 제안한 조기 출하 Blueprint를 Twin 시뮬레이션으로 검증하는 프로젝트.

---

## 프로젝트 한 줄 요약

**센서값 + 딸기 생육 상태 + 가상 카메라 관측값을 기반으로 AI Blueprint를 만들고, 실제로 적용하기 전에 Digital Twin에서 먼저 검증하는 SmartFarm OmniOps 시스템.**

---

## 핵심 아이디어

- Baseline = 현재 스마트팜 상태
- Plan A/B/C = Gemma/RAG가 생성한 운영 Blueprint 후보
- Twin simulation = 후보 Blueprint의 현실성 검증 단계
- 목표 = 딸기를 가능한 빠르게 조기 출하하면서 수량, 비용, 병해 위험을 함께 관리
- AI와 현실의 간극을 줄이기 위해 현재 센서값과 딸기 상태를 계속 입력으로 사용

---

## 주요 기능

### 1. SmartFarm Digital Twin

- Omniverse Kit 기반 딸기 스마트팜 Twin scene
- LED, 관수, 팬, CO2, 습도, DLI, 생육 상태를 Twin 내부 상태로 표현
- Baseline은 항상 현재 상태를 나타내는 고정 기준
- Plan 적용 시 작물 상태, actuator visual, KPI가 함께 변화

### 2. Gemma/RAG Blueprint 생성

- `Generate Gemma/RAG Blueprints` 버튼으로 Blueprint 후보 생성
- 현재 sensor state, crop state, vision assessment를 RAG 요청 context로 전달
- Gemma/RAG 응답을 Plan A/B/C 후보로 정규화
- Plan A/B/C는 고정 전략명이 아니라 중립적인 display slot

### 3. Twin 기반 후보 검증

- 각 Blueprint를 rolling-horizon simulation으로 평가
- 평가 기준:
  - 예상 수확 가능일
  - 예상 수량 점수
  - 운영 비용 변화
  - 병해 위험
  - harvest horizon 내 수확 가능 여부
- Plan score는 Gemma confidence가 아니라 Twin validation score

### 4. Twin Quality Gate

- Gemma 후보가 너무 위험하거나 0점에 가까우면 즉시 폐기하지 않음
- 원본 후보는 JSON trace에 보존
- airflow, light, CO2 중심으로 1회만 안전 보정
- 보정 후보를 다시 Twin simulation에 넣어 재평가
- 시연 중 “한 후보만 0점”처럼 보이는 문제를 줄이고, 동시에 조작이 아닌 검증 기반 보정임을 보여줌

### 5. OmniOps Dashboard

- Omniverse 오른쪽 Dock: 운영자가 누르는 control 중심
- 하단 Evidence Dashboard:
  - 추천 Plan
  - 적용 Plan
  - Gemma/RAG 호출 상태
  - Plan A/B/C 설명과 점수
  - RAG trace
  - live strawberry camera view
- 수업/시연 중 API 호출과 평가 근거를 보여주기 위한 trace panel 포함

### 6. Growth Camera / Vision POC

- Omniverse 내부 GrowthPhenotypeCamera 사용
- `Capture & Analyze Growth` 버튼으로 현재 딸기 view capture
- Gemma vision endpoint가 가능하면 image 분석 요청
- 현재 POC에서는 image-capable Gemma 배포가 아닐 경우 deterministic fallback 사용
- fallback 여부와 분석 결과는 sidecar JSON과 UI trace에 표시

### 7. Omniverse Direct Viewer

- 브라우저 전체 화면에 Omniverse stream만 표시하는 경량 web viewer
- 별도 portal UI 없이 Connect Stream 역할만 수행
- TwinX 내부망에서 LoadBalancer 형태로 배포할 수 있도록 Helm chart 포함

---

## 주요 디렉터리

```txt
source/apps/
  joon.smartfarm_*.kit
  SmartFarm / OmniOps Kit app entrypoint

source/extensions/joon.smartfarm.twin/
  SmartFarm Twin scene, actuator/crop simulation, Gemma/RAG adapter

source/extensions/joon.smartfarm.omniops/
  Omniverse OmniOps dashboard UI, evidence panel, RAG trace UI

source/OwnType/
  프로젝트에서 사용하는 딸기/팬 관련 경량 asset

web/smartfarm-web/
  기존 SmartFarm web dashboard source

web/omniverse-direct-viewer/
  Omniverse stream 전용 direct viewer web source + Helm chart

services/smartfarm-service/
  SmartFarm service API POC

scripts/
  SmartFarm Twin / OmniOps 실행, 상태 확인, smoke test script

docs/Progess/
  개발 진행 기록과 설계 의사결정 로그

Agent.md
  처음 보는 사람도 전체 구조와 로직을 이해할 수 있는 상세 handoff 문서

docs/05-final-submission-demo-reproduction.md
  최종 제출 ZIP/데모 영상 검증자가 그대로 따라 할 수 있는 재현 가이드
```

---

## Blueprint 점수의 의미

Plan row의 `score /100`은 AI가 “자신 있다”고 말한 확률이 아님.
현재 Twin이 해당 plan을 실제로 적용했을 때의 결과를 단순화해 계산한 검증 점수.

주요 구성:

- 빠른 출하 가능성
- 수확 가능일이 Baseline보다 얼마나 앞서는지
- 예상 수량
- 병해 위험
- 운영 비용 증가
- 수확 조건을 horizon 안에 만족하는지

따라서 0점은 UI 오류가 아니라, Twin 기준에서 위험하거나 수확 조건을 만족하지 못했다는 의미.

---

## 현재 상태

동작하는 부분:

- SmartFarm Twin scene 구성
- Baseline / Plan A/B/C 적용 흐름
- Gemma/RAG Blueprint 요청 adapter
- RAG trace 저장 및 dashboard 표시
- Plan A/B/C 중립 slot rotation
- Twin Quality Gate
- Growth Camera capture + analysis flow
- Direct Viewer web source 및 Helm chart

POC 제한:

- 실제 농장 IP camera ingestion은 아직 범위 밖
- 실제 환경과 Twin 예측값의 장기 assimilation은 아직 범위 밖
- image-capable Gemma 배포가 아닐 경우 vision은 fallback 분석 사용
- 재현 편의를 위해 일부 대형 USD/asset이 repository에 포함되어 있어 제출 ZIP 크기가 커질 수 있음


