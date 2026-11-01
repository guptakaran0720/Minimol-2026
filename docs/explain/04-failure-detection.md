# 04 · Failure detection and discovery

**One line:** Every node pings every other node every 2 s; a peer becomes `suspect` after 2 missed pings or one failed transfer, `dead` after 20 s of silence, and `slow` (tier 2) after 30 s of being much slower than the rest.

**Analogy:** A roll call every 2 seconds. Miss two in a row and the teacher pencils a question mark next to your name. Be gone for 20 seconds and you're marked absent, and someone else takes over your jobs. Show up again and the mark is erased.

## How it works

1. **Heartbeats every 2 s.** Each node calls `GET /health` on every known peer and every unconfirmed candidate address, all in parallel ([peers.py:168](../../node/peers.py#L168), interval at [config.py:15](../../node/config.py#L15)). The request is HMAC-signed and the answer must carry a valid response signature from the expected node; the body's `node_id` must match the signed `X-Node` ([peer_client.py:101](../../node/peer_client.py#L101)). Connect timeout is 1 s, read timeout 5 s ([config.py:20](../../node/config.py#L20)), so a closed laptop lid doesn't stall us.
2. **Suspect.** After 2 consecutive failed heartbeats ([peers.py:121](../../node/peers.py#L121)), or immediately after one failed transfer ([peers.py:67](../../node/peers.py#L67)). A failed transfer also starts a 15 s cooldown that pushes the peer to the back of the download order. Suspect peers are not used for placement, and repair waits while any holder is suspect.
3. **Dead.** When a heartbeat fails and the peer has had no successful contact for 20 s ([peers.py:119](../../node/peers.py#L119), `DEAD_AFTER_S` at [config.py:17](../../node/config.py#L17)). Dead peers stay in the table and keep being probed, and their last inventory stays in the location map, so repair can see which copy went missing.
4. **Back to alive.** Any successful contact, either a heartbeat or a real chunk transfer, resets the missed count and sets the peer `alive` ([peers.py:127](../../node/peers.py#L127)). If a node restarts at the same address with a new `node_id`, the old entry is marked dead ([peers.py:97](../../node/peers.py#L97)). Normally `node_id` survives restarts because it is saved in the data directory ([config.py:95](../../node/config.py#L95)).
5. **Slow tier with hysteresis.** After every heartbeat round, each peer's estimated time to fetch 1 MiB is `rtt_ewma + 1 MiB / bw_ewma` ([peers.py:30](../../node/peers.py#L30)). If it stays above 3× the cluster median for 30 s, the peer moves to tier 2; after 30 s at or below, it moves back ([peers.py:134](../../node/peers.py#L134), `SLOW_FACTOR` and `SLOW_HOLD_S` at [config.py:24](../../node/config.py#L24)). Tier-2 peers get no new chunks, so they'd never get a fresh measurement. To fix that, every 10 s each node downloads one chunk a tier-2 peer holds, hashes it, and records the transfer time ([inventory.py:74](../../node/inventory.py#L74)).
6. **Finding peers.** Three sources feed the candidate list ([discovery.py](../../node/discovery.py)):
   - **Seeds:** addresses typed into `SEEDS` ([discovery.py:25](../../node/discovery.py#L25)).
   - **Gossip:** every 5 s, ask each alive peer for its `/peers` list and add unknown addresses ([discovery.py:31](../../node/discovery.py#L31)). Callers also send their own address in `X-Addr`, so a seed learns about nodes that only know it ([api_peer.py:111](../../node/api_peer.py#L111)).
   - **mDNS:** on by default, `MDNS=0` turns it off. Each node announces `_minimol._tcp` with a tag derived from the cluster key, and ignores records with a different tag ([discovery.py:45](../../node/discovery.py#L45)). If multicast is blocked, it logs a warning and seeds + gossip carry on.

   A candidate becomes a peer **only** after an authenticated heartbeat succeeds ([peers.py:91](../../node/peers.py#L91)). Discovering an address is not the same as trusting it.

## Why this design

**Decision:** fixed heartbeat thresholds (2 s / 2 missed / 20 s). See [ARCHITECTURE_DECISIONS.md §10](../ARCHITECTURE_DECISIONS.md#10-failure-detection-fixed-heartbeat-thresholds).

- **Strongest counter:** adaptive detectors such as phi-accrual are more accurate, especially on noisy Wi-Fi.
- **Our defense:** with 4 nodes, fixed numbers are easy to explain, easy to tune, and easy to watch on the dashboard. The two-step suspect → dead design already absorbs short blips: suspect only changes download order and pauses repair; nothing is copied until a peer has been silent for 20 s.

**Decision:** seed list + gossip always on, mDNS best-effort. See [§13](../ARCHITECTURE_DECISIONS.md#13-discovery-seed-list-plus-gossip-mdns-optional).

- **Counter:** venue Wi-Fi often blocks multicast and isolates clients.
- **Defense:** that is why mDNS is optional. One typed seed is enough, and gossip spreads the rest. We also bring our own hotspot.

**Decision:** a slow tier with 30 s hysteresis in both directions. See [§8](../ARCHITECTURE_DECISIONS.md#8-placement-rendezvous-hashing-with-fixed-weights-and-two-tiers).

- **Counter:** 30 s is slow to react.
- **Defense:** the tier changes placement, and placement must be stable or repair would shuffle data around. Downloads react instantly anyway, through ETA ranking (doc 05).

## Evidence

Tests in [tests/test_peers.py](../../tests/test_peers.py) use a fake clock, so the thresholds are tested exactly:

- [`test_suspect_then_dead_then_back`](../../tests/test_peers.py#L83): 1 miss → alive, 2 misses → suspect, +20 s → dead, still in the table, then alive again.
- [`test_failed_transfer_suspects_and_cools_down`](../../tests/test_peers.py#L102), [`test_transfer_ewma`](../../tests/test_peers.py#L112).
- [`test_slow_peer_moves_to_tier_2_and_back`](../../tests/test_peers.py#L133): 29 s → still tier 1, 30 s → tier 2, and back.
- [`test_slow_peer_is_probed_and_recovers`](../../tests/test_peers.py#L198): the 10 s probe gives a tier-2 peer a way back.
- `test_seed_becomes_peer_after_heartbeat`, [`test_gossip_finds_peers_of_peers`](../../tests/test_peers.py#L183), `test_restarted_node_with_new_id_replaces_old`, [`test_mdns_record_filtering`](../../tests/test_peers.py#L238).
- [tests/test_api_peer.py::test_unknown_caller_address_becomes_candidate](../../tests/test_api_peer.py#L150).

Measured: per-node dead detection was **19.5–20.6 s**. Killing node-2 in the Docker run, it was marked dead after **21.4 s** from the uploader's view (the bench polls every 0.5 s). In the placement benchmark, node-4 (300 ms simulated delay) was already in tier 2 before the A/B began. Conditions: Docker cluster, 4 containers on one laptop. Caveat: one machine, so these prove correctness, not Wi-Fi performance. The multi-laptop run is still to do.

## Limits

- Fixed thresholds, not adaptive. Phi-accrual is a known upgrade, not built.
- A `/health` reply proves the process is up, not that it still has its chunks. Downloads re-hash every chunk, and each node scrubs its own disk in the background, but no node challenges a *remote* peer to prove it still stores its chunks (audits planned).
- A peer that answers heartbeats but hangs on chunk transfers is caught by transfer failures (suspect + cooldown) and by the slow tier, not by heartbeats.
- If a peer accepts the connection but never answers, one heartbeat round can take up to the 5 s read timeout before the next 2 s sleep. Detection still converges, just a few seconds later.
- Every node keeps its own view. Two nodes can briefly disagree about who is alive; repair is designed to tolerate that (doc 06).
- Discovery is LAN-only. Internet-scale discovery (a DHT) is roadmap, not built.

## Judge questions

**Q: Why wait 20 seconds before declaring a node dead?**
A: Wi-Fi drops packets and laptops pause, and a false "dead" would start copying data for nothing. Suspect after 2 missed beats already moves downloads away within about 4 s; only repair waits the full 20 s.
*Follow-up:* "Why not faster?" → We could lower it in `config.py`, but then a short Wi-Fi hiccup would trigger repair storms. 20 s is a deliberate trade.

**Q: What if two nodes disagree about whether a peer is dead?**
A: Each node decides from its own heartbeats, so for a few seconds they can disagree. Repair is built for that: the worst case is two nodes both copying a chunk, which is harmless because PUT is idempotent and the chunk ends up over-replicated, never under-replicated.
*Follow-up:* "Is there consensus?" → No. We don't need it, because every decision is safe to make twice.

**Q: Can another team's laptop join your cluster by announcing itself on mDNS?**
A: It can announce, but it won't get in. Our mDNS records carry a tag derived from the cluster key, and an address only becomes a peer after a heartbeat with a valid HMAC and a valid signed response.
*Follow-up:* "What if they copy the tag?" → The tag only stops us wasting probes. Membership needs the cluster key itself.
