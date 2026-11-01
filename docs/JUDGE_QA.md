# Judge Q&A: Minimol Storage

108 questions (6 in each of 18 categories, A to R), then the 20 hardest back-and-forth exchanges. Every answer describes what the code does today. Anything not built is marked **(planned)**. The design and its counter-arguments are in [ARCHITECTURE_DECISIONS.md](ARCHITECTURE_DECISIONS.md) (cited below as **AD §N**).

## How to use this

**Who answers what.** The owner answers first. If the owner gets stuck, P4 says "let's take that offline" or gives the **Admit** line, and nobody argues on stage.

| Owner | Covers | Categories |
|---|---|---|
| **P1** | Crypto and pipeline: chunking, zstd, AES-GCM, keys, manifests, owner index | D, E, F, most of J |
| **P2** | Network and node: discovery, HMAC auth, heartbeats, chunk store, quotas | C, K, failure detection in I |
| **P3** | Routing, transfer, repair, benchmarks | G, H, repair in I, L |
| **P4** | Pitch, business, comparisons, novelty, the hard counterquestions | A, N, P, Q; P4 routes R |

**The measured numbers, and where they come from.** Every number tagged **[D]** came from one run setup: Docker, 4 containers on **one laptop**, real encryption and compression, node-4 slowed by a **simulated** 300 ms delay, median of 5 repetitions (`bench/results/live-20261101-120658.md`). Say "one laptop, simulated delay" every time you quote one. The multi-laptop run has **not** been done yet.

| What | [D] result |
|---|---|
| 20 MB sensor CSV: encoded / original | 0.302 |
| 20 MB CSV: stored across 3 copies / original | 0.905 |
| 20 MB CSV: upload / download time | 2.32 s / 0.147 s |
| 5 MB random bytes: encoded / original | 1.000 |
| Delta sync, ~1% appended to the 20 MB CSV | 0.188 MB sent of 20.2 MB (1 chunk sent, 20 reused) |
| Share of copies placed on the slow node | tiered 0% vs random 21.7% |
| Download, ETA ordering vs random holder | 0.146 s vs 1.697 s (11.6×) |
| Kill a node: marked dead after | about 19.5–21.4 s |
| Kill a node: back to 3 copies | 21.4 s in one run, 42.7 s in another ("about 20–40 s") |
| Manual kill with 27 files stored | all 27 healed |
| Test suite | `pytest`: 166 passed, 1 skipped (the skipped one is `tests/test_cluster.py`, which needs a running cluster) |
| `tests/test_cluster.py` against live clusters | passed on the Docker cluster and on a local 4-process cluster |

**Five golden rules**

1. **Admit the limit in your first sentence**, then give the mitigation. A judge who has to dig for the weakness stops trusting everything else you say.
2. **Every claim gets a number or a test name.** Quote a number with its conditions ("one laptop, simulated delay, median of 5"). If there's no number, name the test. If there's neither, say "we haven't measured that."
3. **Never say "guaranteed", "fully decentralized", "unhackable" or "production-ready."** Say "survives any 2 holder losses *if*…", "no central server *in the data path*", "designed against…".
4. **Keep three tenses apart: measured, implemented, (planned).** Say "(planned)" out loud. Never describe a roadmap item in the present tense.
5. **Three sentences, then stop.** Let the judge ask the follow-up. Arithmetic beats adjectives: if you can show the calculation, do.

---

## A. Problem and differentiation

**Q1. What problem are you solving, in one sentence?** · *Owner: P4*
- **Answer:** A group of ordinary machines on one network pools its spare disk into encrypted, self-repairing storage, with no cloud account and no central server holding the data. Each file is compressed and encrypted on the uploader's machine, split into chunks, and every chunk is kept as 3 copies on 3 different machines.
- **Follow-up:** Who actually has this problem?
- **Response:** Teams that already have the machines but can't, or won't, put the data in a public cloud: a college lab, a field team on a hotspot, a small office. It also works when the internet is down, because everything runs on the local network.
- **Show:** Dashboard Upload panel (original vs "after compression + encryption" vs "stored across peers"); AD §0.
- **Admit:** We haven't interviewed users; the use cases are our assumption.

**Q2. Why would anyone use this instead of a USB drive or a NAS?** · *Owner: P4*
- **Answer:** A NAS is one box: if it dies, its data is gone or unreachable until restored. Here no single machine is special, and when one dies the others copy the missing chunks back to 3 copies on their own.
- **Follow-up:** A NAS with RAID survives a disk failure too.
- **Response:** RAID protects against a disk dying, not against the whole box being stolen, burnt or unplugged. We spread copies across separate machines, which is the failure RAID doesn't cover.
- **Show:** Demo: `docker compose stop node3`, then the Files panel goes degraded and comes back healthy; `test_kill_one_node_repairs_every_chunk_back_to_three_hosts`.
- **Admit:** A NAS is simpler and faster for one office; we win only when you don't want one box to be the single point of failure.

**Q3. What did the problem statement require, and what did you actually deliver?** · *Owner: P4*
- **Answer:** It asked for peer-to-peer storage with no central server, client-side compression, and smart routing; we added surviving a dead peer, because judges test that. All four are implemented and covered by `tests/test_cluster.py`, which uploads, kills a node, downloads, waits for repair, recovers on another node and kills a second node.
- **Follow-up:** Which requirement is weakest?
- **Response:** Smart routing with only 4 nodes, because each node holds 75% of chunks anyway. So we prove routing with two A/B tests instead of asserting it.
- **Show:** AD §0; bench Placement A/B and Retrieval A/B rows.
- **Admit:** "No central server" holds for the data path, but membership is closed by one shared cluster key.

**Q4. What's the single most impressive thing to watch in your demo?** · *Owner: P4*
- **Answer:** We kill a node that holds copies and the file still downloads with a matching SHA-256; then, with no command from us, the other nodes copy the missing chunks back to 3 copies. In the Docker run, that took about 20–40 s from the kill. **[D]**
- **Follow-up:** Isn't that just failover?
- **Response:** Failover is reading another copy, which we also do; repair is rebuilding the third copy so the *next* failure is also survivable. Demo step 6 kills a second original holder to show exactly that.
- **Show:** Self-repair panel ("copied chunk … → node-…" events); `test_survives_two_sequential_failures_after_repair`.
- **Admit:** The kill in the demo is a container on one laptop, not a laptop lid closing.

**Q5. Who is the user, and what do they see?** · *Owner: P4*
- **Answer:** Each person opens the dashboard on their own machine, unlocks it with a username and passphrase, and uploads files. The dashboard shows peers and their health, every file's status, a chunk map of which node holds each chunk, and a repair log.
- **Follow-up:** Can my teammate see my files?
- **Response:** No. Their node stores your chunks, but only as ciphertext, and your file list is encrypted under a key derived from your passphrase.
- **Show:** Dashboard panels: Unlock, Upload, Files, Chunk map, Peers, Self-repair.
- **Admit:** There's no sharing between users yet (planned).

**Q6. What do you NOT do?** · *Owner: P4*
- **Answer:** We don't traverse NAT over the internet, we don't share files between users, we don't delete or garbage-collect old data, and we don't prove storage cryptographically. All of those are on the roadmap and marked (planned).
- **Follow-up:** That's a lot of missing features.
- **Response:** We cut them deliberately to make the core loop solid: encrypt, place, survive a failure, repair, recover. Each cut is written down with its reason in the architecture doc.
- **Show:** AD §1, §7 "Known limits", §11 "Honest limits", §12 threat table.
- **Admit:** —

## B. Architecture and decentralization

**Q7. Draw the architecture in 30 seconds.** · *Owner: P2*
- **Answer:** Every node is the same Python program: a peer API for other nodes, a user API for the local user, a chunk store on disk, and background loops for heartbeats, inventory and repair. A file becomes 1 MiB chunks, each compressed and encrypted, and each chunk is stored on 3 different hosts chosen by rendezvous hashing. Downloads pick the holder with the lowest estimated fetch time.
- **Follow-up:** Where's the server?
- **Response:** There isn't one. The node you upload through is just the node on your own machine; any other node can recover your files from your passphrase.
- **Show:** AD "Final architecture" diagram; `node/main.py` starts the heartbeat, inventory, gossip and repair loops.
- **Admit:** —

**Q8. Is this fully decentralized?** · *Owner: P2*
- **Answer:** No central server stores data or tracks locations: every node learns where chunks live by asking every other node for its inventory. But membership is closed: you join only with the shared cluster key, and whoever hands that key out is effectively the admin.
- **Follow-up:** So it's permissioned.
- **Response:** Yes, deliberately: an open network invites Sybil attacks we can't defend in a hackathon. Per-node identities with mutual TLS are the better design (planned).
- **Show:** AD §7 (alternative A rejected), §12 Sybil row.
- **Admit:** "Fully decentralized" would be false. Say "no central server in the data path".

**Q9. What happens if the uploader's laptop disappears forever?** · *Owner: P3*
- **Answer:** Nothing is lost. The chunks, the encrypted manifests and the signed file list all live on the peers, and repair is run by whichever peers hold each chunk, not by the uploader. On any other node, the owner types the same username and passphrase and gets every file back.
- **Follow-up:** Show me.
- **Response:** `tests/test_cluster.py` step 7 recovers the file list on a different node with only username and passphrase and checks the SHA-256 of the download.
- **Show:** `test_upload_kill_download_repair_recover`; `test_fresh_device_recovers_and_downloads`; `test_recover_on_fresh_device_with_username_and_passphrase`.
- **Admit:** If the owner also forgets the passphrase, the data is gone for good.

**Q10. Which component is a single point of failure?** · *Owner: P2*
- **Answer:** No single node is: any node can serve chunks, repair and recover. The real single points are the shared cluster key, which is needed to join, and the owner's passphrase, which is needed to decrypt.
- **Follow-up:** What about the seed node?
- **Response:** A seed is only needed to *find* the cluster. Gossip and mDNS find everyone else, and you can list several seeds. In Docker every node seeds from node1, so start node1 first.
- **Show:** `test_gossip_finds_peers_of_peers`; `test_seed_becomes_peer_after_heartbeat`; `compose.yaml` `SEEDS`.
- **Admit:** In the Docker setup, a node that starts while node1 is down depends on mDNS to find the others.

**Q11. Why is location tracking soft state instead of a table you store?** · *Owner: P2*
- **Answer:** Every 10 s each node pulls `/inventory` from every live peer and rebuilds its own chunk-to-holders map in memory. That means no coordinator and no shared table to keep consistent, and manifests never have to be rewritten when chunks move.
- **Follow-up:** That's O(peers × chunks) every 10 s.
- **Response:** Correct, and it's fine for 4 to 10 nodes but not 1,000; DHT provider records are the scalable answer (planned).
- **Show:** AD §7; `test_location_map`; `test_inventory_once_keeps_unreachable_peer_entries`.
- **Admit:** The map can be up to one round (10 s) stale.

**Q12. Why does every node keep its own view rather than agreeing on one?** · *Owner: P3*
- **Answer:** Agreement needs consensus (Raft, Paxos), which is heavy and stalls during partitions. We designed every operation to be safe under disagreement instead: chunk PUTs are content-addressed and idempotent, so the worst a wrong view causes is an extra copy, not a lost one.
- **Follow-up:** Extra copies waste space.
- **Response:** Yes, a little, and we never delete them (GC planned). Over-replication is the safe direction to fail.
- **Show:** `test_racing_repairers_never_under_replicate` (after a racing repair every object has 3–4 live hosts).
- **Admit:** No garbage collection, so extra copies stay forever.

## C. Discovery and networking

**Q13. How does a new node find the cluster?** · *Owner: P2*
- **Answer:** Three ways: a typed seed list, `GET /peers` gossip every 5 s, and mDNS on the LAN, which is best-effort. A discovered address is only a candidate; it becomes a peer after an authenticated heartbeat succeeds.
- **Follow-up:** Why not mDNS alone?
- **Response:** Venue Wi-Fi often blocks multicast or isolates clients from each other, so seeds and gossip always work as the fallback. mDNS records carry a tag derived from the cluster key, so we don't probe other teams' nodes.
- **Show:** `test_seed_becomes_peer_after_heartbeat`; `test_gossip_finds_peers_of_peers`; `test_mdns_record_filtering`; AD §13.
- **Admit:** —

**Q14. Does it work across different networks, say two cities?** · *Owner: P2*
- **Answer:** Not by itself: we don't do NAT traversal. Nodes talk plain HTTP to IP addresses, so the same code should run over a mesh VPN such as Tailscale or ZeroTier, and in that case the VPN does the routing, not us.
- **Follow-up:** Have you tested that?
- **Response:** Not yet. We've run on Docker and as local processes on one laptop; the multi-laptop and VPN runs are still to do.
- **Show:** AD §1 (LAN-first, Kademlia DHT plus relays on the roadmap).
- **Admit:** Cross-network operation is untested. Say so before the judge asks.

**Q15. How do you know a peer is alive?** · *Owner: P2*
- **Answer:** Every node heartbeats every peer every 2 s with a signed `/health` call. A peer becomes suspect after 2 missed heartbeats or its first failed transfer, and dead after 20 s with no successful contact. A dead peer keeps being probed and comes back when it answers.
- **Follow-up:** Why such fixed numbers instead of phi-accrual?
- **Response:** For 4 nodes, fixed thresholds are easy to explain and tune; phi-accrual is better at scale. In the Docker run, a killed node was marked dead after about 19.5–21.4 s. **[D]**
- **Show:** `test_suspect_then_dead_then_back`; `test_failed_transfer_suspects_and_cools_down`; Peers panel "State" and "Last seen".
- **Admit:** A healthy `/health` reply doesn't prove the peer still has its chunks (AD §10).

**Q16. What's on the wire, and who can read it?** · *Owner: P2*
- **Answer:** Plain HTTP between nodes, with every request HMAC-signed with the cluster key and every response signed back. The chunk payloads are already AES-GCM ciphertext, so someone sniffing sees encrypted blobs, chunk IDs and traffic sizes.
- **Follow-up:** Why not TLS?
- **Response:** Time. The data is encrypted end to end anyway; TLS would hide metadata such as chunk IDs and sizes (planned).
- **Show:** AD §12 "Traffic sniffing: Partial"; `node/auth.py`.
- **Admit:** Metadata (which chunk IDs move between which nodes, and how big) is visible on the LAN.

**Q17. What if a node restarts with a new IP or a new ID?** · *Owner: P2*
- **Answer:** The node ID is saved in the data directory, so it normally survives restarts. If a node comes back at the same address with a different ID, the old entry is marked dead, and the new one joins after its first heartbeat.
- **Follow-up:** And the chunks it held?
- **Response:** They're still on its disk, and the next inventory pull lists them again under the node's ID.
- **Show:** `test_restarted_node_with_new_id_replaces_old`; `test_survives_restart_and_cleans_tmp`.
- **Admit:** —

**Q18. A closed laptop lid: does it stall every download?** · *Owner: P2*
- **Answer:** No. The connect timeout is 1 s, a failed transfer puts that peer at the back of the line for 15 s, and downloads try the other holders. Hedged reads also ask the next holder if a request runs past 2× its estimated time.
- **Follow-up:** And if the lid closes mid-transfer?
- **Response:** The read timeout is 5 s, but the hedge usually fires first. The test with a holder that stalls for 1 s finishes in under 0.6 s with hedging and takes over 1 s without it.
- **Show:** `test_hedged_read_beats_a_stalled_holder`; `test_without_hedging_a_stalled_holder_costs_the_full_stall`.
- **Admit:** Those timings come from in-process fakes, not Wi-Fi.

## D. Chunking and content addressing

**Q19. How is a file split up?** · *Owner: P1*
- **Answer:** Into fixed 1 MiB plaintext chunks, read one at a time so the whole file never sits in memory. Each chunk is compressed (kept only if it saves at least 3%), then encrypted with AES-256-GCM, and its ID is the SHA-256 of the encrypted blob.
- **Follow-up:** Why 1 MiB?
- **Response:** It's a balance: big enough that the 28 bytes of encryption overhead and the per-request cost are negligible, and small enough to spread across peers and to repair one chunk at a time. We didn't tune it; it's a reasonable default.
- **Show:** `node/pipeline.py`; `test_chunk_fields`; `test_short_reads_keep_fixed_chunk_boundaries`.
- **Admit:** Chunk size wasn't benchmarked against alternatives.

**Q20. Why hash the ciphertext, not the plaintext?** · *Owner: P1*
- **Answer:** A plaintext hash lets anyone confirm whether a known file is stored, which is the classic convergent-encryption leak. Hashing the ciphertext means a peer can verify integrity on every PUT without learning anything about the content.
- **Follow-up:** So you lose deduplication.
- **Response:** Across users, yes, on purpose. Within versions of one file we get it back through delta sync.
- **Show:** AD §4; `test_hash_mismatch_rejected` (a wrong-hash PUT gets 400); `test_no_equality_leak_across_files`.
- **Admit:** No cross-user deduplication.

**Q21. What stops a peer from returning the wrong bytes?** · *Owner: P1*
- **Answer:** Three checks in order: the blob must hash to its chunk ID, the GCM tag must verify, and after reassembly the whole file must match the SHA-256 stored in the encrypted manifest. A failed check skips that peer, penalises it, and tries the next holder.
- **Follow-up:** And if every holder returns garbage?
- **Response:** The download fails loudly with an error rather than serving wrong data. The file is only handed to the user after the whole-file hash matches.
- **Show:** `test_corrupt_holder_is_skipped_and_penalised`; `test_whole_file_hash_mismatch_raises`; `test_tampered_blob_rejected`.
- **Admit:** —

**Q22. Can a chunk be moved into a different file, or reordered?** · *Owner: P1*
- **Answer:** No. The file's UUID and the compressed flag are the AAD, so a chunk from another file fails the GCM tag. Order is fixed by the chunk list in the authenticated manifest, and the whole-file SHA-256 checks the result again.
- **Follow-up:** Who checks the manifest itself?
- **Response:** It's AES-GCM-encrypted under the owner's key, so any edit fails decryption, and it's validated for in-order indexes and consistent sizes.
- **Show:** `test_wrong_key_file_or_flag_rejected`; `test_chunk_order_and_sizes_checked`.
- **Admit:** —

**Q23. Empty files, and files that are an exact multiple of 1 MiB?** · *Owner: P1*
- **Answer:** An empty file has zero chunks, and a file that's an exact multiple of 1 MiB gets no empty trailing chunk. Both are tested at the pipeline and the transfer level.
- **Follow-up:** Why does that matter?
- **Response:** Off-by-one chunk bugs break delta sync and size checks; the manifest refuses sizes that don't add up.
- **Show:** `test_empty_file_has_no_chunks`; `test_exact_multiple_has_no_trailing_chunk`; `test_empty_file_and_exact_multiple`.
- **Admit:** —

**Q24. Fixed-size chunks break when someone inserts a byte at the start. Why not content-defined chunking?** · *Owner: P1*
- **Answer:** You're right: an insertion shifts every later chunk, so delta sync then resends nearly everything. Fixed chunks still handle appends and in-place edits, which covers logs, CSVs and datasets.
- **Follow-up:** So delta sync is weak.
- **Response:** It's narrow, and we say so. FastCDC content-defined chunking is the fix (planned).
- **Show:** AD §14 Counter 3; `test_append_changes_only_the_tail`; `test_delta_sync_in_place_edit_and_shrink`.
- **Admit:** Insertions near the start defeat delta sync.

## E. Compression and performance

**Q25. How much does compression actually save?** · *Owner: P1*
- **Answer:** On a 20 MB sensor-log CSV, the encoded size was 0.302 of the original, including encryption overhead. On 5 MB of random bytes it was 1.000, because the pipeline stores chunks that don't compress raw. **[D]**
- **Follow-up:** CSV is the best case.
- **Response:** Yes, and we show the worst case right next to it. JPEGs, ZIPs and video behave like the random row.
- **Show:** Bench "Files" table (csv and random rows); Upload panel "After compression + encryption".
- **Admit:** We didn't benchmark a real mixed corpus.

**Q26. Why compress each chunk separately rather than the whole file?** · *Owner: P1*
- **Answer:** Per-chunk compression keeps memory at one chunk, gives each chunk its own integrity check, caps decompression at 1 MiB per chunk, and decides compress-or-not per chunk, so a mixed file is handled correctly. The cost is a slightly worse ratio, because zstd can't look across chunk boundaries.
- **Follow-up:** How much worse?
- **Response:** `measure_compression` in `node/pipeline.py` reports both modes for any file. We haven't put that comparison on a slide; run `python -m node.pipeline FILE` if asked.
- **Show:** `test_measure_compression`; `test_mixed_file_decided_per_chunk`; AD §3.
- **Admit:** The per-chunk vs whole-file numbers aren't in the results yet.

**Q27. How do you stop a decompression bomb?** · *Owner: P1*
- **Answer:** Before decompressing we read the size the zstd frame declares and reject anything over 1 MiB or with no declared size, then decompress with a 1 MiB cap and check the output size matches. We had to add the declared-size check because python-zstandard ignores the output cap when the frame states its size.
- **Follow-up:** Couldn't an attacker just lie in the header?
- **Response:** The output must match the declared size exactly, and the chunk must also pass the GCM tag under the owner's key, which an attacker doesn't have.
- **Show:** `test_decompression_bomb_rejected`; `test_frame_without_content_size_rejected`.
- **Admit:** —

**Q28. Is Python fast enough?** · *Owner: P1*
- **Answer:** zstd, AES and SHA-256 all run in C underneath, so the bottleneck is the network, not Python. In the Docker run a 20 MB CSV uploaded in 2.32 s, which includes compressing, encrypting and writing 3 copies, and downloaded in 0.147 s. **[D]**
- **Follow-up:** That's a virtual network on one laptop.
- **Response:** Exactly, so it's an upper bound for the software; Wi-Fi will be slower, and we'll measure it on the multi-laptop run.
- **Show:** Bench "Files" table; DOCKER.md "What Docker does not prove".
- **Admit:** No Wi-Fi throughput numbers yet.

**Q29. Why zstd level 3 and the 3% threshold?** · *Owner: P1*
- **Answer:** Level 3 is zstd's default speed/ratio balance. The 3% threshold avoids paying decompression for chunks that barely shrink, which is how already-compressed chunks get stored raw.
- **Follow-up:** Did you tune them?
- **Response:** No, they're sensible defaults, not optimised values.
- **Show:** `test_compression_kept_only_if_it_saves_3_percent`; `test_random_data_stored_raw`.
- **Admit:** Not tuned.

**Q30. Where does upload time actually go?** · *Owner: P3*
- **Answer:** Each chunk is encoded in a worker thread, then PUT to 3 peers in parallel, with at most 4 chunks in flight, so memory stays bounded. Writes are fsynced and renamed into place on every peer, which costs time but means a crash never leaves a half-written chunk under a valid ID.
- **Follow-up:** Have you profiled it?
- **Response:** No. We measured end to end only.
- **Show:** `test_upload_keeps_at_most_parallel_chunks_in_flight`; `node/chunkstore.py` `_atomic_write`.
- **Admit:** No profile breakdown.

## F. Encryption and key management

**Q31. Walk me through the keys.** · *Owner: P1*
- **Answer:** scrypt turns your passphrase plus a salt derived from your username into a master secret. HKDF splits that into a key-encryption key and an Ed25519 signing key. Each file gets a random 256-bit data key, which is stored wrapped by the key-encryption key inside the file's encrypted manifest.
- **Follow-up:** Why derive the salt from the username?
- **Response:** A fresh laptop has no stored salt file, and the username keeps two users with the same passphrase from getting the same keys.
- **Show:** `node/keys.py`; `test_same_inputs_same_keys`; `test_username_separates_users`.
- **Admit:** The salt is predictable per username, so an attacker can precompute guesses for one specific username.

**Q32. I get a new laptop. How do I get my files back?** · *Owner: P1*
- **Answer:** Start a node, open the dashboard, and enter username and passphrase. The node re-derives the same keys, asks every peer for your signed file list, keeps the highest valid version, and opens the manifests; nothing needs to be copied from the old laptop.
- **Follow-up:** And if I forget the passphrase?
- **Response:** Then nobody can recover it, us included; that's the price of end-to-end encryption. Recovery codes or splitting the key across trusted devices would help (planned).
- **Show:** `test_fresh_device_recovers_and_downloads`; `test_upload_recover_on_fresh_laptop_and_delta_sync`; `test_cluster.py` step 7.
- **Admit:** A forgotten passphrase means total loss. Changing the passphrase isn't supported either (planned).

**Q33. Can a peer read my files?** · *Owner: P1*
- **Answer:** No. Peers hold only AES-256-GCM ciphertext, the manifests are encrypted under your key-encryption key, and your file list is encrypted too. A peer sees chunk sizes, chunk IDs and when you upload.
- **Follow-up:** What can it infer?
- **Response:** Roughly how big your files are, and, across versions of the same file, which chunks didn't change. It can't link chunks across different files or users.
- **Show:** `test_blob_hides_contents`; `test_no_equality_leak_across_files`; AD §14 Counter 2.
- **Admit:** Sizes, timing and within-file version equality leak.

**Q34. Deterministic nonces with AES-GCM? That's a known footgun.** · *Owner: P1*
- **Answer:** GCM breaks when one key and one nonce encrypt two *different* plaintexts. Our nonce is an HMAC of the plaintext under a secret key, so the same nonce means the same plaintext and the same ciphertext. That's the synthetic-IV idea behind SIV mode (RFC 5297).
- **Follow-up:** And if two different chunks collide in the 96-bit nonce?
- **Response:** By the birthday bound that's about n²/2⁹⁷; even with 2²⁴ chunks under one file key, that's about 2⁻⁴⁹, which we round to "about 2⁻⁴⁸".
- **Show:** `test_deterministic_for_delta_sync`; `test_nonce_must_match_plaintext`; AD §14.
- **Admit:** It's a construction, not a standard mode; AES-GCM-SIV (RFC 8452) would be the off-the-shelf choice (planned).

**Q35. How hard is it to brute-force a passphrase?** · *Owner: P1*
- **Answer:** Passphrases must be at least 12 characters, and scrypt runs with N = 2¹⁷ and r = 8, which needs 128 MiB of RAM per guess. To get anything to test guesses against, an attacker also needs the cluster key, because only members can fetch the index.
- **Follow-up:** With the cluster key, they can guess offline.
- **Response:** Yes. A weak passphrase is the weakest link, and the scrypt cost only slows them down.
- **Show:** `test_production_scrypt_cost_is_used_by_default`; `test_short_passphrase_rejected`.
- **Admit:** We don't check passphrase strength beyond the length; we haven't timed scrypt on our laptops.

**Q36. Who can forge or roll back my file list?** · *Owner: P1*
- **Answer:** The file list is signed with your Ed25519 key, and every peer checks the signature on every PUT and keeps only the highest version. During recovery we ask every peer and take the highest version that verifies.
- **Follow-up:** A peer can still give you an old version.
- **Response:** Yes, but it has to fool every reachable peer. If one honest peer has the newest version, we use it.
- **Show:** `test_rollback_defence_picks_highest_valid`; `test_version_cannot_be_raised_by_a_peer`; `test_tampered_record_rejected`; `test_recover_ignores_forged_index_wrong_passphrase_and_other_user`.
- **Admit:** Rollback is reduced, not prevented (AD §12).

## G. Replication and fault tolerance

**Q37. Does R = 3 guarantee availability?** · *Owner: P3*
- **Answer:** No. It means each chunk survives the loss of any 2 of its holders, *if* all 3 copies landed on different hosts, there's no silent corruption, and you still have your passphrase. And availability right now also needs at least one holder to be reachable.
- **Follow-up:** So what does it give you?
- **Response:** Tolerance of 2 simultaneous holder losses, plus repair to get back to 3 before the next one.
- **Show:** AD §6 "What R = 3 actually guarantees"; `test_download_survives_two_dead_hosts_with_r3`.
- **Admit:** Never say "guaranteed".

**Q38. Why full replication instead of erasure coding?** · *Owner: P3*
- **Answer:** With 4 nodes, erasure coding has nowhere to rebuild: in a 2-of-4 scheme every node holds a piece, so after one death there's no fifth machine. Replication repairs with one download and is simple to verify. Erasure coding with zfec is on the roadmap for 8 or more nodes (planned).
- **Follow-up:** It costs 3× storage.
- **Response:** 3× the *compressed* size: on the CSV, 3 copies took 0.905 of the original size. **[D]** On incompressible data it really is 3.0×.
- **Show:** Bench "Files" table, "Stored/original" column; AD §6.
- **Admit:** For photos and video, replication costs about twice what erasure coding would.

**Q39. What if all three replicas are lost?** · *Owner: P3*
- **Answer:** That chunk is gone, and its file shows as **unavailable** on the dashboard, never hidden or partly served. A download fails with an error rather than returning a broken file.
- **Follow-up:** Can you recover anything?
- **Response:** Other files are unaffected, and the rest of that file's chunks still exist, but we don't serve partial files.
- **Show:** `test_all_holders_gone_is_unavailable`; `test_unavailable_and_unknown_files`; Files panel status badge.
- **Admit:** No off-site backup; three simultaneous losses before repair finishes lose data.

**Q40. How do you make sure two copies don't end up on the same machine?** · *Owner: P3*
- **Answer:** Every node reports a `host_id`, its failure domain. Placement never picks two peers with the same `host_id`, and repair counts copies per host, not per node.
- **Follow-up:** What if I run two nodes on one laptop?
- **Response:** Give them the same `host_id`, and they count as one failure domain.
- **Show:** `test_placement_never_returns_two_nodes_on_one_host`; `test_round_trip_three_distinct_hosts`; Chunk map "live hosts n/3".
- **Admit:** `host_id` is self-reported, so a dishonest member can lie about it (see Q63).

**Q41. Durability or retrieval: which one does each mechanism give you?** · *Owner: P3*
- **Answer:** Retrieval (availability) is about getting the file *now*: ETA ordering, hedged reads and falling back to other holders. Durability is about the data still existing after *future* failures: 3 copies on distinct hosts, plus repair. Demo step 6 kills a second original holder after repair, to show durability rather than a lucky read.
- **Follow-up:** Which one do you measure?
- **Response:** Retrieval: download times and the 11.6× ETA result **[D]**. Durability: repair back to 3 copies in about 20–40 s **[D]** and the test that survives two sequential failures.
- **Show:** `test_survives_two_sequential_failures_after_repair`; `test_cluster.py` step 8.
- **Admit:** We have no long-term durability numbers (bit rot, weeks of churn).

**Q42. What happens if the upload can't reach 3 hosts?** · *Owner: P3*
- **Answer:** The upload still succeeds and is reported as **degraded**, not durable, with the actual holders per chunk. If no peer accepts a chunk at all, the upload fails with 503.
- **Follow-up:** Does it fix itself later?
- **Response:** Yes, once a third host appears, the repair loop tops the chunk up to 3.
- **Show:** `test_upload_with_two_hosts_is_degraded_not_failed`; `test_upload_with_no_peers_raises`; `test_upload_with_no_live_peers_is_503`.
- **Admit:** —

## H. Routing and placement

**Q43. What does rendezvous hashing give you over round-robin?** · *Owner: P3*
- **Answer:** Every node computes the same ranking from just the chunk ID and the peer list, so there's no placement table to store or agree on. When a peer leaves, only chunks it held are affected, and removing a peer that wasn't in a chunk's top 3 changes nothing. Round-robin needs shared state and reshuffles on every join or leave.
- **Follow-up:** You never rebalance, so who cares about movement?
- **Response:** Fair point. Today the win is stateless agreement: repair targets and the repair leader come from the same ranking on every node. Rebalancing on join is (planned).
- **Show:** `test_placement_is_deterministic`; `test_removing_a_non_winner_does_not_move_chunks`; AD §8.
- **Admit:** No rebalancing when a node joins.

**Q44. What's the formula, and why is it right?** · *Owner: P3*
- **Answer:** For each peer, u = SHA-256(chunk ID, node ID) mapped strictly into (0, 1), and the key is −w / ln(u). Because −ln(u) is exponentially distributed, peer i ranks first with probability wᵢ / Σw.
- **Follow-up:** Prove it works.
- **Response:** In the test, weights 1 and 3 over 4,000 chunks give the heavy peer about 75% of first choices, within 4 points.
- **Show:** `test_weight_controls_first_choice_share`; `test_hrw_u_is_strictly_inside_unit_interval`.
- **Admit:** All demo nodes have weight 1, so weights aren't visible in the demo.

**Q45. Prove routing helps.** · *Owner: P3*
- **Answer:** Two A/B tests on the same cluster, with node-4 delayed 300 ms (simulated). Placement: tiered placement put 0% of copies on the slow node, random put 21.7%. Retrieval: with the file placed randomly so the slow node held copies, ETA ordering downloaded in 0.146 s versus 1.697 s for a random holder, 11.6× faster. **[D]**
- **Follow-up:** The delay is fake.
- **Response:** Yes, and we say so on stage. It shows the mechanism routes around a slow peer; the size of the gain depends on how slow the peer really is.
- **Show:** Bench "Placement A/B" and "Retrieval A/B" rows; `bench/bench.py`.
- **Admit:** One laptop, simulated delay, and the ETA arm includes hedged reads (see exchange 6).

**Q46. How do you rank holders for a download?** · *Owner: P3*
- **Answer:** By estimated fetch time: rtt + chunk size / bandwidth, both exponentially weighted averages from real transfers, with α = 0.3. It's in seconds, so there are no arbitrary weights. Alive peers go before suspect ones, and a peer that just failed waits 15 s at the back.
- **Follow-up:** A brand-new peer has no history.
- **Response:** It starts at the median of the peers that do have history.
- **Show:** `test_retrieval_prefers_lower_eta`; `test_retrieval_new_peer_gets_median_prior`; `test_retrieval_cooldown_and_suspect_go_last_dead_dropped`.
- **Admit:** —

**Q47. Why not put live scores into placement too?** · *Owner: P3*
- **Answer:** Live scores change every few seconds, so a chunk's best 3 peers would keep changing and repair would shuffle copies back and forth. Placement uses fixed weights plus one hysteresis-protected signal: a peer goes to the slow tier only after its ETA stays above 3× the cluster median for 30 s, and comes back after 30 s at or below it.
- **Follow-up:** Then how does a slow peer ever leave the slow tier?
- **Response:** It gets no traffic, so every 10 s each node fetches one chunk from it as a fresh measurement.
- **Show:** `test_slow_peer_moves_to_tier_2_and_back`; `test_slow_peer_is_probed_and_recovers`; Peers panel "slow tier" tag.
- **Admit:** —

**Q48. With 4 nodes and 3 copies, every node holds 75% of chunks. Isn't smart placement invisible?** · *Owner: P3*
- **Answer:** For healthy nodes, yes: 3 of 4 means each holds 75% whatever we do. That's why the visible effect is the slow tier: the slow node gets no new chunks while 3 healthy hosts exist, and it's used only as a fallback.
- **Follow-up:** So weights don't matter here.
- **Response:** Not at 4 nodes; they matter once you have more nodes than copies.
- **Show:** `test_slow_tier_never_chosen_while_three_healthy_hosts_exist`; `test_slow_tier_used_as_fallback`; Placement A/B row (0% vs 21.7%) **[D]**.
- **Admit:** At 4 nodes the "smart" part of placement is almost entirely the tiering.

## I. Failure detection and self-repair

**Q49. Walk me through repair after a node dies.** · *Owner: P3*
- **Answer:** Every 10 s each node checks the chunks it holds and counts live distinct hosts. If a chunk has fewer than 3, the holder that ranks first by rendezvous hash becomes its leader. The leader HEADs the best eligible peer to confirm it's missing the chunk, PUTs the chunk, then HEADs again to verify. In the Docker run that got everything back to 3 copies in about 20–40 s after the kill. **[D]**
- **Follow-up:** Why not repair immediately?
- **Response:** A suspect peer may just be a flaky Wi-Fi link; repair waits until it's dead (20 s) so we don't trigger a storm of copies.
- **Show:** `test_kill_one_node_repairs_every_chunk_back_to_three_hosts`; `test_suspect_holder_delays_repair`; Self-repair panel.
- **Admit:** During those 20–40 s the chunk has only 2 copies.

**Q50. Two peers try to repair the same chunk. What happens?** · *Owner: P3*
- **Answer:** Normally it doesn't happen: every holder computes the same leader, and only the leader acts in the first round. If views differ and two act anyway, PUT is content-addressed and idempotent, and each one HEADs first, so the worst case is a 4th copy, never fewer than 3.
- **Follow-up:** Show it.
- **Response:** The racing test makes every holder act at once, then checks that every object has 3–4 live hosts.
- **Show:** `test_only_leader_copies_in_first_round`; `test_racing_repairers_never_under_replicate`.
- **Admit:** Extra copies aren't cleaned up (GC planned).

**Q51. The repair source dies mid-repair. Now what?** · *Owner: P3*
- **Answer:** A half-sent chunk can't be stored: the receiver checks the hash before writing, and writes go to a temp file that is renamed into place only when complete. The leader then goes suspect, so the others wait; once it's dead, the remaining holders recompute the leader and the new one copies.
- **Follow-up:** What if the leader is alive but silently not repairing?
- **Response:** The holder ranked k takes over after 2k short rounds, so the second holder acts in round 3.
- **Show:** `test_follower_takes_over_after_two_rounds_when_leader_is_silent`; `test_hash_mismatch_rejected`; `test_survives_restart_and_cleans_tmp`.
- **Admit:** If the leader dies mid-repair, the chunk waits about 20 s longer.

**Q52. What if the network partitions?** · *Owner: P2*
- **Answer:** Each side marks the other dead after 20 s. A side with 3 or more hosts repairs back to 3 copies; a smaller side can't and shows chunks as degraded. Nothing is deleted, so when the partition heals there are just extra copies.
- **Follow-up:** And if someone uploads on both sides?
- **Response:** The chunks are fine, because different content gets different IDs. But both sides may publish the same file-list version, and peers keep the first one they saw, so one side's update can be lost.
- **Show:** AD §7 "Known limits"; `test_only_two_hosts_left_reports_degraded`.
- **Admit:** No partition-tolerant merge of the file list (CRDT planned).

**Q53. Different nodes see the network differently. Is that a problem?** · *Owner: P3*
- **Answer:** Every node has its own peer table and location map, and they can disagree for up to one round. Every action is safe under disagreement: placement and repair over-replicate rather than lose a copy, and a download that finds a stale location asks every other live peer before giving up.
- **Follow-up:** Can a stale view cause a false "unavailable"?
- **Response:** The dashboard status can lag for a round, but the download path still asks everyone.
- **Show:** `test_stale_location_map_falls_back_to_asking_everyone`; `test_inventory_once_keeps_unreachable_peer_entries`.
- **Admit:** Dashboard status can be about 10 s stale.

**Q54. Can repair spread a corrupted copy?** · *Owner: P3*
- **Answer:** No. Before copying, the leader re-hashes its own copy, and if it doesn't match the chunk ID it logs it and doesn't spread it. Receivers also re-check the hash on every PUT.
- **Follow-up:** Do you scrub for bit rot in the background?
- **Response:** No. Corruption is caught when a chunk is read or repaired, not proactively (planned).
- **Show:** `test_corrupt_local_copy_is_not_spread`; Self-repair panel "failed its hash check; not spread" event.
- **Admit:** A silently corrupted copy still counts toward the 3 until someone reads it.

## J. Metadata consistency and recovery

**Q55. Who owns the manifest?** · *Owner: P1*
- **Answer:** The file's owner. It's encrypted under the owner's passphrase-derived key-encryption key and stored on peers like a chunk, with 3 copies, content-addressed and immutable. Peers hold it and repair it, but they can't read or change it.
- **Follow-up:** How do you find a manifest?
- **Response:** Through the owner index: your signed, encrypted list of manifest IDs, one per file, stored on every live peer under your public key.
- **Show:** `node/manifest.py`; `test_blob_hides_contents`; `test_wrong_kek_and_tampering_rejected`; `test_fresh_laptop_reads_index`.
- **Admit:** —

**Q56. Why are manifests immutable?** · *Owner: P1*
- **Answer:** Chunk locations are learned from inventories, not written into the manifest, so a manifest never needs to change after upload. A new version writes a new manifest, and the index points to the latest one. That removes the lost-update race between repair and upload.
- **Follow-up:** What happens to old versions?
- **Response:** They stay on peers until garbage collection, which is (planned).
- **Show:** `test_index_keeps_one_manifest_per_file`; AD §7.
- **Admit:** No old-version cleanup.

**Q57. How do you delete a file globally?** · *Owner: P3*
- **Answer:** You can't today. There's no DELETE route on peers, on purpose, so a stolen cluster key can't wipe data. A user-level delete would remove the file from the owner index and let garbage collection reclaim unreferenced chunks (planned).
- **Follow-up:** That fails GDPR-style "right to erasure".
- **Response:** Agreed. The ciphertext without your keys is unreadable, but that isn't erasure.
- **Show:** `node/api_peer.py` ("There is no DELETE route"); AD §12.
- **Admit:** No delete at all, not even from your own file list.

**Q58. Two of my devices upload at the same time. What happens?** · *Owner: P1*
- **Answer:** The chunks and manifests are safe because they're content-addressed. The file list is the weak spot: both devices may publish the same version number, peers keep the first, and the other device's new file may not appear when you recover elsewhere.
- **Follow-up:** Does the user get told?
- **Response:** Not today: the upload reports success even if peers rejected the list update. A CRDT merge of the index is (planned).
- **Show:** AD §7 "Only one device should write the index at a time"; `test_index_store_keeps_highest_version`.
- **Admit:** This is a real lost-update risk with concurrent writers.

**Q59. What metadata is stored where?** · *Owner: P1*
- **Answer:** Peers hold chunks (ciphertext), manifests (encrypted name, size, plaintext hash, wrapped data key, chunk list) and the signed, encrypted owner index. Your own node also keeps a local catalog cache so the dashboard is fast; the index on peers is the durable copy.
- **Follow-up:** Is that local cache encrypted?
- **Response:** No. It's plain JSON on your own machine with names, sizes and hashes; peers never see it.
- **Show:** `node/transfer.py` `_save_catalog`; `test_catalog_persists_to_disk`.
- **Admit:** The local catalog cache is unencrypted on the user's disk.

**Q60. How does recovery pick the right file list if peers disagree?** · *Owner: P1*
- **Answer:** It asks every alive peer, throws away anything that fails the Ed25519 signature check or belongs to another owner, and keeps the highest version. Then it decrypts that list and fetches each manifest.
- **Follow-up:** And if the peers with the newest version are offline?
- **Response:** You get an older list until they're back.
- **Show:** `test_rollback_defence_picks_highest_valid`; `test_recover_ignores_forged_index_wrong_passphrase_and_other_user`.
- **Admit:** Possible stale recovery if the newest holders are all down.

## K. Security and malicious peers

**Q61. How do you know a peer really stores a chunk?** · *Owner: P2*
- **Answer:** Today: a successful PUT returns a signed response from that exact node, repair HEADs again after copying, and every download re-hashes what comes back. We don't have a cryptographic proof-of-storage challenge yet; a `POST /audit` challenge is (planned).
- **Follow-up:** So a peer could delete chunks and keep listing them?
- **Response:** Yes, until someone reads that chunk. Then the download falls back to another holder.
- **Show:** `test_unsigned_or_impostor_responses_rejected`; `node/repair.py` HEAD-PUT-HEAD; AD §12 threat table.
- **Admit:** A lying peer can quietly reduce a chunk to 2 real copies. Random spot checks are listed as MVP in AD §12, but the code only spot-checks slow-tier peers.

**Q62. What if a peer lies about its free space?** · *Owner: P2*
- **Answer:** Free space is only used to decide who's eligible; a copy counts only after the PUT succeeds with a signed reply. If the liar rejects the PUT with "quota full", it goes suspect, waits 15 s at the back, and the next-ranked peer gets the copy.
- **Follow-up:** And if it accepts and then drops the data?
- **Response:** That's the proof-of-storage gap: we find out on the next read, not before.
- **Show:** `test_full_peer_is_skipped_for_next_ranked`; `test_quota`; `test_failed_transfer_suspects_and_cools_down`.
- **Admit:** Self-reported free space isn't verified.

**Q63. What about a Sybil attack?** · *Owner: P2*
- **Answer:** Membership is closed: every request needs an HMAC with the cluster key, so an outsider can't add fake nodes. An insider with the key could run many node IDs and claim different `host_id`s, which would defeat our distinct-host rule.
- **Follow-up:** How bad would that be?
- **Response:** With 4 honest nodes and 4 fake ones, the chance a chunk's top 3 are all fake is C(4,3)/C(8,3) = 4/56, about 7%.
- **Show:** AD §12 "Sybil: closed membership (not open-network safe)"; `test_hmac_rejection`.
- **Admit:** Not safe on an open network; per-node identities are (planned).

**Q64. Can someone on the Wi-Fi download my files?** · *Owner: P2*
- **Answer:** The user API that serves plaintext only answers requests from the machine itself; every other address gets 403. The peer API requires the cluster HMAC and only ever returns ciphertext. Without your passphrase, the ciphertext and manifests are useless.
- **Follow-up:** What about other users on the same machine?
- **Response:** Once unlocked, any local process can call the user API; there's no session token.
- **Show:** `test_rejects_requests_from_other_machines`; `test_user_api_rejects_non_local_clients`; `test_hmac_rejection`.
- **Admit:** No per-session auth on localhost.

**Q65. Can a stranger impersonate a peer?** · *Owner: P2*
- **Answer:** No. Requests are signed over method, path, node ID, timestamp and body hash, and accepted only within ±30 s. Responses are signed back and bound to the request's signature, so a stranger can't fake a `/health` or an "I have it" reply.
- **Follow-up:** Replay within 30 s?
- **Response:** Possible for requests, and we accept that: the replayable ones are idempotent PUTs and reads of ciphertext. A replayed *response* is rejected.
- **Show:** `test_any_change_rejected`; `test_timestamp_window`; `test_replayed_response_rejected`; `test_unsigned_or_impostor_responses_rejected`.
- **Admit:** Request replay within 30 s is acknowledged in AD §12.

**Q66. One laptop gets stolen. What's exposed?** · *Owner: P2*
- **Answer:** The thief gets the cluster key, so they can join the cluster and fetch ciphertext. They don't get your files without your passphrase: keys exist only in memory while unlocked. They can also read that laptop's unencrypted local catalog (names, sizes, hashes).
- **Follow-up:** How do you revoke them?
- **Response:** Rotate the cluster key on every node; there's no per-node revocation yet (planned, with per-node certificates).
- **Show:** AD §12 "One leaked laptop exposes the shared key".
- **Admit:** One leaked key compromises membership for everyone.

## L. Testing and benchmarks

**Q67. What's your strongest evidence that it's correct?** · *Owner: P3*
- **Answer:** `tests/test_cluster.py` runs against a real cluster: upload, check 3 distinct hosts, kill a holder, download with matching SHA-256, wait for repair, recover on another node from passphrase, kill a second original holder, download again. It passed on the Docker cluster and on a local 4-process cluster, and the full suite is 166 passed, 1 skipped.
- **Follow-up:** Tests you wrote yourselves.
- **Response:** True. That's why every download also checks the whole-file SHA-256 at runtime, so a bug shows up as an error rather than silently wrong data.
- **Show:** `test_upload_kill_download_repair_recover`; `pytest -q` output; `scripts/docker_e2e.sh`.
- **Admit:** No independent audit, no fuzzing.

**Q68. Are these machines actually independent?** · *Owner: P3*
- **Answer:** Not yet. Our numbers come from 4 Docker containers on one laptop, each with its own data directory, `host_id` and network address, but sharing one kernel, one disk and one power supply. The multi-laptop run is still to do.
- **Follow-up:** So your failure tests are fake?
- **Response:** The failure is real for our software, since the process is gone and its port is closed. It doesn't prove anything about hardware failures or Wi-Fi.
- **Show:** DOCKER.md "What Docker does not prove".
- **Admit:** One laptop.

**Q69. How did you measure, and can I reproduce it?** · *Owner: P3*
- **Answer:** `bench/bench.py` drives the cluster through its public API, runs every timed step 5 times and reports median, min and max. It writes JSON and Markdown into `bench/results/`, and `scripts/docker_e2e.sh` reproduces the whole thing from a fresh cluster.
- **Follow-up:** Do you have a simulated mode?
- **Response:** Yes, `--sim`, but only to check the script works; we never present its timings.
- **Show:** `bench/results/live-20261101-120658.md`; `test_simulated_bench_runs_end_to_end`.
- **Admit:** 5 repetitions on one machine is a small sample.

**Q70. How do you test failure handling without a real cluster?** · *Owner: P3*
- **Answer:** `tests/fakes.py` provides an in-memory peer table, client and location map, so tests can kill nodes, mark them suspect, corrupt copies or stall replies on demand. Routing and repair were built against those fakes first, then swapped onto the real classes.
- **Follow-up:** Fakes can hide bugs.
- **Response:** That's why the cluster test also runs on real processes and Docker.
- **Show:** `tests/fakes.py`; `test_only_two_hosts_left_reports_degraded`; `test_corrupt_holder_is_skipped_and_penalised`.
- **Admit:** —

**Q71. How fast is self-repair, and why did your two runs differ so much?** · *Owner: P3*
- **Answer:** Detection took about 19.5–21.4 s, and getting back to 3 copies took 21.4 s in one run and 42.7 s in another. **[D]** Repair runs every 10 s and locations refresh every 10 s, so after the 20 s detection, it can take 0 to about 20 s more depending on where those loops are.
- **Follow-up:** 21.4 s for both detection and repair in one run?
- **Response:** The bench polls one node every 0.5 s and checks repair only after that node reports the death. The likely explanation is that another node noticed the death first and had already repaired by then; we haven't confirmed it from logs.
- **Show:** Bench "Kill a node and repair" block; DOCKER.md "Break it and watch it heal".
- **Admit:** Only two timed runs.

**Q72. Which test would you show a skeptic first?** · *Owner: P3*
- **Answer:** `test_racing_repairers_never_under_replicate`: it forces every holder to repair at once, which is the worst case for our no-consensus design, and checks no object ends with fewer than 3 hosts. Second, `test_rollback_defence_picks_highest_valid` for the metadata side.
- **Follow-up:** And for crypto?
- **Response:** `test_tampered_blob_rejected` and `test_decompression_bomb_rejected`.
- **Show:** Those tests in `tests/test_repair.py`, `tests/test_index.py`, `tests/test_pipeline.py`.
- **Admit:** —

## M. Scalability and production readiness

**Q73. What fails first at 1,000 peers?** · *Owner: P2*
- **Answer:** The all-to-all loops. Every node heartbeats every other node every 2 s, which is about 500 requests per second per node. Every node also pulls every other node's full inventory every 10 s; at 10,000 chunks each, that's about 640 KB × 999 ≈ 640 MB per node every 10 s.
- **Follow-up:** What would you replace them with?
- **Response:** SWIM-style gossip membership for heartbeats and DHT provider records for locations (planned).
- **Show:** AD §7 Alternative B counter; `node/config.py` intervals.
- **Admit:** It's designed for about 4–10 nodes.

**Q74. Is this production-ready?** · *Owner: P4*
- **Answer:** No. It's a working prototype with real crypto and end-to-end tests, but it lacks TLS, garbage collection, delete, proof of storage, per-node identities and a multi-machine soak test.
- **Follow-up:** What would you build first?
- **Response:** Proof-of-storage audits and garbage collection, because they protect durability and disk space.
- **Show:** AD §12 threat table "Status" column.
- **Admit:** —

**Q75. How large a file can you store?** · *Owner: P3*
- **Answer:** Uploads are capped at 256 MiB per request, and the cap is enforced while the body streams in. The manifest must fit in one 1 MiB chunk, which is fine for 256 chunks.
- **Follow-up:** Why the cap?
- **Response:** FastAPI has no default body limit, so an unbounded upload could fill the disk. The cap is a constant we can raise.
- **Show:** `test_upload_size_limit`; `test_large_file_manifest_fits_one_chunk`.
- **Admit:** No resumable or multi-part uploads.

**Q76. How much disk does each node give up?** · *Owner: P2*
- **Answer:** Each node has a quota (2 GiB by default, 1 GiB in Docker). A full node answers 507, and placement skips peers with less than 2 MiB free.
- **Follow-up:** And when the whole cluster is full?
- **Response:** Uploads degrade, then fail with 503. There's no eviction.
- **Show:** `test_quota`; `test_placement_filters_dead_full_and_excluded_hosts`.
- **Admit:** No capacity planning or alerts.

**Q77. How does the system behave when a node joins?** · *Owner: P3*
- **Answer:** It becomes eligible for new chunks and repair targets after its first heartbeat; existing chunks stay where they are. Rendezvous hashing would move only the chunks it now wins, but we don't run that rebalance yet (planned).
- **Follow-up:** So a new node starts empty.
- **Response:** Yes, and it fills as new data arrives.
- **Show:** `test_seed_becomes_peer_after_heartbeat`.
- **Admit:** No rebalancing.

**Q78. What's your operations story: logs, monitoring, upgrades?** · *Owner: P2*
- **Answer:** The dashboard's `/stats` feed shows peers, file health and repair events, and each node logs its loops. Docker Compose brings up a 4-node cluster in one command.
- **Follow-up:** Upgrades with format changes?
- **Response:** Manifests and the index carry a format number and the crypto labels carry `v1`, so a v2 can coexist, but we haven't written a migration.
- **Show:** `docker compose up -d --build`; `test_stats_shows_dead_peers_and_repair`.
- **Admit:** No metrics export or alerting.

## N. Competitive alternatives

**Q79. Why not just use IPFS?** · *Owner: P4*
- **Answer:** IPFS gives you content addressing and a DHT, but data persists only while someone pins it, it doesn't encrypt by default, and it doesn't repair to a target number of copies. Kubo's README also recommends at least 6 GB of RAM and 2 cores, which is heavy for a lab of old laptops.
- **Follow-up:** IPFS Cluster does pinning with replication.
- **Response:** True, and that's a fair alternative for many teams. Ours bundles client-side encryption, passphrase recovery and peer-driven repair into one small process.
- **Show:** AD "Sources" (Kubo README).
- **Admit:** IPFS scales far beyond what we've tested.

**Q80. Why not Syncthing?** · *Owner: P4*
- **Answer:** Syncthing synchronises full folders, so every device stores everything you share with it. We spread chunks so each node stores only part of the data, with 3 copies; that's storage pooling, not sync.
- **Follow-up:** Syncthing is mature and battle-tested.
- **Response:** Absolutely. If you want the same folder on every laptop, use Syncthing.
- **Show:** AD "Sources" (Syncthing local discovery spec).
- **Admit:** Syncthing is far more mature.

**Q81. Why not Google Drive?** · *Owner: P4*
- **Answer:** Drive needs internet, an account and trust in the provider. Ours runs on a LAN with no account, and peers never see plaintext.
- **Follow-up:** Drive is free and far more reliable.
- **Response:** For most people, yes. We target groups where the cloud isn't allowed, isn't affordable, or isn't reachable.
- **Show:** Demo on a hotspot with no internet (planned for the multi-laptop run).
- **Admit:** Drive's durability, sharing and UX are far beyond ours.

**Q82. Isn't this a smaller Tahoe-LAFS?** · *Owner: P4*
- **Answer:** Partly, and we say so. Tahoe uses erasure coding (3-of-10 by default) and a convergence secret. Our differences are repair that doesn't need the uploader, measured routing against a baseline, passphrase-only recovery on a new device, and encrypted delta sync.
- **Follow-up:** Tahoe has years of security review.
- **Response:** Yes. We're an integration project, not a replacement.
- **Show:** AD "Counter to the whole idea"; AD §4.
- **Admit:** None of the algorithms are new.

**Q83. Why not Storj?** · *Owner: P4*
- **Answer:** Storj is an internet-scale paid network that relies on satellites for coordination and uses heavy erasure coding. We run inside a group's own LAN with no coordinator and no payments.
- **Follow-up:** Storj is far more robust.
- **Response:** At internet scale, yes; it's a different problem.
- **Show:** AD "Sources" (Storj forum, 29/80/110; a forum post, not official docs).
- **Admit:** Our only source on their parameters is a forum post.

**Q84. What do you do that none of them do?** · *Owner: P4*
- **Answer:** No single feature is unique. What's unusual is the combination in one small LAN process: client-side compression and encryption, delta sync that still works under encryption, repair run by peers rather than the uploader, recovery from username and passphrase alone, and routing proven with an A/B test.
- **Follow-up:** Combination isn't innovation.
- **Response:** It's engineering integration, and we claim exactly that.
- **Show:** AD "Counter to the whole idea"; bench Delta sync row.
- **Admit:** —

## O. Implementation trade-offs

**Q85. Why Python and FastAPI rather than Go with libp2p?** · *Owner: P2*
- **Answer:** Wi-Fi is the bottleneck, and the heavy work (zstd, AES, SHA-256) runs in C. FastAPI let three people build in parallel against frozen contracts, and every endpoint is debuggable from a browser or curl. libp2p would give NAT traversal, but it would have taken the whole day to learn.
- **Follow-up:** Would you rewrite it?
- **Response:** For internet scale, probably in Go with libp2p. For a LAN prototype, no.
- **Show:** AD §2; `node/contracts.py`.
- **Admit:** —

**Q86. Why HTTP rather than a custom protocol?** · *Owner: P2*
- **Answer:** HTTP gives us request bodies, status codes (507 full, 413 too big, 409 stale) and tooling for free. Signing method, path and body hash makes it authenticated.
- **Follow-up:** It costs extra overhead.
- **Response:** A little per request; with 1 MiB chunks, the headers are noise.
- **Show:** `test_status_codes`; TEAM_WORKFLOW "HTTP API contract".
- **Admit:** —

**Q87. Why pull inventories rather than push location updates?** · *Owner: P2*
- **Answer:** Pulling is self-healing: a missed update is fixed on the next poll, and a dead peer's last inventory is kept, so repair can see which copy went missing. Pushing needs acknowledgments and retries to get right.
- **Follow-up:** Pulling wastes bandwidth.
- **Response:** Yes, at scale. Fine at 4 nodes.
- **Show:** `test_inventory_once_keeps_unreachable_peer_entries`.
- **Admit:** Doesn't scale (see Q73).

**Q88. Why does the user API share a port with the peer API?** · *Owner: P2*
- **Answer:** One process and one port per node keeps deployment simple, especially in Docker. Every user route checks the caller's address and returns 403 unless it's localhost (or the Docker gateway, which is only allowed in Docker).
- **Follow-up:** The workflow doc says it's bound to 127.0.0.1.
- **Response:** The effect is the same, localhost-only, but the mechanism is an address check, not a separate bind; we'll fix the doc.
- **Show:** `test_user_api_rejects_non_local_clients`; `node/main.py` `localhost_only`.
- **Admit:** The doc and code differ on the mechanism.

**Q89. Why fixed thresholds and intervals everywhere?** · *Owner: P2*
- **Answer:** Every interval is a named constant in `node/config.py`: heartbeat 2 s, dead after 20 s, inventory and repair every 10 s. Fixed values are easy to explain and to reason about in tests.
- **Follow-up:** They're slow for repair.
- **Response:** They're tuned against Wi-Fi flapping; you can lower them on a wired network.
- **Show:** `node/config.py`.
- **Admit:** Not adaptive.

**Q90. Why hedged reads? Don't they double the load?** · *Owner: P3*
- **Answer:** A hedge fires only when a request runs past 2× its estimated time, so it adds load only for slow outliers; the loser is cancelled. That's the idea from "The Tail at Scale".
- **Follow-up:** Do you count how often it fires?
- **Response:** The transfer object counts hedges, but we don't show that count on the dashboard yet.
- **Show:** `test_hedged_read_beats_a_stalled_holder`; `test_random_baseline_is_never_hedged`.
- **Admit:** Hedge counts aren't in the bench output.

## P. Business and real-world use

**Q91. Who would pay for this?** · *Owner: P4*
- **Answer:** Our first guess is institutions with idle machines and data they can't put in a public cloud: college labs, research groups, small offices, field teams. The likely model is open-source software with paid setup and support.
- **Follow-up:** Have you validated that?
- **Response:** No. It's a hypothesis, and the next step is talking to five lab admins.
- **Show:** —
- **Admit:** No customer validation.

**Q92. What's the real-world killer use case?** · *Owner: P4*
- **Answer:** Append-heavy data in places with bad internet: sensor logs, lab datasets, field recordings. Compression shrinks it (the CSV was 0.302 of its size), and delta sync sends only new data: appending about 1% sent 0.188 MB of a 20.2 MB file. **[D]**
- **Follow-up:** Does that work for edits in the middle?
- **Response:** In-place edits yes; insertions no, until content-defined chunking (planned).
- **Show:** Bench "Delta sync" row; `test_reupload_reports_delta`.
- **Admit:** Insertions defeat delta sync.

**Q93. What happens when people turn their laptops off at night?** · *Owner: P4*
- **Answer:** Each laptop that goes off is marked dead after 20 s, and repair copies its chunks elsewhere if there are enough hosts left. When it comes back, its copies count again, and the cluster just has extra copies.
- **Follow-up:** If half the lab goes home?
- **Response:** With fewer than 3 hosts awake, files show as degraded until people return; reads still work while any holder is up.
- **Show:** `test_suspect_then_dead_then_back`; `test_only_two_hosts_left_reports_degraded`.
- **Admit:** Daily churn would trigger lots of repair traffic; we haven't measured that.

**Q94. What's the cost compared with cloud storage?** · *Owner: P4*
- **Answer:** The marginal cost is disk you already own, plus electricity and LAN bandwidth. You pay in storage overhead: about 0.9× the original for compressible data and 3× for incompressible data. **[D]**
- **Follow-up:** Plus admin time.
- **Response:** Yes. That's the real cost, and what paid support would cover.
- **Show:** Bench "Files" table (stored/original 0.905 for CSV; 3 copies of incompressible data is 3.0×).
- **Admit:** We haven't modelled total cost of ownership.

**Q95. Legal and compliance: is this usable for sensitive data?** · *Owner: P4*
- **Answer:** The design helps: data never leaves the premises, and peers hold only ciphertext. But there's no delete, no audit log and no third-party review, so we wouldn't claim compliance with anything.
- **Follow-up:** So who can use it today?
- **Response:** Teams experimenting, or data that isn't regulated.
- **Show:** AD §12.
- **Admit:** Not compliance-ready.

**Q96. What's next after the hackathon?** · *Owner: P4*
- **Answer:** First, the multi-laptop and VPN runs for real numbers. Then proof-of-storage audits, garbage collection and delete, then per-node identities with TLS, then erasure coding for 8 or more nodes and content-defined chunking. All of those are (planned).
- **Follow-up:** Which one matters most?
- **Response:** Proof of storage. Without it, R = 3 relies on peers being honest.
- **Show:** AD roadmap notes in §1, §6, §12, §14.
- **Admit:** —

## Q. Hackathon novelty

**Q97. What's novel here?** · *Owner: P4*
- **Answer:** The algorithms aren't new; the integration is. Encrypted delta sync, where synthetic nonces make unchanged chunks re-encrypt identically. Repair that doesn't need the uploader. Passphrase-only recovery on a fresh device. Routing proven with an A/B test instead of claimed.
- **Follow-up:** Which of those have you seen nowhere else?
- **Response:** Encrypted delta sync in a LAN storage pool is the closest. It came from our production delta OTA pipeline, which shipped a 21.6 MB release as 0.41 MB.
- **Show:** Bench "Delta sync" row (0.188 MB of 20.2 MB) **[D]**; AD §14.
- **Admit:** It's engineering, not research.

**Q98. Isn't this a thin wrapper around zstd, AES and FastAPI?** · *Owner: P4*
- **Answer:** The libraries do the math. The parts we wrote are the parts that break in real systems: failure detection with hysteresis, leader-elected repair that stays safe under disagreement, signed responses, rollback-resistant recovery, the bomb guard python-zstandard didn't give us, and the 166 tests that check all of it.
- **Follow-up:** Name one thing you had to figure out yourselves.
- **Response:** python-zstandard ignores the output cap when the frame declares its size, so we check the declared size ourselves; there's a test for it.
- **Show:** `test_decompression_bomb_rejected`; `test_racing_repairers_never_under_replicate`; `test_replayed_response_rejected`.
- **Admit:** —

**Q99. What did you change your mind about during the build?** · *Owner: P4*
- **Answer:** Lots, and it's written down. Whole-file encryption became per-chunk, live-score placement became fixed-weight rendezvous with a slow tier, and uploader-owned locations became soft state. Keys moved from a key file to passphrase derivation.
- **Follow-up:** Why change the keys?
- **Response:** With a key file on one laptop, losing that laptop would lose every file even with 3 copies, so the redundancy claim would have been false.
- **Show:** AD §3, §5, §7, §8 (each "Verdict: CHANGE").
- **Admit:** —

**Q100. What was the trickiest thing to measure fairly?** · *Owner: P3*
- **Answer:** The retrieval A/B. Random placement had to be used for the retrieval test, otherwise the slow node held nothing and both strategies looked equal. And the random baseline had to be kept un-hedged on purpose so we knew what we were comparing.
- **Follow-up:** Isn't that rigging it?
- **Response:** It's the opposite: without it, the test can't show anything. We state the conditions with every number.
- **Show:** `bench/bench.py` `bench_retrieval` comment; `test_random_baseline_is_never_hedged`.
- **Admit:** The ETA arm includes hedging (exchange 6).

**Q101. How did four people build this in a day without stepping on each other?** · *Owner: P4*
- **Answer:** We froze the interfaces in `node/contracts.py` in the first 30 minutes, gave every file a single owner, and built against fakes, so routing and repair were tested before the network existed. Merge gates had concrete pass criteria.
- **Follow-up:** Did the contracts hold?
- **Response:** Yes. Changes needed sign-off from P1, P2 and P3.
- **Show:** TEAM_WORKFLOW.md; `tests/fakes.py`.
- **Admit:** —

**Q102. If you had one more day, what would you add?** · *Owner: P4*
- **Answer:** The multi-laptop run for real Wi-Fi numbers, then a proof-of-storage audit challenge. Both close the two biggest gaps in our evidence.
- **Follow-up:** Not erasure coding?
- **Response:** Not at 4 nodes. It only pays off at 8 or more.
- **Show:** AD §6, §12.
- **Admit:** —

## R. Hard counterquestions that expose contradictions

**Q103. You say "no central server", but everything goes through one node's localhost API.** · *Owner: P4*
- **Answer:** That's *your* node on *your* machine, like a Git client. Any node can do the same job, and `test_cluster.py` recovers and downloads through a different node.
- **Follow-up:** And the cluster key is a central authority.
- **Response:** Yes, for membership. That's the honest caveat: no central server in the data path, closed membership.
- **Show:** `test_upload_kill_download_repair_recover` step 7.
- **Admit:** Membership is centrally keyed.

**Q104. You claim smart routing, but with 4 nodes everyone holds 75% of chunks.** · *Owner: P3*
- **Answer:** Correct for healthy nodes, so we don't claim placement is smart there. The measurable parts are the slow tier (0% of copies on the slow node vs 21.7% random) and download ordering (11.6×). **[D]**
- **Follow-up:** And the placement A/B didn't make downloads faster.
- **Response:** True: ETA ordering already avoids the slow node on reads. Tiering keeps writes off it and keeps it out of future reads if a fast node dies.
- **Show:** Bench "Placement A/B" (download columns about equal) and "Retrieval A/B".
- **Admit:** The placement A/B shows no download speedup.

**Q105. You say "self-repairing", but a chunk sits at 2 copies for up to 40 s.** · *Owner: P3*
- **Answer:** Yes, about 20–40 s in our runs **[D]**, and that's deliberate: 20 s to avoid repairing for a flaky laptop, then up to two 10 s loops. Reads keep working from the other 2 copies the whole time.
- **Follow-up:** A second failure in that window?
- **Response:** Then the chunk is down to 1 copy, still readable, and repair copies it to whatever live hosts remain; with 4 hosts, that's only 2 copies, so it stays degraded. Losing all 3 holders inside the window loses that chunk.
- **Show:** `test_download_survives_two_dead_hosts_with_r3`.
- **Admit:** The window is real; the intervals are tunable.

**Q106. Your doc says random spot checks are in the MVP. Where are they?** · *Owner: P2*
- **Answer:** You're right, that row in the threat table overstates it. The code verifies on PUT, HEADs after repair, re-hashes every download, and fetches-and-hashes a chunk from slow-tier peers every 10 s. There's no random spot check of healthy peers.
- **Follow-up:** So the doc is wrong.
- **Response:** On that row, yes; we'll correct it. Audits are (planned).
- **Show:** `node/inventory.py` `probe_slow`; AD §12 table.
- **Admit:** Doc overstated; concede immediately.

**Q107. You say the plaintext hash lives only in the encrypted manifest, but your node keeps it in a JSON file.** · *Owner: P1*
- **Answer:** Correct: the local catalog cache stores names, sizes and plaintext hashes in plain JSON on the owner's own disk, and downloads return the hash in a header to the local user. Peers never see it, which is what AD §4 is protecting against.
- **Follow-up:** A stolen laptop leaks it.
- **Response:** Yes. Encrypting the cache under the key-encryption key is a small fix (planned).
- **Show:** `node/transfer.py` `_save_catalog`; `test_catalog_persists_to_disk`.
- **Admit:** The local cache is unencrypted.

**Q108. You say every node is equal, but in Docker everyone seeds from node1.** · *Owner: P2*
- **Answer:** Seeds are only for the first contact. After one heartbeat, gossip and the X-Addr header spread everyone's address, and node1 has no other special role. You can list several seeds.
- **Follow-up:** Start node2 to node4 while node1 is down.
- **Response:** Then they rely on mDNS to find each other; with mDNS blocked, they'd wait for node1.
- **Show:** `compose.yaml` `SEEDS`; `test_unknown_caller_address_becomes_candidate`.
- **Admit:** Bootstrap depends on a reachable seed or working mDNS.

---

## 20 hardest exchanges

Format: **J** = judge, **U** = us. "Weakness" is what a sharp judge finds in our first answer. "Best answer" is the position we can defend to the end. "Concede when" says when to stop defending.

### 1. Storage overhead: "3 copies is wasteful"
- **J:** Three full copies? That's 3× storage.
- **U:** On compressible data it's less than one raw copy: the CSV encoded to 0.302 of its size, and 3 × 0.302 ≈ 0.906, which matches the measured 0.905. **[D]**
- **Weakness:** That's the best case. Random data was 1.000, so 3 copies cost 3.0×.
- **J (tougher):** Most real data (photos, video, ZIPs) is already compressed, so you pay 3×. A 3-of-5 erasure code pays 5/3 ≈ 1.67× and also survives 2 losses.
- **Best answer:** Agreed on the arithmetic: for incompressible data, erasure coding saves about 44% (1.67 vs 3.0). With 4 nodes, though, a 3-of-5 code can't even be placed, and a 2-of-4 code (2×) has nowhere to rebuild after one death. We switch at 8+ nodes (planned).
- **Evidence:** Bench "Files" table, csv and random rows; AD §6.
- **Concede when:** Immediately if the judge assumes 8+ nodes or a photo library. Replication is the right choice for small clusters, not in general.

### 2. Rendezvous probability: "why should I believe weights work?"
- **J:** Why does −w/ln(u) give a peer its fair share?
- **U:** u is uniform in (0, 1), so E = −ln(u) is exponential with rate 1. The key is w/E, so the largest key is the smallest E/w, and E/w is exponential with rate w. Among independent exponentials, the one with rate wᵢ is smallest with probability wᵢ/Σw.
- **Weakness:** That assumes SHA-256 output behaves uniformly and independently per (chunk, node) pair.
- **J (tougher):** And for copies 2 and 3? They aren't w/Σw.
- **Best answer:** Right. Probability w/Σw holds for the first choice. Later picks are first choices among the remaining peers, so a heavy peer's share of all copies is less than proportional. With 4 equal peers and 3 copies, each holds 3/4 of chunks no matter what. The test checks first choice only: weights 1:3 gave about 75% to the heavy peer over 4,000 chunks.
- **Evidence:** `test_weight_controls_first_choice_share`; `test_hrw_u_is_strictly_inside_unit_interval`.
- **Concede when:** If asked about share of *all* copies: it isn't exactly proportional, and we didn't measure it.

### 3. "Two of four hosts left: why not just make 3 copies?"
- **J:** Two nodes are down. Why does the dashboard say degraded? Put a second copy on one of the survivors.
- **U:** The rule is one copy per `host_id`. Two hosts can hold at most 2 distinct-host copies; a third copy would have to share a host.
- **Weakness:** Two copies on one host would at least protect against a disk error.
- **J (tougher):** So you'd rather show "degraded" than add protection you could have?
- **Best answer:** A second copy on the same host fails with that host: lost laptop, dead power supply, closed lid. Counting it would turn "3 copies" into a number that no longer means "survives 2 host losses". We report degraded honestly, and repair tops up to 3 as soon as a third host appears.
- **Evidence:** `test_only_two_hosts_left_reports_degraded`; `test_upload_with_two_hosts_is_degraded_not_failed`; Chunk map "live hosts 2/3".
- **Concede when:** If they ask about disk-level bit rot: same-host extra copies would help there, and we don't do it.

### 4. Deterministic nonces with GCM
- **J:** You derive the GCM nonce from the plaintext. Nonce reuse destroys GCM.
- **U:** Reuse is fatal when one key and nonce encrypt *different* plaintexts. Our nonce is HMAC(nonce key, flag ‖ plaintext), so equal nonces mean equal plaintexts and identical ciphertexts. That's the synthetic-IV construction.
- **Weakness:** The nonce is truncated to 96 bits, so two different plaintexts can collide.
- **J (tougher):** Give me the collision probability.
- **Best answer:** By the birthday bound, about n²/2⁹⁷ for n chunks under one file key. With n = 2²⁴ (16 TiB of distinct chunks in one file's history), that's 2⁴⁸/2⁹⁷ = 2⁻⁴⁹; the doc rounds to "about 2⁻⁴⁸". A single upload is capped at 256 MiB, which is 256 chunks, so n²/2⁹⁷ = 2¹⁶/2⁹⁷ = 2⁻⁸¹.
- **Evidence:** `test_deterministic_for_delta_sync`; `test_nonce_must_match_plaintext`; AD §14.
- **Concede when:** If asked "why not a standard mode?": AES-GCM-SIV (RFC 8452) is the better engineering choice (planned). And we leak which chunks are unchanged between versions of the same file.

### 5. Repair timing arithmetic
- **J:** 42.7 s to repair one dead node? That's slow.
- **U:** It's 20 s to declare death (to avoid repair storms from a flaky Wi-Fi laptop) plus up to 10 s for the inventory refresh and up to 10 s for the repair loop, so 20 to about 40 s. We measured 21.4 s and 42.7 s. **[D]**
- **Weakness:** That window is when a second failure hurts most.
- **J (tougher):** What's the probability of losing a chunk in that window?
- **Best answer:** We haven't measured failure rates, so any probability would be invented. Structurally, losing a chunk needs both remaining holders to die within those ~40 s, and reads keep working from either one meanwhile. All the intervals are constants in `node/config.py`; on a wired network we'd lower them.
- **Evidence:** Bench "Kill a node and repair" block; `node/config.py`; `test_download_survives_two_dead_hosts_with_r3`.
- **Concede when:** Immediately on "it's slower than production systems". It is.

### 6. "Your 11.6× is rigged"
- **J:** You added a 300 ms delay to one node and then showed you avoid it. Of course it's faster.
- **U:** Yes, the delay is simulated, and we say so. The test shows the mechanism works: ETA ordering 0.146 s vs random holder 1.697 s. **[D]**
- **Weakness:** The ETA arm also has hedged reads switched on; the random arm doesn't.
- **J (tougher):** So is the 11.6× from ETA ordering or from hedging?
- **Best answer:** It's from our full read strategy, ETA plus hedging, against a plain random baseline; we didn't run the ablation. With ETA ordering, the slow node is ranked last, so a hedge fires only if a fast holder stalls. Our expectation is that most of the gain is ordering, but we didn't measure the hedge count in the bench, so we won't claim it.
- **Evidence:** Bench "Retrieval A/B"; `test_random_baseline_is_never_hedged`; `node/transfer.py` `_fetch`.
- **Concede when:** As soon as they spot the hedging confound. Offer the next step: rerun with hedging off.

### 7. "Your placement A/B shows nothing"
- **J:** In your placement A/B, tiered and random downloads take about the same time. So tiered placement doesn't help?
- **U:** Its job is to keep data off the slow node (0% vs 21.7% of copies) **[D]**, not to speed up this particular download.
- **Weakness:** If ETA routing already avoids the slow node on reads, tiering looks redundant.
- **J (tougher):** Then why keep it?
- **Best answer:** Three reasons. Writes: with random placement, roughly a fifth of copies wait on the slow node at upload time. Resilience: if a fast holder dies, a chunk on the slow node might be the only remaining choice. Repair: repair copies come from the same ranking, so they also avoid the slow node.
- **Evidence:** Bench "Placement A/B"; `test_slow_tier_never_chosen_while_three_healthy_hosts_exist`.
- **Concede when:** On "you haven't shown a user-visible speedup from placement": true, we haven't.

### 8. Independent machines
- **J:** Four containers on one laptop is one machine. Your fault tolerance is unproven.
- **U:** Correct, it's one machine. Each container has its own disk directory, `host_id` and address, and when we kill one, the process really is gone.
- **Weakness:** They share disk, kernel, power and a virtual network with no packet loss.
- **J (tougher):** So none of your timing numbers would hold on Wi-Fi.
- **Best answer:** Throughput won't; the bridge is faster than Wi-Fi, so treat upload/download times as software upper bounds. Detection and repair times are driven by our fixed intervals (2 s, 10 s, 20 s), so they should carry over roughly. Correctness (SHA-256 match after kill and repair) doesn't depend on the network. The multi-laptop run is the next thing we do.
- **Evidence:** DOCKER.md "What Docker does not prove"; `test_cluster.py` passed on Docker and on local processes.
- **Concede when:** Immediately. Never defend "independent machines".

### 9. Proof of storage
- **J:** How do you know node-3 really has the chunks it lists?
- **U:** A copy counts only after a signed 200/201 from that node; repair HEADs again after copying; every read re-hashes.
- **Weakness:** All of those trust the peer's own answer at that moment.
- **J (tougher):** A malicious member stores chunks, answers HEAD correctly, then deletes them. What happens?
- **Best answer:** Its inventory keeps listing them, so repair keeps counting it as a holder, and that chunk effectively has 2 real copies. We notice only when someone reads the chunk from it: the 404 makes the download fall back to another holder. The fix is a challenge-response audit: ask for a hash of the chunk with a random nonce, which you can only answer if you have the bytes (planned, `POST /audit`).
- **Evidence:** AD §12 threat table; `node/repair.py`; `test_stale_location_map_falls_back_to_asking_everyone`.
- **Concede when:** Immediately on "so R = 3 assumes honest peers": yes, it does today.

### 10. Sybil insider with fake host IDs
- **J:** You prevent two copies on one host. But `host_id` is just a string the node reports.
- **U:** Correct, it's self-reported. Outsiders can't join without the cluster key.
- **Weakness:** An insider can start 4 nodes on one laptop with 4 different `host_id`s.
- **J (tougher):** What fraction of chunks would end up entirely on the attacker's machine?
- **Best answer:** With 4 honest and 4 fake nodes at equal weight, the top 3 of 8 are uniformly random, so P(all three fake) = C(4,3)/C(8,3) = 4/56 ≈ 7%. That machine could then drop 7% of chunks entirely. The defence is per-node identities issued by an admin, ideally tied to hardware (planned). Our model assumes members are trusted.
- **Evidence:** AD §12 "Sybil: closed membership (not open-network safe)"; `test_placement_never_returns_two_nodes_on_one_host`.
- **Concede when:** At once. Trusted membership is an assumption, not a defence.

### 11. Network partition 2–2
- **J:** Split your 4 nodes into 2 and 2. What happens?
- **U:** Each side marks the other dead after 20 s. Each side has only 2 hosts, so nothing can get back to 3 copies; every chunk shows degraded.
- **Weakness:** Reads: a chunk whose 3 copies are split 2–1 has only 1 copy on one side.
- **J (tougher):** And if users upload on both sides, then the network heals?
- **Best answer:** Chunks and manifests merge cleanly: different content, different IDs, and extra copies are harmless. The owner index doesn't merge: if both sides publish the same version number, peers keep the first one they saw and reject the other with 409, so one side's new file can drop out of the list. The data still exists on peers, but it's unreferenced.
- **Evidence:** AD §7 "Known limits"; `test_index_store_keeps_highest_version`; `node/transfer.py` `_publish_index`.
- **Concede when:** On "lost update": yes. CRDT index merge is (planned), and we should surface the 409 to the user.

### 12. Concurrent writers silently lose
- **J:** Your upload returns 201. Is the file definitely in my recoverable file list?
- **U:** The chunks and manifest are on 3 hosts, and the new file list is pushed to every live peer.
- **Weakness:** The upload ignores how many peers *accepted* the new list.
- **J (tougher):** So if every peer rejects it as stale, I get success but can't recover the file on a new device?
- **Best answer:** Yes, that's possible when two devices of the same owner write at once, which we tell users not to do. The fix is small: fail or retry the upload if zero peers accept the new index version, and later merge indexes (planned).
- **Evidence:** `node/transfer.py` `_publish_index` (returns the count); AD §7 "Only one device should write the index at a time".
- **Concede when:** Immediately. It's a real gap.

### 13. 1,000 peers
- **J:** What breaks first at 1,000 nodes?
- **U:** The all-to-all loops: heartbeats and inventory pulls.
- **Weakness:** Show the numbers.
- **J (tougher):** Quantify it.
- **Best answer:** Heartbeats: each node probes 999 peers every 2 s, about 500 requests/s per node and about 500,000/s across the cluster. Inventory: each node downloads every other node's chunk list every 10 s. At 10,000 chunks of 64-hex-character IDs, that's about 640 KB per list, ×999 ≈ 640 MB per node every 10 s, or about 64 MB/s per node, before any real data moves. Also, every upload pushes the index to all 999 peers. The fixes are SWIM-style membership and DHT provider records (planned).
- **Evidence:** `node/config.py` intervals; `node/inventory.py`; AD §7 Alternative B counter.
- **Concede when:** At once. It's a 4–10 node design.

### 14. Forgotten passphrase
- **J:** Your users will forget passphrases and lose everything.
- **U:** That's the trade-off of end-to-end encryption: nobody, including us, can decrypt without it.
- **Weakness:** Consumer products all have recovery flows.
- **J (tougher):** So your durability claim is really "durable unless you forget a password"?
- **Best answer:** Yes. AD §6 lists "the owner still has the passphrase" as a condition of R = 3. Options are recovery codes printed at sign-up, or splitting the key among trusted devices with Shamir secret sharing (planned). We chose passphrase derivation because a key *file* on one laptop was worse: losing the laptop lost everything.
- **Evidence:** AD §5, §6; `test_fresh_device_recovers_and_downloads`.
- **Concede when:** Immediately. It's a stated condition, not a hidden one.

### 15. Global delete
- **J:** I uploaded a file by mistake. Delete it everywhere.
- **U:** There's no delete today. Peers have no DELETE route on purpose, so a leaked cluster key can't wipe the cluster.
- **Weakness:** Then mistakes and old versions accumulate forever.
- **J (tougher):** Can you at least make it unreadable?
- **Best answer:** It's already unreadable to anyone without your passphrase. We can't crypto-shred one file, though: its data key is wrapped by your account-wide key, and old manifests holding it stay on peers. A real delete removes the manifest from the signed index, then GC reclaims chunks no index references (planned).
- **Evidence:** `node/api_peer.py` docstring; AD §11 "garbage collection is planned".
- **Concede when:** On erasure or compliance: we don't support it.

### 16. Thin wrapper
- **J:** zstd, AES-GCM, SHA-256, Ed25519, scrypt, FastAPI. What did you actually build?
- **U:** The system around them: placement, failure detection, repair, recovery, and the A/B tests.
- **Weakness:** Plenty of projects glue libraries together.
- **J (tougher):** Name something that would be wrong if you'd just used the libraries naively.
- **Best answer:** Three things. python-zstandard ignores its output cap when the frame declares a size, so a naive bomb guard doesn't work; we check the declared size. Unsigned responses would let a stranger on the Wi-Fi answer HEAD with "I have it" and silently stop repair, so we sign responses and bind them to the request. Without a deterministic leader, repair races; ours is leader-elected and still safe if the race happens.
- **Evidence:** `test_decompression_bomb_rejected`; `test_frame_without_content_size_rejected`; `test_unsigned_or_impostor_responses_rejected`; `test_racing_repairers_never_under_replicate`.
- **Concede when:** On "none of these algorithms are new": agree. We claim integration.

### 17. Erasure coding with 4 nodes
- **J:** Erasure coding works fine with 4 nodes: use 2-of-4.
- **U:** 2-of-4 stores 2× and survives 2 losses; R = 3 stores 3× and survives 2 losses.
- **Weakness:** So erasure coding uses a third less storage for the same tolerance.
- **J (tougher):** Why pay 50% more storage?
- **Best answer:** Look at what happens after the first failure. With 2-of-4, the dead node's piece can't be rebuilt anywhere, because the other 3 nodes already hold a piece each. You're left with 3 pieces, tolerating only 1 more loss. With R = 3, repair makes a fresh copy on the 4th host, back to tolerating 2 more losses. Repair also needs one download, not k downloads plus decoding.
- **Evidence:** AD §6; `test_survives_two_sequential_failures_after_repair`.
- **Concede when:** If they add nodes: at 8 or more, erasure coding wins, and it's on our roadmap.

### 18. Uploader disappears before replication finishes
- **J:** The uploader's laptop dies halfway through an upload. Who repairs?
- **U:** Every chunk already on a peer is repaired by its holders, not the uploader.
- **Weakness:** The manifest and file list are written *last*.
- **J (tougher):** So a half-finished upload is just orphaned chunks?
- **Best answer:** Yes. Without a manifest in the signed index, the file doesn't exist for recovery, and those chunks are unreferenced ciphertext. You re-upload, and delta sync skips chunks already on 3 live hosts, *if* it's the same file under the same name with an existing version. A brand-new file gets a new key, so its chunks re-encrypt differently. Orphans stay until GC (planned).
- **Evidence:** `node/transfer.py` upload order; `test_delta_sync_sends_only_changed_chunks`.
- **Concede when:** On "atomic uploads": they aren't atomic; they just never expose half a file.

### 19. Unauthorized download from the same machine
- **J:** Your user API is localhost-only. I'm another user on that same laptop.
- **U:** Then you're inside the trust boundary; once the owner unlocks, the node serves files to any local process.
- **Weakness:** Shared machines, lab computers.
- **J (tougher):** Your workflow doc says the API is "bound to 127.0.0.1", but the node listens on 0.0.0.0.
- **Best answer:** Correct, the doc describes the effect, not the mechanism. The peer and user APIs share one port; every user route checks the caller's address and returns 403 unless it's localhost (or, in Docker only, the gateway address). Static dashboard files load from anywhere, but they hold no data. Per-session tokens for the user API are (planned).
- **Evidence:** `test_user_api_rejects_non_local_clients`; `test_rejects_requests_from_other_machines`; `node/main.py` `localhost_only`.
- **Concede when:** On multi-user machines: not protected.

### 20. Durability vs retrieval: "you showed a download, not durability"
- **J:** You killed a node and the download worked. That only proves one surviving copy was reachable.
- **U:** Agreed, that's retrieval. Durability is that we get back to 3 copies without the dead node and can then survive 2 *more* losses.
- **Weakness:** The second kill in your demo might hit a node that never held those chunks.
- **J (tougher):** How do you know you killed an *original* holder?
- **Best answer:** The cluster test reads the chunk map before the first kill, chooses the second victim from the original holders of chunk 0 (when one is left that isn't the uploader's node), and checks the SHA-256 again. Demo step 6 does the same from the Chunk map panel. In the Docker manual run, all 27 files healed after a kill. **[D]**
- **Evidence:** `test_upload_kill_download_repair_recover` (steps 5–8); `test_survives_two_sequential_failures_after_repair`; Chunk map panel.
- **Concede when:** On long-term durability (weeks, bit rot, churn): we have no data.
