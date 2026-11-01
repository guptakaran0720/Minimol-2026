"""P1: key derivation and key wrapping (ARCHITECTURE_DECISIONS.md section 5).

    scrypt(passphrase, owner_salt(username)) -> master secret (32 bytes)
    HKDF(master, "kek")  -> KEK: wraps each file's DEK and seals manifests/index
    HKDF(master, "sign") -> Ed25519 seed: signs the owner index

Every derivation is deterministic, so a fresh laptop with the same username and
passphrase gets the same KEK and signing key and can recover every file.
"""
from __future__ import annotations

import os
import unicodedata
import uuid

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from node.contracts import MasterKeys

MIN_PASSPHRASE_LEN = 12
KEY_LEN = 32
NONCE_LEN = 12

# scrypt cost. n=2**17, r=8 uses 128 MiB of RAM and roughly 0.3-1 s per derivation,
# which makes offline passphrase guessing expensive. Tests lower it through the
# MINIMOL_SCRYPT_N environment variable; never lower it for the demo cluster,
# because every node must derive the same keys from the same passphrase.
SCRYPT_N_DEFAULT = 2**17
SCRYPT_R = 8
SCRYPT_P = 1

_INFO_KEK = b"minimol-2026/kek/v1"
_INFO_SIGN = b"minimol-2026/sign/v1"
_AAD_DEK_WRAP = b"minimol-2026/dek-wrap/v1"


class CryptoError(ValueError):
    """Base class for every P1 integrity or decryption failure.

    Callers (P2, P3) can catch this one class and treat the data as corrupt."""


class UnwrapError(CryptoError):
    pass


def hkdf(key: bytes, info: bytes, length: int = KEY_LEN) -> bytes:
    """HKDF-SHA256 with no salt. Shared by pipeline.py for the nonce key."""
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=None, info=info).derive(key)


def _scrypt_n() -> int:
    raw = os.environ.get("MINIMOL_SCRYPT_N")
    return int(raw) if raw else SCRYPT_N_DEFAULT


def derive_master(passphrase: str, salt: bytes) -> MasterKeys:
    """Derive the owner's keys. Always call with salt = contracts.owner_salt(username)."""
    if len(passphrase) < MIN_PASSPHRASE_LEN:
        raise ValueError(f"passphrase must be at least {MIN_PASSPHRASE_LEN} characters")
    if len(salt) < 16:
        raise ValueError("salt must be at least 16 bytes; use contracts.owner_salt(username)")
    # NFKC so the same passphrase typed on macOS, Windows or Linux gives the same bytes.
    secret = unicodedata.normalize("NFKC", passphrase).encode("utf-8")
    master = Scrypt(salt=salt, length=KEY_LEN, n=_scrypt_n(), r=SCRYPT_R, p=SCRYPT_P).derive(secret)

    kek = hkdf(master, _INFO_KEK)
    sign_key = Ed25519PrivateKey.from_private_bytes(hkdf(master, _INFO_SIGN))
    sign_priv = sign_key.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
    )
    sign_pub = sign_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return MasterKeys(kek=kek, sign_priv=sign_priv, sign_pub=sign_pub)


def new_dek() -> bytes:
    """Random 256-bit data key for a new file. Re-uploads of the same file reuse it."""
    return AESGCM.generate_key(bit_length=256)


def new_file_uuid() -> str:
    """Random file identifier (section 4: never a hash of the plaintext)."""
    return str(uuid.uuid4())


def wrap_key(kek: bytes, dek: bytes) -> bytes:
    """Encrypt a DEK under the KEK. Returns nonce || ciphertext || tag (60 bytes)."""
    if len(dek) != KEY_LEN:
        raise ValueError("dek must be 32 bytes")
    nonce = os.urandom(NONCE_LEN)
    return nonce + AESGCM(kek).encrypt(nonce, dek, _AAD_DEK_WRAP)


def unwrap_key(kek: bytes, wrapped: bytes) -> bytes:
    if len(wrapped) != NONCE_LEN + KEY_LEN + 16:
        raise UnwrapError("wrapped key has the wrong length")
    try:
        return AESGCM(kek).decrypt(wrapped[:NONCE_LEN], wrapped[NONCE_LEN:], _AAD_DEK_WRAP)
    except InvalidTag as e:
        raise UnwrapError("wrong KEK or tampered wrapped key") from e
