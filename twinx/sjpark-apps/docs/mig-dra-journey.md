# sv4000-1 A100 MIG GitOps 정착 — 시도·실패·해결 전 과정

> 대상 환경: TwinX K8s 1.33.3 · gpu-operator v25.3.4 · Kyverno v1.17.1 · ArgoCD v3.1.8
> 대상 노드: sv4000-1 (RTX A6000 x2 + A100-PCIE-40GB x1)
> 작성 시점 상태: **전부 원복 완료 — 노드 라벨 `all-disabled`, mig-dra/sjpark-infra 비활성화, RBAC 추가분 제거. 다음 진입 시 §7 "Round 2 진단" 의 결론을 출발점으로 사용.**

---

## 1. 배경 · 출발점

### 1.1 노드 구성
```
sv4000-1
  GPU 0 (PCI 01:00.0)  RTX A6000   — sjpark/gemma4-vllm 점유 (45 GiB)
  GPU 1 (PCI 02:00.0)  A100-40GB   — 학습·실험 대상 ★
  GPU 2 (PCI C1:00.0)  RTX A6000   — trident/ollama   점유 (idle)
```

### 1.2 학습 목표
1. **MIG** 적용 — A100을 슬라이스로 분할
2. **Profiling** 실습 — DCGM Profiler, nsys, ncu
3. **DRA** 도입 — 동적 자원 할당

### 1.3 사전 조건 (충족 후 진행)
ollama가 A100을 점유하던 상태 → ArgoCD `helm.parameters` 오버라이드로 ollama를 A6000(GPU 2)으로 이전 → A100 free. (별도 문서: `a100-mig-profiling-dra-plan.md`)

---

## 2. 시도 흐름 (시간순)

### 2.1 1차 시도 — Kyverno `mutate.existing`으로 노드 라벨 GitOps화

**의도**: 노드 라벨(`nvidia.com/mig.config`)도 git source-of-truth로. Kyverno background-controller가 노드를 reconcile하면서 라벨 patch.

**구성**: `argocd/multi-tenancy/apps/sjpark/apps/mig-dra/policy.yaml`
```yaml
kind: ClusterPolicy
spec:
  admission: true
  background: true
  rules:
    - name: sv4000-1-mig-balanced
      match: { any: [{ resources: { kinds: [Node], names: [sv4000-1] } }] }
      mutate:
        mutateExistingOnPolicyUpdate: true
        targets: [{ apiVersion: v1, kind: Node, name: sv4000-1 }]
        patchStrategicMerge:
          metadata:
            labels: { nvidia.com/mig.config: all-balanced }
```

**1차 막힘 — 권한 부족**

Kyverno admission webhook이 정책 생성 자체 거부:
```
auth check fails, additional privileges are required for the service account
'system:serviceaccount:kyverno:kyverno-background-controller':
requires permissions get,update for resource v1/Node
```

**해결**: ClusterRole aggregation으로 background-controller에 Node 권한 부여 — `rbac.yaml` 추가
```yaml
kind: ClusterRole
metadata:
  labels:
    rbac.kyverno.io/aggregate-to-background-controller: "true"
rules:
  - apiGroups: [""]
    resources: ["nodes"]
    verbs: ["get", "list", "watch", "update", "patch"]
```
→ admission webhook 통과, ClusterPolicy 생성됨

**2차 막힘 — `skipBackgroundRequests: true` 자동 박힘**

Kyverno가 정책 생성 시 default로 `skipBackgroundRequests: true` 주입. 이러면 background-controller가 우리 rule을 skip → mutate-existing 동작 안 함.

ArgoCD diff에서:
```
Live:    skipBackgroundRequests: true     ← Kyverno가 채움
Desired: (없음)
```

**해결**: policy.yaml에 명시적 `skipBackgroundRequests: false` 추가 → 우리 git 값으로 update됨

**3차 막힘 — UpdateRequest 0개**

`skipBackgroundRequests: false`까지 들어갔지만 `kubectl get updaterequests -A` → **No resources found**. background-controller가 mutate-existing을 한 번도 트리거하지 않음.

```
ClusterPolicy status: Ready=True (OK)
admissionpolicy-generator: policy created/updated (OK)
background-controller logs: 우리 정책 처리 흔적 0건  ← 결정적
UpdateRequest 큐:           비어 있음               ← 결정적
```

**원인 추정** (정확한 근본 원인은 Kyverno 1.17 변경 트래킹 필요):
- Kyverno 1.17.1에서 `ClusterPolicy` v1의 cluster-scope `mutate.targets`가 UpdateRequest를 생성하지 않는 회귀
- 1.17이 mutate-existing 일부 기능을 `policies.kyverno.io/MutatingPolicy v1beta1` 새 API로 이전 중인 과도기

→ Kyverno만으로는 막힘. 우회 필요.

### 2.2 2차 시도 — ArgoCD Sync Hook Job 우회

**의도**: ArgoCD sync 시점에 한 번 실행되는 Job으로 `kubectl label` 직접 호출. GitOps source-of-truth는 유지(Job 매니페스트가 git에 있음).

**구성**: 같은 `policy.yaml`에 5개 매니페스트 동거
```
ClusterPolicy        pin-mig-config              ← 미래 selfHeal용(현재는 동작 안 함)
ServiceAccount       mig-dra-node-labeler
ClusterRole          mig-dra-node-labeler        (nodes get/patch)
ClusterRoleBinding   mig-dra-node-labeler
Job                  pin-sv4000-1-mig-config     ← argocd hook=Sync
```

**1차 막힘 — 이미지 태그 부재**

`bitnami/kubectl:1.33` 태그가 Docker Hub에 없음 → Pod ImagePullBackOff 6분간 대기.

**해결**: `bitnami/kubectl:latest` + `imagePullPolicy: Always`로 교체. Job 재실행 시 성공 (duration 10s, completion 1/1).

**결과**: 노드 라벨 `nvidia.com/mig.config=all-balanced` 박힘 ✅

### 2.3 마지막 막힘 — mig-manager가 GPU reset 실패

라벨 박힌 직후 mig-manager가 작동 시작 → `state: pending` → **`state: failed`**

mig-manager 로그:
```
GPU 1 (0x20F110DE, A100):
  Asserting MIG mode: Enabled
  Current MIG mode: Disabled
  Mode change pending: true

Resetting all GPUs...
ERROR: GPU 00000000:02:00.0: In use by another client
  → exit status 255
```

A100이 어떤 client에 의해 잡혀 있어 reset 불가. 사전 검증에선 DCGM `gpu="1"`에 container/pod 라벨이 없었지만, **NVIDIA 드라이버 차원**에서는 device-plugin/dcgm-exporter/operator-validator 등이 모든 GPU에 fd를 hold할 수 있음. 또는 vllm/ollama 컨테이너가 NVIDIA_VISIBLE_DEVICES와 무관하게 nvidia-uvm 드라이버를 통해 A100에도 attach될 수 있음.

mig-manager는 reset 전에 `nvidia.com/gpu.deploy.*=paused-for-mig-change`로 device-plugin/gfd/dcgm을 일시 정지시켜야 하는데, 우리 클러스터에선 `nvsm`만 paused되고 나머지는 실패 후 빠르게 복구되어 충분한 정지 시간을 못 가졌을 가능성이 큼.

### 2.4 다음에 해야 할 일

**A. mig-manager 재시도 트리거 + 노드 GPU client 정리**

1. sv4000-1에서 모든 GPU 워크로드 일시 scale 0
   - `kubectl scale -n sjpark deploy gemma4-vllm --replicas=0`
   - `kubectl scale -n trident deploy ollama --replicas=0` (admin 필요)
2. 노드 라벨을 다른 값으로 토글 → 다시 `all-balanced`로 (mig-manager 재트리거)
   - `kubectl label node sv4000-1 nvidia.com/mig.config=all-disabled --overwrite`
   - 잠시 대기
   - `kubectl label node sv4000-1 nvidia.com/mig.config=all-balanced --overwrite`
3. `nvidia.com/mig.config.state: success` 떨어지는지 모니터
4. 성공 후 워크로드 복구 (vllm·ollama scale=1)

**B. 또는 노드 cordon + drain**

더 안전: `kubectl cordon sv4000-1` → drain → 라벨 토글 → uncordon. workload 자동 복구.

**C. 또는 Hook Job을 "노드 prep + label + verify"로 확장**

Job 내부에서:
1. sv4000-1의 GPU 점유 워크로드 일시 scale 0
2. mig.config 라벨 patch
3. mig.config.state=success 대기
4. 워크로드 scale 복구

→ 1회 GitOps sync로 모든 단계 자동화. 다만 권한 확장 필요 (deploy scale).

---

## 3. 원리 — 왜 이 설계가 이렇게 굴러가는가

### 3.1 GPU Operator의 두 계층 — 메뉴와 주문

```
1층 ─ 메뉴 (gpu-operator가 차려놓음)
   gpu-operator/default-mig-parted-config ConfigMap
   ├── all-disabled         (MIG off)
   ├── all-1g.5gb           (A100: 1g.5gb x 7)
   ├── all-balanced         (A100: 1g.5gb x2 + 2g.10gb x1 + 3g.20gb x1)
   ├── all-7g.40gb          (A100: 7g.40gb x 1)
   └── ... 수십 가지 프로파일

2층 ─ 주문 (노드 라벨)
   nvidia.com/mig.config: <메뉴 이름>
   → 노드별로 다른 라벨 → 노드별로 다른 프로파일
```

운영자가 만질 부분은 2층(라벨)만. 1층은 GPU operator가 클러스터 설치 시 자동 셋업.

### 3.2 mig-manager 작동 시퀀스

```
[1] Watch  : nvidia.com/mig.config 라벨 변화 감지
[2] Pause  : 노드 위 GPU client 컴포넌트를 일시 정지
             nvidia.com/gpu.deploy.device-plugin=paused-for-mig-change
             nvidia.com/gpu.deploy.gpu-feature-discovery=paused-...
             nvidia.com/gpu.deploy.dcgm-exporter=paused-...
             nvidia.com/gpu.deploy.nvsm=paused-...
[3] Reset  : nvidia-smi mig 명령으로 GPU MIG 모드 변경
             ← active client가 있으면 여기서 실패 (우리 케이스)
[4] Apply  : default-mig-parted-config에서 매칭되는 프로파일 찾아 슬라이스 생성
[5] Resume : 컴포넌트 라벨 다시 enable → device-plugin/gfd/dcgm 재시작
[6] Advertise: 새 device-plugin이 슬라이스를 nvidia.com/mig-* 리소스로 노출
```

`[3] Reset`이 우리가 막힌 지점. NVIDIA 드라이버는 MIG mode 전환 시 GPU에 active CUDA context가 있으면 거부. 그래서 [2] Pause 단계가 깨끗해야 [3]이 성공.

### 3.3 Kyverno mutate.existing — GitOps 노드 라벨 패턴 (이상적 동작)

```
[git push policy.yaml]
    ↓
[ArgoCD sync] ClusterPolicy CR 적용
    ↓
[Kyverno admission webhook] 권한 검증 → 통과 (ClusterRole aggregation 덕분)
    ↓
[Kyverno policy-controller] mutate-existing 정책 등록
    ↓
[Kyverno background-controller] UpdateRequest 생성 ★ ← 1.17.1에서 막힘
    ↓
[Kyverno background-controller worker] UR 처리, patch.targets로 Node 패치
    ↓
[Kubernetes] Node 리소스 라벨 변경
    ↓
[mig-manager] 라벨 watch, 위 시퀀스 시작
```

★ 부분이 회귀로 멈춰 ArgoCD Hook Job으로 우회.

### 3.4 ClusterRole aggregation — Kyverno 권한 확장 메커니즘

Kyverno는 정책마다 *그 정책이 실행해야 할 작업의 권한*을 자기 SA가 가졌는지 검증. mutate.targets로 Node를 만지는 정책이면 SA에 `nodes get/update`가 필요.

라벨 `rbac.kyverno.io/aggregate-to-background-controller: "true"` 가 붙은 ClusterRole은 **자동으로** background-controller의 기본 ClusterRole에 합쳐짐. 사용자가 Kyverno chart values를 건드릴 필요 없이 *추가* 권한만 별도 ClusterRole로 박으면 됨.

```
[Built-in ClusterRole]
  kyverno:background-controller (기본 권한)
       +
[Aggregated ClusterRole (우리 추가)]
  mig-dra:background-controller-nodes (nodes get/update/...)
       =
[Effective Permission]
  background-controller SA가 둘의 합집합 권한으로 동작
```

### 3.5 ArgoCD Sync Hook Job — GitOps 우회 패턴

```yaml
kind: Job
metadata:
  annotations:
    argocd.argoproj.io/hook: Sync                    # 매 sync 시 실행
    argocd.argoproj.io/hook-delete-policy: BeforeHookCreation
                                                     # 다음 sync 직전에 이전 Job 정리
spec:
  ttlSecondsAfterFinished: 600                       # 성공 후 10분 뒤 자동 삭제
```

이 패턴이 좋은 이유:
- **GitOps source-of-truth 유지**: Job 매니페스트가 git에 있음 → 누가·언제·왜를 git log로 추적
- **명령형 작업을 선언형 컨테이너에 캡슐화**: `kubectl label` 한 줄을 Pod로 wrapping
- **반복 가능**: ArgoCD가 sync마다 Job 새로 만듦 → 라벨이 떼였어도 다음 sync 때 다시 박힘 (Kyverno mutate-existing이 1.17에서 작동하면 selfHeal 항상 보장; 작동 안 해도 sync 주기로 복구)

한계:
- *실시간* selfHeal은 아님 (Kyverno와 달리 노드 라벨 watch가 없음 — ArgoCD polling 주기에 의존)
- Job pod의 SA에 노드 patch 권한 필요 → ClusterRole 별도 부여

### 3.6 우리가 짠 전체 그림 (현재 GitOps 구조)

```
argocd/multi-tenancy/apps/sjpark/
├── values.yaml                    # 자식 Application 등록
└── apps/
    ├── gemma4-vllm/              (기존 워크로드)
    ├── sjpark-infra/             (기존 인프라, enabled: false)
    └── mig-dra/                  (★ 신규)
        ├── policy.yaml           # ClusterPolicy + SA + ClusterRole + RoleBinding + Hook Job
        └── rbac.yaml             # Kyverno background-controller 권한 보강

[GitOps Sync 흐름]
git push
  ↓
ArgoCD sjpark-root sync (Helm chart로 자식 Application 렌더)
  ↓
mig-dra Application sync (디렉토리 통째로 적용)
  ├── ClusterPolicy 적용 (selfHeal용, 현재 정지)
  ├── SA/ClusterRole/RoleBinding 적용
  └── Job (Hook=Sync) 실행 → kubectl label
       ↓
   노드 라벨 변경
       ↓
   mig-manager 작동 → A100 reset → 슬라이스 생성
       ↓
   device-plugin이 nvidia.com/mig-* 리소스로 advertise
```

---

## 4. 학습 메모 — 다음에 같은 길 갈 사람을 위해

1. **`mig.config` 라벨 박기 자체와 mig-manager 작동은 분리된 두 단계**. 라벨이 박히는 것 = 절반. GPU reset 성공 = 나머지 절반.
2. **노드의 GPU client가 모두 깨끗하게 release되어야 reset 성공**. workload scale=0 또는 노드 drain이 가장 확실.
3. **Kyverno cluster-scope mutate-existing은 1.17.1에서 신뢰 어려움**. 같은 패턴 쓸 거면 LTS(1.13.x) 또는 더 최신 안정판 확인 필요.
4. **ArgoCD Hook Job 패턴은 "GitOps의 마지막 1마일"**. 선언형으로 안 풀리는 작업(노드 prep, 외부 시스템 호출, 일회성 마이그레이션)에 효과적.
5. **gpu-operator는 노드 단위로 동작**. 단일 GPU만 MIG로 바꾸는 게 아니라 노드 전체 GPU operator 컴포넌트가 한 번 흔들림. 운영 시간 계획 필요.
6. **`default-mig-parted-config` CM은 NVIDIA가 차려놓은 메뉴**. 거기 없는 조합이 필요하면 그 CM을 fork하거나 ClusterPolicy의 `migManager.config.name`을 다른 CM으로 가리키게 (gpu-operator values 수정 필요).

---

## 5. 참고 명령 모음

### 5.1 상태 점검
```bash
# 노드 MIG 라벨 + state
kubectl get node sv4000-1 -o json | jq '.metadata.labels | with_entries(select(.key|test("mig|gpu\\.deploy")))'

# 노드 capacity (MIG 슬라이스 노출 여부)
kubectl get node sv4000-1 -o json | jq '.status.capacity | with_entries(select(.key|test("nvidia.com/")))'

# DCGM 메트릭 (MIG 활성 시 GPU_I_ID/GPU_I_PROFILE 라벨 보임)
kubectl exec -n sjpark gemma4-vllm-c7f874877-qgt5w -c vllm -- \
  curl -s http://10.234.75.38:9400/metrics | grep -E 'GPU_I_ID|GPU_I_PROFILE'

# mig-manager 로그
kubectl logs -n gpu-operator -l app=nvidia-mig-manager --tail=200 -f
```

### 5.2 mig 작업 재시도
```bash
# 워크로드 일시 정지
kubectl scale -n sjpark deploy gemma4-vllm --replicas=0
kubectl scale -n trident deploy ollama --replicas=0   # admin 필요

# 라벨 토글로 mig-manager 재트리거
kubectl label node sv4000-1 nvidia.com/mig.config=all-disabled --overwrite
# 잠시 대기 (state=success 또는 5초)
kubectl label node sv4000-1 nvidia.com/mig.config=all-balanced --overwrite

# 모니터
watch 'kubectl get node sv4000-1 -o json | jq "{
  cfg:.metadata.labels[\"nvidia.com/mig.config\"],
  state:.metadata.labels[\"nvidia.com/mig.config.state\"]
}"'

# 성공 후 워크로드 복구
kubectl scale -n sjpark deploy gemma4-vllm --replicas=1
kubectl scale -n trident deploy ollama --replicas=1
```

### 5.3 롤백 (필요 시)
```bash
# MIG 해제 (단일 GPU 복원)
kubectl label node sv4000-1 nvidia.com/mig.config=all-disabled --overwrite

# Hook Job · RBAC · ClusterPolicy 통째로 제거하려면 values.yaml에서
# mig-dra application을 enabled: false로 → ArgoCD prune
```

---

## 6. 이어지는 작업

- **Profiling 단계 (Phase 2)**: MIG 슬라이스 위에 cuBLAS / transformer 워크로드 + DCGM Profiler·nsys·ncu
- **DRA 단계 (Phase 3)**: `nvidia-dra-driver-gpu` 도입 — MIG 슬라이스를 `ResourceClaim`으로 동적 할당
- **GitOps 정착 옵션**: Kyverno LTS 다운그레이드(1.13) 시 mutate-existing 재시도 → Hook Job 제거 가능

---

## 7. Round 2 — 권한 확장 + 워크로드 evict 시도와 진짜 원인 발견

### 7.1 시도한 것
이전 절(§2.4)이 제시한 "워크로드 evict 후 라벨 토글" 경로를 GitOps로 시도.

1. **sjpark-sa 권한 확장 (최소 범위)** — `sjpark-sa-setup.yaml`에 4개 매니페스트 추가
   - `Role`/`RoleBinding` (trident ns) — `deployments/scale` patch on `ollama` only (`resourceNames`로 한정)
   - `ClusterRole`/`ClusterRoleBinding` — `nodes` get/patch on `sv4000-1` only (`resourceNames`로 한정)
   - `sjpark-infra` Application을 `enabled: true`로 전환해 sync
2. **워크로드 일시 evict**
   - `kubectl scale -n sjpark deploy gemma4-vllm --replicas=0` ✓
   - `kubectl scale -n trident deploy ollama --replicas=0` → **ArgoCD selfHeal로 즉시 replicas=1 복구** ← 새 변수
   - 해결: ArgoCD UI에서 ollama Application의 auto-sync OFF → scale 0 유지
3. **라벨 토글** (`all-disabled` → `all-balanced`)
4. **mig-manager 재시도** → 또 `state: failed`

### 7.2 진짜 원인 — `nvidia-persistenced` 누락

mig-manager 로그의 새 단서:
```
"Shutting down all GPU clients in Kubernetes by disabling their component-specific nodeSelector labels"
"Shutting down all GPU clients on the host by stopping their systemd services"
...
ERROR: GPU 00000000:02:00.0: In use by another client
```

K8s 컴포넌트뿐 아니라 **호스트 systemd 서비스**도 stop 시도. 그래도 A100이 active client.

`default-gpu-clients` ConfigMap의 stop 목록 확인:
```
nvsm.service / nvsm-mqtt.service / nvsm-core.service /
nvsm-api-gateway.service / nvsm-notifier.service /
nv_peer_mem.service /
nvidia-dcgm.service / dcgm.service / dcgm-exporter.service

★ 누락: nvidia-persistenced.service  ← NVIDIA driver의 GPU 상태 영구 유지 데몬
```

`nvidia-persistenced`는 NVIDIA 드라이버 패키지가 깔리면 systemd로 자동 시작되어 모든 GPU에 NVRM client로 등록. mig-manager가 이 데몬을 stop하지 않으니 reset 명령이 driver level에서 거부.

→ **vllm/ollama가 원인이 아니라 호스트 데몬 한 개가 진짜 원인**. 비유: "회의실 지킴이가 안 나가서 인부가 구조 변경을 못 함".

### 7.3 GitOps 정착 옵션 (다음 진입 시 사용)

**방식 A — gpu-operator Helm values에 `migManager.gpuClientsConfig` 추가** + 별도 CM
1. `argocd/multi-tenancy/apps/sjpark/apps/mig-dra/gpu-clients.yaml` 신규 — `nvidia-persistenced.service` 포함한 ConfigMap `mig-gpu-clients`
2. `argocd/twinx-infra/apps/gpu-operator/values.yaml`의 `migManager`에 `gpuClientsConfig.name: mig-gpu-clients` 추가
3. ArgoCD sync → gpu-operator-controller가 ClusterPolicy 변경 감지 → mig-manager DaemonSet 재배포 (sv4000-1·sv4000-2·l40s 잠깐 영향)
4. 그 후 라벨 토글 한 번이면 reset 성공

**방식 B — 어드민 SSH 일회성** (학습 시연 용도, 비추천 운영)
```bash
sudo systemctl stop nvidia-persistenced
sudo nvidia-smi mig -i 1 -mig 1
sudo systemctl start nvidia-persistenced
```

### 7.4 원복 결정 — 학습 흐름을 위해 일단 깨끗한 상태로

GitOps 정착(방식 A)을 진행하려면 `argocd/twinx-infra/apps/gpu-operator/values.yaml` 수정 = **cluster 전반 영향** (sv4000-1·sv4000-2·l40s의 mig-manager 모두 재배포). 학습 단계에서 단발성으로 가져갈 부담이 크므로 **이번엔 모두 원복**하고, gpu-operator 변경은 별도 정식 PR로 시간 두고 진행하기로.

### 7.5 원복 작업 정리

| 항목 | 상태 |
|---|---|
| 노드 라벨 `nvidia.com/mig.config` | `all-balanced` → **`all-disabled`** (state: success) |
| `sjpark-infra` Application | `enabled: true` → **`false`** (RBAC 4개 자동 prune 예정) |
| `mig-dra` Application | `enabled: true` → **`false`** (ClusterPolicy / SA / Role / Hook Job 자동 prune 예정) |
| `sjpark-sa-setup.yaml` | MIG 권한 4개 매니페스트 **제거** → 원래 7 매니페스트로 복귀 |
| vllm deployment | 사용자가 evict → **scale 1 복구** |
| ollama deployment | ArgoCD UI에서 auto-sync OFF 상태 → **사용자가 ArgoCD UI에서 auto-sync ON 재활성화 필요** ★ |
| 문서 (`mig-dra-journey.md`) | **여기 §7 추가**하여 다음 진입 시 출발점 명시 |

### 7.6 다음 세션 진입 시 추천 출발점

1. **gpu-operator values 변경 PR**부터 (방식 A) — 다른 GPU 노드 영향 시간대 협의 후
2. PR merge → ArgoCD sync 완료 확인
3. mig-dra Application 재활성화 + 라벨 토글 한 번 → reset 성공해야 정상
4. capacity에서 `nvidia.com/mig-1g.5gb: 2`, `nvidia.com/mig-2g.10gb: 1`, `nvidia.com/mig-3g.20gb: 1` 노출 확인
5. DCGM 메트릭에서 `GPU_I_ID`/`GPU_I_PROFILE` 라벨 등장 확인
6. Phase 2 (Profiling)으로 진입

### 7.7 학습 가치 정리

이 라운드의 핵심 교훈:
- **NVIDIA driver level에서 GPU client는 K8s만이 아니다** — 호스트 systemd 데몬도 잡고 있음
- **mig-manager의 stop 목록 (`default-gpu-clients` CM)** 이 모든 NVIDIA 데몬을 커버하지 않음. 환경에 따라 커스텀 필요
- **ArgoCD `selfHeal: true`의 함정** — 명령형 일시 작업 (kubectl scale) 이 즉시 되돌아감. Application 자체의 auto-sync OFF 또는 git values 변경이 필요
- **`resourceNames`로 RBAC 좁히기**는 매우 효과적 — sjpark-sa가 cross-ns로 ollama scale 가능하지만 다른 trident 리소스는 못 봄
- **GitOps의 마지막 1마일은 종종 imperative** — 노드 라벨, GPU reset 같은 hardware-touching 작업은 결국 누군가가 명령을 실행해야 함. 그걸 Hook Job/Operator로 묶는 게 진짜 GitOps

### 7.8 관련 커밋 히스토리

```
8083572 fix(ollama): pin to RTX A6000 by overriding gpu.enabled=false        (이전 단계)
a756ee4 feat(argocd-trident): support helm.parameters override               (이전 단계)
5eb43d2 feat(mig-dra): pin sv4000-1 A100 MIG to all-balanced via Kyverno     (Round 1 시작)
1b9c9a4 fix(mig-dra): grant Kyverno background-controller node patch perms
fa8d93d fix(mig-dra): set skipBackgroundRequests=false for mutate-existing
639b00d feat(mig-dra): add Sync hook Job to enforce sv4000-1 mig.config label
c8a9d6f fix(mig-dra): use bitnami/kubectl:latest, not non-existent 1.33 tag
8ba17ca chore(mig-dra): tighten comment wording in rbac.yaml
7c27cba feat(sjpark-infra): grant scoped MIG ops perms and enable sync       (Round 2 정점)
<NEXT>  revert(mig-dra,sjpark-infra): rollback all MIG attempts              (이 원복 커밋)
```
