#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/smartfarm-twin-common.sh"
mkdir -p "$(dirname "$LOG_FILE")"
touch "$LOG_FILE"
tail -f "$LOG_FILE"
