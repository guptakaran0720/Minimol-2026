"""Chunk location map built from peers' /inventory (ARCHITECTURE_DECISIONS.md section 7).

Soft state: every 10 s each reachable peer's list replaces what we knew about it.
Dead peers keep their last inventory, so repair can see which copy went missing.

The same round re-measures tier-2 (slow) peers by fetching one chunk they hold:
nothing else sends them traffic, so without this they could never leave tier 2.
"""
from __future__ import annotations

import asyncio
import hashlib
import random
import time
from collections.abc import Iterable

from node.chunkstore import DiskChunkStore
from node.peers import PeerTable


class LocationMap:
    """Implements contracts.LocationMap."""

    def __init__(self) -> None:
        self._by_chunk: dict[str, set[str]] = {}
        self._by_node: dict[str, set[str]] = {}

    def holders(self, chunk_id: str) -> set[str]:
        return set(self._by_chunk.get(chunk_id, ()))

    def note(self, chunk_id: str, node_id: str) -> None:
        self._by_chunk.setdefault(chunk_id, set()).add(node_id)
        self._by_node.setdefault(node_id, set()).add(chunk_id)

    def replace_inventory(self, node_id: str, chunk_ids: Iterable[str]) -> None:
        new = set(chunk_ids)
        old = self._by_node.get(node_id, set())
        for cid in old - new:
            holders = self._by_chunk.get(cid)
            if holders is not None:
                holders.discard(node_id)
                if not holders:
                    del self._by_chunk[cid]
        for cid in new - old:
            self._by_chunk.setdefault(cid, set()).add(node_id)
        self._by_node[node_id] = new

    def forget(self, node_id: str) -> None:
        self.replace_inventory(node_id, ())
        self._by_node.pop(node_id, None)

    def chunks_of(self, node_id: str) -> set[str]:
        return set(self._by_node.get(node_id, ()))

    def chunk_count(self) -> int:
        return len(self._by_chunk)


async def inventory_once(locations: LocationMap, table: PeerTable, client, store: DiskChunkStore) -> None:
    locations.replace_inventory(table.self_id, store.list_ids())

    async def pull(peer) -> None:
        try:
            ids = await client.get_inventory(peer)
        except Exception:
            return                      # heartbeats decide suspect/dead; keep the old list
        locations.replace_inventory(peer.node_id, ids)

    others = [p for p in table.all() if p.node_id != table.self_id and p.state != "dead"]
    await asyncio.gather(*(pull(p) for p in others))
    await asyncio.gather(*(probe_slow(locations, table, client, p) for p in others if p.tier == 2))


async def probe_slow(locations: LocationMap, table: PeerTable, client, peer) -> None:
    """One real chunk transfer from a slow peer, as a fresh bandwidth sample."""
    held = sorted(locations.chunks_of(peer.node_id))
    if not held:
        return
    chunk_id = random.choice(held)
    started = time.monotonic()
    try:
        blob = await client.get_chunk(peer, chunk_id)
    except Exception:
        table.record_failure(peer.node_id)
        return
    if blob is None or hashlib.sha256(blob).hexdigest() != chunk_id:
        return
    table.record_transfer(peer.node_id, len(blob), time.monotonic() - started)
