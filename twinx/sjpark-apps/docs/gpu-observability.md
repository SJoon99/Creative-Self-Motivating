# GPU Observability / Profiling — sjpark

## 현황

- 클러스터 GPU 스택: NVIDIA GPU Operator (helm chart `gpu-operator-v25.3.4`)
- ClusterPolicy `cluster-policy`가 데몬셋들 관리 (별도 설치 X)
  - `nvidia-dcgm-exporter` (메트릭)
  - `nvidia-device-plugin-daemonset`
  - `nvidia-container-toolkit-daemonset`
  - `nvidia-mig-manager`
- 모니터링: `monitoring` 네임스페이스에 Prometheus + Grafana 기존 운영 중
- 대상 워크로드: `sjpark/gemma4-vllm` (sv4000-1, A100, vllm-openai)
- `sjpark-sa` 권한: pod create 가능, 추가 권한 이슈 적음
- 노드 드라이버: 535.288.01 / CUDA runtime 12.2

## 1. 전용 Grafana — 권장 O

- Prometheus는 공용 그대로 재사용 (중복 scrape 비용 큼)
- Grafana만 sjpark에 별도 배포 → datasource = `monitoring/prometheus`
- PromQL `namespace="sjpark"` 필터로 격리
- 전용 Prometheus는 1s 해상도/별도 retention 필요 시점에만 추가

## 2. 진도 로드맵

### Phase 1 — 메트릭 (반나절)

- [ ] vLLM `/metrics` ServiceMonitor (`argocd/sjpark/apps/gemma4-vllm/servicemonitor.yaml`)
- [ ] sjpark Grafana (helm `grafana/grafana`)
- [ ] datasource: 기존 Prometheus
- [ ] 통합 대시보드 1개
  - DCGM: SM util, mem util, power, temp, ECC
  - vLLM: TTFT, ITL, throughput, KV cache hit, queue depth
- ✅ 산출물: "지금 GPU 얼마나 바쁜가" 답 가능

### Phase 2 — 앱 프로파일 (1일)

- [ ] `VLLM_TORCH_PROFILER_DIR=/data/profiler` env 추가
- [ ] PVC `gemma4-vllm-cache` 안에 dump (별도 PVC도 가능)
- [ ] 부하 중 `POST /start_profile` → `POST /stop_profile`
- [ ] trace → TensorBoard / Perfetto
- ✅ 산출물: kernel/operator 단위 병목 식별

### Phase 3 — 시스템 프로파일 (1~2일, 권한 의존)

- [ ] `nsys profile` — 디버그 이미지 or 사이드카
- [ ] `ncu` — 노드 `NVreg_RestrictProfilingToAdminUsers=0` 선결
  - GPU Operator clusterpolicy 통해 토글 가능 여부 확인 필요
- ✅ 산출물: occupancy / memory stall / warp 분석

### Phase 4 — 트레이싱 (선택)

- [ ] vLLM OpenTelemetry export
- [ ] Tempo (sjpark) 수신
- ✅ 산출물: 요청 ID 단위 토큰 생성 trace

### Phase 5 — 연속 프로파일링 (선택)

- Pyroscope/Parca + CUDA: 미성숙
- 단발성 nsys로 충분한 경우 많음 — 보류

## 권장 시작점

Phase 1 → 2 까지가 "deep GPU observability 테스트" 정의에 충분
Phase 3은 마이크로 최적화 필요 시점에 추가

## 권한/리스크 메모

- DCGM exporter 메트릭 소비: 권한 이슈 없음
- vLLM torch profiler: 컨테이너 내부, 권한 이슈 없음
- nsys: 보통 OK (CAP_SYS_ADMIN 가끔 필요)
- ncu: 노드 드라이버 설정 필요 → sjpark 단독 변경 불가
- ServiceMonitor: Prometheus가 cross-namespace selector 허용 가정 (`monitoring` 쪽 설정 확인 필요)
