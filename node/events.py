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
