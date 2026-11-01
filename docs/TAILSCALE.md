# Cross-network run over Tailscale

**Goal:** real numbers for "does it work beyond one Wi-Fi?", measured on the three laptops while they sit on **different networks** (for example laptop 3 on a phone hotspot). No code changes: nodes already talk plain HTTP to IP addresses, so they run unchanged over a mesh VPN.

**Say on stage:** *Tailscale does the routing between networks, not our code.* NAT traversal of our own is on the roadmap (ARCHITECTURE_DECISIONS.md §1).

## 1. One-time setup (every laptop, ~10 min)

1. Install Tailscale: the macOS app from tailscale.com/download (or `brew install tailscale`), and sign in.
2. Put all three laptops in **one tailnet**: either sign in with the same account, or have one person invite the others (admin console → Users → Invite).
3. Get each laptop's Tailscale address, and write all three down:
   ```bash
   tailscale ip -4
   ```
   It looks like `100.x.y.z`. With the App Store app, the CLI is `/Applications/Tailscale.app/Contents/MacOS/Tailscale ip -4`.
4. Check every pair can reach each other (from each laptop, ping the other two):
   ```bash
   tailscale ping 100.x.y.z
   ```
   "via DERP" means traffic is relayed (slower); "via <ip>:<port>" means a direct path. Record which you got: it explains the numbers.
5. Move **at least one laptop to another network** (phone hotspot is easiest) and check `tailscale ping` again.

## 2. Start the nodes on their Tailscale addresses

Same commands as the campus run, with three changes: `ADVERTISE_ADDR` and `SEEDS` use the `100.x` addresses, and `MDNS=0` (multicast doesn't cross Tailscale, and it would advertise the Wi-Fi address instead).

Laptop 1 (seed):
```bash
CLUSTER_KEY='1234567891234567' NODE_ID=laptop-1 HOST_ID=laptop-1 MDNS=0 ADVERTISE_ADDR=$(tailscale ip -4):8000 .venv/bin/python -m node.main
```

Laptops 2 and 3 (replace `N`, and `<laptop-1 100.x>` with laptop 1's Tailscale address):
```bash
CLUSTER_KEY='1234567891234567' NODE_ID=laptop-N HOST_ID=laptop-N MDNS=0 ADVERTISE_ADDR=$(tailscale ip -4):8000 SEEDS=<laptop-1 100.x>:8000 .venv/bin/python -m node.main
```

If a laptop ran on campus Wi-Fi before, stop its old node first: its peers would otherwise keep the old Wi-Fi address until it re-announces. Data directories can stay; chunks are the same.

## 3. Check the cluster

From every laptop, every other laptop must answer `401` (reachable; unsigned request rejected):
```bash
curl -s -o /dev/null -m 5 -w "%{http_code}\n" http://<other 100.x>:8000/health
```

All three must be `alive`, with `100.x` addresses:
```bash
curl -s localhost:8000/stats | python3 -c "import json,sys; s=json.load(sys.stdin); print([(p['node_id'], p['addr'], p['state'], p['rtt_ms']) for p in s['peers']])"
```

Open http://localhost:8000/ui/ and unlock as `team-minimol`. The Peers panel shows each link's RTT; the Cluster timeline shows joins, failures and repairs as they happen.

## 4. Measure

Run on **laptop 1**, against its own node. Nothing below is estimated: record only what these commands print.

**a. Benchmark** (files, compression, delta sync, upload and download speed). Results land in `bench/results/`:
```bash
.venv/bin/python -m bench.bench --target http://127.0.0.1:8000 --username team-minimol --passphrase '123456789123' --reps 5 --csv-mb 8 --random-mb 2
```
Smaller files than the campus run (`--csv-mb 8`), because relayed links can be slow. Run `.venv/bin/python -m bench.bench --help` for `--skip` if a step takes too long.

**b. Self-test.** Each laptop runs its self-test steps 0–11 as on campus, writing `data/selftest-laptop-N.md`.

**c. Failure and repair across networks.** Laptop 3 stops its node (on the hotspot). On laptop 1, time until the timeline shows `laptop-3 is dead` (expect ~20 s), download every file (all must match), then restart laptop 3 and time until every file is `healthy` again.

**d. Self-healing across networks.** On laptop 2, flip one byte of a chunk under `data/node-8000/chunks/` (keep a backup). Its timeline shows `chunk … failed its hash check: quarantined` within seconds; time until another laptop's timeline shows `repair copied chunk … → laptop-2`.

## 5. Record

P4 adds a "Run 4: three laptops on different networks over Tailscale" section to `docs/RESULTS.md`:

| | |
|---|---|
| Date, place | |
| Networks | e.g. laptop 1 + 2 campus Wi-Fi, laptop 3 phone hotspot |
| Paths | direct / DERP relay per pair (from `tailscale ping`) |
| RTT per pair | from the dashboard Peers panel |
| Upload / download MB/s | median (min–max) of 5, from bench |
| Compression, delta sync | from bench |
| Dead detection | seconds, from the timeline |
| Repair after rejoin | seconds until all files healthy |
| Self-heal | seconds from quarantine to `repair copied` |
| Self-tests | PASS/FAIL per laptop |

## If it doesn't work

| Problem | Fix |
|---|---|
| `tailscale ping` fails | Both laptops signed in to the same tailnet? Check the admin console's machine list |
| `curl` gives `000` | macOS firewall blocking Python on the Tailscale interface: allow Python, or retry |
| Peers show Wi-Fi addresses, not `100.x` | A node started without `ADVERTISE_ADDR=$(tailscale ip -4):8000`; restart it |
| Very slow transfers | Probably relayed (DERP). Say so in the results; it's still a valid cross-network run |
| Nothing works in time | Fall back to the campus Wi-Fi run (Run 3) and say cross-network is next |
