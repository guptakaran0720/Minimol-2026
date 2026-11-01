"""User-facing API (P3). Only reachable from this machine.

Wiring: P2's node/main.py calls create_router(node) and serves the routes on the
node's port behind its own localhost-only dependency. Tests pass a UserState instead.

The node starts locked. POST /recover {username, passphrase} derives the owner keys,
unlocks the node and pulls the owner's signed index from peers, so the same call
serves "log in on my laptop" and "recover everything on a fresh laptop".

Uploads take the raw file as the request body (?name=...), which avoids a
multipart dependency and lets the dashboard send File objects with fetch().

Crypto comes from P1's modules (load_codec). Until they exist, DEV_FAKE_CODEC=1
swaps in tests/fakes.FakeCodec so the network path can be exercised; it does NOT
encrypt or compress, and /stats says so.
"""
from __future__ import annotations

import importlib
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

from node.contracts import CHUNK_SIZE, Codec, LocationMap, PeerClient, PeerTable, owner_salt
from node.repair import Repairer
from node.transfer import ChunkUnavailable, IntegrityError, NotEnoughPeers, Transfer

log = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 256 * 1024 * 1024
MIN_PASSPHRASE_LEN = 12
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}

# Where each Codec function lives in P1's code (node/contracts.py, Codec).
CODEC_MODULES = {
    "node.pipeline": ("encode_chunk", "decode_chunk", "sha256_hex"),
    "node.keys": ("derive_master", "wrap_key", "unwrap_key"),
    "node.manifest": ("seal_manifest", "open_manifest"),
    "node.index": ("seal_index", "verify_index", "open_index"),
}


def load_codec() -> tuple[Codec | None, str]:
    """P1's functions as one Codec, or (None, reason) if any are missing."""
    if os.environ.get("DEV_FAKE_CODEC") == "1":
        from tests.fakes import FakeCodec

        log.warning("DEV_FAKE_CODEC=1: files are NOT encrypted or compressed")
        return FakeCodec(), "FAKE (DEV_FAKE_CODEC=1): no encryption, no compression"
    functions = {}
    for module, names in CODEC_MODULES.items():
        try:
            mod = importlib.import_module(module)
        except ImportError:
            return None, f"{module} is not available yet (P1)"
        for name in names:
            if not callable(fn := getattr(mod, name, None)):
                return None, f"{module}.{name} is not available yet (P1)"
            functions[name] = fn
    return SimpleNamespace(**functions), "P1 pipeline"


@dataclass
class UserState:
    codec: Codec | None
    peers: PeerTable
    client: PeerClient
    locations: LocationMap
    data_dir: Path
    repairer: Repairer | None = None
    chunk_size: int = CHUNK_SIZE
    allowed_hosts: set[str] = field(default_factory=lambda: set(LOCAL_HOSTS))
    codec_label: str = "injected"
    self_id: str | None = None
    transfer: Transfer | None = None
    username: str | None = None

    @classmethod
    def from_node(cls, node) -> UserState:
        """Build from P2's main.Node (settings, peers, client, locations)."""
        codec, label = load_codec()
        if codec is None:
            log.warning("user API is up but locked: %s", label)
        return cls(codec=codec, peers=node.peers, client=node.client, locations=node.locations,
                   data_dir=Path(node.settings.data_dir) / "user", codec_label=label,
                   self_id=node.settings.node_id)


class RecoverBody(BaseModel):
    username: str
    passphrase: str


def create_router(source) -> APIRouter:
    """Routes bound to one node. `source` is P2's Node or a ready UserState."""
    st = source if isinstance(source, UserState) else UserState.from_node(source)
    router = APIRouter()

    def local(request: Request) -> UserState:
        host = request.client.host if request.client else ""
        if host not in st.allowed_hosts:
            raise HTTPException(403, "user API is only available on this machine")
        return st

    def with_codec(s: UserState = Depends(local)) -> UserState:
        if s.codec is None:
            raise HTTPException(503, f"crypto pipeline missing: {s.codec_label}")
        return s

    def unlocked(s: UserState = Depends(with_codec)) -> Transfer:
        if s.transfer is None:
            raise HTTPException(401, "node is locked: POST /recover with username and passphrase")
        return s.transfer

    @router.post("/recover")
    async def recover(body: RecoverBody, s: UserState = Depends(with_codec)) -> dict:
        username = body.username.strip()
        if not username:
            raise HTTPException(400, "username is required")
        if len(body.passphrase) < MIN_PASSPHRASE_LEN:
            raise HTTPException(400, f"passphrase must be at least {MIN_PASSPHRASE_LEN} characters")
        keys = s.codec.derive_master(body.passphrase, owner_salt(username))
        s.data_dir.mkdir(parents=True, exist_ok=True)
        transfer = Transfer(
            keys, s.codec, s.peers, s.client, s.locations,
            catalog_path=s.data_dir / f"catalog-{keys.sign_pub.hex()[:16]}.json",
            chunk_size=s.chunk_size,
        )
        restored = await transfer.recover()
        s.transfer, s.username = transfer, username
        return {"username": username, "files_restored": restored, "files": transfer.list_files()}

    @router.post("/files", status_code=201)
    async def upload(
        request: Request,
        name: str = Query(..., min_length=1, max_length=255),
        placement: Literal["tiered", "random"] = "tiered",     # "random" = bench.py baseline only
        transfer: Transfer = Depends(unlocked),
    ) -> dict:
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, f"upload limit is {MAX_UPLOAD_BYTES} bytes")
        # Spool to disk first so memory stays bounded and the size cap holds
        # even without a Content-Length header.
        with tempfile.TemporaryFile() as spool:
            received = 0
            async for part in request.stream():
                received += len(part)
                if received > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, f"upload limit is {MAX_UPLOAD_BYTES} bytes")
                spool.write(part)
            spool.seek(0)
            try:
                result = await transfer.upload(spool, name, placement)
            except NotEnoughPeers as e:
                raise HTTPException(503, f"not enough peers accepted the data: {e}") from e
        out = asdict(result)
        out["compression_ratio"] = (round(result.encoded_bytes / result.original_bytes, 4)
                                    if result.original_bytes else None)
        return out

    @router.get("/files")
    async def list_files(transfer: Transfer = Depends(unlocked)) -> list[dict]:
        return transfer.list_files()

    @router.get("/files/{file_uuid}")
    async def download(
        file_uuid: str,
        retrieval: Literal["eta", "random"] = "eta",            # "random" = bench.py baseline only
        transfer: Transfer = Depends(unlocked),
    ) -> FileResponse:
        entry = transfer.catalog.get(file_uuid)
        if entry is None:
            raise HTTPException(404, "unknown file")
        # Write to a temp file and only serve it after the whole-file hash checks out.
        fd, path = tempfile.mkstemp(prefix="dl-")
        try:
            with os.fdopen(fd, "wb") as dst:
                await transfer.download(file_uuid, dst, retrieval)
        except ChunkUnavailable as e:
            os.unlink(path)
            raise HTTPException(503, f"chunk unavailable on every reachable peer: {e}") from e
        except IntegrityError as e:
            os.unlink(path)
            raise HTTPException(502, str(e)) from e
        except BaseException:
            os.unlink(path)
            raise
        return FileResponse(
            path,
            filename=entry["name"],
            media_type="application/octet-stream",
            headers={"X-File-SHA256": entry["sha256"]},
            background=BackgroundTask(os.unlink, path),
        )

    @router.get("/files/{file_uuid}/map")
    async def chunk_map(file_uuid: str, transfer: Transfer = Depends(unlocked)) -> dict:
        if file_uuid not in transfer.catalog:
            raise HTTPException(404, "unknown file")
        return {
            "file_uuid": file_uuid,
            "status": transfer.file_status(file_uuid),
            "replication": transfer.replication,
            "chunks": transfer.chunk_map(file_uuid),
        }

    @router.get("/stats")
    async def stats(request: Request, s: UserState = Depends(local)) -> dict:
        """Dashboard feed. Works while locked (peers and repair only)."""
        if callable(snapshot := getattr(s.peers, "snapshot", None)):
            peers = snapshot()
        else:
            list_all = getattr(s.peers, "all", None)
            peers = [
                {"node_id": p.node_id, "host_id": p.host_id, "addr": p.addr, "state": p.state,
                 "tier": p.tier, "rtt_ms": round(p.rtt_ewma * 1000, 2),
                 "bw_mbps": round(p.bw_ewma * 8 / 1e6, 2), "free_bytes": p.free_bytes,
                 "self": p.node_id == s.self_id}
                for p in (list_all() if callable(list_all) else s.peers.alive())
            ]
        files = s.transfer.list_files() if s.transfer else []
        repairer = s.repairer or getattr(request.app.state, "repairer", None)
        return {
            "node_id": s.self_id,
            "codec": s.codec_label,
            "unlocked": s.transfer is not None,
            "username": s.username,
            "peers": sorted(peers, key=lambda p: p["node_id"]),
            "files": {
                "count": len(files),
                "healthy": sum(f["status"] == "healthy" for f in files),
                "degraded": sum(f["status"] == "degraded" for f in files),
                "unavailable": sum(f["status"] == "unavailable" for f in files),
            },
            "repair": {
                "last_round": repairer.last_stats if repairer else None,
                "total_copies": repairer.total_copies if repairer else 0,
                "events": list(repairer.events)[-20:] if repairer else [],
            },
        }

    return router
