#!/usr/bin/env bash
set -euo pipefail

APP_HOME="${SMARTFARM_APP_HOME:-$HOME/kit-app-template}"
APP_FILE="${SMARTFARM_APP_FILE:-$APP_HOME/source/apps/joon.smartfarm_composer_streaming.kit}"
LOG_FILE="${SMARTFARM_LOG_FILE:-$APP_HOME/logs/smartfarm-streaming.log}"
API_HOST="${SMARTFARM_API_HOST:-127.0.0.1}"
API_PORT="${SMARTFARM_API_PORT:-8011}"
SIGNALING_PORT="${SMARTFARM_SIGNALING_PORT:-49100}"
MEDIA_PORT="${SMARTFARM_MEDIA_PORT:-47998}"
PUBLIC_HOST="${SMARTFARM_PUBLIC_HOST:-100.73.161.118}"
SMARTFARM_RAG_BASE_URL="${SMARTFARM_RAG_BASE_URL:-http://10.38.38.241:8080}"
SMARTFARM_RAG_TOKEN_FILE="${SMARTFARM_RAG_TOKEN_FILE:-$HOME/.smartfarm-rag-token}"
SMARTFARM_RAG_TIMEOUT="${SMARTFARM_RAG_TIMEOUT:-30}"
export SMARTFARM_RAG_BASE_URL SMARTFARM_RAG_TOKEN_FILE SMARTFARM_RAG_TIMEOUT

if [[ -d "$APP_HOME/_build/linux-aarch64/release" ]]; then
  KIT_PLATFORM="linux-aarch64"
elif [[ -d "$APP_HOME/_build/linux-x86_64/release" ]]; then
  KIT_PLATFORM="linux-x86_64"
else
  echo "ERROR: Kit build directory not found under $APP_HOME/_build" >&2
  exit 1
fi

KIT_BIN="$APP_HOME/_build/$KIT_PLATFORM/release/kit/kit"
RELEASE_DIR="$APP_HOME/_build/$KIT_PLATFORM/release"

find_smartfarm_pids() {
  # Match only the real SmartFarm Kit process. This catches both:
  # - joon.smartfarm_runtime_streaming.kit   (service/kiosk WebRTC)
  # - joon.smartfarm_composer_streaming.kit  (legacy headless/WebRTC)
  # - joon.smartfarm_composer.kit            (local GUI)
  local app_marker="$APP_HOME/source/apps/joon.smartfarm"
  ps -eo pid=,comm=,args= | awk -v marker="$app_marker" -v kit="$KIT_BIN" '$2 == "kit" && index($0, kit) && index($0, marker) {print $1}'
}

require_layout() {
  [[ -x "$KIT_BIN" ]] || { echo "ERROR: Kit binary not executable: $KIT_BIN" >&2; exit 1; }
  [[ -f "$APP_FILE" ]] || { echo "ERROR: SmartFarm app not found: $APP_FILE" >&2; exit 1; }
  [[ -d "$APP_HOME/source/extensions/joon.smartfarm.twin" ]] || { echo "ERROR: SmartFarm extension not found" >&2; exit 1; }
}

print_endpoints() {
  cat <<EOF
API local:       http://127.0.0.1:${API_PORT}/smartfarm/state
API remote:      http://${PUBLIC_HOST}:${API_PORT}/smartfarm/state
WebRTC signaling ${PUBLIC_HOST}:${SIGNALING_PORT}
WebRTC media UDP ${PUBLIC_HOST}:${MEDIA_PORT}
Gemma/RAG API:    ${SMARTFARM_RAG_BASE_URL} (token file: ${SMARTFARM_RAG_TOKEN_FILE})
Log:             ${LOG_FILE}
EOF
}
