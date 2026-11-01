"""Peer discovery: seed list, /peers gossip, and optional mDNS (ARCHITECTURE_DECISIONS.md section 13).

Knowing one peer is enough to find all of them. Addresses learned here are
only candidates; a peer joins the table after an authenticated heartbeat.

mDNS (MDNS=1, the default) announces this node as _minimol._tcp on the LAN and
browses for others. Venue Wi-Fi often blocks multicast, so it is best-effort:
if it fails, seeds and gossip still work. The TXT record carries a tag derived
from the cluster key, so nodes from other clusters aren't probed.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import socket

from node.peers import PeerTable

log = logging.getLogger("node.discovery")
SERVICE = "_minimol._tcp.local."


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


def cluster_tag(key: bytes) -> str:
    return hmac.new(key, b"minimol-2026/mdns-tag/v1", hashlib.sha256).hexdigest()[:16]


def candidate_from_service(properties: dict, addresses: list[str], port: int | None,
                           tag: str, self_id: str) -> str | None:
    """The addr to probe for one mDNS service record, or None if it isn't ours to probe."""
    props = {(k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
             for k, v in properties.items() if v is not None}
    if props.get("tag") != tag or props.get("node_id") in (None, self_id) or not addresses or not port:
        return None
    return f"{addresses[0]}:{port}"


class MdnsDiscovery:
    def __init__(self, table: PeerTable, node_id: str, advertise_addr: str, cluster_key: bytes):
        self.table = table
        self.node_id = node_id
        self.advertise_addr = advertise_addr
        self.tag = cluster_tag(cluster_key)
        self.azc = None
        self.browser = None
        self.info = None

    async def start(self) -> bool:
        try:
            from zeroconf import IPVersion
            from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf

            host, port = self.advertise_addr.rsplit(":", 1)
            self.azc = AsyncZeroconf(ip_version=IPVersion.V4Only)
            self.info = AsyncServiceInfo(
                SERVICE, f"{self.node_id}.{SERVICE}", addresses=[socket.inet_aton(host)], port=int(port),
                properties={"node_id": self.node_id, "tag": self.tag},
            )
            await self.azc.async_register_service(self.info)
            loop = asyncio.get_running_loop()

            def on_change(zeroconf, service_type, name, state_change):
                loop.call_soon_threadsafe(lambda: loop.create_task(self._resolve(service_type, name)))

            self.browser = AsyncServiceBrowser(self.azc.zeroconf, SERVICE, handlers=[on_change])
            log.info("mDNS: announcing %s as %s", self.advertise_addr, self.node_id)
            return True
        except Exception as e:
            log.warning("mDNS unavailable (%s); using seeds and gossip only", e)
            await self.stop()
            return False

    async def _resolve(self, service_type: str, name: str) -> None:
        from zeroconf.asyncio import AsyncServiceInfo

        info = AsyncServiceInfo(service_type, name)
        try:
            if not await info.async_request(self.azc.zeroconf, 3000):
                return
        except Exception:
            return
        addr = candidate_from_service(info.properties or {}, info.parsed_addresses(), info.port,
                                      self.tag, self.node_id)
        if addr and addr != self.advertise_addr:
            self.table.add_candidate(addr)

    async def stop(self) -> None:
        if self.browser is not None:
            await self.browser.async_cancel()
            self.browser = None
        if self.azc is not None:
            if self.info is not None:
                try:
                    await self.azc.async_unregister_service(self.info)
                except Exception:
                    pass
            await self.azc.async_close()
            self.azc = None
