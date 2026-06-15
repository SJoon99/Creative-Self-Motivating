# A100 MIG / Profiling / DRA 학습·검증 계획

> sv4000-1의 A100-PCIE-40GB를 활용해 MIG, GPU profiling, 그리고 Dynamic
> Resource Allocation(DRA)을 단계적으로 검증하는 계획. 본 문서는 **실행 전 참고용
> 청사진**이며, 각 phase는 별도 PR/커밋으로 진행한다.

## 0. 사전 상태 (2026-05-15 기준)

- 노드: `sv4000-1` (a100-gpu-node 라벨)
- GPU 인벤토리 (DCGM 검증 완료)
  - GPU 0 (01:00.0) RTX A6000 — `sjpark/gemma4-vllm` 점유
  - GPU 1 (02:00.0) A100-PCIE-40GB — **idle / free** ★ MIG 대상
  - GPU 2 (C1:00.0) RTX A6000 — `trident/ollama` 점유 (NVIDIA_VISIBLE_DEVICES 핀)
- gpu-operator: `v25.3.4`, k8s-device-plugin: `v0.17.4`
- 노드 MIG 라벨: `nvidia.com/mig.capable=true`, `nvidia.com/mig.config=all-disabled`,
  `nvidia.com/mig.strategy=mixed`
- nvidia-mig-manager DaemonSet은 sv4000-1에서 Running

## 1. Phase 1 — MIG 적용 (`all-1g.5gb`, 7 slices)

### 1.1 목표
A100 한 장을 7개의 1g.5gb 슬라이스로 분할해 추후 profiling 학습 시 다중 워크로드
격리 효과를 관찰할 수 있도록 한다.

### 1.2 사전 조건
- A100(GPU 1)은 어떤 Pod도 점유하지 않아야 함 (현재 충족)
- `gpu-operator/default-mig-parted-config` ConfigMap에 `all-1g.5gb` 프로파일
  정의가 있어야 함 (적용 직전 재확인)

### 1.3 검증 명령 (실행 전 확인)
```bash
kubectl get cm -n gpu-operator default-mig-parted-config -o yaml | \
  grep -E "^\s*all-1g\.5gb:" -A 5

kubectl exec -n sjpark gemma4-vllm-c7f874877-qgt5w -c vllm -- \
  curl -s --max-time 5 http://10.234.75.38:9400/metrics | \
  grep -E '^DCGM_FI_DEV_FB_USED\{gpu="1"'   # ollama·다른 점유자 없는지 재확인
```

### 1.4 적용
```bash
kubectl label node sv4000-1 nvidia.com/mig.config=all-1g.5gb --overwrite

# 진행 상태 모니터
watch 'kubectl get node sv4000-1 -o json | jq "{state: .metadata.labels[\"nvidia.com/mig.config.state\"], cfg: .metadata.labels[\"nvidia.com/mig.config\"]}"'
# 기대: state=pending → success
```

### 1.5 사후 검증
```bash
# (a) 노드 capacity가 MIG 리소스로 분리 advertise됐는지
kubectl get node sv4000-1 -o json | \
  jq '.status.capacity | with_entries(select(.key|test("nvidia.com/")))'
# 기대: nvidia.com/gpu: "2"           (A6000 두 장)
#       nvidia.com/mig-1g.5gb: "7"    (A100 7 슬라이스)

# (b) DCGM에서 MIG instance 메트릭 노출
kubectl exec -n sjpark gemma4-vllm-c7f874877-qgt5w -c vllm -- \
  curl -s http://10.234.75.38:9400/metrics | \
  grep -E 'GPU_I_ID|GPU_I_PROFILE' | head -20
# 기대: GPU_I_ID 라벨이 1~7로 노출

# (c) nvidia-smi mig 출력 (mig-manager Pod 로그로 확인 가능)
kubectl logs -n gpu-operator -l app=nvidia-mig-manager --tail=80
```

### 1.6 롤백
```bash
kubectl label node sv4000-1 nvidia.com/mig.config=all-disabled --overwrite
```
GPU reset이 1회 필요. A100 슬라이스를 쓰던 Pod는 evict 됨.

### 1.7 위험·주의
- A100 reset 진행 중 `nvidia.com/mig.config.state=pending` → `success` 전환
  실패 시 `failed`로 떨어질 수 있음. 그 때는 mig-manager 로그 + nvsm 상태 점검.
- MIG 활성 후 `nvidia.com/gpu` 풀에서 A100이 빠지므로, 직접 `nvidia.com/gpu:1`을
  요청해 A100을 쓰던 매니페스트가 있다면 깨짐 (현재 없음 — ollama는 helm
  parameter override로 회계 밖).

## 2. Phase 2 — Profiling 실습

### 2.1 목표
MIG 슬라이스 위에 작은 워크로드를 올려 다음 도구의 사용 흐름을 익힌다.
- **DCGM Profiler** (클러스터 기존 메트릭) — 시계열·격리 효과
- **`nvidia-smi mig`** / **`dcgmi`** — 슬라이스 인스턴스 조회
- **Nsight Systems (`nsys`)** — 커널 타임라인·CUDA API 트레이스
- **Nsight Compute (`ncu`)** — 커널 단위 마이크로프로파일링 (1g.5gb에서 일부
  메트릭 제한)

### 2.2 워크로드 후보
- A. **cuBLAS GEMM 마이크로벤치** (`nvidia/cuda` 이미지 + 간단한 행렬곱 코드)
  → SM activity, tensor core 사용률, DRAM throughput 관찰
- B. **작은 transformer 추론** (DistilBERT 또는 7B 양자화 모델 일부 — 1g.5gb는
  메모리 5GB라 양자화 필수) → 토큰 latency·메모리 패턴 관찰
- C. **동시 multi-tenant 실험** — 같은 A100의 두 슬라이스에 서로 다른 워크로드
  띄워 격리 효과 측정

### 2.3 메트릭 확인 경로
- Grafana (이미 운영 중): `10.38.38.204` — DCGM 대시보드에 MIG instance
  드릴다운 추가 (기존 `gpu-observability.md` 참조)
- Prometheus 쿼리 예:
  ```promql
  DCGM_FI_PROF_SM_ACTIVE{Hostname="sv4000-1",GPU_I_ID=~".+"}
  DCGM_FI_PROF_DRAM_ACTIVE{Hostname="sv4000-1",GPU_I_ID=~".+"}
  DCGM_FI_DEV_FB_USED{Hostname="sv4000-1",GPU_I_ID=~".+"}
  ```
- Pod 안 `nsys profile` → 결과 `.qdrep` 아티팩트를 PVC로 export

### 2.4 결정해야 할 것 (Phase 2 진입 시)
- Pod 안에서 `nsys`/`ncu` 실행 권한 (privileged 또는 NVIDIA capabilities)
- 결과 아티팩트 저장 경로 (rook-ceph PVC 또는 trident object store)
- 동시 실험 시 슬라이스 간 격리 효과 정량화 기준 (latency p99, throughput)

## 3. Phase 3 — DRA (Dynamic Resource Allocation)

### 3.1 배경
Kubernetes의 차세대 GPU 할당 메커니즘. `device-plugin`의 한계(단일 resource
name, 정적 할당)를 해결.
- k8s `1.26`: alpha → `1.27`: beta → `1.32`: stable (v1 API)
- 클러스터: `1.33.3` → DRA 사용 가능
- NVIDIA 구현: `NVIDIA/k8s-dra-driver-gpu` (별도 Helm 차트)

### 3.2 가치
- MIG 슬라이스를 `ResourceClaim` 형태로 동적 할당 (Pod가 spec 시점에 어떤
  슬라이스를 어떤 옵션으로 받을지 더 풍부하게 표현)
- 같은 노드에서 GPU 모델별 분리 advertise (현재 device-plugin이 미지원하던
  영역)
- `ResourceClaimTemplate` + `DeviceClass`로 워크로드별 GPU 정책 분리

### 3.3 도입 전 체크리스트
- [ ] `nvidia-dra-driver-gpu` Helm 차트 버전 ↔ gpu-operator `v25.3.4` 호환성
- [ ] kubelet/kube-apiserver feature gate `DynamicResourceAllocation` 활성 여부
      (1.33은 기본 활성)
- [ ] device-plugin과 공존 운영 (DRA 도입 = device-plugin 완전 대체 아님)
- [ ] CRD: `ResourceClaim`, `ResourceClaimTemplate`, `DeviceClass`,
      `ResourceSlice`
- [ ] 영향 범위: 현재 GPU 사용 Pod 전부 — 단계적 마이그레이션 필요

### 3.4 1차 검증 시나리오 (단일 Pod)
1. `nvidia-dra-driver-gpu` Helm 설치 (별도 네임스페이스, 기존 gpu-operator
   유지)
2. `DeviceClass` 정의: A100 MIG 1g.5gb 슬라이스
3. `ResourceClaimTemplate` 정의 → 테스트 Pod에 `resourceClaims` 명시
4. Pod 생성 → DRA driver가 슬라이스 할당 → 컨테이너 안에서 인식 확인
5. 동시 Pod 여러 개로 자동 슬라이스 분배 검증

### 3.5 위험
- 클러스터 차원 변경, 운영 워크로드(현재 vllm/ollama)에 잠재 영향
- DRA driver와 device-plugin 동시 운영 시 GPU "이중 advertise" 가능성 →
  사전에 분리 정책 설계 필수
- DRA 도입은 **Phase 1·2 안정화 이후**로 미루고, 별도 long-running PoC로
  진행 권장

## 4. 일정 / 순서 권장

| 단계 | 작업 | 영향 범위 | 롤백 비용 |
|---|---|---|---|
| Phase 1 | A100 MIG `all-1g.5gb` 적용 | sv4000-1 GPU 1만 | 라벨 1줄, GPU reset |
| Phase 2 | Profiling 실습 (DCGM/nsys/ncu) | 새 워크로드만 추가 | Pod 삭제 |
| Phase 3 | DRA driver 도입 PoC | 클러스터 전반 | Helm uninstall + 검증 |

각 phase 사이에 일주일 이상의 안정화 관찰을 두는 것을 권장.

## 5. 참고 자료

- NVIDIA GPU Operator MIG 가이드:
  https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/gpu-operator-mig.html
- NVIDIA Nsight Systems / Compute MIG 제약:
  https://docs.nvidia.com/nsight-systems/UserGuide/index.html
- NVIDIA k8s-dra-driver-gpu:
  https://github.com/NVIDIA/k8s-dra-driver-gpu
- Kubernetes DRA 공식 문서:
  https://kubernetes.io/docs/concepts/scheduling-eviction/dynamic-resource-allocation/
- 본 저장소 내 관련 문서: `argocd/multi-tenancy/apps/sjpark/docs/gpu-observability.md`
