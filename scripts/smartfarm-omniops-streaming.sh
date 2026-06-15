#!/usr/bin/env bash
set -euo pipefail
APP_HOME="${SMARTFARM_APP_HOME:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
export SMARTFARM_APP_HOME="${SMARTFARM_APP_HOME:-$APP_HOME}"
COMMON_SH="$APP_HOME/scripts/smartfarm-twin-common.sh"
if [[ -f "$COMMON_SH" ]]; then
  # Keep the streaming/WebRTC app on the same TwinX Gemma/RAG defaults
  # as the local OmniOps GUI launcher. Without this, Generate/Capture runs
  # deterministic fallback because SMARTFARM_RAG_BASE_URL is absent.
  # shellcheck source=scripts/smartfarm-twin-common.sh
  source "$COMMON_SH"
  APP_HOME="$SMARTFARM_APP_HOME"
fi
APP_FILE="$APP_HOME/source/apps/joon.smartfarm_omniops_streaming.kit"
LOG_FILE="${SMARTFARM_OMNIOPS_LOG:-$APP_HOME/logs/smartfarm-omniops-streaming.log}"
KEEP_EXISTING="${SMARTFARM_OMNIOPS_KEEP_EXISTING:-0}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --keep-existing) KEEP_EXISTING="1" ;;
    *) echo "Usage: $0 [--keep-existing]" >&2; exit 2 ;;
  esac
  shift
done
if [[ -x "$APP_HOME/_build/linux-aarch64/release/kit/kit" ]]; then
  KIT_PLATFORM="linux-aarch64"
elif [[ -x "$APP_HOME/_build/linux-x86_64/release/kit/kit" ]]; then
  KIT_PLATFORM="linux-x86_64"
else
  echo "ERROR: executable Kit binary not found under $APP_HOME/_build" >&2
  exit 1
fi
KIT_BIN="$APP_HOME/_build/$KIT_PLATFORM/release/kit/kit"
RELEASE_DIR="$APP_HOME/_build/$KIT_PLATFORM/release"

find_conflicting_pids() {
  ps -eo pid=,comm=,args= | awk -v home="$APP_HOME" -v kit="$KIT_BIN" '
    $2 == "kit" && index($0, kit) && index($0, home "/source/apps/joon.smartfarm") {print $1}
  '
}

stop_conflicts() {
  mapfile -t pids < <(find_conflicting_pids)
  if (( ${#pids[@]} == 0 )); then
    return 0
  fi
  if [[ "$KEEP_EXISTING" == "1" ]]; then
    echo "WARNING: existing SmartFarm Kit process(es) still running: ${pids[*]}" >&2
    echo "WARNING: WebRTC/API ports may conflict with the new streaming app." >&2
    return 0
  fi
  echo "Stopping existing SmartFarm Kit process(es) before starting OmniOps streaming: ${pids[*]}"
  kill "${pids[@]}" 2>/dev/null || true
  for _ in {1..20}; do
    mapfile -t remain < <(find_conflicting_pids)
    (( ${#remain[@]} == 0 )) && return 0
    sleep 0.5
  done
  mapfile -t remain < <(find_conflicting_pids)
  if (( ${#remain[@]} > 0 )); then
    echo "Force-stopping stuck SmartFarm Kit process(es): ${remain[*]}"
    kill -9 "${remain[@]}" 2>/dev/null || true
  fi
}

mkdir -p "$(dirname "$LOG_FILE")"
stop_conflicts
cd "$APP_HOME"
echo "Starting SmartFarm OmniOps streaming app. Log: $LOG_FILE"
exec "$KIT_BIN" "$APP_FILE" \
  --portable --no-window \
  --ext-folder "$APP_HOME/source/extensions" \
  --ext-folder "$APP_HOME/source/apps" \
  --ext-folder "$RELEASE_DIR/exts" \
  --ext-folder "$RELEASE_DIR/extscache" \
  --/app/enableStdoutOutput=1 \
  --/log/flushStandardStreamOutput=1 \
  >"$LOG_FILE" 2>&1
