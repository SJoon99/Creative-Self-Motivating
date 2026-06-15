#!/usr/bin/env bash
set -euo pipefail
APP_HOME="${SMARTFARM_APP_HOME:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$APP_HOME"
python3 -m py_compile \
  source/extensions/joon.smartfarm.twin/joon/smartfarm/twin/rag_adapter.py \
  source/extensions/joon.smartfarm.twin/joon/smartfarm/twin/extension.py \
  source/extensions/joon.smartfarm.omniops/joon/smartfarm/omniops/model.py \
  source/extensions/joon.smartfarm.omniops/joon/smartfarm/omniops/extension.py \
  services/smartfarm-service/app/main.py
PYTHONPATH="$APP_HOME/source/extensions/joon.smartfarm.twin" \
  python3 -m unittest joon.smartfarm.twin.tests.test_rag_adapter
PYTHONPATH="$APP_HOME/source/extensions/joon.smartfarm.omniops" \
  python3 -m unittest joon.smartfarm.omniops.tests.test_model
printf 'SmartFarm OmniOps smoke passed.\n'
