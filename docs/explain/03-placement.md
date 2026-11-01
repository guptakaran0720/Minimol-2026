# 03 · Placement: where each chunk is stored

**One line:** For every chunk we rank the eligible peers with tiered, weighted rendezvous hashing and store 3 copies on the top 3, never two on the same host.

**Analogy:** Every chunk holds its own lottery. Each peer gets a ticket number computed from the chunk's ID and the peer's ID, so everyone who runs the lottery gets the same winners without talking to each other. Peers known to be slow are put in a second draw that only runs if the first draw doesn't have enough winners.

## How it works

1. **Who is eligible.** A peer must be `alive`, report at least 2 MiB free, and sit on a host that doesn't already hold a copy ([routing.py:43](../../node/routing.py#L43), `MIN_FREE_BYTES` at [routing.py:19](../../node/routing.py#L19)). This node is in its own peer table, so it can hold copies too.
2. **The hash value `u`.** For each (chunk, peer) pair: `u = (first 8 bytes of SHA-256(chunk_id ":" node_id) + 0.5) / 2^64` ([routing.py:24](../../node/routing.py#L24)). The `+ 0.5` keeps `u` strictly between 0 and 1, so `ln(u)` is always defined.
3. **The rank key `-w / ln(u)`.** `w` is the peer's fixed capacity weight, always greater than 0 (`WEIGHT` env, default 1.0) ([routing.py:30](../../node/routing.py#L30)). With this formula, the chance that a peer ranks first is `w / sum(w)`. Higher key wins.
4. **Two tiers.** Peers are sorted by `(tier, -key)` ([routing.py:47](../../node/routing.py#L47)). Every tier-1 (healthy) peer ranks above every tier-2 (slow) peer. Tier is set by the peer table with 30 s hysteresis, see [04](04-failure-detection.md).
5. **Distinct hosts.** Walking down the ranked list, we keep only the first peer for each `host_id` ([routing.py:48](../../node/routing.py#L48)). `host_id` is the failure domain: two nodes on one laptop share it.
6. **Store the copies.** Upload asks the top peers in parallel, as many as copies still needed. If one refuses (quota full, hash error, network error), it moves on down the list ([transfer.py:184](../../node/transfer.py#L184)). Copies that already exist on live distinct hosts are counted first (that is delta sync, see [09](09-delta-sync.md)). If only 1 or 2 hosts accept, the upload succeeds but reports `degraded`. If none accept, it fails with 503.

The manifest is placed with exactly the same function ([transfer.py:153](../../node/transfer.py#L153)), and so are repair targets ([repair.py:114](../../node/repair.py#L114)).

## Why live metrics are kept out of placement

Placement uses only the fixed weight and the tier, never live RTT or bandwidth ([routing.py:3](../../node/routing.py#L3)). Live scores change every few seconds. If they decided placement, a chunk's "best 3 peers" would keep changing, and repair would keep copying chunks back and forth. The tier is the one live signal we allow, and it only changes after 30 s of consistent evidence in either direction.

## Why this design

**Decision:** rendezvous hashing with fixed weights and two tiers. See [ARCHITECTURE_DECISIONS.md §8](../ARCHITECTURE_DECISIONS.md#8-placement-rendezvous-hashing-with-fixed-weights-and-two-tiers).

- **Strongest counter:** with 4 nodes and 3 copies, every node holds about 75% of the chunks anyway, so "smart placement" is invisible.
- **Our defense:** that is exactly why we added the slow tier. Weights alone wouldn't show anything with 4 nodes, but tiers make the effect visible: the slow node gets **0** new chunks while 3 healthy hosts exist. That is measurable and we measured it.

**Alternative we rejected: round-robin.** It needs stored state, and every join or leave reshuffles placement. Rendezvous hashing is stateless, every node computes the same order, and when a peer leaves, only the chunks it held move. It is about 15 lines of code.

**About the original formula:** `score * (-1 / ln x)` is the correct weighted form, but the original let the score reach 0 or below and could hit `ln(0)`. Fixed positive weights and `u` strictly inside (0, 1) remove both problems.

## Evidence

Tests in [tests/test_routing.py](../../tests/test_routing.py):

- [`test_hrw_u_is_strictly_inside_unit_interval`](../../tests/test_routing.py#L24)
- [`test_placement_filters_dead_full_and_excluded_hosts`](../../tests/test_routing.py#L30)
- [`test_placement_never_returns_two_nodes_on_one_host`](../../tests/test_routing.py#L42)
- [`test_placement_is_deterministic`](../../tests/test_routing.py#L49)
- [`test_slow_tier_never_chosen_while_three_healthy_hosts_exist`](../../tests/test_routing.py#L57) and [`test_slow_tier_used_as_fallback`](../../tests/test_routing.py#L64)
- [`test_removing_a_non_winner_does_not_move_chunks`](../../tests/test_routing.py#L70)
- [`test_weight_controls_first_choice_share`](../../tests/test_routing.py#L79)

And in [tests/test_transfer.py](../../tests/test_transfer.py): `test_round_trip_three_distinct_hosts`, `test_full_peer_is_skipped_for_next_ranked`, `test_upload_with_two_hosts_is_degraded_not_failed`, `test_upload_with_no_peers_raises`.

Measured, placement A/B ([bench.py:289](../../bench/bench.py#L289)). Docker cluster, 4 containers on one laptop, real encryption + compression, node-4 delayed 300 ms (simulated), 20 MB CSV, 5 reps, medians. Node-4 was already in tier 2 before the A/B started.

| Strategy | Share of copies on the slow node |
|---|---|
| Tiered rendezvous (ours) | **0%** |
| Random baseline (same eligibility and distinct hosts, random order) | **21.7%** |

In the last tiered run, node-1, node-2 and node-3 each held all 20 chunks; node-4 held none.

Caveat: one machine, so these prove correctness, not Wi-Fi performance. The multi-laptop run is still to do.

## Limits

- Weights are static and set by hand (`WEIGHT`). We don't learn capacity.
- With 4 nodes and 3 copies, placement among healthy nodes looks almost uniform. The tier is what shows the difference.
- Free space comes from each peer's own `/health` claim. A peer that lies just causes a failed PUT, and we move on to the next one.
- A failed PUT marks the peer `suspect`, which removes it from placement until its next good heartbeat (about 2 s). The 15 s cooldown only affects download ordering, not placement.
- No rebalancing: when a new peer joins, existing chunks stay where they are. Only new chunks and repairs use the new ranking.

## Judge questions

**Q: Why not just send chunks to the fastest peers right now?**
A: Because "fastest right now" changes every few seconds, so the best 3 peers for a chunk would keep changing and repair would move data back and forth. We use a stable hash for placement and a slow tier that only flips after 30 s of evidence.
*Follow-up:* "So where do live measurements matter?" → In downloads: retrieval ranks holders by measured ETA, see doc 05.

**Q: Why the formula `-w / ln(u)`?**
A: It is weighted rendezvous hashing: each peer wins first place with probability proportional to its weight, and every node computes the same ranking with no coordination. We keep `u` strictly between 0 and 1 so the log is always defined.
*Follow-up:* "Prove the weights work?" → `test_weight_controls_first_choice_share` checks the first-place share follows the weights.

**Q: What if two of my nodes run on the same laptop?**
A: Give them the same `HOST_ID`; placement never puts two copies on one host_id, so losing that laptop loses at most one copy of any chunk. In the Docker demo each container has its own host_id, and we say that it's one machine.
*Follow-up:* "And if there are only 2 hosts?" → The upload still succeeds, but the file is reported `degraded`, not hidden.
