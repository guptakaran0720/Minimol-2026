"""On-disk chunk store and owner-index store.

Chunks are content-addressed: the file name is sha256(blob). Writes go to a
temp file, are fsynced, then renamed into place, so a crash never leaves a
half-written chunk under a valid ID.

Scrubbing (scrub_some) re-hashes stored chunks a few at a time in the
background. A chunk whose bytes no longer match its ID (disk rot, tampering)
is moved to quarantine/ and dropped from the store, so it disappears from
/inventory; peers then see one copy missing and repair restores it.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from node.contracts import HashMismatch, QuotaExceeded

_HEX64 = re.compile(r"[0-9a-f]{64}")


def is_hex64(s: str) -> bool:
    return bool(_HEX64.fullmatch(s))


def _atomic_write(path: Path, data: bytes, tmp_dir: Path) -> None:
    tmp = tmp_dir / f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


@dataclass
class ScrubResult:
    checked: int = 0
    quarantined: list[str] | None = None    # corrupt: moved to quarantine/
    missing: list[str] | None = None        # file vanished from disk
    pass_completed: bool = False            # the cursor wrapped round to the start


class DiskChunkStore:
    """Implements contracts.ChunkStore. Thread-safe; endpoints call it from the threadpool."""

    def __init__(self, root: Path, quota_bytes: int):
        self.root = Path(root)
        self.quota_bytes = quota_bytes
        self._chunks = self.root / "chunks"
        self._tmp = self.root / "tmp"
        self._quarantine = self.root / "quarantine"
        self._chunks.mkdir(parents=True, exist_ok=True)
        self._tmp.mkdir(parents=True, exist_ok=True)
        for leftover in self._tmp.iterdir():
            leftover.unlink()
        self._lock = threading.Lock()
        self._sizes: dict[str, int] = {}
        for f in self._chunks.glob("*/*"):
            if is_hex64(f.name):
                self._sizes[f.name] = f.stat().st_size
        self._used = sum(self._sizes.values())
        self._scrub_cursor = 0
        self.scrub_stats = {"checked": 0, "quarantined": 0, "missing": 0, "passes": 0, "last_pass_at": None}

    def _path(self, chunk_id: str) -> Path:
        return self._chunks / chunk_id[:2] / chunk_id

    def put(self, chunk_id: str, blob: bytes) -> bool:
        if not is_hex64(chunk_id):
            raise ValueError("chunk_id must be 64 lowercase hex characters")
        if hashlib.sha256(blob).hexdigest() != chunk_id:
            raise HashMismatch(chunk_id)
        with self._lock:
            if chunk_id in self._sizes:
                return False
            if self._used + len(blob) > self.quota_bytes:
                raise QuotaExceeded(f"{self.free_bytes()} bytes free, need {len(blob)}")
            path = self._path(chunk_id)
            path.parent.mkdir(exist_ok=True)
            _atomic_write(path, blob, self._tmp)
            self._sizes[chunk_id] = len(blob)
            self._used += len(blob)
            return True

    def get(self, chunk_id: str) -> bytes | None:
        if chunk_id not in self._sizes:
            return None
        try:
            return self._path(chunk_id).read_bytes()
        except FileNotFoundError:
            return None

    def has(self, chunk_id: str) -> bool:
        return chunk_id in self._sizes

    def list_ids(self) -> list[str]:
        with self._lock:
            return list(self._sizes)

    def used_bytes(self) -> int:
        return self._used

    def free_bytes(self) -> int:
        return max(0, self.quota_bytes - self._used)

    # ---- scrubbing ----

    def scrub_some(self, limit: int) -> ScrubResult:
        """Re-hash up to `limit` chunks, continuing where the last call stopped."""
        result = ScrubResult(quarantined=[], missing=[])
        with self._lock:
            ids = sorted(self._sizes)
        if not ids or limit <= 0:
            return result
        start = self._scrub_cursor % len(ids)
        batch = ids[start:start + limit]
        self._scrub_cursor = start + len(batch)
        if self._scrub_cursor >= len(ids):
            self._scrub_cursor = 0
            result.pass_completed = True
        for chunk_id in batch:
            result.checked += 1
            try:
                data = self._path(chunk_id).read_bytes()
            except FileNotFoundError:
                if self._drop(chunk_id, quarantine=False):
                    result.missing.append(chunk_id)
                continue
            if hashlib.sha256(data).hexdigest() != chunk_id and self._drop(chunk_id, quarantine=True):
                result.quarantined.append(chunk_id)
        stats = self.scrub_stats
        stats["checked"] += result.checked
        stats["quarantined"] += len(result.quarantined)
        stats["missing"] += len(result.missing)
        if result.pass_completed:
            stats["passes"] += 1
            stats["last_pass_at"] = time.time()
        return result

    def _drop(self, chunk_id: str, quarantine: bool) -> bool:
        """Remove a chunk from the store; corrupt files are kept in quarantine/ for inspection."""
        with self._lock:
            size = self._sizes.pop(chunk_id, None)
            if size is None:
                return False
            self._used -= size
            if quarantine:
                self._quarantine.mkdir(exist_ok=True)
                try:
                    os.replace(self._path(chunk_id), self._quarantine / f"{chunk_id}.{int(time.time())}")
                except FileNotFoundError:
                    pass
            return True


class IndexStore:
    """Signed owner-index records, one per owner public key; keeps only the highest version.

    Records must be JSON-serialisable (P1's seal_index returns hex/base64 strings,
    not bytes). The version passed to put() comes from verify_index, never from
    the unverified record.
    """

    def __init__(self, root: Path):
        self.dir = Path(root) / "index"
        self._tmp = Path(root) / "tmp"
        self.dir.mkdir(parents=True, exist_ok=True)
        self._tmp.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _load(self, owner_pub_hex: str) -> dict | None:
        if not is_hex64(owner_pub_hex):   # also keeps the name inside self.dir
            raise ValueError("owner_pub must be 64 lowercase hex characters")
        try:
            return json.loads((self.dir / f"{owner_pub_hex}.json").read_text())
        except FileNotFoundError:
            return None

    def put(self, owner_pub_hex: str, record: dict, version: int) -> bool:
        """False if the stored version is the same or newer."""
        with self._lock:
            current = self._load(owner_pub_hex)
            if current is not None and current["version"] >= version:
                return False
            data = json.dumps({"version": version, "record": record}).encode("utf-8")
            _atomic_write(self.dir / f"{owner_pub_hex}.json", data, self._tmp)
            return True

    def get(self, owner_pub_hex: str) -> dict | None:
        current = self._load(owner_pub_hex)
        return None if current is None else current["record"]
