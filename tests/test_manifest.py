import dataclasses
import hashlib

import pytest

from node.contracts import CHUNK_SIZE, Manifest, owner_salt
from node.keys import CryptoError, derive_master, new_dek, new_file_uuid, unwrap_key, wrap_key
from node.manifest import ManifestError, manifest_id, open_manifest, seal_manifest


@pytest.fixture(autouse=True)
def fast_scrypt(monkeypatch):
    monkeypatch.setenv("MINIMOL_SCRYPT_N", str(2**12))


@pytest.fixture
def kek():
    return derive_master("correct horse battery staple", owner_salt("kiran")).kek


def make_manifest(kek, n_chunks=3, last=1234, version=1) -> Manifest:
    sizes = [CHUNK_SIZE] * (n_chunks - 1) + [last]
    return Manifest(
        file_uuid=new_file_uuid(),
        name="sensor_log.csv",
        size=sum(sizes),
        sha256=hashlib.sha256(b"original file").hexdigest(),
        wrapped_dek=wrap_key(kek, new_dek()),
        chunks=[
            {"index": i, "chunk_id": hashlib.sha256(bytes([i])).hexdigest(), "plain_size": s, "compressed": i % 2 == 0}
            for i, s in enumerate(sizes)
        ],
        version=version,
    )


def test_round_trip(kek):
    m = make_manifest(kek, version=4)
    assert open_manifest(seal_manifest(m, kek), kek) == m


def test_dek_survives_round_trip(kek):
    m = make_manifest(kek)
    m2 = open_manifest(seal_manifest(m, kek), kek)
    assert unwrap_key(kek, m2.wrapped_dek) == unwrap_key(kek, m.wrapped_dek)


def test_empty_file_manifest(kek):
    m = dataclasses.replace(make_manifest(kek), size=0, chunks=[])
    assert open_manifest(seal_manifest(m, kek), kek) == m


def test_blob_hides_contents(kek):
    blob = seal_manifest(make_manifest(kek), kek)
    assert b"sensor_log" not in blob
    assert manifest_id(blob) == hashlib.sha256(blob).hexdigest()


def test_wrong_kek_and_tampering_rejected(kek):
    blob = seal_manifest(make_manifest(kek), kek)
    other = derive_master("correct horse battery staple", owner_salt("karan")).kek
    with pytest.raises(ManifestError):
        open_manifest(blob, other)
    with pytest.raises(ManifestError):
        open_manifest(blob[:-1] + bytes([blob[-1] ^ 1]), kek)
    with pytest.raises(ManifestError):
        open_manifest(blob[:20], kek)
    assert issubclass(ManifestError, CryptoError)


@pytest.mark.parametrize(
    "change",
    [
        {"version": 0},
        {"sha256": "not-hex"},
        {"size": 999},                                                    # sizes don't add up
    ],
)
def test_inconsistent_manifest_refused_at_seal(kek, change):
    with pytest.raises(ManifestError):
        seal_manifest(dataclasses.replace(make_manifest(kek), **change), kek)


def test_chunk_order_and_sizes_checked(kek):
    m = make_manifest(kek)
    m.chunks[0], m.chunks[1] = m.chunks[1], m.chunks[0]
    with pytest.raises(ManifestError, match="order"):
        seal_manifest(m, kek)
    m = make_manifest(kek)
    m.chunks[0]["plain_size"] = 10                                        # short non-final chunk
    m.size = sum(c["plain_size"] for c in m.chunks)
    with pytest.raises(ManifestError):
        seal_manifest(m, kek)


def test_large_file_manifest_fits_one_chunk(kek):
    m = make_manifest(kek, n_chunks=256)                                   # 256 MiB upload cap
    blob = seal_manifest(m, kek)
    assert len(blob) < 64 * 1024
