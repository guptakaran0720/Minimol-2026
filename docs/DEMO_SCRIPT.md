# Five-minute demo script (3 laptops)

**Goal:** show working evidence for every claim, not just slides. Each step names what the audience sees, what you say, what proves it, and what to do if it breaks.

**What 3 laptops change:**
- **Every chunk lives on all three laptops.** When one is off, files are honestly **degraded** until it returns. There's no fourth laptop to repair onto.
- **We show repair two ways:**
  - **Rejoin:** a file uploaded while a laptop was off heals when it comes back. Measured: 6 s.
  - **Replace:** an empty replacement laptop gets refilled. Measured: about 19 s.
- **Slow-laptop routing can't be shown live.** With only 3 laptops it has nowhere to route around, so we show the measured Docker A/B on slides 6–7.

All timings below are from our run on 1 November ([RESULTS.md](RESULTS.md), Run 3).

## Before going on stage (T-20 min)

1. **Network:** all 3 laptops on the same network. Our own hotspot is safest; campus Wi-Fi worked in testing.
2. **Laptop 1's IP:** note it; it replaces `LAPTOP1_IP` below:
   ```bash
   ipconfig getifaddr en0
   ```
3. **Fresh secrets:** pick a random cluster key (it replaces `SHARED_SECRET` below), and a new team username + passphrase:
   ```bash
   python3 -c "import secrets; print(secrets.token_urlsafe(24))"
   ```
   Keep them in a shared note and copy-paste them; never retype.
4. **Start all 3 nodes from scratch.** This also clears stale peers like the old `laptop-4`. Use one terminal per laptop and leave it visible.
   - **Laptop 1:**
     ```bash
     CLUSTER_KEY='SHARED_SECRET' NODE_ID=laptop-1 HOST_ID=laptop-1 ADVERTISE_ADDR=$(ipconfig getifaddr en0):8000 .venv/bin/python -m node.main
     ```
   - **Laptops 2 and 3** (change the number in both places; replace `SHARED_SECRET` with the key and `LAPTOP1_IP` with laptop 1's address):
     ```bash
     CLUSTER_KEY='SHARED_SECRET' NODE_ID=laptop-2 HOST_ID=laptop-2 ADVERTISE_ADDR=$(ipconfig getifaddr en0):8000 SEEDS=LAPTOP1_IP:8000 .venv/bin/python -m node.main
     ```
5. **Keep laptops awake:** run `caffeinate -i &` on each Mac.
6. **Dashboard:**
   - Open `http://localhost:8000/ui/` on laptop 1 and put it on the projector.
   - Check that it shows **3 of 3 alive**, with no stale entries.
   - Unlock with the team login.
   - Unlock laptop 3 as well.
   - **Leave laptop 2 locked** for the recovery step.
7. **Files on laptop 1's desktop:**
   - `sensor_log.csv` (8 MB):
     ```bash
     .venv/bin/python -c "from bench.bench import make_csv; open('sensor_log.csv','wb').write(make_csv(8*1024*1024))"
     ```
   - `photo.jpg`: any real photo.
   - `notes.txt`: anything small.
8. **Plan B:** `docker compose up -d` already run on laptop 1, with `localhost:8001/ui/` open in another tab.
9. **Plan C:** the backup video.

## The script

| Time | Step | Audience sees | You say | Proof | If it breaks |
|---|---|---|---|---|---|
| 0:00 | **Hook** | Cover slide | "Your cloud has one owner. We turned three ordinary laptops into one drive that survives losing a machine and heals itself." | — | — |
| 0:20 | **1. Upload the log** (laptop 1) | Upload card: 8 MB → about 2.4 MB (≈30%); chunk map shows each chunk on laptop-1, -2 and -3 | "Compressed and encrypted on this laptop before anything left it. Every piece is now on three laptops." | Upload card %; chunk map 3/3 | Upload 503 → a peer is down; check Peers and restart it |
| 0:50 | **2. Upload the photo** | About 100% | "A JPEG is already compressed. Each piece is kept compressed only if that saves 3%, so we don't waste CPU." | Upload card ≈100% | — |
| 1:05 | **3. Unreadable pieces** (laptop 3's terminal) | `file data/node-8000/chunks/*/* \| head -3` prints `data` | "This laptop stores our pieces but can't read them: they're encrypted, and named by their own hash." | Terminal output | — |
| 1:25 | **4. Switch laptop 3 off** | Ctrl-C laptop 3's node (or close the lid); **immediately** click Download on the log | "One laptop just disappeared. The file still downloads, and the browser checks its SHA-256." | Download opens | Slow first try → it's skipping laptop 3; it moves on within about a second |
| 1:55 | **5. Detection** | About 20 s later laptop 3 turns **red**; files go **degraded** | "Every laptop agreed it's gone. With two laptops left we can't keep three independent copies, so we say *degraded* instead of pretending." | Peers row red; badges | — |
| 2:15 | **6. Upload while it's away** | Upload `notes.txt` → **degraded**, 2 copies | "New data is still safe on two laptops, and the system tells you it owes a third copy." | Upload card status | — |
| 2:35 | **7. Laptop 3 comes back** | Restart laptop 3's node → green; within about **6 s** everything is **healthy**; Self-repair panel lists the copy | "No one told it what to fix. The elected holder copied the missing piece to laptop 3." | Badges healthy; repair event | Not healthy after 30 s → it's waiting for the next 10 s cycle; keep talking, then point at it |
| 3:15 | **8. Delta sync** | Append rows to the log and upload with the same name → "1 sent, N reused", about 1% sent | "Change 1%, send 1%: the same idea as our production app updates." | "Sent this upload" line | — |
| 3:40 | **9. Brand-new laptop** (laptop 2) | Stop laptop 2's node; start it again with `DATA_DIR=data/fresh NODE_ID=laptop-2-fresh` added; unlock with the team login → **"Restored N files"** → download one. Meanwhile laptop 1's Self-repair panel shows copies going **to laptop-2-fresh** | "This laptop has no files and no keys. A username and passphrase rebuild the keys, the peers return the signed file list, and the cluster refills the new laptop's storage on its own (about 19 s in our test)." | Banner; repair events; download opens | "Restored 0" → typo in the login; reload and paste it again |
| 4:30 | **Close** | Slides 12 (real laptops) → 15 (limits) → 16 | "Measured on real laptops. LAN today; DHT and NAT traversal next. Questions?" | — | — |

**After the demo:** restart laptop 2 with its normal command, without `DATA_DIR` and without `-fresh`.

## If judges ask

| Ask | Show |
|---|---|
| "Prove a corrupted piece is caught" | On laptop 1, flip one byte in a stored chunk of the log, then download: it still matches, because the bad copy is rejected and another laptop's copy is used. Restore the chunk afterwards. Exact steps are in test 7 of the self-test prompt. |
| "Where's the smart routing?" | Slides 6–7: tiered placement put **0%** of copies on a slow node (random: 21.7%), and ETA ranking + hedged reads were **11.6×** faster than a random holder. That's on a 4-node Docker cluster with a simulated 300 ms delay. With 3 laptops every chunk must be on all three, so placement has no choice to make; we say so. |
| "What if two laptops die?" | We tested it: every file still downloaded and was reported degraded. With one laptop left there's still a full copy of everything. |
| "Can an outsider join?" | A node started with the wrong cluster key never appears as a peer (tested on all 3 laptops). |

## Fallbacks

| Problem | Do this |
|---|---|
| Laptops can't reach each other | Switch to Docker on laptop 1 (`localhost:8001/ui/`); run the same steps with `docker compose stop node2` / `start node2`; say it's containers on one machine. |
| A laptop keeps dropping | It's sleeping or switching Wi-Fi: `caffeinate -i`; plug in power. |
| Dashboard won't load | `curl -s localhost:8000/stats \| python -m json.tool` on the projector, with a large terminal font. |
| Everything fails | Backup video, then `pytest` output and [RESULTS.md](RESULTS.md) Run 3. |

## Rehearsal checklist (run twice)

- [ ] Every step lands within its slot. Actual times: ______
- [ ] Detection seen: ____ s (target about 20 s). Rejoin heal: ____ s (target under 30 s). Fresh laptop refilled: ____ s.
- [ ] Laptop 2 restored to its normal node after step 9.
- [ ] The backup video is recorded from a clean run.
- [ ] Every speaker can answer the "If judges ask" table and their categories in [JUDGE_QA.md](JUDGE_QA.md).
