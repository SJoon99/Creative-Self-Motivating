#!/usr/bin/env bash
set -euo pipefail

APP_HOME="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$APP_HOME/scripts/smartfarm-twin-common.sh"

GUI_APP_FILE="$APP_HOME/source/apps/joon.smartfarm_composer.kit"
if [[ ! -f "$GUI_APP_FILE" ]]; then
  GUI_APP_FILE="$APP_HOME/source/apps/joon.smartfarm_composer_streaming.kit"
fi

SCENE_MODE="growth"
RESTART="true"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-restart) RESTART="false" ;;
    --scene) SCENE_MODE="${2:-growth}"; shift ;;
    --scene=*) SCENE_MODE="${1#--scene=}" ;;
    --no-scene) SCENE_MODE="" ;;
    *) echo "Usage: $0 [--no-restart] [--scene growth|mature|reset] [--no-scene]" >&2; exit 2 ;;
  esac
  shift
done

require_layout
[[ -f "$GUI_APP_FILE" ]] || { echo "ERROR: GUI app file not found: $GUI_APP_FILE" >&2; exit 1; }

# Target node has an active local Xorg/GNOME session on :1.
export DISPLAY="${DISPLAY:-:1}"
if [[ -z "${XAUTHORITY:-}" ]]; then
  for candidate in "/run/user/$(id -u)/gdm/Xauthority" "$HOME/.Xauthority"; do
    if [[ -r "$candidate" ]]; then
      export XAUTHORITY="$candidate"
      break
    fi
  done
fi
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=/run/user/$(id -u)/bus}"

GUI_LOG="${SMARTFARM_GUI_LOG_FILE:-$APP_HOME/logs/smartfarm-gui.log}"
mkdir -p "$(dirname "$GUI_LOG")"

if [[ "$RESTART" == "true" ]]; then
  "$APP_HOME/scripts/smartfarm-twin-stop.sh" || true
fi

mapfile -t pids < <(find_smartfarm_pids)
if (( ${#pids[@]} > 0 )); then
  echo "SmartFarm Kit is already running: ${pids[*]}"
else
  : > "$GUI_LOG"
  cd "$APP_HOME"
  setsid -f "$KIT_BIN" \
    "$GUI_APP_FILE" \
    --portable \
    --ext-folder "$APP_HOME/source/extensions" \
    --ext-folder "$APP_HOME/source/apps" \
    --ext-folder "$RELEASE_DIR/exts" \
    --ext-folder "$RELEASE_DIR/extscache" \
    --/app/enableStdoutOutput=1 \
    --/log/flushStandardStreamOutput=1 \
    </dev/null >"$GUI_LOG" 2>&1
  sleep 2
fi

mapfile -t pids < <(find_smartfarm_pids)
if (( ${#pids[@]} == 0 )); then
  echo "ERROR: GUI Kit failed to start. Log tail:" >&2
  tail -160 "$GUI_LOG" >&2 || true
  exit 1
fi

echo "SmartFarm GUI Kit started: ${pids[*]}"
echo "DISPLAY=$DISPLAY"
echo "XAUTHORITY=${XAUTHORITY:-<unset>}"
echo "GUI log: $GUI_LOG"

echo "Waiting for SmartFarm API..."
ready=false
for _ in $(seq 1 90); do
  if curl -fsS --max-time 3 "http://${API_HOST}:${API_PORT}/smartfarm/state" -o /tmp/smartfarm-gui-state.json 2>/dev/null; then
    ready=true
    break
  fi
  sleep 2
done

if [[ "$ready" != "true" ]]; then
  echo "ERROR: GUI Kit started but API did not become ready. Log tail:" >&2
  tail -160 "$GUI_LOG" >&2 || true
  exit 1
fi

if [[ -n "$SCENE_MODE" ]]; then
  has_stage=$(python3 - <<'PY'
import json
j=json.load(open('/tmp/smartfarm-gui-state.json'))
print('true' if j.get('hasStage') else 'false')
PY
)
  if [[ "$has_stage" == "true" ]]; then
    echo "SmartFarm scene already exists."
  else
    echo "Creating SmartFarm scene in GUI: $SCENE_MODE"
    curl -fsS --max-time 60 -X POST "http://${API_HOST}:${API_PORT}/smartfarm/scene/${SCENE_MODE}" -o /tmp/smartfarm-gui-scene.json
    python3 - <<'PY'
import json
j=json.load(open('/tmp/smartfarm-gui-scene.json'))
print({k:j.get(k) for k in ['ok','sceneMode','hasStage','appliedBlueprintId']})
PY
  fi
fi

print_endpoints
cat <<EOF

확인 방법:
- 대상 노드의 물리/원격 데스크톱 화면에서 Omniverse 창이 떠야 합니다.
- 창이 뒤에 숨어 있으면 Alt+Tab 또는 Activities에서 "Smart Farm"/"Kit" 창을 찾으세요.
- 종료: ./stop-twin.sh
EOF
