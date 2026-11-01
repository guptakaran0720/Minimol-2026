"""Background scrubbing: find corrupt chunks before anyone reads them.

Every second, re-hash the next SCRUB_PER_S stored chunks (DiskChunkStore.scrub_some).
A chunk that fails is quarantined and dropped from this node's inventory at once,
so the location map counts one copy fewer. P3's repair loop on another holder then
sees the chunk short of R copies and copies a good one back, often to this node.

Nothing here talks to the network: healing reuses the normal inventory + repair path.
"""
from __future__ import annotations

import asyncio
import logging

from node.chunkstore import DiskChunkStore
from node.events import EventLog
from node.inventory import LocationMap

log = logging.getLogger("node.scrub")


async def scrub_once(store: DiskChunkStore, locations: LocationMap, self_id: str,
                     events: EventLog, per_round: int) -> None:
    result = await asyncio.to_thread(store.scrub_some, per_round)
    for chunk_id in result.quarantined or []:
        log.warning("scrub: chunk %s failed its hash check; quarantined", chunk_id[:12])
        events.add("chunk_quarantined", node=self_id, chunk=chunk_id[:12], reason="failed hash check")
    for chunk_id in result.missing or []:
        log.warning("scrub: chunk %s vanished from disk", chunk_id[:12])
        events.add("chunk_missing", node=self_id, chunk=chunk_id[:12], reason="file missing on disk")
    if result.quarantined or result.missing:
        # Peers learn at their next /inventory pull; our own map should know now.
        locations.replace_inventory(self_id, store.list_ids())
