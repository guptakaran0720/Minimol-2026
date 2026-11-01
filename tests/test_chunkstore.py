import hashlib

import pytest

from node.chunkstore import DiskChunkStore, IndexStore
from node.contracts import HashMismatch, QuotaExceeded


def cid(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def test_put_get_has(tmp_path):
    s = DiskChunkStore(tmp_path, quota_bytes=1024)
    blob = b"hello"
    assert s.put(cid(blob), blob) is True
    assert s.put(cid(blob), blob) is False          # idempotent, not counted twice
    assert s.get(cid(blob)) == blob
    assert s.has(cid(blob))
    assert s.list_ids() == [cid(blob)]
    assert s.used_bytes() == 5
    assert s.free_bytes() == 1019
    assert s.get(cid(b"other")) is None


def test_hash_mismatch_rejected(tmp_path):
    s = DiskChunkStore(tmp_path, quota_bytes=1024)
    with pytest.raises(HashMismatch):
        s.put(cid(b"a"), b"b")
    assert s.list_ids() == []


def test_bad_id_rejected(tmp_path):
    s = DiskChunkStore(tmp_path, quota_bytes=1024)
    with pytest.raises(ValueError):
        s.put("../../etc/passwd", b"x")
    with pytest.raises(ValueError):
        s.put(cid(b"x").upper(), b"x")


def test_quota(tmp_path):
    s = DiskChunkStore(tmp_path, quota_bytes=10)
    s.put(cid(b"123456"), b"123456")
    with pytest.raises(QuotaExceeded):
        s.put(cid(b"abcdef"), b"abcdef")
    assert s.used_bytes() == 6


def test_survives_restart_and_cleans_tmp(tmp_path):
    s = DiskChunkStore(tmp_path, quota_bytes=1024)
    s.put(cid(b"keep"), b"keep")
    (tmp_path / "tmp" / "half-written.tmp").write_bytes(b"junk")
    s2 = DiskChunkStore(tmp_path, quota_bytes=1024)
    assert s2.list_ids() == [cid(b"keep")]
    assert s2.used_bytes() == 4
    assert list((tmp_path / "tmp").iterdir()) == []


def test_index_store_keeps_highest_version(tmp_path):
    idx = IndexStore(tmp_path)
    owner = "ab" * 32
    assert idx.get(owner) is None
    assert idx.put(owner, {"v": 2}, 2) is True
    assert idx.put(owner, {"v": 1}, 1) is False
    assert idx.put(owner, {"v": 2}, 2) is False
    assert idx.get(owner) == {"v": 2}
    assert idx.put(owner, {"v": 3}, 3) is True
    assert IndexStore(tmp_path).get(owner) == {"v": 3}
    with pytest.raises(ValueError):
        idx.get("../x")
