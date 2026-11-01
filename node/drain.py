"""Graceful drain: take a laptop out of the cluster without leaving any file degraded.

POST /drain {"draining": true} (localhost only) marks this node as draining:
- it takes no new chunks: PeerTable.alive() leaves it out here, and peers learn it
  from /health and do the same;
- it keeps serving reads;
- peers' repair stops counting its copies (state != "alive") and copies them to
  other laptops.

GET /drain reports progress. A chunk is safe when enough *other* live hosts hold it:
REPLICATION, or every other live host if fewer remain. When every chunk is safe the
node logs "drain_complete" and the dashboard says it's safe to power off.
"""
from __future__ import annotations

import time

from node.chunkstore import DiskChunkStore
from node.contracts import REPLICATION
from node.events import EventLog
from node.inventory import LocationMap
from node.peers import PeerTable


class Drain:
    def __init__(self) -> None:
        self.since: float | None = None
        self.announced = False

    @property
    def active(self) -> bool:
        return self.since is not None

    def start(self, table: PeerTable, events: EventLog) -> None:
        if self.active:
            return
        self.since, self.announced = time.time(), False
        table.set_self_draining(True)
        events.add("drain_started", node=table.self_id)

    def stop(self, table: PeerTable, events: EventLog) -> None:
        if not self.active:
            return
        self.since = None
        table.set_self_draining(False)
        events.add("drain_cancelled", node=table.self_id)

    def status(self, store: DiskChunkStore, locations: LocationMap, table: PeerTable) -> dict:
        others = {p.host_id for p in table.alive() if p.node_id != table.self_id}
        target = min(REPLICATION, len(others))
        unsafe = []
        ids = store.list_ids()
        for chunk_id in ids:
            hosts = set()
            for n in locations.holders(chunk_id):
                p = table.get(n)
                if n != table.self_id and p is not None and p.state == "alive":
                    hosts.add(p.host_id)
            if target == 0 or len(hosts) < target:
                unsafe.append(chunk_id)
        return {
            "draining": self.active,
            "since": self.since,
            "chunks": len(ids),
            "safe_chunks": len(ids) - len(unsafe),
            "unsafe_sample": [c[:12] for c in unsafe[:10]],
            "other_live_hosts": len(others),
            "copies_needed_elsewhere": target,
            "safe_to_power_off": self.active and target > 0 and not unsafe,
        }

    async def check_once(self, store: DiskChunkStore, locations: LocationMap, table: PeerTable,
                         events: EventLog) -> None:
        if not self.active or self.announced:
            return
        status = self.status(store, locations, table)
        if status["safe_to_power_off"]:
            self.announced = True
            events.add("drain_complete", node=table.self_id, chunks=status["chunks"],
                       seconds=round(time.time() - self.since, 1))
