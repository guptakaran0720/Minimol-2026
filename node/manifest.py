"""P1: sealed manifests (ARCHITECTURE_DECISIONS.md section 7).

A manifest is JSON encrypted under the KEK with AES-256-GCM:
    blob = nonce || ciphertext || tag,   manifest_id = sha256(blob)
It is stored on peers exactly like a chunk (PUT /chunks/{manifest_id}), so it
must fit in one chunk. The random nonce means sealing the same manifest twice
gives two different blobs; that is fine because manifests are immutable and the
owner index points at one manifest_id per file.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from node.contracts import CHUNK_SIZE, Manifest
from node.keys import CryptoError

NONCE_LEN = 12
FORMAT = 1
_AAD = b"minimol-2026/manifest/v1"
_HEX64 = re.compile(r"[0-9a-f]{64}")


class ManifestError(CryptoError):
    pass


def manifest_id(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _to_json(m: Manifest) -> bytes:
    doc = {
        "format": FORMAT,
        "file_uuid": m.file_uuid,
        "name": m.name,
        "size": m.size,
        "sha256": m.sha256,
        "wrapped_dek": base64.b64encode(m.wrapped_dek).decode("ascii"),
        "version": m.version,
        "chunks": [
            {
                "index": c["index"],
                "chunk_id": c["chunk_id"],
                "plain_size": c["plain_size"],
                "compressed": bool(c["compressed"]),
            }
            for c in m.chunks
        ],
    }
    return json.dumps(doc, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _check(m: Manifest) -> None:
    """Reject manifests that would make a download silently wrong."""
    if m.version < 1:
        raise ManifestError("version must be >= 1")
    if not _HEX64.fullmatch(m.sha256):
        raise ManifestError("sha256 must be 64 lowercase hex characters")
    total = 0
    for i, c in enumerate(m.chunks):
        if c["index"] != i:
            raise ManifestError(f"chunk {i} has index {c['index']}; chunks must be in order 0..n-1")
        if not _HEX64.fullmatch(c["chunk_id"]):
            raise ManifestError(f"chunk {i} has a malformed chunk_id")
        last = i == len(m.chunks) - 1
        if not (0 < c["plain_size"] <= CHUNK_SIZE) or (not last and c["plain_size"] != CHUNK_SIZE):
            raise ManifestError(f"chunk {i} has plain_size {c['plain_size']}")
        total += c["plain_size"]
    if total != m.size:
        raise ManifestError(f"chunk sizes add up to {total}, manifest says {m.size}")


def seal_manifest(m: Manifest, kek: bytes) -> bytes:
    _check(m)
    nonce = os.urandom(NONCE_LEN)
    blob = nonce + AESGCM(kek).encrypt(nonce, _to_json(m), _AAD)
    if len(blob) > CHUNK_SIZE:
        raise ManifestError(f"sealed manifest is {len(blob)} bytes; it must fit in one chunk")
    return blob


def open_manifest(blob: bytes, kek: bytes) -> Manifest:
    if len(blob) <= NONCE_LEN + 16:
        raise ManifestError("manifest blob too short")
    try:
        raw = AESGCM(kek).decrypt(blob[:NONCE_LEN], blob[NONCE_LEN:], _AAD)
    except InvalidTag as e:
        raise ManifestError("wrong KEK or tampered manifest") from e
    doc = json.loads(raw)
    if doc.get("format") != FORMAT:
        raise ManifestError(f"unknown manifest format {doc.get('format')}")
    m = Manifest(
        file_uuid=doc["file_uuid"],
        name=doc["name"],
        size=doc["size"],
        sha256=doc["sha256"],
        wrapped_dek=base64.b64decode(doc["wrapped_dek"]),
        chunks=doc["chunks"],
        version=doc["version"],
    )
    _check(m)
    return m
