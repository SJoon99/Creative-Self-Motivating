# SmartFarm Twin target-node runbook

Existing Kubernetes/GitOps deployment is not modified by these scripts.
These scripts only run the copied Omniverse Kit twin on this node.

## Quick start

`run-twin.sh` now waits until the API is ready and creates the baseline growth scene automatically.

```bash
ssh user@100.73.161.118
cd ~/kit-app-template
./run-twin.sh
```

## Check status

```bash
./status-twin.sh
```

Expected runtime state:

```text
sceneMode: growth
hasStage: true
appliedBlueprintId: baseline
```

## Restart cleanly

```bash
./restart-twin.sh
```

## Start without creating scene

```bash
./run-twin.sh --no-scene
```

## Select scene mode at start

```bash
./run-twin.sh --scene growth
./run-twin.sh --scene mature
./run-twin.sh --scene reset
```

## Manual scene creation

```bash
./init-scene.sh growth
./init-scene.sh mature
./init-scene.sh reset
```

## Planner V2

```bash
./run-planner.sh
```

## Stop

```bash
./stop-twin.sh
```

## Logs

```bash
./scripts/smartfarm-twin-tail-log.sh
```

## Endpoints

- API local: `http://127.0.0.1:8011/smartfarm/state`
- API remote: `http://100.73.161.118:8011/smartfarm/state`
- WebRTC signaling: `100.73.161.118:49100`
- WebRTC media UDP: `100.73.161.118:47998`

## Local Omniverse GUI 확인

대상 노드의 실제 데스크톱 화면에 Omniverse/Kit 창을 띄우려면:

```bash
cd ~/kit-app-template
./run-twin-gui.sh
```

이 명령은 기존 headless SmartFarm Kit을 중지하고, `DISPLAY=:1`의 로컬 GNOME/Xorg 화면에 GUI Kit을 띄운 뒤, API ready 대기 및 growth scene 생성을 수행한다.

터미널 foreground로 직접 보고 싶으면:

```bash
./run-twin-gui-foreground.sh
```

GUI 종료:

```bash
./stop-twin.sh
```
