"""Peer-driven replica repair (ARCHITECTURE_DECISIONS.md section 11).

Every node checks the chunks it holds. A chunk is short when fewer than R
distinct live hosts hold it. Only the deterministic leader copies it; the
holder ranked k takes over after 2k short rounds in case the leader is
silently gone. Copies are content-addressed PUTs, so two repairers racing
can only over-replicate, never lose a copy.

Invariants:
- never copy a blob whose hash doesn't match its id
- never count two copies on one host_id
- never repair while a holder is only suspect (it may come back)
- never delete anything, except a chunk the owner deleted: a peer that answers a
  repair copy with a tombstone reveals the owner's delete token, and we drop our copy
  only if sha256(token) matches the delete hash stored with it
- a copy carries the chunk's delete hash, so the owner can still delete it later
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections import deque

from node.contracts import REPLICATION, ChunkDeleted, ChunkStore, LocationMap, PeerClient, PeerTable
from node.routing import rank_for_placement, repair_order

log = logging.getLogger(__name__)


def _token_matches(token: str, delete_hash: str) -> bool:
    try:
        return hashlib.sha256(bytes.fromhex(token)).hexdigest() == delete_hash
    except ValueError:
        return False


class Repairer:
    def __init__(
        self,
        self_id: str,
        self_host: str,
        store: ChunkStore,
        peers: PeerTable,
        client: PeerClient,
        locations: LocationMap,
        replication: int = REPLICATION,
        interval: float = 10.0,
        max_parallel: int = 4,
        takeover_rounds: int = 2,
    ):
        self.self_id = self_id
        self.self_host = self_host
        self.store = store
        self.peers = peers
        self.client = client
        self.locations = locations
        self.replication = replication
        self.interval = interval
        self.max_parallel = max_parallel
        self.takeover_rounds = takeover_rounds
        self.short_rounds: dict[str, int] = {}
        self.last_stats: dict = {}
        self.events: deque[dict] = deque(maxlen=200)   # shown on the dashboard
        self.total_copies = 0

    def live_holders(self, chunk_id: str) -> tuple[dict[str, str], bool]:
        """(host_id -> node_id of alive holders including this node, any holder suspect?)."""
        live = {self.self_host: self.self_id}
        suspect = False
        for n in sorted(self.locations.holders(chunk_id)):
            if n == self.self_id:
                continue
            p = self.peers.get(n)
            if p is None:
                continue
            if p.state == "alive":
                live.setdefault(p.host_id, n)
            elif p.state == "suspect":
                suspect = True
        return live, suspect

    async def run_once(self) -> dict:
        stats = {"checked": 0, "healthy": 0, "waiting": 0, "short": 0, "repairing": 0,
                 "copies": 0, "degraded": 0, "skipped_corrupt": 0, "deleted": 0}
        work = []
        for cid in self.store.list_ids():
            stats["checked"] += 1
            live, suspect = self.live_holders(cid)
            if len(live) >= self.replication:
                self.short_rounds.pop(cid, None)
                stats["healthy"] += 1
                continue
            if suspect:
                stats["waiting"] += 1
                continue
            stats["short"] += 1
            rounds = self.short_rounds[cid] = self.short_rounds.get(cid, 0) + 1
            rank = repair_order(cid, list(live.values())).index(self.self_id)
            if rank * self.takeover_rounds >= rounds:
                continue          # a higher-ranked holder should handle it this round
            work.append((cid, live))

        stats["repairing"] = len(work)
        sem = asyncio.Semaphore(self.max_parallel)
        for outcome in await asyncio.gather(*(self._repair(cid, live, sem) for cid, live in work)):
            stats[outcome[0]] += 1
            stats["copies"] += outcome[1]
        self.total_copies += stats["copies"]
        self.last_stats = stats | {"at": time.time()}
        return stats

    async def _repair(self, cid: str, live: dict[str, str], sem: asyncio.Semaphore) -> tuple[str, int]:
        async with sem:
            blob = self.store.get(cid)
            if blob is None:
                return "degraded", 0
            if hashlib.sha256(blob).hexdigest() != cid:
                self.events.append({"t": time.time(), "kind": "corrupt_local", "chunk": cid[:12]})
                return "skipped_corrupt", 0
            hosts = set(live)
            copies = 0
            delete_hash = self.store.delete_hash(cid) if hasattr(self.store, "delete_hash") else None
            for p in rank_for_placement(cid, self.peers.alive(), hosts):
                if len(hosts) >= self.replication:
                    break
                started = time.monotonic()
                try:
                    if await self.client.head_chunk(p, cid):     # someone else already repaired it
                        self.locations.note(cid, p.node_id)
                        hosts.add(p.host_id)
                        continue
                    if await self.client.put_chunk(p, cid, blob, delete_hash) and await self.client.head_chunk(p, cid):
                        self.peers.record_transfer(p.node_id, len(blob), time.monotonic() - started)
                        self.locations.note(cid, p.node_id)
                        hosts.add(p.host_id)
                        copies += 1
                        self.events.append({"t": time.time(), "kind": "copied", "chunk": cid[:12], "to": p.node_id})
                        continue
                except ChunkDeleted as gone:
                    # The owner deleted this chunk while we were away. Trust the token only if it
                    # matches the hash stored with our copy, then finish the owner's delete here.
                    if delete_hash and _token_matches(gone.token, delete_hash):
                        self.store.delete(cid, gone.token)
                        self.short_rounds.pop(cid, None)
                        self.events.append({"t": time.time(), "kind": "deleted", "chunk": cid[:12], "to": p.node_id})
                        return "deleted", copies
                except Exception:
                    pass
                self.peers.record_failure(p.node_id)
            if len(hosts) >= self.replication:
                self.short_rounds.pop(cid, None)
                return "healthy", copies
            return "degraded", copies

    async def run_forever(self) -> None:
        while True:
            try:
                await self.run_once()
            except Exception:
                log.exception("repair round failed")
            await asyncio.sleep(self.interval)
