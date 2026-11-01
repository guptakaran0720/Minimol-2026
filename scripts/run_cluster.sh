#!/usr/bin/env bash
# Run a local cluster on this laptop: node-1..node-N on 127.0.0.1:8001..800N.
# Each node gets its own host_id, so placement treats them as separate hosts;
# say so on stage. Ctrl-C stops every node.
#
#   scripts/run_cluster.sh                  # 4 nodes
#   NODES=5 scripts/run_cluster.sh
#   DELAY_NODE=4 DELAY_MS=300 scripts/run_cluster.sh   # make node-4 slow (routing A/B)
#   FRESH=1 scripts/run_cluster.sh          # wipe data/cluster first
set -euo pipefail
cd "$(dirname "$0")/.."

NODES=${NODES:-4}
BASE_PORT=${BASE_PORT:-8000}
DELAY_NODE=${DELAY_NODE:-0}
DELAY_MS=${DELAY_MS:-300}
QUOTA_MB=${QUOTA_MB:-512}
ROOT=data/cluster
export CLUSTER_KEY=${CLUSTER_KEY:-local-dev-cluster-key-not-secret}

PY=python3
[ -x .venv/bin/python ] && PY=.venv/bin/python

[ "${FRESH:-0}" = 1 ] && rm -rf "$ROOT"
mkdir -p "$ROOT/logs"

pids=()
cleanup() {
  echo "stopping ${#pids[@]} nodes"
  kill "${pids[@]}" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

for i in $(seq 1 "$NODES"); do
  port=$((BASE_PORT + i))
  delay=0
  [ "$i" = "$DELAY_NODE" ] && delay=$DELAY_MS
  NODE_ID="node-$i" HOST_ID="host-$i" PORT=$port BIND_HOST=127.0.0.1 \
  ADVERTISE_ADDR="127.0.0.1:$port" SEEDS="127.0.0.1:$((BASE_PORT + 1))" \
  DATA_DIR="$ROOT/node-$i" QUOTA_MB=$QUOTA_MB SIMULATED_DELAY_MS=$delay \
    "$PY" -m node.main >"$ROOT/logs/node-$i.log" 2>&1 &
  pids+=($!)
  echo "node-$i  127.0.0.1:$port  pid $!  delay ${delay}ms  log $ROOT/logs/node-$i.log"
done

echo "cluster key: $CLUSTER_KEY   (Ctrl-C to stop all)"
wait
