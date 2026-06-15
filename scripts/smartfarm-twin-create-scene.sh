#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/smartfarm-twin-common.sh"

MODE="${1:-growth}"
case "$MODE" in
  growth|mature|reset) ;;
  *) echo "Usage: $0 [growth|mature|reset]" >&2; exit 2 ;;
esac

curl -fsS --max-time 30 -X POST "http://${API_HOST}:${API_PORT}/smartfarm/scene/${MODE}" -o /tmp/smartfarm-scene.json
python3 -m json.tool /tmp/smartfarm-scene.json | sed -n '1,180p'
