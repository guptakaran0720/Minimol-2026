#!/usr/bin/env bash
# End-to-end check on the Docker cluster (compose.yaml):
#   1. fresh 4-node cluster -> tests/test_cluster.py (upload, kill, download, repair, recover, 2nd kill)
#   2. fresh cluster with node-4 delayed 300 ms -> bench.py live run (results in bench/results/)
# Leaves the benchmark cluster running so you can open http://localhost:8001/ui/.
#   scripts/docker_e2e.sh            REPS=3 scripts/docker_e2e.sh
set -euo pipefail
cd "$(dirname "$0")/.."
[ -d /Applications/Docker.app/Contents/Resources/bin ] && export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"
PY=python3
[ -x .venv/bin/python ] && PY=.venv/bin/python
URLS=http://127.0.0.1:8001,http://127.0.0.1:8002,http://127.0.0.1:8003,http://127.0.0.1:8004

wait_alive() {
  "$PY" - <<'PY'
import json, time, urllib.request
deadline = time.time() + 90
while time.time() < deadline:
    try:
        s = json.load(urllib.request.urlopen("http://127.0.0.1:8001/stats", timeout=2))
        if sum(p["state"] == "alive" for p in s["peers"]) >= 4:
            print(f"cluster ready: 4 nodes alive, codec = {s['codec']}")
            raise SystemExit(0)
    except OSError:
        pass
    time.sleep(1)
raise SystemExit("cluster did not come up within 90 s")
PY
}

echo "== 1/2 cluster test"
docker compose down --remove-orphans >/dev/null 2>&1 || true
docker compose up -d --build
wait_alive
P2P_CLUSTER=$URLS P2P_KILL_CMD='docker compose stop node$(({port}-8000))' "$PY" -m pytest -q -p no:warnings tests/test_cluster.py

echo "== 2/2 live benchmark (node-4 delayed 300 ms, simulated)"
docker compose down >/dev/null
DELAY_MS=300 docker compose up -d
wait_alive
"$PY" -m bench.bench --target http://127.0.0.1:8001 --username bench --passphrase 'docker bench passphrase' \
  --slow-node node-4 --kill-node node-2 --kill-cmd 'docker compose stop node2' --reps "${REPS:-5}"
docker compose start node2 >/dev/null
echo "dashboard: http://localhost:8001/ui/  (docker compose down to stop)"
