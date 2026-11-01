"""Placement and retrieval ranking.

Placement: tiered weighted rendezvous hashing over static weights
(ARCHITECTURE_DECISIONS.md section 8). Live metrics are deliberately kept out of
placement so the best peers for a chunk don't change every few seconds.

Retrieval: rank holders by estimated fetch time, ETA = rtt + size / bandwidth (section 9).
"""
from __future__ import annotations

import hashlib
import math
import statistics
import time

from node.contracts import CHUNK_SIZE, Peer

MIN_FREE_BYTES = 2 * CHUNK_SIZE
PRIOR_RTT_S = 0.010              # used until a peer has real transfer samples
PRIOR_BW_BPS = 10 * 1024 * 1024


def hrw_u(chunk_id: str, node_id: str) -> float:
    """Uniform value strictly inside (0, 1), derived from (chunk, node)."""
    digest = hashlib.sha256(f"{chunk_id}:{node_id}".encode()).digest()
    return (int.from_bytes(digest[:8], "big") + 0.5) / 2**64


def hrw_key(chunk_id: str, peer: Peer) -> float:
    """Weighted rendezvous key -w / ln(u). P(peer ranks first) = w / sum(w)."""
    weight = max(peer.weight, 1e-9)
    return -weight / math.log(hrw_u(chunk_id, peer.node_id))


def rank_for_placement(chunk_id: str, peers: list[Peer], exclude_hosts: set[str]) -> list[Peer]:
    """Eligible peers in preference order, at most one per host_id.

    Tier 1 (healthy) always ranks before tier 2 (slow). Within a tier the
    rendezvous key decides, so the order is deterministic and a peer
    joining or leaving moves only the chunks it wins or held.
    """
    eligible = [
        p for p in peers
        if p.state == "alive" and p.free_bytes >= MIN_FREE_BYTES and p.host_id not in exclude_hosts
    ]
    eligible.sort(key=lambda p: (p.tier, -hrw_key(chunk_id, p)))
    ranked, seen_hosts = [], set()
    for p in eligible:
        if p.host_id not in seen_hosts:
            seen_hosts.add(p.host_id)
            ranked.append(p)
    return ranked


def eta_seconds(peer: Peer, size: int, prior_rtt: float, prior_bw: float) -> float:
    rtt = peer.rtt_ewma if peer.rtt_ewma > 0 else prior_rtt
    bw = peer.bw_ewma if peer.bw_ewma > 0 else prior_bw
    return rtt + size / bw


def rank_for_retrieval(holders: list[Peer], size: int = CHUNK_SIZE) -> list[Peer]:
    """Holders ordered by estimated fetch time; dead peers dropped.

    Alive peers go before suspect ones and peers in failure cooldown go last.
    Peers without samples get the median of the peers that have them.
    """
    now = time.monotonic()
    candidates = [p for p in holders if p.state != "dead"]
    rtts = [p.rtt_ewma for p in candidates if p.rtt_ewma > 0]
    bws = [p.bw_ewma for p in candidates if p.bw_ewma > 0]
    prior_rtt = statistics.median(rtts) if rtts else PRIOR_RTT_S
    prior_bw = statistics.median(bws) if bws else PRIOR_BW_BPS
    return sorted(
        candidates,
        key=lambda p: (
            p.cooldown_until > now,
            p.state != "alive",
            eta_seconds(p, size, prior_rtt, prior_bw),
        ),
    )


def repair_order(chunk_id: str, live_holder_ids: list[str]) -> list[str]:
    """Deterministic repair priority. Every holder computes the same order, so
    order[0] is the leader; order[k] takes over if the chunk is still short
    after 2k rounds (see repair.py)."""
    return sorted(set(live_holder_ids), key=lambda n: -hrw_u(chunk_id, n))


def repair_leader(chunk_id: str, live_holder_ids: list[str]) -> str:
    return repair_order(chunk_id, live_holder_ids)[0]
