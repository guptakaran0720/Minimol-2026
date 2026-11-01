"""Node entry point.

    CLUSTER_KEY=... uvicorn node.main:app --host 0.0.0.0 --port 8000
    CLUSTER_KEY=... python -m node.main          # same, using BIND_HOST / PORT

Starts the peer API plus the background loops (heartbeat, inventory, gossip).
Other owners' parts are wired in when their modules exist:
- P1 node/index.py: verify_index(record, owner_pub) -> version
- P3 node/api_user.py: create_router(node: Node) -> APIRouter, served on this
  port but answering only requests from localhost
- P3 node/repair.py: Repairer(self_id, self_host, store, peers, client, locations).run_forever()
"""
from __future__ import annotations

import asyncio
import importlib
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import Depends, FastAPI, HTTPException, Request

from node import config
from node.api_peer import create_peer_app
from node.chunkstore import DiskChunkStore, IndexStore
from node.config import Settings
from node.contracts import Peer
from node.discovery import MdnsDiscovery, add_seeds, gossip_once
from node.inventory import LocationMap, inventory_once
from node.peer_client import HttpPeerClient
from node.peers import PeerTable, heartbeat_once

log = logging.getLogger("node")
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}


@dataclass
class Node:
    settings: Settings
    store: DiskChunkStore
    index_store: IndexStore
    peers: PeerTable
    client: HttpPeerClient
    locations: LocationMap


def build_node(settings: Settings) -> Node:
    me = Peer(node_id=settings.node_id, host_id=settings.host_id, addr=settings.advertise_addr,
              weight=settings.weight)
    store = DiskChunkStore(settings.data_dir, settings.quota_bytes)
    me.free_bytes = store.free_bytes()
    peers = PeerTable(me)
    add_seeds(peers, settings.seeds)
    return Node(
        settings=settings,
        store=store,
        index_store=IndexStore(settings.data_dir),
        peers=peers,
        client=HttpPeerClient(settings.node_id, settings.cluster_key, advertise_addr=settings.advertise_addr),
        locations=LocationMap(),
    )


def _optional(module: str, attr: str):
    try:
        return getattr(importlib.import_module(module), attr)
    except (ImportError, AttributeError):
        return None


def _unverified_index(record: dict, owner_pub: bytes) -> int:
    return int(record["version"])


async def _every(interval: float, name: str, fn) -> None:
    while True:
        try:
            await fn()
        except Exception:
            log.exception("%s loop failed; retrying", name)
        await asyncio.sleep(interval)


def localhost_only(request: Request) -> None:
    if request.client is None or request.client.host not in LOCAL_HOSTS:
        raise HTTPException(403, "user API is only served to localhost")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    node = build_node(settings)

    verify_index = _optional("node.index", "verify_index")
    if verify_index is None:
        log.warning("node/index.py not available: index signatures are NOT verified")
        verify_index = _unverified_index

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        n = node
        loops = [
            _every(config.HEARTBEAT_INTERVAL_S, "heartbeat",
                   lambda: heartbeat_once(n.peers, n.client, n.store.free_bytes)),
            _every(config.INVENTORY_INTERVAL_S, "inventory",
                   lambda: inventory_once(n.locations, n.peers, n.client, n.store)),
            _every(config.GOSSIP_INTERVAL_S, "gossip", lambda: gossip_once(n.peers, n.client)),
        ]
        repairer_cls = _optional("node.repair", "Repairer")
        if repairer_cls is not None:
            repairer = repairer_cls(settings.node_id, settings.host_id, n.store, n.peers, n.client, n.locations)
            app.state.repairer = repairer
            loops.append(repairer.run_forever())
        tasks = [asyncio.create_task(c) for c in loops]
        mdns = MdnsDiscovery(n.peers, settings.node_id, settings.advertise_addr, settings.cluster_key)
        if settings.mdns:
            await mdns.start()
        log.info("node %s (host %s) at %s, seeds %s", settings.node_id, settings.host_id,
                 settings.advertise_addr, settings.seeds or "none")
        try:
            yield
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await mdns.stop()
            await n.client.aclose()

    app = create_peer_app(settings, node.store, node.index_store, node.peers, verify_index, lifespan)
    app.state.node = node

    create_router = _optional("node.api_user", "create_router")
    if create_router is not None:
        app.include_router(create_router(node), dependencies=[Depends(localhost_only)])
    return app


_app: FastAPI | None = None


def __getattr__(name: str):
    """`uvicorn node.main:app` builds the app on first access, so importing this module needs no env."""
    global _app
    if name == "app":
        if _app is None:
            _app = create_app()
        return _app
    raise AttributeError(name)


def main() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    settings = Settings.from_env()
    uvicorn.run(create_app(settings), host=settings.bind_host, port=settings.port, log_level="warning")


if __name__ == "__main__":
    main()
