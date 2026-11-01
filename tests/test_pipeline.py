import hashlib
import os

import pytest
import zstandard
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from node import pipeline
from node.contracts import CHUNK_SIZE
from node.keys import CryptoError, new_dek, new_file_uuid
from node.pipeline import DecodeError, codec, decode_chunk, encode_chunk


def encode_all(data: bytes, file_uuid: str, dek: bytes):
    """What P3's upload loop does: read CHUNK_SIZE at a time, encode each piece."""
    return [
        encode_chunk(data[off:off + CHUNK_SIZE], i, file_uuid, dek)
        for i, off in enumerate(range(0, len(data), CHUNK_SIZE))
    ]


def decode_all(chunks, file_uuid, dek) -> bytes:
    return b"".join(decode_chunk(c.blob, file_uuid, c.compressed, dek) for c in chunks)


@pytest.fixture
def fid():
    return new_file_uuid()


@pytest.fixture
def dek():
    return new_dek()


def text(n: int) -> bytes:
    line = b"2026-11-01T11:30:00,sensor-07,temperature=23.4,humidity=41,status=OK\n"
    return (line * (n // len(line) + 1))[:n]


# ---- round trips and chunk boundaries ----

@pytest.mark.parametrize("size", [1, 1000, CHUNK_SIZE - 1, CHUNK_SIZE + 1, 3 * CHUNK_SIZE + 12345])
def test_round_trip_random(size, fid, dek):
    data = os.urandom(size)
    chunks = encode_all(data, fid, dek)
    assert decode_all(chunks, fid, dek) == data


def test_round_trip_compressible(fid, dek):
    data = text(3 * CHUNK_SIZE)
    chunks = encode_all(data, fid, dek)
    assert all(c.compressed for c in chunks)
    assert sum(len(c.blob) for c in chunks) < len(data) // 5
    assert decode_all(chunks, fid, dek) == data


def test_empty_file_has_no_chunks(fid, dek):
    assert encode_all(b"", fid, dek) == []
    with pytest.raises(ValueError):
        encode_chunk(b"", 0, fid, dek)


def test_exact_multiple_has_no_trailing_chunk(fid, dek):
    chunks = encode_all(os.urandom(2 * CHUNK_SIZE), fid, dek)
    assert [c.plain_size for c in chunks] == [CHUNK_SIZE, CHUNK_SIZE]


def test_oversized_chunk_rejected(fid, dek):
    with pytest.raises(ValueError):
        encode_chunk(b"x" * (CHUNK_SIZE + 1), 0, fid, dek)


def test_chunk_fields(fid, dek):
    c = encode_chunk(b"hello world", 4, fid, dek)
    assert c.index == 4
    assert c.plain_size == 11
    assert c.chunk_id == hashlib.sha256(c.blob).hexdigest()
    assert len(c.blob) == 11 + pipeline.OVERHEAD      # tiny input: stored raw


# ---- compression decision ----

def test_random_data_stored_raw(fid, dek):
    c = encode_chunk(os.urandom(CHUNK_SIZE), 0, fid, dek)
    assert not c.compressed
    assert len(c.blob) == CHUNK_SIZE + pipeline.OVERHEAD


def test_mixed_file_decided_per_chunk(fid, dek):
    data = text(CHUNK_SIZE) + os.urandom(CHUNK_SIZE) + text(CHUNK_SIZE)
    assert [c.compressed for c in encode_all(data, fid, dek)] == [True, False, True]


def test_compression_kept_only_if_it_saves_3_percent(fid, dek, monkeypatch):
    plain = os.urandom(10_000)
    # Pretend zstd saves exactly 2 %: below the threshold, so the chunk is stored raw.
    monkeypatch.setattr(
        zstandard.ZstdCompressor, "compress", lambda self, b: b"z" * int(len(b) * 0.98)
    )
    assert not encode_chunk(plain, 0, fid, dek).compressed


# ---- delta sync: same key + same plaintext -> same blob ----

def test_deterministic_for_delta_sync(fid, dek):
    data = text(2 * CHUNK_SIZE) + os.urandom(CHUNK_SIZE)
    a = [c.chunk_id for c in encode_all(data, fid, dek)]
    b = [c.chunk_id for c in encode_all(data, fid, dek)]
    assert a == b


def test_append_changes_only_the_tail(fid, dek):
    v1 = text(3 * CHUNK_SIZE + 5000)
    v2 = v1 + b"new rows appended\n" * 100
    ids1 = [c.chunk_id for c in encode_all(v1, fid, dek)]
    ids2 = [c.chunk_id for c in encode_all(v2, fid, dek)]
    assert ids1[:3] == ids2[:3]          # unchanged full chunks are reused
    assert ids1[3] != ids2[3]            # the partial last chunk changed


def test_no_equality_leak_across_files(dek):
    plain = text(CHUNK_SIZE)
    a = encode_chunk(plain, 0, new_file_uuid(), dek)
    b = encode_chunk(plain, 0, new_file_uuid(), dek)
    assert a.chunk_id != b.chunk_id       # different file_uuid -> different tag
    c = encode_chunk(plain, 0, new_file_uuid(), new_dek())
    assert c.blob[:12] != a.blob[:12]     # different DEK -> different nonce


# ---- integrity failures all raise DecodeError ----

def test_tampered_blob_rejected(fid, dek):
    c = encode_chunk(text(5000), 0, fid, dek)
    for pos in (0, 12, len(c.blob) - 1):          # nonce, ciphertext, tag
        bad = bytearray(c.blob)
        bad[pos] ^= 1
        with pytest.raises(DecodeError):
            decode_chunk(bytes(bad), fid, c.compressed, dek)


def test_wrong_key_file_or_flag_rejected(fid, dek):
    c = encode_chunk(text(5000), 0, fid, dek)
    with pytest.raises(DecodeError):
        decode_chunk(c.blob, fid, c.compressed, new_dek())
    with pytest.raises(DecodeError):
        decode_chunk(c.blob, new_file_uuid(), c.compressed, dek)   # chunk moved to another file
    with pytest.raises(DecodeError):
        decode_chunk(c.blob, fid, not c.compressed, dek)           # flag flipped in manifest


def test_truncated_or_oversized_blob_rejected(fid, dek):
    with pytest.raises(DecodeError):
        decode_chunk(b"\0" * 28, fid, False, dek)
    with pytest.raises(DecodeError):
        decode_chunk(b"\0" * (CHUNK_SIZE + 29), fid, False, dek)


def test_decode_error_is_a_crypto_error():
    assert issubclass(DecodeError, CryptoError)


def _seal_raw(payload: bytes, flag: int, nonce: bytes, file_uuid: str, dek: bytes) -> bytes:
    """Build a correctly encrypted blob around an arbitrary payload (attacker/bug model)."""
    return nonce + AESGCM(dek).encrypt(nonce, payload, file_uuid.encode() + bytes([flag]))


def test_decompression_bomb_rejected(fid, dek):
    bomb = zstandard.ZstdCompressor(level=3).compress(b"\0" * (50 * CHUNK_SIZE))
    assert len(bomb) < 10_000                       # tiny frame, 50 MiB declared
    blob = _seal_raw(bomb, pipeline.FLAG_ZSTD, os.urandom(12), fid, dek)
    with pytest.raises(DecodeError, match="declares"):
        decode_chunk(blob, fid, True, dek)


def test_frame_without_content_size_rejected(fid, dek):
    frame = zstandard.ZstdCompressor(level=3, write_content_size=False).compress(text(5000))
    blob = _seal_raw(frame, pipeline.FLAG_ZSTD, os.urandom(12), fid, dek)
    with pytest.raises(DecodeError):
        decode_chunk(blob, fid, True, dek)


def test_nonce_must_match_plaintext(fid, dek):
    # Validly encrypted, but the nonce was not derived from this plaintext.
    blob = _seal_raw(b"some plaintext", pipeline.FLAG_RAW, os.urandom(12), fid, dek)
    with pytest.raises(DecodeError, match="nonce"):
        decode_chunk(blob, fid, False, dek)


# ---- codec object and measurement helper ----

def test_codec_object_matches_functions(fid, dek):
    c = codec.encode_chunk(b"abc" * 1000, 0, fid, dek)
    assert codec.decode_chunk(c.blob, fid, c.compressed, dek) == b"abc" * 1000
    assert codec.sha256_hex(b"x") == hashlib.sha256(b"x").hexdigest()


def test_measure_compression(fid, dek):
    data = text(2 * CHUNK_SIZE) + os.urandom(CHUNK_SIZE)
    r = pipeline.measure_compression(data)
    assert r["chunks"] == 3 and r["compressed_chunks"] == 2
    assert r["stored_blob_bytes"] == sum(len(c.blob) for c in encode_all(data, fid, dek))
    assert pipeline.measure_compression(b"") == {"original_bytes": 0}
