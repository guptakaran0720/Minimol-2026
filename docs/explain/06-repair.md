# 06 · Repair: getting back to 3 copies

**One line:** Every 10 s each node checks the chunks it holds; when a chunk has fewer than 3 live copies on distinct hosts, one deterministic leader among its holders copies it to a new peer, with no help from the uploader.

**Analogy:** Three neighbours each keep a spare key to the same house. When one moves away, the remaining two agree on who goes to cut a new key, using a rule they both know (say, alphabetical order), so they don't need to call each other. If the chosen one doesn't do it after a while, the other one does. Two new keys by accident is fine; zero is not.

## How it works

1. **Every 10 s, check every local chunk** ([repair.py:74](../../node/repair.py#L74), loop at [repair.py:138](../../node/repair.py#L138)). For each chunk, count the distinct *hosts* of its alive holders, including this node ([repair.py:58](../../node/repair.py#L58)). Holders come from the location map, which still lists a dead peer's last inventory, so the missing copy is visible.
2. **Healthy or waiting.** 3 or more live hosts → healthy, nothing to do ([repair.py:81](../../node/repair.py#L81)). If any holder is only `suspect`, we **wait** ([repair.py:85](../../node/repair.py#L85)). A suspect peer may come back, so repair starts only once it is dead, which takes 20 s of silence.
3. **Pick the leader.** Every holder computes the same order: live holders sorted by the rendezvous value `u(chunk, node)`, highest first ([routing.py:101](../../node/routing.py#L101)). `order[0]` is the leader and repairs in the first short round. The holder at rank *k* only acts once the chunk has been short for more than 2*k* rounds ([repair.py:90](../../node/repair.py#L90)). So if the leader is silently gone, the second holder takes over from round 3, the third from round 5.
4. **Copy carefully** ([repair.py:104](../../node/repair.py#L104)):
   - re-hash the local blob first; a corrupt local copy is never spread ([repair.py:109](../../node/repair.py#L109)),
   - pick targets with the same tiered placement used for uploads, excluding hosts that already have a copy ([repair.py:114](../../node/repair.py#L114)),
   - `HEAD` the target: if it already has the chunk (someone else repaired it), just record that ([repair.py:119](../../node/repair.py#L119)),
   - otherwise `PUT`, then `HEAD` again to confirm ([repair.py:123](../../node/repair.py#L123)),
   - a failure marks the target suspect and tries the next one ([repair.py:132](../../node/repair.py#L132)).
5. **Limit the load.** At most 4 repair copies run in parallel per node ([repair.py:40](../../node/repair.py#L40)).
6. **Report honestly.** If fewer than 3 hosts can be reached, the chunk is `degraded`. A file's status on the dashboard is `healthy` (every chunk on 3 live hosts), `degraded` (some chunk on fewer) or `unavailable` (some chunk on none) ([transfer.py:408](../../node/transfer.py#L408)). Repair events and counts appear in `/stats` and the dashboard's Repair panel ([api_user.py:248](../../node/api_user.py#L248)).

Manifests are stored like chunks, so they are repaired by exactly the same loop.

**Timing.** A killed node is marked dead after about 20 s. The next repair round on the leader comes within 0–10 s, and the uploader's location map learns about the new copy within another 0–10 s (inventory runs every 10 s). So the file shows healthy again **about 20–40 s** after the kill.

## Why this design

**Decision:** repair driven by the peers that hold the chunk, not by the uploader. See [ARCHITECTURE_DECISIONS.md §11](../ARCHITECTURE_DECISIONS.md#11-repair-driven-by-peers-not-by-the-uploader).

- **Strongest counter:** peers may see the network differently, so two nodes can both think they're the leader and both copy the chunk. And the leader itself may be dead without anyone having noticed.
- **Our defense:** chunks are content-addressed, so `PUT` is idempotent and a duplicate copy is harmless: the chunk ends up **over-replicated, never under-replicated**. A silent leader is covered by the takeover after 2 rounds. Waiting on `suspect` stops a flapping peer from causing a storm of copies.

**Why it can be peer-driven at all:** chunk locations are soft state learned from `/inventory`, not stored in the uploader's manifest ([§7](../ARCHITECTURE_DECISIONS.md#7-chunk-locations-are-soft-state-and-manifests-never-change)). Any holder knows enough to repair without the owner's keys, because it copies ciphertext as-is.

## Evidence

Tests in [tests/test_repair.py](../../tests/test_repair.py) (on in-memory fakes, one repair round at a time):

- [`test_kill_one_node_repairs_every_chunk_back_to_three_hosts`](../../tests/test_repair.py#L53)
- [`test_survives_two_sequential_failures_after_repair`](../../tests/test_repair.py#L65)
- [`test_only_leader_copies_in_first_round`](../../tests/test_repair.py#L78): exactly one copy per short object.
- [`test_racing_repairers_never_under_replicate`](../../tests/test_repair.py#L89): everyone acts at once; every chunk ends with 3 or 4 live hosts.
- [`test_suspect_holder_delays_repair`](../../tests/test_repair.py#L98)
- [`test_follower_takes_over_after_two_rounds_when_leader_is_silent`](../../tests/test_repair.py#L107): nothing in rounds 1–2, repaired in round 3.
- [`test_only_two_hosts_left_reports_degraded`](../../tests/test_repair.py#L127), [`test_corrupt_local_copy_is_not_spread`](../../tests/test_repair.py#L137).
- [tests/test_cluster.py::test_upload_kill_download_repair_recover](../../tests/test_cluster.py#L46) does it live: kill a holder, wait for dead, wait for healthy, then kill a second original holder and download again.

Measured:

- Docker cluster (4 containers on one laptop), kill node-2: marked dead at **21.4 s**, back to 3 copies at **21.4 s** in that run (the bench polls every 0.5 s and saw both at the same poll).
- Another run, 4 local processes on one laptop: **42.7 s** to healthy.
- Per-node dead detection: **19.5–20.6 s**.
- Manual `docker compose stop node3`: all **27** files went degraded and came back to healthy with no intervention.

We describe repair time as "about 20–40 s", because repair and inventory each run every 10 s. Caveat: one machine, so these prove correctness, not Wi-Fi performance. The multi-laptop run is still to do.

## Limits

- **Over-replication is not cleaned up.** When a dead node comes back, some chunks have 4 copies. Extra copies and old versions stay until garbage collection, which is (planned).
- A node only checks chunks **it holds**. If every holder of a chunk is gone, nobody can repair it; the file shows `unavailable`, never hidden.
- With only 2 live hosts, 3 copies on distinct hosts is impossible; the chunk stays `degraded` until a third host appears.
- No rebalancing onto newly joined nodes beyond normal repair.
- Repair trusts `HEAD`. A peer that says "I have it" but has deleted the chunk would fool it until a download hits that peer. Storage audits are (planned).
- No priority for the most at-risk chunks (1 copy before 2 copies).

## Judge questions

**Q: Who decides which node repairs a chunk, if there's no coordinator?**
A: Every holder computes the same ranking from the chunk ID and the holders' IDs, so they all agree on the leader without talking. If the leader doesn't fix it within 2 rounds, the next one in the ranking takes over.
*Follow-up:* "What if they disagree on who's alive?" → Then two might copy it. That's harmless: the PUT is idempotent and we end up with 4 copies, never fewer than 3.

**Q: Doesn't the uploader need to be online to repair its files?**
A: No. Holders copy the encrypted blob as it is, so they need no keys, and they learn locations from each other's inventories. The uploader can be switched off for the whole repair.
*Follow-up:* "So can holders read my file?" → No, they only ever hold ciphertext; the key is wrapped under the owner's passphrase-derived key.

**Q: Why not start repairing the moment a heartbeat is missed?**
A: A missed heartbeat on Wi-Fi is often just a blip. We wait until the peer has been silent for 20 s, and while it is only suspect, downloads route around it anyway.
*Follow-up:* "So what's the window of risk?" → About 20–40 s with one fewer copy, during which any one more failure is still survivable because 2 copies remain.
