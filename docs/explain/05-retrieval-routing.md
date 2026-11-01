# 05 · Retrieval routing: which copy we download

**One line:** For each chunk we try the holders in order of estimated fetch time (`ETA = rtt + size / bandwidth`, both measured from real transfers), and if the first one is late we also ask the next one and take whichever verified answer arrives first.

**Analogy:** Three shops sell the same part. You phone the one that's usually quickest. If they haven't picked up in twice the usual time, you also call the second shop, and you take whichever delivers first. A shop that just let you down goes to the bottom of your list for a while.

## How it works

1. **Find the holders.** The location map (built every 10 s from every peer's `/inventory`) says which nodes hold a chunk ([transfer.py:265](../../node/transfer.py#L265)).
2. **Rank them** ([routing.py:62](../../node/routing.py#L62)). Dead peers are dropped. The rest are sorted by three keys, in order ([routing.py:74](../../node/routing.py#L74)):
   - peers in a failure cooldown go last (a failed transfer starts a 15 s cooldown, [peers.py:71](../../node/peers.py#L71)),
   - suspect peers go after alive ones,
   - then lowest ETA first: `rtt_ewma + size / bw_ewma` ([routing.py:56](../../node/routing.py#L56)).
3. **Where the numbers come from.** Both averages are EWMAs with α = 0.3 ([config.py:23](../../node/config.py#L23)). Transfers of 64 KiB or more update bandwidth; smaller ones and heartbeats update RTT ([peers.py:56](../../node/peers.py#L56)). A peer with no samples yet gets the median of the peers that have them, or 10 ms / 10 MiB/s if nobody has samples ([routing.py:70](../../node/routing.py#L70)).
4. **Hedged reads** ([transfer.py:279](../../node/transfer.py#L279)). We ask the best holder. If no answer arrives within `max(50 ms, 2 × its ETA)` ([transfer.py:276](../../node/transfer.py#L276)), we also ask the next holder, and take the first reply whose SHA-256 matches the chunk ID. The losing request is cancelled. A request that fails moves on to the next holder at once.
5. **Verify every blob.** Each answer is re-hashed. A wrong hash or a network error marks that peer suspect with a cooldown; a 404 just means the location map was stale and isn't held against the peer ([transfer.py:309](../../node/transfer.py#L309)). Good transfers update the peer's EWMAs.
6. **Fallback.** If every listed holder fails, we ask every other alive peer before giving up, because the location map is soft state and may be out of date ([transfer.py:270](../../node/transfer.py#L270)). Only then do we raise `ChunkUnavailable` (HTTP 503).

Downloads fetch up to 4 chunks in parallel, write them in order, and check the whole-file SHA-256 before the user API serves the file ([transfer.py:259](../../node/transfer.py#L259), [api_user.py:187](../../node/api_user.py#L187)).

## Why this design

**Decision:** rank by estimated fetch time in seconds, not a weighted score. See [ARCHITECTURE_DECISIONS.md §9](../ARCHITECTURE_DECISIONS.md#9-retrieval-routing-estimated-fetch-time-not-a-weighted-sum).

- **Strongest counter:** a new peer has no transfer history, so its ETA is a guess.
- **Our defense:** we start new peers at the cluster median, so they're neither favoured nor ignored, and the first real transfer replaces the guess. The original weighted sum (0.35 / 0.25 / 0.20 …) had arbitrary weights and could go negative; an ETA is in seconds, so there's nothing to tune or defend.

**Decision:** hedged reads, from Dean & Barroso's "The Tail at Scale".

- **Counter:** sending duplicate requests wastes bandwidth.
- **Defense:** the second request only fires for outliers that are already 2× late, and the loser is cancelled. In the normal case there is exactly one request per chunk.

## Evidence

Tests (on in-memory fakes, so they test the logic, not the network):

- [tests/test_routing.py](../../tests/test_routing.py): [`test_retrieval_prefers_lower_eta`](../../tests/test_routing.py#L85), [`test_retrieval_cooldown_and_suspect_go_last_dead_dropped`](../../tests/test_routing.py#L91), [`test_retrieval_new_peer_gets_median_prior`](../../tests/test_routing.py#L101).
- [tests/test_transfer.py](../../tests/test_transfer.py): [`test_hedged_read_beats_a_stalled_holder`](../../tests/test_transfer.py#L311) (a holder that stalls for 1 s; the hedged download finishes in under 0.6 s), [`test_without_hedging_a_stalled_holder_costs_the_full_stall`](../../tests/test_transfer.py#L319), [`test_random_baseline_is_never_hedged`](../../tests/test_transfer.py#L327), `test_download_survives_one_dead_holder`, `test_suspect_holder_still_tried_after_alive_ones`, [`test_corrupt_holder_is_skipped_and_penalised`](../../tests/test_transfer.py#L176), [`test_stale_location_map_falls_back_to_asking_everyone`](../../tests/test_transfer.py#L197).
- [tests/test_peers.py::test_transfer_ewma](../../tests/test_peers.py#L112).

**The A/B benchmark** ([bench.py:305](../../bench/bench.py#L305)):

- Setup: Docker cluster, 4 containers on one laptop, real encryption + compression, node-4 delayed 300 ms per request (simulated), 20 MB CSV, 5 reps each.
- The file is uploaded with the **random** placement baseline, so the slow node really holds some chunks. Otherwise tiered placement would keep it empty and there would be nothing to route around.
- We alternate which strategy runs first in each rep, to cancel drift ([bench.py:311](../../bench/bench.py#L311)). Every download's SHA-256 is checked.

| Strategy | Median download (min–max) |
|---|---|
| ETA ordering (ours, with hedging) | **0.146 s** (0.113–0.192) |
| Random holder (baseline, no hedging) | **1.697 s** (1.106–1.977) |
| Speedup (median) | **11.6×** |

Be precise on stage: "ours" is ETA ordering plus hedged reads; the baseline is random order with no hedging ([transfer.py:264](../../node/transfer.py#L264)). The comparison is our full read path against a naive one.

Caveat: one machine, so these prove correctness, not Wi-Fi performance. A 300 ms delay on a virtual network is a big, clean gap; on real Wi-Fi the gap will be smaller and noisier. The multi-laptop run is still to do.

## Limits

- The hedge delay uses the peer's own EWMA, or fixed defaults (10 ms, 10 MiB/s) if it has none, not the cluster median.
- We don't fetch from several holders at once to add up bandwidth (striping). One holder per chunk, plus a hedge.
- ETA is per peer, not per path. On a LAN that's fine; across networks it wouldn't be.
- The location map can be up to 10 s stale. The fallback covers that, at the cost of extra requests.
- We haven't separately measured "ETA without hedging" vs random, so we can't split the 11.6× between the two parts.

## Judge questions

**Q: How do you know the routing is actually smart and not just luck?**
A: We ran an A/B: same file, same cluster, one node slowed by a simulated 300 ms, alternating the order of runs. ETA ordering took 0.146 s median against 1.697 s for a random holder, 11.6× faster, with the SHA-256 checked every time.
*Follow-up:* "Is that real network?" → No, it's Docker on one laptop, and we say so; the multi-laptop run is next.

**Q: Isn't some of that speedup from hedging rather than ETA ranking?**
A: Yes, the A/B compares our full read path (ETA order plus hedging) with a naive random pick. ETA ranking alone should avoid the slow node most of the time, and hedging covers the cases where the estimate is wrong.
*Follow-up:* "Can you separate them?" → `Transfer(hedge=False)` exists and is tested; we haven't run that benchmark yet.

**Q: What happens when the fastest holder is lying or corrupted?**
A: Every blob is re-hashed against its chunk ID before use. A mismatch counts as a failed transfer, so the peer becomes suspect, goes to the back of the line for 15 s, and the next holder is tried.
*Follow-up:* "Could it pass the hash but still be wrong?" → Not in practice: the chunk ID comes from our own encrypted manifest, so a matching hash means it's the exact blob we uploaded. The GCM tag and the whole-file SHA-256 are two more checks behind it.
