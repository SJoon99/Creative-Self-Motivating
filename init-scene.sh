#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
exec ./scripts/smartfarm-twin-create-scene.sh "${1:-growth}"
