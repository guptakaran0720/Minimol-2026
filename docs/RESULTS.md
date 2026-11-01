# Results

Every number in this file comes from a run of `bench/bench.py` or a test in `tests/`. Nothing is estimated. Each table states where and how it ran.

How to reproduce:
- **Docker:** `scripts/docker_e2e.sh` (see [DOCKER.md](DOCKER.md)).
- **Laptops:** see [TEAM_WORKFLOW.md](TEAM_WORKFLOW.md), the P4 section.

Each timed step runs 5 times. Times are reported as **median (min–max)**.

## Metric definitions

| Metric | Definition |
|---|---|
| Compression ratio | encoded bytes ÷ original bytes. Includes 28 B of AES-GCM nonce + tag per chunk. Lower is better. |
| Stored ÷ original | bytes held across all copies ÷ original bytes. 3 copies of an incompressible file = 3.0. |
| Throughput | original bytes ÷ seconds, measured end to end by the client. |
| Delta sent fraction | bytes sent on re-upload ÷ size of the new version. |
| Slow-node share | copies placed on the delayed node ÷ all copies. |
| Detection / repair time | seconds from stopping a node until the uploader's node shows it **dead** / shows every chunk back at **3 live copies**. |

## Run 1: Docker, 4 containers on one laptop (2026-11-01)

**Setup:** `scripts/docker_e2e.sh` on Docker Desktop (macOS). Real P1 encryption and compression. node-4 had `SIMULATED_DELAY_MS=300` on every peer request. **The delay is simulated; say so on stage.**

### Files

| Data | Original | Ratio | Stored ÷ original | Upload s | Download s | Up MB/s | Down MB/s | SHA-256 |
|---|---|---|---|---|---|---|---|---|
| Sensor CSV (generated) | 20.00 MB | **0.302** | 0.905 | 2.317 (2.013–2.364) | 0.147 (0.140–0.166) | 8.6 | 136.1 | match |
| Random bytes | 5.00 MB | 1.000 | 3.000 | 1.295 (0.667–1.306) | 0.061 (0.059–0.066) | 3.9 | 82.2 | match |

Random bytes don't compress, so every chunk is stored raw (ratio 1.000), as designed.

### Delta sync (append ~1% to the CSV and re-upload under the same name)

| New version | Sent | Sent fraction | Chunks sent / reused | SHA-256 |
|---|---|---|---|---|
| 20.20 MB | **0.188 MB** | 0.0093 | 1 / 20 | match |

"Sent" counts every copy that went over the network: 3 copies of the one changed chunk.

### Placement A/B: smart (tiered rendezvous) vs random baseline

Before the A/B started, node-4 had reached the slow tier (tier 2) after an 11.0 s warm-up.

| Strategy | Slow-node share | Download s | Copies per node (last run) |
|---|---|---|---|
| Smart | **0.000** (0.000–0.000) | 0.152 (0.132–0.196) | node-1 20, node-2 20, node-3 20, node-4 0 |
| Random | 0.217 (0.183–0.300) | 0.140 (0.121–0.143) | node-1 18, node-2 14, node-3 17, node-4 11 |

Download times are about the same in both rows. That's because downloads already route around the slow node; the next table isolates that effect.

### Retrieval A/B: ETA ranking with hedged reads vs random holder

The file was placed with the random baseline so that the slow node really holds chunks. The smart path is ETA ranking **plus** hedged reads; the baseline tries holders in random order with no hedging. The speedup is for the two together, not for ETA ranking alone.

| ETA ordering | Random holder | Median speedup |
|---|---|---|
| 0.146 s (0.113–0.192) | 1.697 s (1.106–1.977) | **11.6×** |

### Kill a node, then repair

| Event | Result |
|---|---|
| `docker compose stop node2` | 20 chunks lost a copy |
| node-1 shows node-2 dead | 21.4 s |
| node-1 shows every chunk at 3 live copies | 21.4 s (the repair had already finished on node-3 by the time node-1 noticed) |
| SHA-256 after repair | match |

Separate check, stopping node-3 by hand:
- node-4, node-3's view and node-1 marked it dead after **19.5 s, 19.8 s and 20.6 s**.
- All **27 / 27** files went from degraded back to healthy without anyone doing anything.

## Run 2: 4 local processes on one laptop (`scripts/run_cluster.sh`)

This run used the dev stand-in codec (no compression, no encryption). Only the routing and repair rows are meaningful.

| Measurement | Result |
|---|---|
| Delta sync, append ~1% to 20 MB | 0.60 MB sent (1 chunk sent, 20 reused) |
| Slow-node share: smart vs random | 0% vs 21.7% |
| Download: ETA vs random holder | 0.072 s vs 1.005 s (13.9×) |
| Dead / back to 3 copies | 21.3 s / 42.7 s |

**Why repair time varies (21 s vs 43 s):**
- Detection takes about 20 s.
- Repair then waits for the next 10 s repair round.
- The uploader learns where the new copies are on its next 10 s inventory poll.

So the honest figure is **about 20–40 s**.

## Correctness

| Check | Result |
|---|---|
| `pytest` (Python 3.12 local, 3.11 in Docker) | 166 passed, 1 skipped (the live cluster test, which needs running nodes) |
| `tests/test_cluster.py` on Docker and on local processes | passed: upload → distinct hosts → kill → download → dead → repair → recover on another node → second kill → download |
| Fresh-node recovery from username + passphrase | passed (part of the cluster test) |

## Run 3: real laptops on the hotspot (to do)

Fill this in only from `bench/results/live-*.md` on the demo laptops.

| Measurement | Result |
|---|---|
| CSV ratio / stored ÷ original | — |
| Upload / download 20 MB (s) | — |
| Delta sent for ~1% append | — |
| Slow-node share, smart vs random | — |
| Download, ETA vs random holder | — |
| Dead / back to 3 copies (s) | — |

## What these numbers do not show

- **Runs 1 and 2 are on one machine.** Throughput reflects a virtual network, not Wi-Fi.
- **The slow node is simulated** with a fixed 300 ms delay. Real slowness is noisier.
- **Durability over days, disk failures and many simultaneous users were not tested.**
