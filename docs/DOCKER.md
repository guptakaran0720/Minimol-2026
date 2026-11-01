# Running the cluster in Docker

Four nodes, each in its own container with its own `host_id`, on a private Docker network. This uses the same image and code as the laptops: P1's real encryption and compression, P2's networking, P3's routing and repair, and the dashboard.

Requires Docker Desktop (macOS/Windows) or Docker Engine + Compose v2 (Linux).

## Start it

```bash
docker compose up -d --build
```

Open the dashboard at http://localhost:8001/ui/. Ports 8002–8004 serve the same dashboard from the other nodes.

To make node-4 slow, so you can show the routing difference (say on stage that the delay is simulated):

```bash
DELAY_MS=300 docker compose up -d
```

## Break it and watch it heal

```bash
docker compose stop node3
```

What to expect:
- After about 20 s, the dashboard shows node-3 dead and its files degraded.
- Within the next 0–20 s, another holder copies the missing chunks (repair runs every 10 s, and nodes learn locations every 10 s), and the files return to healthy.

Bring the node back with:

```bash
docker compose start node3
```

## Automated checks

| Command | What it does |
|---|---|
| `scripts/docker_e2e.sh` | Fresh cluster → `tests/test_cluster.py` (upload, kill, download, repair, recover on another node, second kill). Then a fresh cluster with node-4 delayed → live `bench.py` run, results in `bench/results/`. Leaves the cluster running. |
| `docker compose run --rm unit` | The whole pytest suite on Python 3.11, the same version as CI. |
| `docker compose down` | Stop and remove everything, including stored chunks. |

## How the user API stays private

- The user API and dashboard data are localhost-only.
- In Docker, requests from your browser arrive from the gateway address (`192.168.65.1` on Docker Desktop, `172.28.0.1` on Linux). `compose.yaml` allows exactly those two through `USER_API_ALLOW`.
- `compose.yaml` publishes the ports on `127.0.0.1` only, so other machines on your network can't reach them.
- Don't set `USER_API_ALLOW` to a LAN range on the real laptops.

## What Docker does not prove

- All containers share one machine, one disk and one network stack. Failure domains are separate processes, not separate hardware.
- Throughput numbers come from a virtual bridge, not Wi-Fi.
- Use Docker for correctness and for rehearsing the demo. Take the `RESULTS.md` numbers from the multi-laptop run.
