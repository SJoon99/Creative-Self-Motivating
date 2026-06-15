# TwinX sjpark GitOps Apps

이 디렉터리는 SmartFarm POC와 연결되는 TwinX `sjpark` 네임스페이스 GitOps 앱 묶음이다.

원본 운영 위치:

```txt
ssh netai-sys@10.38.36.32
~/TwinX-Ops/argocd/multi-tenancy/apps/sjpark
```

이 저장소에는 수업/공유용으로 필요한 앱 정의와 소스만 복사해 두었다. 실제 운영 Secret 값은 공개 저장소에 포함하지 않고 placeholder 또는 `secretKeyRef` 형태로만 남긴다.

## 포함된 앱

```txt
twinx/sjpark-apps/
  Chart.yaml / values.yaml / templates/applications.yaml
    sjpark app-of-apps Helm chart

  apps/gemma4-vllm/
    Gemma vLLM backend, auth proxy, cloudflared 관련 매니페스트

  apps/rag-strawberry/
    딸기 Blueprint 생성을 위한 RAG API 서버 Helm chart와 rag_server.py

  apps/omniverse-direct-viewer/
    브라우저 전체 화면에 Omniverse stream만 띄우는 direct viewer web app + Helm chart

  apps/smartfarm-twin/
    SmartFarm web/service/Postgres를 TwinX 내부망에 배포하는 Kubernetes manifest

  apps/mig-dra/
    A100 MIG/DRA 자원 정책과 RBAC

  apps/sjpark-infra/
    sjpark namespace용 device-plugin/config/service-account 보조 리소스

  docs/
    MIG, DRA, GPU observability 관련 운영 기록
```

## SmartFarm POC와의 연결

- Omniverse SmartFarm Kit 앱은 로컬/워크스테이션에서 Twin scene과 OmniOps UI를 실행한다.
- TwinX 내부망에는 Gemma vLLM, RAG API, SmartFarm service/web, direct viewer가 GitOps로 배포된다.
- `Generate Gemma/RAG Blueprints` 흐름은 현재 센서값, 딸기 상태, vision 상태를 RAG/Gemma 쪽 context로 전달하고, 결과를 Plan A/B/C 후보로 정규화한다.
- 후보 Plan은 Twin simulation과 quality gate를 거쳐 점수화되고 OmniOps Evidence Dashboard에 표시된다.

## 배포 메모

- `twinx/sjpark-apps/values.yaml`의 `argo.sourceRepo.url`과 `source.path`는 원본 TwinX-Ops GitOps layout을 보존한다.
- 이 공개 mirror를 직접 ArgoCD source로 쓰려면 repo URL과 path를 현재 저장소 layout에 맞게 바꿔야 한다.
- 운영 클러스터에 바로 적용하기 전에는 placeholder Secret, LoadBalancer IP, nodeSelector, image tag를 실제 환경 값으로 점검한다.

## 보안 메모

- 공개 저장소에는 실제 DB password, Hugging Face token, cloudflared token, API token을 넣지 않는다.
- `smartfarm-postgres-secret`은 공개 mirror에서 placeholder로 치환되어 있다.
- 실제 TwinX 운영 클러스터에서는 ArgoCD sync 전에 별도 Secret 또는 sealed/external secret 방식으로 값을 주입해야 한다.
