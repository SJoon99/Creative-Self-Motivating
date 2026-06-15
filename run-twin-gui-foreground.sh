#!/usr/bin/env bash
set -euo pipefail
APP_HOME="$(cd "$(dirname "$0")" && pwd)"
source "$APP_HOME/scripts/smartfarm-twin-common.sh"
GUI_APP_FILE="$APP_HOME/source/apps/joon.smartfarm_composer.kit"
[[ -f "$GUI_APP_FILE" ]] || GUI_APP_FILE="$APP_HOME/source/apps/joon.smartfarm_composer_streaming.kit"
export DISPLAY="${DISPLAY:-:1}"
if [[ -z "${XAUTHORITY:-}" ]]; then
  for candidate in "/run/user/$(id -u)/gdm/Xauthority" "$HOME/.Xauthority"; do
    [[ -r "$candidate" ]] && export XAUTHORITY="$candidate" && break
  done
fi
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=/run/user/$(id -u)/bus}"
cd "$APP_HOME"
exec "$KIT_BIN" "$GUI_APP_FILE" \
  --portable \
  --ext-folder "$APP_HOME/source/extensions" \
  --ext-folder "$APP_HOME/source/apps" \
  --ext-folder "$RELEASE_DIR/exts" \
  --ext-folder "$RELEASE_DIR/extscache" \
  --/app/enableStdoutOutput=1 \
  --/log/flushStandardStreamOutput=1
