"""In-memory event log for the dashboard timeline.

P2 parts record what happens to the cluster as it happens: a peer joins, goes
suspect, dies or comes back; a peer moves between tiers; the scrubber finds and
quarantines a corrupt chunk. GET /events (localhost only, see main.py) merges
these with P3's repair events so the demo story reads top to bottom:

    laptop-3 suspect -> laptop-3 dead -> chunk ab12 copied to laptop-1 -> ...

Events are kept in memory only (last MAX_EVENTS); they are for watching, not auditing.
"""
from __future__ import annotations

import itertools
import time
from collections import deque

MAX_EVENTS = 500


class EventLog:
    def __init__(self, clock=time.time, maxlen: int = MAX_EVENTS):
        self.clock = clock
        self._events: deque[dict] = deque(maxlen=maxlen)
        self._seq = itertools.count(1)

    def add(self, kind: str, **fields) -> dict:
        event = {"seq": next(self._seq), "t": self.clock(), "kind": kind, **fields}
        self._events.append(event)
        return event

    def since(self, seq: int = 0) -> list[dict]:
        """Events newer than seq, oldest first."""
        return [e for e in self._events if e["seq"] > seq]

    def __len__(self) -> int:
        return len(self._events)


class TransferLog:
    """Recent chunk transfers made by this node, for the dashboard's per-file Logs.

    One entry per successful PUT (direction "upload": this node -> peer) or GET
    (direction "download": peer -> this node), with the peer's address and MAC.
    Repair copies and probes are logged too: they are real transfers. Memory only.
    """

    def __init__(self, clock=time.time, maxlen: int = 5000):
        self.clock = clock
        self._entries: deque[dict] = deque(maxlen=maxlen)
        self._seq = itertools.count(1)

    def add(self, direction: str, chunk_id: str, node_id: str, addr: str, mac: str | None,
            nbytes: int, seconds: float) -> dict:
        entry = {"seq": next(self._seq), "t": self.clock(), "direction": direction, "chunk_id": chunk_id,
                 "node_id": node_id, "addr": addr, "ip": addr.rsplit(":", 1)[0], "mac": mac,
                 "bytes": nbytes, "ms": round(seconds * 1000, 1)}
        self._entries.append(entry)
        return entry

    def recent(self, chunk_ids: set[str] | None = None, limit: int = 500) -> list[dict]:
        """Newest first, optionally only for these chunk ids."""
        out = []
        for e in reversed(self._entries):
            if chunk_ids is None or e["chunk_id"] in chunk_ids:
                out.append(e)
                if len(out) >= limit:
                    break
        return out
