"""End-to-end P1 flow with no networking: what P3's upload, download and /recover
will do, using only P1 functions. Passing this is the P1 half of Merge 1."""
import hashlib
import io
import os

import pytest

from node.contracts import CHUNK_SIZE, Manifest, owner_salt
from node.index import latest_valid, open_index, seal_index
from node.keys import derive_master, new_dek, new_file_uuid, unwrap_key, wrap_key
from node.manifest import manifest_id, open_manifest, seal_manifest
from node.pipeline import decode_chunk, encode_chunk


@pytest.fixture(autouse=True)
def fast_scrypt(monkeypatch):
    monkeypatch.setenv("MINIMOL_SCRYPT_N", str(2**12))


def upload(src, name, keys, store, file_uuid=None, dek=None, version=1):
    """Stream src CHUNK_SIZE at a time, like Transfer.upload. Returns (manifest_id, sent_chunks)."""
    file_uuid, dek = file_uuid or new_file_uuid(), dek or new_dek()
    whole, chunks, sent, i = hashlib.sha256(), [], 0, 0
    while piece := src.read(CHUNK_SIZE):
        whole.update(piece)
        c = encode_chunk(piece, i, file_uuid, dek)
        if c.chunk_id not in store:          # delta sync: skip chunks peers already hold
            store[c.chunk_id] = c.blob
            sent += 1
        chunks.append({"index": i, "chunk_id": c.chunk_id, "plain_size": c.plain_size, "compressed": c.compressed})
        i += 1
    m = Manifest(file_uuid, name, sum(c["plain_size"] for c in chunks), whole.hexdigest(),
                 wrap_key(keys.kek, dek), chunks, version)
    blob = seal_manifest(m, keys.kek)
    store[manifest_id(blob)] = blob
    return manifest_id(blob), sent


def download(mid, keys, store) -> bytes:
    m = open_manifest(store[mid], keys.kek)
    dek, out = unwrap_key(keys.kek, m.wrapped_dek), io.BytesIO()
    for c in m.chunks:
        blob = store[c["chunk_id"]]
        assert hashlib.sha256(blob).hexdigest() == c["chunk_id"]
        out.write(decode_chunk(blob, m.file_uuid, c["compressed"], dek))
    data = out.getvalue()
    assert hashlib.sha256(data).hexdigest() == m.sha256
    return data


def test_upload_recover_on_fresh_laptop_and_delta_sync():
    store, index_on_peers = {}, []          # stands in for the peers
    laptop = derive_master("correct horse battery staple", owner_salt("kiran"))

    log = b"ts,sensor,value\n" + b"2026-11-01T11:30:00,s7,23.4\n" * 150_000   # ~4 MiB, compressible
    photo = os.urandom(CHUNK_SIZE + 999)                                         # incompressible
    log_id, _ = upload(io.BytesIO(log), "log.csv", laptop, store)
    photo_id, _ = upload(io.BytesIO(photo), "photo.jpg", laptop, store)
    index_on_peers.append(seal_index([log_id, photo_id], 1, laptop))

    # The laptop dies. A fresh laptop knows only the username and passphrase.
    fresh = derive_master("correct horse battery staple", owner_salt("kiran"))
    rec = latest_valid(index_on_peers, fresh.sign_pub)
    recovered = {open_manifest(store[mid], fresh.kek).name: download(mid, fresh, store) for mid in open_index(rec, fresh)}
    assert recovered == {"log.csv": log, "photo.jpg": photo}

    # Delta sync: append rows, re-upload with the same file_uuid + DEK, version 2.
    m1 = open_manifest(store[log_id], fresh.kek)
    log_v2 = log + b"2026-11-01T12:00:00,s7,24.1\n" * 100
    v2_id, sent = upload(io.BytesIO(log_v2), "log.csv", fresh, store, m1.file_uuid,
                         unwrap_key(fresh.kek, m1.wrapped_dek), version=2)
    assert len(m1.chunks) == 5 and sent == 1          # 5 chunks; only the changed last one is sent
    index_on_peers.append(seal_index([v2_id, photo_id], 2, fresh))
    rec = latest_valid(index_on_peers, fresh.sign_pub)
    assert v2_id in open_index(rec, fresh)
    assert download(v2_id, fresh, store) == log_v2
