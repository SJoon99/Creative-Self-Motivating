# Smart Farm Web Portal (`smartfarm-web`)

Operational web portal for the **Smart Farm Early-Shipment Reference Twin**.

This is a **prototype shell**: Vite + React + TypeScript, typed data models, and
mock blueprint data. It renders one dense operational screen — not a landing
page — with a large Omniverse viewer panel plus blueprint candidates, virtual
sensors, actuators, and scenario results.

> Frontend implementation owner: **Claude Code**. Verification: **Codex**.

## What it is / is not

- Single operational screen: viewer + blueprints + 5 sensors + 3 actuators + results.
- Typed models (`src/domain/types.ts`) shared across every panel.
- Runtime config (`public/config.json`) exposing the NUC stream host.
- `OmniverseViewport` uses NVIDIA `AppStreamer` for local direct WebRTC.
- No Service API, no Gemma backend yet.
- Does **not** touch the Omniverse Kit extension (`source/extensions/joon.smartfarm.twin`).

## Architecture context

```
Browser ──HTTP──▶ K8S (this React portal + optional API)   ← LoadBalancer / ingress
Browser ──WebRTC─▶ NUC (USD Composer / Kit App, stream source)   ← DIRECT, not proxied
```

The browser reads `config.json` at runtime and connects **directly** to the NUC
WebRTC endpoint. WebRTC media is **never** proxied through the K8S ingress.
Kubernetes runs only the web portal (and, later, the Service API).

See `docs/Progess/2026-05-26-web-portal-design.md` for the full design.

## Project layout

```
web/smartfarm-web/
├── public/config.json          # runtime config (NUC stream endpoint) — swapped per env
├── deploy/k8s/smartfarm-web.yaml
│                               # LoadBalancer deployment template for GitOps
├── scripts/build-and-push-image.sh
│                               # NUC build + Harbor-first push script
├── src/
│   ├── main.tsx                # loads config.json, then mounts <App>
│   ├── app/                    # providers, layout, app state wiring
│   ├── config/loadRuntimeConfig.ts
│   │                           # config loader + validation + defaults
│   ├── domain/                 # typed models + mock blueprint data
│   ├── features/               # viewer, blueprints, sensors, actuators, results
│   └── styles.css              # dashboard theme
├── Dockerfile                  # multi-stage: node build → nginx serve
├── nginx.conf                  # SPA + optional API proxy (no WebRTC proxy)
└── vite.config.ts / tsconfig*.json / package.json
```

## Develop / build / run

```bash
cd web/smartfarm-web

npm install          # first time only
npm run dev          # dev server at http://localhost:5173
npm run typecheck    # tsc --noEmit (no build)
npm run build        # typecheck + production build → dist/
npm run preview      # serve the production build at http://localhost:4173
```

## Runtime config (`public/config.json`)

The portal fetches `config.json` before first render. Edit it (or mount a
ConfigMap over it in K8S) to point at the NUC stream — no rebuild needed.

```json
{
  "facilityId": "smartfarm-v1",
  "facilityName": "Seolhyang Reference Greenhouse",
  "apiBaseUrl": "/api",
  "stream": {
    "source": "local",
    "server": "10.34.20.10",
    "streamUrl": "http://10.34.20.10:8011",
    "signalingPath": "",
    "width": 1920,
    "height": 1080
  }
}
```

| Field                  | Meaning                                                        |
| ---------------------- | -------------------------------------------------------------- |
| `stream.source`        | `local` (NUC) \| `gfn` \| `nvcf`. POC v1 uses `local`.         |
| `stream.server`        | NUC host/IP running USD Composer / Kit App.                    |
| `stream.streamUrl`     | Kit services base URL, useful for health/docs checks.          |
| `stream.signalingPath` | Legacy field; local direct WebRTC uses port `49100`, not a path. |
| `apiBaseUrl`           | Service API base (mock today; reachable via K8S ingress).      |

If `config.json` is missing or invalid, the app falls back to safe localhost
defaults (`src/config/runtimeConfig.ts`).

## Omniverse viewer

`src/features/viewer/OmniverseViewport.tsx` connects with NVIDIA
`@nvidia/omniverse-webrtc-streaming-library`, following the official
`web-viewer-sample` local direct streaming path.

For the current NUC:

```text
Kit services:  http://10.34.21.100:8011
WebRTC signal: 10.34.21.100:49100
```

`/streaming/webrtc-client/` is not a browser viewer route in this Kit setup.
Open the portal and use **Connect stream** instead.

## Docker image

```bash
cd web/smartfarm-web

# Build (run on the NUC per the deploy plan)
docker build -t smartfarm-web:0.1.0 .

# Run locally
docker run --rm -p 8080:80 smartfarm-web:0.1.0
#   → http://localhost:8080   (health: /healthz)

# Tag + push to DockerHub or internal Harbor
docker tag smartfarm-web:0.1.0 <registry>/smartfarm-web:0.1.0
docker push <registry>/smartfarm-web:0.1.0
```

Harbor-first fallback script:

```bash
cd web/smartfarm-web

# Harbor first. If Harbor push fails, DockerHub is used as fallback.
HARBOR_REGISTRY=harbor.internal.example \
HARBOR_PROJECT=smartfarm \
DOCKERHUB_REPOSITORY=dockerhub-user/smartfarm-web \
IMAGE_TAG=0.1.0 \
npm run image:push
```

Notes:

- Run this on the NUC.
- Run `docker login <harbor>` and/or `docker login` before the script.
- If Harbor variables are missing or Harbor push fails, the script falls back to
  `DOCKERHUB_REPOSITORY`.
- If neither push target is configured, the script builds locally and exits with
  instructions.

The image is a static nginx serving `dist/`. In K8S, override the stream
endpoint by mounting a ConfigMap over `/usr/share/nginx/html/config.json` — the
browser reads it at runtime, so no rebuild is needed. `nginx.conf` serves the
SPA and can optionally proxy the Service API; it deliberately does **not** proxy
WebRTC.

## Kubernetes template

`deploy/k8s/smartfarm-web.yaml` is a starting template for the existing GitOps
repo. It includes:

- `ConfigMap`: runtime `config.json` with the NUC stream endpoint.
- `Deployment`: nginx static portal pod.
- `Service`: `LoadBalancer` exposure for node4 K8S.

Before applying through GitOps, replace:

- `image: harbor.example.local/smartfarm/smartfarm-web:0.1.0`
- `stream.server`
- `stream.streamUrl`

## Deploy flow (per design doc)

1. NUC: write code (Claude Code), `npm run build`, `docker build`, push to registry.
2. GitOps: bump the `smartfarm-web` image tag in the manifest.
3. node4 K8S: GitOps controller pulls the image, runs the pod, exposes it via LoadBalancer.
4. NUC separately runs USD Composer / Kit App as the WebRTC stream source.
