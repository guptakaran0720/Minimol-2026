"""Peer discovery: seed list plus /peers gossip (ARCHITECTURE_DECISIONS.md section 13).

Knowing one peer is enough to find all of them. Addresses learned here are
only candidates; a peer joins the table after an authenticated heartbeat.
mDNS is optional polish and not implemented yet.
"""
from __future__ import annotations

import asyncio

from node.peers import PeerTable


def add_seeds(table: PeerTable, seeds: list[str]) -> None:
    for addr in seeds:
        if addr != table.me.addr:
            table.add_candidate(addr)


async def gossip_once(table: PeerTable, client) -> None:
    async def ask(peer) -> list[dict]:
        try:
            return await client.get_peers(peer)
        except Exception:
            return []

    alive = [p for p in table.alive() if p.node_id != table.self_id]
    for entries in await asyncio.gather(*(ask(p) for p in alive)):
        for e in entries:
            if e.get("node_id") != table.self_id and table.get(e.get("node_id", "")) is None:
                table.add_candidate(e.get("addr", ""))
