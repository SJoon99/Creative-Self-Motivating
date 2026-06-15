#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/smartfarm-twin-common.sh"

printf '== layout ==\n'
echo "APP_HOME=$APP_HOME"
echo "KIT_PLATFORM=$KIT_PLATFORM"
echo "KIT_BIN=$KIT_BIN"
echo "APP_FILE=$APP_FILE"

printf '\n== process ==\n'
mapfile -t pids < <(find_smartfarm_pids)
if (( ${#pids[@]} > 0 )); then
  ps -fp "${pids[@]}"
else
  echo "not running"
fi

printf '\n== ports ==\n'
ss -lntup 2>/dev/null | egrep "(:${API_PORT}|:${SIGNALING_PORT})" || echo "no smartfarm tcp ports listening"
ss -lunp 2>/dev/null | egrep "(:${MEDIA_PORT})" || true

printf '\n== api ==\n'
if curl -fsS --max-time 5 "http://${API_HOST}:${API_PORT}/smartfarm/state" -o /tmp/smartfarm-state.json 2>/tmp/smartfarm-curl.err; then
  python3 - <<'PY'
import json
j=json.load(open('/tmp/smartfarm-state.json'))
print({k:j.get(k) for k in ['ok','sceneMode','hasStage','appliedBlueprintId']})
print('recommended:', j.get('recommendation',{}).get('recommendedBlueprintId'))
print('camera:', j.get('view',{}).get('defaultCameraPath'))
PY
else
  cat /tmp/smartfarm-curl.err || true
fi

printf '\n== endpoints ==\n'
print_endpoints

printf '\n== recent errors ==\n'
if [[ -f "$LOG_FILE" ]]; then
  grep -Ei '\[Error\]|NVST|Traceback|Exception|failed' "$LOG_FILE" | tail -80 || true
else
  echo "no log file: $LOG_FILE"
fi
