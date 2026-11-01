"""Peer HTTP API (docs/TEAM_WORKFLOW.md, "HTTP API contract").

Every route needs a valid cluster HMAC, and every answer to an authenticated
request is signed back (X-Node, X-Resp-Sig), so a stranger on the Wi-Fi can't
pose as a node. Request bodies are capped while they stream in, so an oversized
upload is rejected before it is fully read. There is no DELETE route.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from node import auth, config
from node.chunkstore import DiskChunkStore, IndexStore, is_hex64
from node.config import Settings
from node.contracts import HashMismatch, QuotaExceeded
from node.peers import PeerTable

# verify_index(record, owner_pub) -> version; raises if the signature is bad (P1, node/index.py)
IndexVerifier = Callable[[dict, bytes], int]
ADDR_RE = re.compile(r"[A-Za-z0-9.\-]{1,253}:\d{1,5}")


@dataclass
class Caller:
    node_id: str
    body: bytes


class SignResponses:
    """ASGI middleware: sign the response to every request that passed auth.verify."""

    def __init__(self, app, key: bytes, node_id: str):
        self.app, self.key, self.node_id = app, key, node_id

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        start: dict = {}
        parts: list[bytes] = []

        async def capture(message):
            if message["type"] == "http.response.start":
                start.update(message)
            elif message["type"] == "http.response.body":
                parts.append(message.get("body", b""))
                if message.get("more_body"):
                    return
                body = b"".join(parts)
                headers = list(start.get("headers", []))
                request_sig = scope.get("state", {}).get("verified_sig")
                if request_sig:
                    sig = auth.sign_response(self.key, start["status"], request_sig, self.node_id, body)
                    headers += [(b"x-node", self.node_id.encode()), (b"x-resp-sig", sig.encode())]
                await send({**start, "headers": headers})
                await send({"type": "http.response.body", "body": body})
            else:
                await send(message)

        await self.app(scope, receive, capture)


async def read_capped(request: Request, limit: int) -> bytes:
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > limit:
                raise HTTPException(413, "body too large")
        except ValueError:
            raise HTTPException(400, "bad Content-Length") from None
    parts, size = [], 0
    async for part in request.stream():
        size += len(part)
        if size > limit:
            raise HTTPException(413, "body too large")
        parts.append(part)
    return b"".join(parts)


def create_peer_app(
    settings: Settings,
    store: DiskChunkStore,
    index_store: IndexStore,
    peers: PeerTable,
    verify_index: IndexVerifier,
    lifespan=None,
) -> FastAPI:
    app = FastAPI(title=f"peer {settings.node_id}", lifespan=lifespan)
    app.add_middleware(SignResponses, key=settings.cluster_key, node_id=settings.node_id)
    started = time.monotonic()

    def authed(limit: int):
        async def dep(request: Request) -> Caller:
            body = await read_capped(request, limit)
            try:
                node_id = auth.verify(settings.cluster_key, request.method, request.url.path,
                                      request.headers, body)
            except auth.AuthError as e:
                raise HTTPException(401, str(e)) from None
            request.state.verified_sig = request.headers["x-sig"]
            # A node that only knows us (e.g. we are its seed) announces its address.
            # X-Addr is not signed, so it is only a candidate until a heartbeat confirms it.
            addr = request.headers.get("x-addr", "")
            if peers.get(node_id) is None and ADDR_RE.fullmatch(addr):
                peers.add_candidate(addr)
            if settings.simulated_delay_ms:
                await asyncio.sleep(settings.simulated_delay_ms / 1000)
            return Caller(node_id, body)
        return dep

    no_body = Depends(authed(0))
    chunk_body = Depends(authed(config.CHUNK_BODY_MAX))
    index_body = Depends(authed(config.INDEX_BODY_MAX))

    def check_id(value: str, what: str) -> None:
        if not is_hex64(value):
            raise HTTPException(400, f"{what} must be 64 lowercase hex characters")

    @app.get("/health")
    async def health(_: Caller = no_body):
        return {
            "node_id": settings.node_id,
            "host_id": settings.host_id,
            "addr": settings.advertise_addr,
            "weight": settings.weight,
            "free_bytes": store.free_bytes(),
            "used_bytes": store.used_bytes(),
            "chunk_count": len(store.list_ids()),
            "uptime_s": round(time.monotonic() - started, 1),
        }

    @app.get("/peers")
    async def list_peers(_: Caller = no_body):
        return [{"node_id": p.node_id, "host_id": p.host_id, "addr": p.addr}
                for p in peers.all() if p.state != "dead"]

    @app.put("/chunks/{chunk_id}")
    async def put_chunk(chunk_id: str, caller: Caller = chunk_body):
        check_id(chunk_id, "chunk_id")
        try:
            new = await run_in_threadpool(store.put, chunk_id, caller.body)
        except HashMismatch:
            raise HTTPException(400, "sha256(body) does not match chunk_id") from None
        except QuotaExceeded as e:
            raise HTTPException(507, f"quota full: {e}") from None
        return JSONResponse({"chunk_id": chunk_id, "new": new}, status_code=201 if new else 200)

    @app.get("/chunks/{chunk_id}")
    async def get_chunk(chunk_id: str, _: Caller = no_body):
        check_id(chunk_id, "chunk_id")
        blob = await run_in_threadpool(store.get, chunk_id)
        if blob is None:
            raise HTTPException(404, "not stored here")
        return Response(blob, media_type="application/octet-stream")

    @app.head("/chunks/{chunk_id}")
    async def head_chunk(chunk_id: str, _: Caller = no_body):
        check_id(chunk_id, "chunk_id")
        return Response(status_code=200 if store.has(chunk_id) else 404)

    @app.get("/inventory")
    async def inventory(_: Caller = no_body):
        return store.list_ids()

    @app.put("/index/{owner_pub}")
    async def put_index(owner_pub: str, caller: Caller = index_body):
        check_id(owner_pub, "owner_pub")
        try:
            record = json.loads(caller.body)
        except ValueError:
            raise HTTPException(400, "body must be JSON") from None
        if not isinstance(record, dict):
            raise HTTPException(400, "body must be a JSON object")
        try:
            version = int(verify_index(record, bytes.fromhex(owner_pub)))
        except Exception:
            raise HTTPException(401, "bad index signature") from None
        if not await run_in_threadpool(index_store.put, owner_pub, record, version):
            raise HTTPException(409, "stored version is the same or newer")
        return JSONResponse({"version": version}, status_code=201)

    @app.get("/index/{owner_pub}")
    async def get_index(owner_pub: str, _: Caller = no_body):
        check_id(owner_pub, "owner_pub")
        record = await run_in_threadpool(index_store.get, owner_pub)
        if record is None:
            raise HTTPException(404, "no index for this owner")
        return record

    return app
