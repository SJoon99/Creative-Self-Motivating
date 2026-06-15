#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/smartfarm-twin-common.sh"

curl -fsS --max-time 30 -X POST "http://${API_HOST}:${API_PORT}/smartfarm/planning/run" -o /tmp/smartfarm-planning.json
python3 - <<'PY'
import json
j=json.load(open('/tmp/smartfarm-planning.json'))
print('ok:', j.get('ok'))
print('source:', j.get('planningRun',{}).get('source'))
print('recommended:', j.get('recommendation',{}).get('recommendedBlueprintId'))
for s in j.get('recommendation',{}).get('scores',[]):
    print('-', s.get('blueprintId'), 'score=', s.get('score'), 'risk=', s.get('diseaseRisk'), 'ship=', s.get('expectedShipment'))
PY
