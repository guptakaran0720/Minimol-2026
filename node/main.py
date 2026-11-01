"""Node entry point.

    CLUSTER_KEY=... uvicorn node.main:app --host 0.0.0.0 --port 8000
    CLUSTER_KEY=... python -m node.main          # same, using BIND_HOST / PORT

Starts the peer API plus the background loops (heartbeat, inventory, gossip,
scrub, audit, drain check). Localhost-only routes for the dashboard and tools:
GET /events (timeline), GET /transfers (per-chunk upload/download log with peer
IP and MAC), GET+POST /drain (graceful leave), GET /metrics (Prometheus text).
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
import os
import random
from collections import Counter
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import Body, Depends, FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from node import config
from node import metrics
from node.api_peer import create_peer_app
from node.audit import audit_once
from node.chunkstore import DiskChunkStore, IndexStore
from node.config import Settings, user_api_client_ok
from node.contracts import Peer
from node.discovery import MdnsDiscovery, add_seeds, gossip_once
from node.drain import Drain
from node.events import EventLog, TransferLog
from node.inventory import LocationMap, inventory_once
from node.peer_client import HttpPeerClient
from node.peers import PeerTable, heartbeat_once
from node.scrub import scrub_once

log = logging.getLogger("node")
UI_DIST = Path(__file__).resolve().parent.parent / "ui" / "dist"


@dataclass
class Node:
    settings: Settings
    store: DiskChunkStore
    index_store: IndexStore
    peers: PeerTable
    client: HttpPeerClient
    locations: LocationMap
    events: EventLog = field(default_factory=EventLog)
    transfers: TransferLog = field(default_factory=TransferLog)
    drain: Drain = field(default_factory=Drain)
    audit_stats: Counter = field(default_factory=Counter)


def build_node(settings: Settings) -> Node:
    me = Peer(node_id=settings.node_id, host_id=settings.host_id, addr=settings.advertise_addr,
              weight=settings.weight)
    store = DiskChunkStore(settings.data_dir, settings.quota_bytes)
    me.free_bytes = store.free_bytes()
    events = EventLog()
    peers = PeerTable(me, events=events)
    peers.set_mac(settings.node_id, settings.mac)
    add_seeds(peers, settings.seeds)
    node = Node(
        settings=settings,
        store=store,
        index_store=IndexStore(settings.data_dir),
        peers=peers,
        client=HttpPeerClient(settings.node_id, settings.cluster_key, advertise_addr=settings.advertise_addr),
        locations=LocationMap(),
        events=events,
    )
    node.client.on_transfer = lambda direction, peer, chunk_id, nbytes, seconds: node.transfers.add(
        direction, chunk_id, peer.node_id, peer.addr, peers.mac(peer.node_id), nbytes, seconds)
    node.client.is_distrusted = node.locations.distrusted
    node.client.on_fresh_copy = node.locations.trust
    return node


def timeline(node: Node, repairer=None, limit: int = 200) -> dict:
    """P2 events plus P3's repair events, newest first, for the dashboard."""
    merged = [{**e, "source": "node"} for e in node.events.since(0)]
    for e in list(getattr(repairer, "events", None) or []):
        merged.append({**e, "source": "repair"})
    merged.sort(key=lambda e: e["t"], reverse=True)
    return {"node_id": node.settings.node_id, "events": merged[:limit], "scrub": node.store.scrub_stats}


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


def localhost_only(settings: Settings):
    def check(request: Request) -> None:
        host = request.client.host if request.client else None
        if not user_api_client_ok(host, settings.user_api_allow):
            raise HTTPException(403, f"user API is only served to localhost (request from {host}; see USER_API_ALLOW)")
    return check


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
        if settings.scrub_per_s > 0:
            loops.append(_every(config.SCRUB_INTERVAL_S, "scrub", lambda: scrub_once(
                n.store, n.locations, settings.node_id, n.events, settings.scrub_per_s)))
        if settings.audit_per_round > 0:
            rng = random.Random()
            loops.append(_every(config.AUDIT_INTERVAL_S, "audit", lambda: audit_once(
                n.store, n.locations, n.peers, n.client, n.events, settings.audit_per_round, n.audit_stats, rng)))
        loops.append(_every(config.DRAIN_CHECK_INTERVAL_S, "drain",
                            lambda: n.drain.check_once(n.store, n.locations, n.peers, n.events)))
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
        n.events.add("node_started", node=settings.node_id, chunks=len(n.store.list_ids()))
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

    local = [Depends(localhost_only(settings))]

    @app.get("/events", dependencies=local)
    async def events():
        return timeline(node, getattr(app.state, "repairer", None))

    @app.get("/transfers", dependencies=local)
    async def transfers(chunks: str = "", limit: int = 500):
        """Chunks this node uploaded to / downloaded from peers, newest first, with each peer's IP and MAC.
        `chunks`: comma-separated chunk ids to filter on (the dashboard passes one file's chunks)."""
        wanted = {c for c in chunks.split(",") if c} or None
        return {"node_id": settings.node_id, "mac": settings.mac or None,
                "transfers": node.transfers.recent(wanted, max(1, min(limit, 5000)))}

    @app.get("/drain", dependencies=local)
    async def drain_status():
        return node.drain.status(node.store, node.locations, node.peers)

    @app.post("/drain", dependencies=local)
    async def drain_set(draining: bool = Body(..., embed=True)):
        (node.drain.start if draining else node.drain.stop)(node.peers, node.events)
        return node.drain.status(node.store, node.locations, node.peers)

    @app.get("/metrics", dependencies=local, response_class=PlainTextResponse)
    async def prometheus_metrics():
        return PlainTextResponse(metrics.render(node, app.state.served, getattr(app.state, "repairer", None)),
                                 media_type="text/plain; version=0.0.4")

    create_router = _optional("node.api_user", "create_router")
    if create_router is not None:
        app.include_router(create_router(node), dependencies=[Depends(localhost_only(settings))])

    ui_dir = Path(os.environ.get("UI_DIR", UI_DIST))
    if (ui_dir / "index.html").exists():
        # Static files only; the data they show comes from the localhost-only user API.
        app.mount("/ui", StaticFiles(directory=ui_dir, html=True), name="ui")
        app.add_api_route("/", lambda: RedirectResponse("/ui/"), include_in_schema=False)
    else:
        log.info("dashboard not built (%s missing): run `npm run build` in ui/", ui_dir / "index.html")
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
