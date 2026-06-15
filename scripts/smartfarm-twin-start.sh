#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/smartfarm-twin-common.sh"

INIT_SCENE="growth"
RESTART="false"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --restart) RESTART="true" ;;
    --no-scene) INIT_SCENE="" ;;
    --scene) INIT_SCENE="${2:-growth}"; shift ;;
    --scene=*) INIT_SCENE="${1#--scene=}" ;;
    *) echo "Usage: $0 [--restart] [--no-scene] [--scene growth|mature|reset]" >&2; exit 2 ;;
  esac
  shift
done

require_layout
mkdir -p "$(dirname "$LOG_FILE")"

wait_api_ready() {
  local timeout="${SMARTFARM_API_WAIT_SECONDS:-150}"
  local elapsed=0
  while (( elapsed < timeout )); do
    if curl -fsS --max-time 3 "http://${API_HOST}:${API_PORT}/smartfarm/state" >/tmp/smartfarm-state.json 2>/dev/null; then
      return 0
    fi
    sleep 2
    elapsed=$((elapsed + 2))
  done
  return 1
}

has_stage() {
  python3 - <<'PY'
import json, sys
try:
    j=json.load(open('/tmp/smartfarm-state.json'))
except Exception:
    sys.exit(1)
sys.exit(0 if j.get('sceneMode') not in (None, 'uninitialized') and j.get('appliedBlueprintId') else 1)
PY
}

create_scene_if_needed() {
  [[ -n "$INIT_SCENE" ]] || return 0
  if has_stage; then
    echo "SmartFarm scene already exists. Skipping scene init."
    return 0
  fi
  echo "Creating SmartFarm scene: ${INIT_SCENE}"
  curl -fsS --max-time 60 -X POST "http://${API_HOST}:${API_PORT}/smartfarm/scene/${INIT_SCENE}" -o /tmp/smartfarm-scene.json
  python3 - <<'PY'
import json
j=json.load(open('/tmp/smartfarm-scene.json'))
print({k:j.get(k) for k in ['ok','sceneMode','hasStage','appliedBlueprintId']})
PY
}

if [[ "$RESTART" == "true" ]]; then
  "$SCRIPT_DIR/smartfarm-twin-stop.sh" || true
fi

mapfile -t pids < <(find_smartfarm_pids)
if (( ${#pids[@]} > 0 )); then
  echo "SmartFarm Twin process is already running: ${pids[*]}"
  if wait_api_ready; then
    create_scene_if_needed
    print_endpoints
    exit 0
  fi
  echo "ERROR: process exists but API is not ready. Use ./restart-twin.sh" >&2
  tail -120 "$LOG_FILE" >&2 || true
  exit 1
fi

: > "$LOG_FILE"
cd "$APP_HOME"
setsid -f "$KIT_BIN" \
  "$APP_FILE" \
  --portable --no-window \
  --ext-folder "$APP_HOME/source/extensions" \
  --ext-folder "$APP_HOME/source/apps" \
  --ext-folder "$RELEASE_DIR/exts" \
  --ext-folder "$RELEASE_DIR/extscache" \
  --/app/enableStdoutOutput=1 \
  --/log/flushStandardStreamOutput=1 \
  </dev/null >"$LOG_FILE" 2>&1

sleep 2
mapfile -t pids < <(find_smartfarm_pids)
if (( ${#pids[@]} == 0 )); then
  echo "ERROR: SmartFarm Twin failed to start. Log tail:" >&2
  tail -120 "$LOG_FILE" >&2 || true
  exit 1
fi

echo "SmartFarm Twin process started: ${pids[*]}"
echo "Waiting for SmartFarm API..."
if ! wait_api_ready; then
  echo "ERROR: API did not become ready. Log tail:" >&2
  tail -160 "$LOG_FILE" >&2 || true
  exit 1
fi

echo "SmartFarm API is ready."
create_scene_if_needed
print_endpoints
