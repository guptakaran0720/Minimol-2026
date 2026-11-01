"""Upload, download and passphrase recovery (P3).

Upload:   encode (P1) -> skip chunks that already have R live copies (delta sync)
          -> place the rest on distinct hosts -> store the sealed manifest the same way
          -> publish the signed owner index to every alive peer.
Download: manifest -> chunks in parallel, holders tried in ETA order, every blob re-hashed
          -> decode -> whole-file SHA-256 check.
Recover:  highest valid index version across peers -> manifests -> catalog.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
import uuid
from collections import deque
from pathlib import Path
from typing import BinaryIO

from node.contracts import (
    CHUNK_SIZE,
    REPLICATION,
    Codec,
    LocationMap,
    Manifest,
    MasterKeys,
    Peer,
    PeerClient,
    PeerTable,
    UploadResult,
)
from node.routing import (
    PRIOR_BW_BPS,
    PRIOR_RTT_S,
    eta_seconds,
    rank_for_placement,
    rank_for_placement_baseline,
    rank_for_retrieval,
    rank_for_retrieval_baseline,
)

log = logging.getLogger(__name__)

MANIFEST_SIZE_HINT = 64 * 1024
# The baselines exist only so bench.py can A/B the real strategies against them.
PLACEMENTS = {"tiered": rank_for_placement, "random": rank_for_placement_baseline}
RETRIEVALS = {"eta": rank_for_retrieval, "random": rank_for_retrieval_baseline}


class NotEnoughPeers(Exception):
    pass


class ChunkUnavailable(Exception):
    pass


class IntegrityError(Exception):
    pass


class Transfer:
    def __init__(
        self,
        keys: MasterKeys,
        codec: Codec,
        peers: PeerTable,
        client: PeerClient,
        locations: LocationMap,
        replication: int = REPLICATION,
        parallel: int = 4,
        catalog_path: Path | None = None,
        chunk_size: int = CHUNK_SIZE,
        hedge: bool = True,
        hedge_factor: float = 2.0,
        hedge_min_s: float = 0.05,
    ):
        self.chunk_size = chunk_size
        self.hedge = hedge
        self.hedge_factor = hedge_factor
        self.hedge_min_s = hedge_min_s
        self.hedges_fired = 0
        self.unrecovered: list[str] = []      # manifest ids the last recover() could not fetch
        self.last_index_acks = 0              # peers that accepted the last published owner index
        self.keys = keys
        self.codec = codec
        self.peers = peers
        self.client = client
        self.locations = locations
        self.replication = replication
        self.parallel = parallel
        self.catalog_path = catalog_path
        # file_uuid -> {file_uuid, name, manifest_id, version, size, sha256, chunk_ids}
        self.catalog: dict[str, dict] = {}
        self.index_version = 0
        self._catalog_lock = asyncio.Lock()
        self._load_catalog()

    # ---------- upload ----------

    async def upload(self, src: BinaryIO, name: str, placement: str = "tiered") -> UploadResult:
        """Read src CHUNK_SIZE at a time; at most `parallel` chunks are in memory at once.

        Re-uploading a name reuses its file_uuid + DEK (version + 1), so unchanged
        chunks encode to the same chunk_id and are not sent again (delta sync)."""
        rank = PLACEMENTS[placement]
        # Pull files uploaded from other laptops first: the index we publish below is this
        # catalog, and re-uploading a name another laptop created should reuse its key.
        await self.recover()
        prev = self.latest_by_name(name)
        if prev:
            old = await self._load_manifest(prev["manifest_id"])
            file_uuid, version = prev["file_uuid"], old.version + 1
            dek = self.codec.unwrap_key(self.keys.kek, old.wrapped_dek)
        else:
            file_uuid, version, dek = str(uuid.uuid4()), 1, os.urandom(32)

        sem = asyncio.Semaphore(self.parallel)

        async def encode_and_store(plain: bytes, index: int) -> tuple[dict, list[str], int]:
            c = await asyncio.to_thread(self.codec.encode_chunk, plain, index, file_uuid, dek)
            holders, sent = await self._store_object(c.chunk_id, c.blob, sem, rank)
            row = {"index": c.index, "chunk_id": c.chunk_id, "plain_size": c.plain_size,
                   "compressed": c.compressed, "blob_size": len(c.blob)}
            return row, holders, sent

        hasher, size, index = hashlib.sha256(), 0, 0
        window: deque[asyncio.Task] = deque()
        placed: list[tuple[dict, list[str], int]] = []
        try:
            while plain := await asyncio.to_thread(read_full, src, self.chunk_size):
                hasher.update(plain)
                size += len(plain)
                window.append(asyncio.create_task(encode_and_store(plain, index)))
                index += 1
                if len(window) >= self.parallel:
                    placed.append(await window.popleft())
            while window:
                placed.append(await window.popleft())
        except BaseException:
            for task in window:
                task.cancel()
            raise

        rows = [row for row, _, _ in placed]
        manifest = Manifest(
            file_uuid=file_uuid,
            name=name,
            size=size,
            sha256=hasher.hexdigest(),
            wrapped_dek=self.codec.wrap_key(self.keys.kek, dek),
            chunks=[{k: r[k] for k in ("index", "chunk_id", "plain_size", "compressed")} for r in rows],
            version=version,
        )
        manifest_blob = self.codec.seal_manifest(manifest, self.keys.kek)
        manifest_id = self.codec.sha256_hex(manifest_blob)
        manifest_holders, _ = await self._store_object(manifest_id, manifest_blob, sem, rank)

        async with self._catalog_lock:
            self.catalog[file_uuid] = {
                "file_uuid": file_uuid,
                "name": name,
                "manifest_id": manifest_id,
                "version": version,
                "size": size,
                "sha256": manifest.sha256,
                "chunk_ids": [r["chunk_id"] for r in rows],
            }
            self.last_index_acks = await self._publish_index()
            if self.last_index_acks == 0:
                log.warning("no peer accepted owner index v%d; this upload is only in the local catalog", self.index_version)
            self._save_catalog()

        copies = [len(h) for _, h, _ in placed] + [len(manifest_holders)]
        return UploadResult(
            file_uuid=file_uuid,
            manifest_id=manifest_id,
            name=name,
            version=version,
            original_bytes=size,
            encoded_bytes=sum(r["blob_size"] for r in rows),
            sent_bytes=sum(sent * r["blob_size"] for r, _, sent in placed),
            replicated_bytes=sum(r["blob_size"] * len(h) for r, h, _ in placed),
            sent_chunks=sum(1 for _, _, sent in placed if sent),
            reused_chunks=sum(1 for _, _, sent in placed if not sent),
            status="durable" if min(copies) >= self.replication else "degraded",
            chunks=[{"index": r["index"], "chunk_id": r["chunk_id"], "holders": h} for r, h, _ in placed],
        )

    async def _store_object(self, object_id: str, blob: bytes, sem: asyncio.Semaphore,
                            rank=rank_for_placement) -> tuple[list[str], int]:
        """Ensure `replication` live copies on distinct hosts. Returns (holders, copies sent).

        Copies that already exist on live distinct hosts are reused, which is what
        makes delta sync send only changed chunks."""
        async with sem:
            existing = self._live_holders_by_host(object_id)
            holders = list(existing.values())
            sent = 0
            candidates = rank(object_id, self.peers.alive(), set(existing))
            i = 0
            while len(holders) < self.replication and i < len(candidates):
                batch = candidates[i : i + self.replication - len(holders)]
                i += len(batch)
                oks = await asyncio.gather(*(self._put(p, object_id, blob) for p in batch))
                for p, ok in zip(batch, oks):
                    if ok:
                        holders.append(p.node_id)
                        sent += 1
            if not holders:
                raise NotEnoughPeers(f"no peer accepted {object_id[:12]}")
            return holders, sent

    async def _put(self, peer: Peer, object_id: str, blob: bytes) -> bool:
        started = time.monotonic()
        try:
            ok = await self.client.put_chunk(peer, object_id, blob)
        except Exception:
            ok = False
        if ok:
            self.peers.record_transfer(peer.node_id, len(blob), time.monotonic() - started)
            self.locations.note(object_id, peer.node_id)
        else:
            self.peers.record_failure(peer.node_id)
        return ok

    # ---------- download ----------

    async def download(self, file_uuid: str, dst: BinaryIO, retrieval: str = "eta") -> Manifest:
        """Write the file to dst in order, fetching up to `parallel` chunks ahead.

        Raises IntegrityError after writing if the whole-file SHA-256 doesn't match,
        so callers must write to a temp file and only keep it on success."""
        entry = self.catalog.get(file_uuid)
        if entry is None:
            raise FileNotFoundError(file_uuid)
        rank = RETRIEVALS[retrieval]
        manifest = await self._load_manifest(entry["manifest_id"], rank)
        dek = self.codec.unwrap_key(self.keys.kek, manifest.wrapped_dek)

        async def one(c: dict) -> bytes:
            blob = await self._fetch(c["chunk_id"], c["plain_size"], rank)
            return await asyncio.to_thread(self.codec.decode_chunk, blob, file_uuid, c["compressed"], dek)

        pending = iter(sorted(manifest.chunks, key=lambda c: c["index"]))
        window: deque[asyncio.Task] = deque()

        def launch_next() -> None:
            if (c := next(pending, None)) is not None:
                window.append(asyncio.create_task(one(c)))

        hasher = hashlib.sha256()
        try:
            for _ in range(self.parallel):
                launch_next()
            while window:
                plain = await window.popleft()
                launch_next()
                hasher.update(plain)
                await asyncio.to_thread(dst.write, plain)
        except BaseException:
            for task in window:
                task.cancel()
            raise
        if hasher.hexdigest() != manifest.sha256:
            raise IntegrityError(f"{file_uuid}: reconstructed file hash mismatch")
        return manifest

    async def _fetch(self, object_id: str, size: int, rank=rank_for_retrieval) -> bytes:
        hedge = self.hedge and rank is rank_for_retrieval      # baselines stay un-hedged for a fair A/B
        holders = [p for n in self.locations.holders(object_id) if (p := self.peers.get(n))]
        ranked = rank(holders, size)
        if (blob := await self._first_verified(ranked, object_id, size, hedge)) is not None:
            return blob
        # The location map is soft state and may be stale: ask everyone else before giving up.
        tried = {p.node_id for p in ranked}
        others = rank([p for p in self.peers.alive() if p.node_id not in tried], size)
        if (blob := await self._first_verified(others, object_id, size, hedge)) is not None:
            return blob
        raise ChunkUnavailable(object_id)

    def _hedge_delay(self, peer: Peer, size: int) -> float:
        return max(self.hedge_min_s, self.hedge_factor * eta_seconds(peer, size, PRIOR_RTT_S, PRIOR_BW_BPS))

    async def _first_verified(self, ranked: list[Peer], object_id: str, size: int, hedge: bool) -> bytes | None:
        """Try peers in order; return the first blob whose hash matches.

        Hedged read ("The Tail at Scale"): if the newest request runs past 2x its
        ETA, also ask the next peer and take whichever verified reply lands first.
        A request that fails moves on at once. Losing requests are cancelled."""
        queue = list(ranked)
        running: dict[asyncio.Task, Peer] = {}
        try:
            while queue or running:
                if not running:
                    p = queue.pop(0)
                    running[asyncio.create_task(self._get(p, object_id))] = p
                newest = next(reversed(running.values()))
                timeout = self._hedge_delay(newest, size) if hedge and queue else None
                done, _ = await asyncio.wait(running, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
                if not done:
                    p = queue.pop(0)
                    self.hedges_fired += 1
                    running[asyncio.create_task(self._get(p, object_id))] = p
                    continue
                for task in done:
                    del running[task]
                    if (blob := task.result()) is not None:
                        return blob
            return None
        finally:
            for task in running:
                task.cancel()

    async def _get(self, peer: Peer, object_id: str) -> bytes | None:
        started = time.monotonic()
        try:
            blob = await self.client.get_chunk(peer, object_id)
        except Exception:
            self.peers.record_failure(peer.node_id)
            return None
        if blob is None:          # 404: stale location, not a peer fault
            return None
        if self.codec.sha256_hex(blob) != object_id:
            self.peers.record_failure(peer.node_id)
            return None
        self.peers.record_transfer(peer.node_id, len(blob), time.monotonic() - started)
        self.locations.note(object_id, peer.node_id)
        return blob

    async def _load_manifest(self, manifest_id: str, rank=rank_for_retrieval) -> Manifest:
        blob = await self._fetch(manifest_id, MANIFEST_SIZE_HINT, rank)
        return self.codec.open_manifest(blob, self.keys.kek)

    # ---------- owner index + recovery ----------

    async def _publish_index(self) -> int:
        """Caller holds _catalog_lock. Returns how many peers accepted the new version."""
        self.index_version += 1
        record = self.codec.seal_index(
            [e["manifest_id"] for e in self.catalog.values()], self.index_version, self.keys
        )
        owner = self.keys.sign_pub.hex()

        async def push(p: Peer) -> bool:
            try:
                return await self.client.put_index(p, owner, record)
            except Exception:
                return False

        return sum(await asyncio.gather(*(push(p) for p in self.peers.alive())))

    async def recover(self) -> int:
        """Merge the owner's newest signed file list from peers into the catalog.

        Used on unlock, before every upload, and by the auto-sync loop, so files uploaded
        from another laptop appear here. Only manifests not already in the catalog are
        fetched. A manifest no reachable peer can serve is skipped, not fatal; its id is
        kept in self.unrecovered and the next sync retries it. Returns how many files of
        the newest list are now in the catalog."""
        owner = self.keys.sign_pub.hex()
        alive = self.peers.alive()
        records = await asyncio.gather(*(self.client.get_index(p, owner) for p in alive), return_exceptions=True)
        best, best_version = None, -1
        for record in records:
            if not isinstance(record, dict):
                continue
            try:
                version = self.codec.verify_index(record, self.keys.sign_pub)
            except Exception:
                continue          # forged or corrupted record
            if version > best_version:
                best, best_version = record, version
        if best is None:
            return 0
        manifest_ids = self.codec.open_index(best, self.keys)
        known = {e["manifest_id"] for e in self.catalog.values()}
        to_load = [mid for mid in manifest_ids if mid not in known]
        loaded = await asyncio.gather(*(self._load_manifest(mid) for mid in to_load), return_exceptions=True)
        self.unrecovered = [mid for mid, m in zip(to_load, loaded) if not isinstance(m, Manifest)]
        restored = [(mid, m) for mid, m in zip(to_load, loaded) if isinstance(m, Manifest)]
        async with self._catalog_lock:
            self.index_version = max(self.index_version, best_version)
            for mid, m in restored:
                current = self.catalog.get(m.file_uuid)
                if current and current["version"] > m.version:
                    continue          # this laptop already has a newer version of the file
                self.catalog[m.file_uuid] = {
                    "file_uuid": m.file_uuid,
                    "name": m.name,
                    "manifest_id": mid,
                    "version": m.version,
                    "size": m.size,
                    "sha256": m.sha256,
                    "chunk_ids": [c["chunk_id"] for c in sorted(m.chunks, key=lambda c: c["index"])],
                }
            self._save_catalog()
            have = {e["manifest_id"] for e in self.catalog.values()}
        return sum(mid in have for mid in manifest_ids)

    # ---------- health views for the dashboard ----------

    def latest_by_name(self, name: str) -> dict | None:
        matches = [e for e in self.catalog.values() if e["name"] == name]
        return max(matches, key=lambda e: e["version"]) if matches else None

    def _live_holders_by_host(self, object_id: str) -> dict[str, str]:
        """host_id -> node_id for alive peers believed to hold the object."""
        out: dict[str, str] = {}
        for n in sorted(self.locations.holders(object_id)):
            p = self.peers.get(n)
            if p and p.state == "alive":
                out.setdefault(p.host_id, n)
        return out

    def chunk_map(self, file_uuid: str) -> list[dict]:
        entry = self.catalog[file_uuid]
        rows = []
        for i, cid in enumerate(entry["chunk_ids"]):
            holders = []
            for n in sorted(self.locations.holders(cid)):
                p = self.peers.get(n)
                holders.append({"node_id": n, "state": p.state if p else "unknown"})
            rows.append({"index": i, "chunk_id": cid, "holders": holders,
                         "live_hosts": len(self._live_holders_by_host(cid))})
        return rows

    def file_status(self, file_uuid: str) -> str:
        """healthy: every chunk has R live distinct hosts; degraded: some have fewer; unavailable: one has none."""
        lows = [len(self._live_holders_by_host(cid)) for cid in self.catalog[file_uuid]["chunk_ids"]]
        if lows and min(lows) == 0:
            return "unavailable"
        return "healthy" if not lows or min(lows) >= self.replication else "degraded"

    def list_files(self) -> list[dict]:
        return [
            {k: v for k, v in e.items() if k != "chunk_ids"} | {"chunks": len(e["chunk_ids"]), "status": self.file_status(f)}
            for f, e in self.catalog.items()
        ]

    # ---------- local catalog cache (the index on peers is the durable copy) ----------

    def _load_catalog(self) -> None:
        if self.catalog_path and self.catalog_path.exists():
            saved = json.loads(self.catalog_path.read_text())
            self.catalog = saved["catalog"]
            self.index_version = saved["index_version"]

    def _save_catalog(self) -> None:
        if self.catalog_path:
            tmp = self.catalog_path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"catalog": self.catalog, "index_version": self.index_version}))
            tmp.replace(self.catalog_path)


def read_full(src: BinaryIO, n: int) -> bytes:
    """Read exactly n bytes unless EOF. Streams may return short reads, and
    delta sync needs every chunk boundary at a fixed multiple of CHUNK_SIZE."""
    parts, got = [], 0
    while got < n:
        part = src.read(n - got)
        if not part:
            break
        parts.append(part)
        got += len(part)
    return b"".join(parts)
