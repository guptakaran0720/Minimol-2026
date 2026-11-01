"""Proof-of-storage audits: peers prove they still hold the chunks they list.

Scrubbing (scrub.py) checks this node's own disk. Audits check the others:
every AUDIT_INTERVAL_S, for AUDIT_PER_ROUND chunks this node holds, pick another
live holder and challenge it with a fresh random nonce. It must answer
HMAC-SHA256(nonce, chunk bytes), which only a node holding the exact bytes can
compute; we check it against our own copy (re-hashed first, so we never accuse a
peer on the strength of a rotten local copy).

A failed audit (no copy, or a wrong proof) distrusts that copy in the location map
for AUDIT_DISTRUST_S: repair then counts one copy fewer and places a real one
elsewhere, and peer_client ignores that peer's "I have it" for the chunk.

Known limit: a peer could relay the challenge to an honest holder and pass on its
answer. Stopping that needs per-node identities (planned).
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import random
from collections import Counter

from node import config
from node.chunkstore import DiskChunkStore
from node.events import EventLog
from node.inventory import LocationMap
from node.peers import PeerTable

log = logging.getLogger("node.audit")


async def audit_once(store: DiskChunkStore, locations: LocationMap, table: PeerTable, client,
                     events: EventLog, per_round: int, stats: Counter, rng: random.Random | None = None) -> None:
    rng = rng or random.Random()
    alive = {p.node_id: p for p in table.all() if p.state in ("alive", "draining") and p.node_id != table.self_id}
    candidates = [(cid, [n for n in locations.holders(cid) if n in alive]) for cid in store.list_ids()]
    candidates = [(cid, holders) for cid, holders in candidates if holders]
    for chunk_id, holders in rng.sample(candidates, min(per_round, len(candidates))):
        peer = alive[rng.choice(sorted(holders))]
        await _audit(store, locations, client, events, stats, chunk_id, peer)


async def _audit(store: DiskChunkStore, locations: LocationMap, client, events: EventLog,
                 stats: Counter, chunk_id: str, peer) -> None:
    mine = await asyncio.to_thread(store.get, chunk_id)
    if mine is None or hashlib.sha256(mine).hexdigest() != chunk_id:
        stats["skipped"] += 1                  # our own copy is bad: scrubbing deals with it
        return
    nonce = os.urandom(16)
    try:
        proof = await client.audit_chunk(peer, chunk_id, nonce)
    except Exception:
        stats["error"] += 1                    # unreachable: heartbeats decide what that means
        return
    expected = hmac.new(nonce, mine, hashlib.sha256).hexdigest()
    if proof is not None and hmac.compare_digest(proof, expected):
        stats["passed"] += 1
        locations.trust(chunk_id, peer.node_id)
        return
    reason = "says it doesn't hold the chunk" if proof is None else "wrong proof: its copy differs"
    stats["failed"] += 1
    locations.distrust(chunk_id, peer.node_id, config.AUDIT_DISTRUST_S)
    log.warning("audit: %s failed for chunk %s (%s)", peer.node_id, chunk_id[:12], reason)
    events.add("audit_failed", node=peer.node_id, chunk=chunk_id[:12], reason=reason)
