# 2026-06-02 Growth Status KPI / Baseline Twin V2

## 적용 목적

시연 피드백의 핵심은 “딸기가 지금 얼마나 잘 자라고 있는지”를 설명할 수 있는 논리였다. 단순히 가상 센서값을 보여주는 것만으로는 부족하므로, 이번 V2는 센서값을 그대로 표시하는 대신 다음 단계를 추가했다.

1. synthetic sensor state
2. deterministic crop-state model
3. operator-facing Growth KPI
4. Omniverse scene metadata / visual morphology
5. Web Growth Status Card

즉, 현재 POC에서는 실제 카메라/저울/생육 측정값이 없기 때문에 `model-estimated` 상태로 명시한다. 다만 센서값, 작물 생육 상태, 질병 압력, 예측 출하일을 하나의 설명 가능한 KPI로 묶어 “현재 트윈이 어떤 근거로 잘/못 자라고 있다고 판단하는지”를 보여준다.

## Growth KPI 정의

Kit twin API `/smartfarm/state`에 `growthKpi`를 추가했다.

```json
{
  "healthScore": 58,
  "stage": "flowering_delayed_fruit_set",
  "fruitMaturityPercent": 44,
  "harvestReadinessPercent": 43,
  "expectedShip": "2027-01-06",
  "diseaseRisk": "high",
  "mainLimitingFactor": "Low DLI limits photosynthesis and fruit maturity",
  "confidence": "model-estimated",
  "basis": "synthetic sensor history + deterministic crop-state model",
  "evidence": ["DLI ...", "Moisture ...", "RH ...", "Fruit set ..."]
}
```

### Health Score 산정 논리

`healthScore`는 단일 센서의 복사값이 아니다.

- 환경 적합도: DLI, 배지 수분, 습도, 온도, CO2가 딸기 재배 recipe band에 얼마나 가까운지 평가한다.
- 작물 상태: vegetative growth, flowering, fruit set, fruit maturity, disease pressure를 반영한다.
- 최종 점수: 환경 적합도와 crop-state를 가중 결합한다.

따라서 “가상 센서값 기반”이라는 한계는 있지만, Web UI가 표시하는 성장 상태는 단순 수치 나열이 아니라 작물 모델의 결과다.

## 초기 Baseline 표시 변경

기존 문제: 웹 최초 연결 또는 Plan 적용 전 Omniverse가 이미 다 자란 듯한 mature 상태로 보였다.

변경 내용:

- 최초 `/scene/growth` 생성 시 timeline을 day 0이 아니라 `BASELINE_VIRTUAL_SENSOR_STATE.twin_day`로 이동한다.
- 현재 baseline은 day 34, flowering/delayed fruit set 상태다.
- Plan 적용 전 화면은 “현재 센서 기반 스마트팜 상태”를 나타내며, 완전 성숙/수확 직전 상태로 보이지 않도록 fruit visual을 crop maturity 기반으로 조정했다.
- Baseline apply/reset도 mature static scene이 아니라 current-day growth scene으로 되돌린다.

## Web UI 변경

- 우측 패널 상단에 `Growth status` card 추가
  - Growth Health Score
  - Fruit maturity
  - Harvest readiness
  - Expected ship
  - Disease risk
  - Fruit set
  - Yield estimate
  - Main limiting factor
  - Evidence list
- kiosk/fullscreen stream overlay에도 간단한 성장 KPI를 노출한다.

## 현재 한계와 향후 포팅 포인트

현재 POC의 `confidence`는 `model-estimated`다. 실제 서비스 버전에서는 다음 입력을 붙이면 된다.

- 카메라 기반 생육 인식: 꽃/과실/색상/크기/병반 detection
- 실측 센서 history: 온습도, CO2, DLI, 배지 수분
- 수확/출하 실적: yield, 품질, 출하일
- Gemma RAG pipeline: 후보 Blueprint 생성 및 설명

그 후 `basis`를 `sensor-observed + vision-assimilated + planner-forecast` 같은 형태로 올리면 된다.

## 마이그레이션 반영 범위

- Spark node `100.73.161.118` Kit extension 반영
- TwinX K8S web image 업데이트
- TwinX GitOps manifest image tag 업데이트
