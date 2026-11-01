"""User-facing API (P3). Only reachable from this machine.

Wiring (P2's main.py):
    app.state.user = UserState(codec=..., peers=..., client=..., locations=..., data_dir=..., repairer=...)
    app.include_router(api_user.router)

The node starts locked. POST /recover {username, passphrase} derives the owner keys,
unlocks the node and pulls the owner's signed index from peers, so the same call
serves "log in on my laptop" and "recover everything on a fresh laptop".

Uploads take the raw file as the request body (?name=...), which avoids a
multipart dependency and lets the dashboard send File objects with fetch().
"""
from __future__ import annotations

import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

from node.contracts import CHUNK_SIZE, Codec, LocationMap, PeerClient, PeerTable, owner_salt
from node.repair import Repairer
from node.transfer import ChunkUnavailable, IntegrityError, NotEnoughPeers, Transfer

MAX_UPLOAD_BYTES = 256 * 1024 * 1024
MIN_PASSPHRASE_LEN = 12
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}


@dataclass
class UserState:
    codec: Codec
    peers: PeerTable
    client: PeerClient
    locations: LocationMap
    data_dir: Path
    repairer: Repairer | None = None
    chunk_size: int = CHUNK_SIZE
    allowed_hosts: set[str] = field(default_factory=lambda: set(LOCAL_HOSTS))
    transfer: Transfer | None = None
    username: str | None = None


class RecoverBody(BaseModel):
    username: str
    passphrase: str


def state(request: Request) -> UserState:
    st: UserState = request.app.state.user
    host = request.client.host if request.client else ""
    if host not in st.allowed_hosts:
        raise HTTPException(403, "user API is only available on this machine")
    return st


def unlocked(st: UserState = Depends(state)) -> Transfer:
    if st.transfer is None:
        raise HTTPException(401, "node is locked: POST /recover with username and passphrase")
    return st.transfer


router = APIRouter()


@router.post("/recover")
async def recover(body: RecoverBody, st: UserState = Depends(state)) -> dict:
    username = body.username.strip()
    if not username:
        raise HTTPException(400, "username is required")
    if len(body.passphrase) < MIN_PASSPHRASE_LEN:
        raise HTTPException(400, f"passphrase must be at least {MIN_PASSPHRASE_LEN} characters")
    keys = st.codec.derive_master(body.passphrase, owner_salt(username))
    st.data_dir.mkdir(parents=True, exist_ok=True)
    transfer = Transfer(
        keys, st.codec, st.peers, st.client, st.locations,
        catalog_path=st.data_dir / f"catalog-{keys.sign_pub.hex()[:16]}.json",
        chunk_size=st.chunk_size,
    )
    restored = await transfer.recover()
    st.transfer, st.username = transfer, username
    return {"username": username, "files_restored": restored, "files": transfer.list_files()}


@router.post("/files", status_code=201)
async def upload(
    request: Request,
    name: str = Query(..., min_length=1, max_length=255),
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
            result = await transfer.upload(spool, name)
        except NotEnoughPeers as e:
            raise HTTPException(503, f"not enough peers accepted the data: {e}") from e
    out = asdict(result)
    out["compression_ratio"] = round(result.encoded_bytes / result.original_bytes, 4) if result.original_bytes else None
    return out


@router.get("/files")
async def list_files(transfer: Transfer = Depends(unlocked)) -> list[dict]:
    return transfer.list_files()


@router.get("/files/{file_uuid}")
async def download(file_uuid: str, transfer: Transfer = Depends(unlocked)) -> FileResponse:
    entry = transfer.catalog.get(file_uuid)
    if entry is None:
        raise HTTPException(404, "unknown file")
    # Write to a temp file and only serve it after the whole-file hash checks out.
    fd, path = tempfile.mkstemp(prefix="dl-")
    try:
        with os.fdopen(fd, "wb") as dst:
            await transfer.download(file_uuid, dst)
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
async def stats(st: UserState = Depends(state)) -> dict:
    """Dashboard feed. Works while locked (peers and repair only)."""
    # PeerTable.all() is a proposed contract addition so the dashboard can show dead peers.
    list_all = getattr(st.peers, "all", None)
    peers = list_all() if callable(list_all) else st.peers.alive()
    files = st.transfer.list_files() if st.transfer else []
    repairer = st.repairer
    return {
        "unlocked": st.transfer is not None,
        "username": st.username,
        "peers": [
            {
                "node_id": p.node_id, "host_id": p.host_id, "addr": p.addr, "state": p.state,
                "tier": p.tier, "rtt_ms": round(p.rtt_ewma * 1000, 2),
                "bw_mbps": round(p.bw_ewma * 8 / 1e6, 2), "free_bytes": p.free_bytes,
            }
            for p in sorted(peers, key=lambda p: p.node_id)
        ],
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
