# Twinx Omniverse Direct Viewer

A minimal browser page for one action only: connect to the SmartFarm OmniOps WebRTC stream and show the actual twin full-screen.

Default stream target:

- Web page LB: `10.38.38.244:80` after GitOps sync
- SmartFarm OmniOps stream host: `10.32.214.23`
- Signaling: `49100/TCP`
- Media: `47998/UDP`

Run locally:

```bash
npm install
npm run build
npm run dev
```

Deploy path:

- Helm chart: `deploy/helm/omniverse-direct-viewer`
- GitOps target: `TwinX-Ops/argocd/multi-tenancy/apps/sjpark/apps/omniverse-direct-viewer`
