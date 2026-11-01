# Five-minute demo script

**Goal:** show working evidence for every claim, not just slides. Each step names what the audience sees, what you say, what proves it, and what to do if it breaks.

## Before going on stage (T-15 min)

1. **Network:** all 4 laptops on **our own hotspot**. On each laptop, from another one, run:
   ```bash
   curl http://<ip>:8000/health
   ```
   It must not time out (any HTTP reply is fine).
2. **Start each laptop's node** with its own `NODE_ID`, a `HOST_ID` set to that laptop, `SEEDS=<laptop-1 ip>:8000`, and the same `CLUSTER_KEY`. Leave the slow laptop's `SIMULATED_DELAY_MS` at `0` for now.
3. **Dashboard:** open `http://localhost:8000/ui/` on laptop 1, put it on the projector, and unlock it with the demo username + passphrase.
4. **Check the dashboard:** all 4 peers green, codec shows "P1 pipeline", files list empty or clean.
5. **Files on the desktop:** `sensor_log.csv` (about 20 MB, from `bench.bench.make_csv`) and `photo.jpg`.
6. **Plan B ready:** `docker compose up -d` already run on laptop 2, dashboard open in a browser tab. **Plan C:** the backup video.

## The script

| Time | Step | Audience sees | You say | Proof | If it breaks |
|---|---|---|---|---|---|
| 0:00 | **Hook** | Cover slide | "Your cloud has one owner. We made the laptops you already have into one drive that survives losing machines and heals itself." | — | — |
| 0:20 | **1. Upload the log** | Upload card: original 20 MB, encoded about 30%, "Stored across peers", chunk map with 3 cells per row | "Compressed and encrypted on this laptop before anything left it. Every chunk now lives on 3 different laptops." | `compression_ratio` in the upload card; chunk map shows 3/3 per row | Upload 503 → a peer is down; check the Peers panel, continue with 3 nodes |
| 0:50 | **2. Upload a photo** | Ratio about 100% | "A JPEG is already compressed. Each chunk is only kept compressed if it saves 3%, so we don't waste CPU." | Upload card ratio ≈ 100% | — |
| 1:10 | **3. Slow a laptop** | Restart laptop 4 with `SIMULATED_DELAY_MS=300`; after about 30 s its row shows "slow tier"; upload the log again under a new name; its column stays empty | "This delay is simulated. Once a peer is three times slower than the median for 30 seconds, new chunks avoid it." | Peers panel "slow tier" tag; chunk map column empty; slide 6 numbers (0% vs 21.7%) | Tier not reached in time → show slide 6 and keep going |
| 2:00 | **4. Close a lid** | Close laptop 2's lid; click Download straight away | "The file still downloads. The browser checks the SHA-256 against the original." | Download succeeds; `X-File-SHA256` header (open devtools if asked) | Download slow → it is retrying the lid-closed peer; wait, it moves on after 1 s |
| 2:40 | **5. Watch it heal** | After about 20 s laptop 2 turns red and files go degraded; 10–20 s later they're green and the Self-repair events list fills | "Every peer agreed it was dead. One holder per chunk copied it to a new laptop. Nobody touched anything." | Peers row red; badges degraded → healthy; repair events | Slow to heal → explain the 10 s cycles; show slide 8 |
| 3:30 | **6. Second failure** | Close laptop 3's lid; download again | "Two laptops gone, and the file still comes back." | Download succeeds | With only 2 laptops left the file shows degraded: say "3 copies on 3 laptops is impossible with 2 laptops; it heals when one returns" |
| 4:00 | **7. Delta sync** | Append rows to the log, upload under the same name; card shows "1 sent, N reused" | "Change 1%, send 1%. Same idea as our production app updates." | "Sent this upload" in the upload card | — |
| 4:20 | **8. Fresh laptop** | Laptop 4 (new data dir) → unlock with the same username + passphrase → file list appears → download | "No key file was copied. The username and passphrase rebuild the keys, and the peers give back the signed file list." | "Restored N files" banner | Index not found → the peer holding it is down; say so and show `test_cluster.py` passing |
| 4:45 | **Close** | Limits slide, then closing slide | "LAN today; DHT and NAT traversal next. Questions?" | — | — |

## Fallbacks

| Problem | Do this |
|---|---|
| Laptops can't reach each other | Switch to Docker on laptop 2: `docker compose up -d`, open `localhost:8001/ui/`. Run the same steps with `docker compose stop node2`, and say it's containers on one machine. |
| Dashboard won't load | `curl -s localhost:8000/stats \| python -m json.tool` on the projector, with the terminal at a large font. |
| Everything fails | Play the backup video, then show `pytest` and `bench/results/*.md`. |

## Rehearsal checklist (run twice, at 19:30)

- [ ] Every step lands within its time slot. Write down the actual times.
- [ ] Detection and repair times observed: _____ s / _____ s.
- [ ] The backup video is recorded from a clean run.
- [ ] Every speaker can answer the 10 most likely questions in [JUDGE_QA.md](JUDGE_QA.md).
