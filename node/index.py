"""P1: the signed owner index (ARCHITECTURE_DECISIONS.md section 7).

The index is the owner's list of manifest IDs, one per file (the latest version).
It lives on peers at slot = owner public key, as a JSON-safe record:

    {"format": 1, "owner_pub": <hex>, "version": <int>,
     "blob": <base64 nonce||ciphertext||tag>, "sig": <base64 Ed25519 signature>}

- blob: the manifest-ID list encrypted under the KEK; AAD binds owner_pub + version.
- sig:  Ed25519 over "minimol-2026/index/v1|" || owner_pub || version (8 bytes) || sha256(blob).

Peers (P2) call verify_index() on every PUT /index and keep only the highest
valid version. Recovery (P3) asks every peer and passes the answers to
latest_valid(), which drops forged or tampered records before picking a version.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re

from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from node.contracts import MasterKeys
from node.keys import CryptoError

FORMAT = 1
NONCE_LEN = 12
MAX_VERSION = 2**63 - 1
_DOMAIN = b"minimol-2026/index/v1|"
_HEX64 = re.compile(r"[0-9a-f]{64}")


class InvalidIndex(CryptoError):
    pass


def _bound(owner_pub: bytes, version: int) -> bytes:
    return _DOMAIN + owner_pub + version.to_bytes(8, "big")


def _signed_message(owner_pub: bytes, version: int, blob: bytes) -> bytes:
    return _bound(owner_pub, version) + hashlib.sha256(blob).digest()


def seal_index(manifest_ids: list[str], version: int, keys: MasterKeys) -> dict:
    if not 1 <= version <= MAX_VERSION:
        raise ValueError("version must be between 1 and 2**63 - 1")
    if len(set(manifest_ids)) != len(manifest_ids):
        raise ValueError("manifest_ids contains duplicates")
    for mid in manifest_ids:
        if not _HEX64.fullmatch(mid):
            raise ValueError(f"malformed manifest id {mid!r}")

    plain = json.dumps(sorted(manifest_ids), separators=(",", ":")).encode("utf-8")
    nonce = os.urandom(NONCE_LEN)
    blob = nonce + AESGCM(keys.kek).encrypt(nonce, plain, _bound(keys.sign_pub, version))
    sig = Ed25519PrivateKey.from_private_bytes(keys.sign_priv).sign(
        _signed_message(keys.sign_pub, version, blob)
    )
    return {
        "format": FORMAT,
        "owner_pub": keys.sign_pub.hex(),
        "version": version,
        "blob": base64.b64encode(blob).decode("ascii"),
        "sig": base64.b64encode(sig).decode("ascii"),
    }


def _parse(record: dict) -> tuple[bytes, int, bytes, bytes]:
    try:
        if record["format"] != FORMAT:
            raise InvalidIndex(f"unknown index format {record['format']}")
        owner_pub = bytes.fromhex(record["owner_pub"])
        version = record["version"]
        blob = base64.b64decode(record["blob"], validate=True)
        sig = base64.b64decode(record["sig"], validate=True)
    except (KeyError, TypeError, ValueError, binascii.Error) as e:
        if isinstance(e, InvalidIndex):
            raise
        raise InvalidIndex(f"malformed index record: {e}") from e
    if not isinstance(version, int) or isinstance(version, bool) or not 1 <= version <= MAX_VERSION:
        raise InvalidIndex("version must be an integer between 1 and 2**63 - 1")
    if len(owner_pub) != 32 or len(sig) != 64 or len(blob) <= NONCE_LEN + 16:
        raise InvalidIndex("owner_pub, sig or blob has the wrong length")
    return owner_pub, version, blob, sig


def verify_index(record: dict, owner_pub: bytes) -> int:
    """Return the record's version if it is validly signed by owner_pub, else raise InvalidIndex.

    Needs no secret keys, so storage peers (P2) can call it."""
    rec_pub, version, blob, sig = _parse(record)
    if rec_pub != owner_pub:
        raise InvalidIndex("record belongs to a different owner")
    try:
        Ed25519PublicKey.from_public_bytes(owner_pub).verify(sig, _signed_message(owner_pub, version, blob))
    except InvalidSignature as e:
        raise InvalidIndex("bad signature") from e
    return version


def open_index(record: dict, keys: MasterKeys) -> list[str]:
    """Verify, then decrypt the manifest-ID list. Raises InvalidIndex."""
    version = verify_index(record, keys.sign_pub)
    blob = base64.b64decode(record["blob"])
    try:
        plain = AESGCM(keys.kek).decrypt(blob[:NONCE_LEN], blob[NONCE_LEN:], _bound(keys.sign_pub, version))
    except InvalidTag as e:
        raise InvalidIndex("index signed by this owner but not decryptable with this KEK") from e
    ids = json.loads(plain)
    if not isinstance(ids, list) or not all(isinstance(i, str) and _HEX64.fullmatch(i) for i in ids):
        raise InvalidIndex("decrypted index is not a list of manifest ids")
    return ids


def latest_valid(records: list[dict | None], owner_pub: bytes) -> dict | None:
    """Pick the highest-version record that verifies. For recovery and rollback defence:
    ask every peer, pass all answers here; forged, tampered or missing ones are skipped."""
    best, best_version = None, 0
    for rec in records:
        if not rec:
            continue
        try:
            v = verify_index(rec, owner_pub)
        except InvalidIndex:
            continue
        if v > best_version:
            best, best_version = rec, v
    return best
