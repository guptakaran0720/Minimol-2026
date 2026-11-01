"""Peer table, heartbeats and health (ARCHITECTURE_DECISIONS.md sections 8-10).

- This node is in the table too (always alive), so it can hold replicas itself.
- get() returns dead and suspect peers as well; alive() returns only alive ones.
- Suspect after 2 missed heartbeats or the first failed transfer; dead after
  20 s with no successful contact. Dead peers keep being probed and come back.
- Tier 2 (slow) when a peer's 1 MiB ETA stays above 3x the cluster median for
  30 s; back to tier 1 after 30 s at or below it.

Everything runs on the event loop, so there are no locks.
"""
from __future__ import annotations

import asyncio
import statistics
import time
from collections.abc import Callable

from node import config
from node.contracts import CHUNK_SIZE, Peer

# Transfers smaller than this are dominated by latency, so they update rtt only.
MIN_BW_SAMPLE_BYTES = 64 * 1024


def _ewma(old: float, sample: float) -> float:
    return sample if old == 0.0 else config.EWMA_ALPHA * sample + (1 - config.EWMA_ALPHA) * old


def eta_1mib(p: Peer) -> float | None:
    """Estimated seconds to fetch one full chunk, or None with no bandwidth samples."""
    return None if p.bw_ewma <= 0 else p.rtt_ewma + CHUNK_SIZE / p.bw_ewma


class PeerTable:
    """Implements contracts.PeerTable."""

    def __init__(self, me: Peer, clock: Callable[[], float] = time.monotonic):
        self.self_id = me.node_id
        self.clock = clock
        self._peers: dict[str, Peer] = {me.node_id: me}
        self._last_ok: dict[str, float] = {me.node_id: clock()}
        self._missed: dict[str, int] = {}
        self._candidates: set[str] = set()      # addrs not yet confirmed by a heartbeat
        self._slow_since: dict[str, float] = {}
        self._fast_since: dict[str, float] = {}

    # ---- contracts.PeerTable ----

    def alive(self) -> list[Peer]:
        return [p for p in self._peers.values() if p.state == "alive"]

    def get(self, node_id: str) -> Peer | None:
        return self._peers.get(node_id)

    def record_transfer(self, node_id: str, nbytes: int, seconds: float) -> None:
        p = self._peers.get(node_id)
        if p is None:
            return
        seconds = max(seconds, 1e-6)
        if nbytes >= MIN_BW_SAMPLE_BYTES:
            p.bw_ewma = _ewma(p.bw_ewma, nbytes / seconds)
        else:
            p.rtt_ewma = _ewma(p.rtt_ewma, seconds)
        self._contact_ok(p)

    def record_failure(self, node_id: str) -> None:
        p = self._peers.get(node_id)
        if p is None or node_id == self.self_id:
            return
        p.cooldown_until = self.clock() + config.FAILURE_COOLDOWN_S
        if p.state == "alive":
            p.state = "suspect"

    # ---- membership ----

    def all(self) -> list[Peer]:
        return list(self._peers.values())

    @property
    def me(self) -> Peer:
        return self._peers[self.self_id]

    def add_candidate(self, addr: str) -> None:
        if addr and addr not in {p.addr for p in self._peers.values()}:
            self._candidates.add(addr)

    def candidates(self) -> list[str]:
        return sorted(self._candidates)

    def heartbeat_ok(self, addr: str, health: dict, rtt: float) -> Peer | None:
        """Apply a successful, authenticated /health reply from addr."""
        self._candidates.discard(addr)
        node_id = health["node_id"]
        if node_id == self.self_id:
            return None
        for other in self._peers.values():         # a restarted node may come back with a new id
            if other.addr == addr and other.node_id != node_id and other.node_id != self.self_id:
                other.state = "dead"
        p = self._peers.get(node_id)
        if p is None:
            p = Peer(node_id=node_id, host_id=health["host_id"], addr=addr)
            self._peers[node_id] = p
        p.addr = addr
        p.host_id = health["host_id"]
        p.free_bytes = int(health.get("free_bytes", 0))
        weight = float(health.get("weight", 1.0))
        p.weight = weight if weight > 0 else 1.0
        p.rtt_ewma = _ewma(p.rtt_ewma, rtt)
        self._contact_ok(p)
        return p

    def heartbeat_failed(self, node_id: str) -> None:
        p = self._peers.get(node_id)
        if p is None or node_id == self.self_id:
            return
        self._missed[node_id] = self._missed.get(node_id, 0) + 1
        silent_for = self.clock() - self._last_ok.get(node_id, self.clock())
        if silent_for >= config.DEAD_AFTER_S:
            p.state = "dead"
        elif self._missed[node_id] >= config.SUSPECT_AFTER_MISSED and p.state == "alive":
            p.state = "suspect"

    def set_self_free(self, free_bytes: int) -> None:
        self.me.free_bytes = free_bytes

    def _contact_ok(self, p: Peer) -> None:
        self._last_ok[p.node_id] = self.clock()
        self._missed[p.node_id] = 0
        p.state = "alive"

    # ---- tiers ----

    def update_tiers(self) -> None:
        etas = {p.node_id: e for p in self._peers.values() if (e := eta_1mib(p)) is not None}
        if len(etas) < 2:
            return
        limit = config.SLOW_FACTOR * statistics.median(etas.values())
        now = self.clock()
        for node_id, eta in etas.items():
            p = self._peers[node_id]
            if eta > limit:
                self._fast_since.pop(node_id, None)
                since = self._slow_since.setdefault(node_id, now)
                if p.tier == 1 and now - since >= config.SLOW_HOLD_S:
                    p.tier = 2
            else:
                self._slow_since.pop(node_id, None)
                since = self._fast_since.setdefault(node_id, now)
                if p.tier == 2 and now - since >= config.SLOW_HOLD_S:
                    p.tier = 1

    def snapshot(self) -> list[dict]:
        """For /stats and the dashboard."""
        now = self.clock()
        return [
            {
                "node_id": p.node_id, "host_id": p.host_id, "addr": p.addr, "state": p.state,
                "tier": p.tier, "rtt_ms": round(p.rtt_ewma * 1000, 1),
                "bw_mbps": round(p.bw_ewma * 8 / 1e6, 2), "free_bytes": p.free_bytes,
                "last_ok_s_ago": round(now - self._last_ok.get(p.node_id, now), 1),
                "self": p.node_id == self.self_id,
            }
            for p in self._peers.values()
        ]


async def heartbeat_once(table: PeerTable, client, self_free_bytes: Callable[[], int]) -> None:
    """Probe every known peer and every unconfirmed candidate address once, in parallel."""
    table.set_self_free(self_free_bytes())

    async def probe(node_id: str | None, addr: str) -> None:
        started = time.monotonic()
        try:
            health = await client.health(addr)
        except Exception:
            if node_id is not None:
                table.heartbeat_failed(node_id)
            return
        table.heartbeat_ok(addr, health, time.monotonic() - started)

    targets = [(p.node_id, p.addr) for p in table.all() if p.node_id != table.self_id]
    targets += [(None, a) for a in table.candidates() if a != table.me.addr]
    await asyncio.gather(*(probe(n, a) for n, a in targets))
    table.update_tiers()
