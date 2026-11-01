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


def test_scrub_quarantines_corrupt_chunk_and_accepts_a_good_copy_again(tmp_path):
    s = DiskChunkStore(tmp_path, quota_bytes=10_000)
    good, bad = b"good chunk", b"soon corrupt"
    s.put(cid(good), good)
    s.put(cid(bad), bad)
    path = tmp_path / "chunks" / cid(bad)[:2] / cid(bad)
    path.write_bytes(b"soon c0rrupt")                     # disk rot / tampering
    result = s.scrub_some(10)
    assert result.checked == 2 and result.quarantined == [cid(bad)] and result.pass_completed
    assert not s.has(cid(bad)) and s.list_ids() == [cid(good)]
    assert s.used_bytes() == len(good)
    assert [f.name.split(".")[0] for f in (tmp_path / "quarantine").iterdir()] == [cid(bad)]
    assert s.put(cid(bad), bad) is True                   # repair can bring a good copy back
    assert s.get(cid(bad)) == bad
    assert s.scrub_stats["quarantined"] == 1 and s.scrub_stats["passes"] == 1


def test_scrub_walks_the_store_a_few_chunks_at_a_time(tmp_path):
    s = DiskChunkStore(tmp_path, quota_bytes=10_000)
    blobs = [bytes([i]) * 10 for i in range(5)]
    for b in blobs:
        s.put(cid(b), b)
    seen = [s.scrub_some(2) for _ in range(3)]
    assert [r.checked for r in seen] == [2, 2, 1]
    assert [r.pass_completed for r in seen] == [False, False, True]
    assert s.scrub_some(2).checked == 2                  # wraps round for the next pass


def test_scrub_notices_a_deleted_file(tmp_path):
    s = DiskChunkStore(tmp_path, quota_bytes=10_000)
    s.put(cid(b"x"), b"x")
    (tmp_path / "chunks" / cid(b"x")[:2] / cid(b"x")).unlink()
    r = s.scrub_some(5)
    assert r.missing == [cid(b"x")] and s.list_ids() == [] and s.used_bytes() == 0


def test_has_drops_a_vanished_file_and_audit_proof(tmp_path):
    import hmac

    s = DiskChunkStore(tmp_path, quota_bytes=1024)
    s.put(cid(b"keep"), b"keep")
    nonce = b"n" * 16
    assert s.audit_proof(cid(b"keep"), nonce) == hmac.new(nonce, b"keep", hashlib.sha256).hexdigest()
    assert s.audit_proof(cid(b"other"), nonce) is None
    (tmp_path / "chunks" / cid(b"keep")[:2] / cid(b"keep")).unlink()
    assert s.has(cid(b"keep")) is False and s.list_ids() == [] and s.used_bytes() == 0


def token_pair(seed: bytes = b"t"):
    token = hashlib.sha256(seed).hexdigest()
    return token, hashlib.sha256(bytes.fromhex(token)).hexdigest()


def test_delete_needs_the_owner_token_and_leaves_a_tombstone(tmp_path):
    from node.contracts import ChunkDeleted
    s = DiskChunkStore(tmp_path, quota_bytes=1024)
    token, dhash = token_pair()
    blob = b"owned chunk"
    s.put(cid(blob), blob, dhash)
    assert s.delete_hash(cid(blob)) == dhash
    assert s.delete(cid(blob), token_pair(b"wrong")[0]) == "forbidden"
    assert s.has(cid(blob))
    assert s.delete(cid(blob), token) == "deleted"
    assert not s.has(cid(blob)) and s.used_bytes() == 0 and s.list_ids() == []
    assert s.delete(cid(blob), token) == "deleted"              # idempotent
    with pytest.raises(ChunkDeleted) as gone:                   # a repair copy can't resurrect it
        s.put(cid(blob), blob, dhash)
    assert gone.value.token == token
    reopened = DiskChunkStore(tmp_path, quota_bytes=1024)      # tombstone survives a restart
    assert reopened.tombstone(cid(blob)) == token
    with pytest.raises(ChunkDeleted):
        reopened.put(cid(blob), blob)


def test_unprotected_and_absent_chunks_cannot_be_deleted(tmp_path):
    s = DiskChunkStore(tmp_path, quota_bytes=1024)
    blob = b"legacy chunk, stored without a delete hash"
    s.put(cid(blob), blob)
    token, _ = token_pair()
    assert s.delete(cid(blob), token) == "unprotected"
    assert s.has(cid(blob))
    assert s.delete(cid(b"never stored"), token) == "absent"
    assert s.delete(cid(blob), "not-hex") == "forbidden"
