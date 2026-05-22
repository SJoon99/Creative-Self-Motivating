#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
./repo.sh launch -n joon.smartfarm_composer.kit "$@"
