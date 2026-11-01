"""P1: per-chunk encode/decode (ARCHITECTURE_DECISIONS.md sections 3, 4, 14).

encode_chunk(plain):
    1. zstd level 3; keep the compressed form only if it saves >= 3 %
    2. nonce = HMAC-SHA256(nonce_key, flag || plain)[:12]
       nonce_key = HKDF-SHA256(dek, info="minimol-2026/nonce/v1")
    3. AES-256-GCM(dek) with AAD = file_uuid || flag
    4. blob = nonce || ciphertext || tag;  chunk_id = sha256(blob)

The nonce depends only on the key and the plaintext, so an unchanged chunk of a
re-uploaded file produces the identical blob and chunk_id (delta sync).

decode_chunk(blob) checks, in order: blob length, the GCM tag, the zstd frame's
declared size (decompression-bomb guard), and that the nonce matches the decoded
plaintext. Any failure raises DecodeError; callers treat it as a corrupt copy.
"""
from __future__ import annotations

import hashlib
import hmac
import sys

import zstandard
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from node import index as _index
from node import keys as _keys
from node import manifest as _manifest
from node.contracts import CHUNK_SIZE, EncodedChunk, Manifest, MasterKeys

ZSTD_LEVEL = 3
MIN_SAVING = 0.03            # keep compression only if it saves at least 3 %
NONCE_LEN = 12
TAG_LEN = 16
OVERHEAD = NONCE_LEN + TAG_LEN   # 28 bytes per blob
MAX_BLOB = CHUNK_SIZE + OVERHEAD

_INFO_NONCE = b"minimol-2026/nonce/v1"
FLAG_RAW = 0
FLAG_ZSTD = 1


class DecodeError(_keys.CryptoError):
    pass


def sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _nonce_key(dek: bytes) -> bytes:
    return _keys.hkdf(dek, _INFO_NONCE)


def _synthetic_nonce(nonce_key: bytes, flag: int, plain: bytes) -> bytes:
    return hmac.new(nonce_key, bytes([flag]) + plain, hashlib.sha256).digest()[:NONCE_LEN]


def _aad(file_uuid: str, flag: int) -> bytes:
    # file_uuid is a fixed-length UUID string, so plain concatenation is unambiguous.
    return file_uuid.encode("utf-8") + bytes([flag])


def encode_chunk(plain: bytes, index: int, file_uuid: str, dek: bytes) -> EncodedChunk:
    """Encode one plaintext chunk (1 byte .. CHUNK_SIZE). An empty file has 0 chunks."""
    if not 0 < len(plain) <= CHUNK_SIZE:
        raise ValueError(f"chunk must be 1..{CHUNK_SIZE} bytes, got {len(plain)}")
    if index < 0:
        raise ValueError("index must be >= 0")

    compressed = zstandard.ZstdCompressor(level=ZSTD_LEVEL).compress(plain)  # writes content size
    if len(compressed) <= len(plain) * (1 - MIN_SAVING):
        flag, payload = FLAG_ZSTD, compressed
    else:
        flag, payload = FLAG_RAW, plain

    nonce = _synthetic_nonce(_nonce_key(dek), flag, plain)
    blob = nonce + AESGCM(dek).encrypt(nonce, payload, _aad(file_uuid, flag))
    return EncodedChunk(
        index=index,
        chunk_id=sha256_hex(blob),
        blob=blob,
        plain_size=len(plain),
        compressed=flag == FLAG_ZSTD,
    )


def decode_chunk(blob: bytes, file_uuid: str, compressed: bool, dek: bytes) -> bytes:
    """Return the plaintext chunk, or raise DecodeError.

    The caller must already have checked sha256(blob) == chunk_id."""
    if not OVERHEAD < len(blob) <= MAX_BLOB:
        raise DecodeError(f"blob size {len(blob)} is outside {OVERHEAD + 1}..{MAX_BLOB}")
    flag = FLAG_ZSTD if compressed else FLAG_RAW
    nonce, sealed = blob[:NONCE_LEN], blob[NONCE_LEN:]
    try:
        payload = AESGCM(dek).decrypt(nonce, sealed, _aad(file_uuid, flag))
    except InvalidTag as e:
        raise DecodeError("GCM tag check failed: wrong key, file, flag, or tampered blob") from e

    if compressed:
        # Bomb guard. python-zstandard ignores max_output_size when the frame header
        # declares its content size, so check the declared size ourselves first.
        try:
            declared = zstandard.frame_content_size(payload)
        except zstandard.ZstdError as e:
            raise DecodeError("not a valid zstd frame") from e
        if not 0 < declared <= CHUNK_SIZE:
            raise DecodeError(f"zstd frame declares {declared} bytes; limit is {CHUNK_SIZE}")
        try:
            plain = zstandard.ZstdDecompressor().decompress(payload, max_output_size=CHUNK_SIZE)
        except zstandard.ZstdError as e:
            raise DecodeError("zstd decompression failed") from e
        if len(plain) != declared:
            raise DecodeError("zstd output size does not match the frame header")
    else:
        plain = payload

    if not hmac.compare_digest(nonce, _synthetic_nonce(_nonce_key(dek), flag, plain)):
        raise DecodeError("nonce does not match the decoded plaintext")
    return plain


def measure_compression(data: bytes) -> dict:
    """Per-chunk vs whole-file zstd, for the section 3 'measure both modes' claim.

    Ratios are compressed/original for the compressible payload only (no encryption
    overhead), so they compare the two compression modes like for like."""
    if not data:
        return {"original_bytes": 0}
    whole = len(zstandard.ZstdCompressor(level=ZSTD_LEVEL).compress(data))
    per_chunk = stored = compressed_chunks = 0
    n_chunks = (len(data) + CHUNK_SIZE - 1) // CHUNK_SIZE
    for i in range(n_chunks):
        part = data[i * CHUNK_SIZE:(i + 1) * CHUNK_SIZE]
        c = len(zstandard.ZstdCompressor(level=ZSTD_LEVEL).compress(part))
        per_chunk += c
        keep = c <= len(part) * (1 - MIN_SAVING)
        stored += (c if keep else len(part)) + OVERHEAD
        compressed_chunks += keep
    return {
        "original_bytes": len(data),
        "chunks": n_chunks,
        "compressed_chunks": compressed_chunks,
        "whole_file_zstd_bytes": whole,
        "per_chunk_zstd_bytes": per_chunk,
        "stored_blob_bytes": stored,   # what encode_chunk actually produces
        "whole_file_ratio": round(whole / len(data), 4),
        "per_chunk_ratio": round(per_chunk / len(data), 4),
        "stored_ratio": round(stored / len(data), 4),
    }


class DefaultCodec:
    """The contracts.Codec implementation. P3 injects this (or a fake in tests)."""

    def encode_chunk(self, plain: bytes, index: int, file_uuid: str, dek: bytes) -> EncodedChunk:
        return encode_chunk(plain, index, file_uuid, dek)

    def decode_chunk(self, blob: bytes, file_uuid: str, compressed: bool, dek: bytes) -> bytes:
        return decode_chunk(blob, file_uuid, compressed, dek)

    def sha256_hex(self, b: bytes) -> str:
        return sha256_hex(b)

    def derive_master(self, passphrase: str, salt: bytes) -> MasterKeys:
        return _keys.derive_master(passphrase, salt)

    def wrap_key(self, kek: bytes, dek: bytes) -> bytes:
        return _keys.wrap_key(kek, dek)

    def unwrap_key(self, kek: bytes, wrapped: bytes) -> bytes:
        return _keys.unwrap_key(kek, wrapped)

    def seal_manifest(self, m: Manifest, kek: bytes) -> bytes:
        return _manifest.seal_manifest(m, kek)

    def open_manifest(self, blob: bytes, kek: bytes) -> Manifest:
        return _manifest.open_manifest(blob, kek)

    def seal_index(self, manifest_ids: list[str], version: int, keys: MasterKeys) -> dict:
        return _index.seal_index(manifest_ids, version, keys)

    def verify_index(self, record: dict, owner_pub: bytes) -> int:
        return _index.verify_index(record, owner_pub)

    def open_index(self, record: dict, keys: MasterKeys) -> list[str]:
        return _index.open_index(record, keys)


codec = DefaultCodec()


if __name__ == "__main__":
    # python -m node.pipeline FILE [FILE ...]  -> compression numbers for RESULTS.md
    import json

    for path in sys.argv[1:]:
        with open(path, "rb") as f:
            print(json.dumps({"file": path, **measure_compression(f.read())}))
