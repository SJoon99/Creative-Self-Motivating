#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/smartfarm-twin-common.sh"

mapfile -t pids < <(find_smartfarm_pids)
if (( ${#pids[@]} == 0 )); then
  echo "SmartFarm Twin is not running."
  exit 0
fi

echo "Stopping SmartFarm Twin: ${pids[*]}"
kill "${pids[@]}" 2>/dev/null || true
sleep 3
mapfile -t remain < <(find_smartfarm_pids)
if (( ${#remain[@]} > 0 )); then
  echo "Force stopping SmartFarm Twin: ${remain[*]}"
  kill -9 "${remain[@]}" 2>/dev/null || true
fi

echo "Stopped."
