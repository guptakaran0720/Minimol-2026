import time

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from node import keys
from node.contracts import owner_salt
from node.keys import UnwrapError, derive_master, new_dek, new_file_uuid, unwrap_key, wrap_key

PASS = "correct horse battery staple"


@pytest.fixture(autouse=True)
def fast_scrypt(monkeypatch):
    monkeypatch.setenv("MINIMOL_SCRYPT_N", str(2**12))


def test_same_inputs_same_keys():
    a = derive_master(PASS, owner_salt("kiran"))
    b = derive_master(PASS, owner_salt("kiran"))
    assert a == b                                    # a fresh laptop re-derives identical keys


def test_username_separates_users():
    a = derive_master(PASS, owner_salt("kiran"))
    b = derive_master(PASS, owner_salt("karan"))
    assert a.kek != b.kek and a.sign_pub != b.sign_pub


def test_passphrase_changes_keys():
    a = derive_master(PASS, owner_salt("kiran"))
    b = derive_master(PASS + "!", owner_salt("kiran"))
    assert a.kek != b.kek


def test_unicode_normalisation():
    # "é" as one code point vs "e" + combining accent must give the same keys.
    a = derive_master("café-passphrase-1", owner_salt("kiran"))
    b = derive_master("café-passphrase-1", owner_salt("kiran"))
    assert a == b


def test_key_shapes_and_signing_pair():
    k = derive_master(PASS, owner_salt("kiran"))
    assert len(k.kek) == 32 and len(k.sign_priv) == 32 and len(k.sign_pub) == 32
    assert k.kek not in (k.sign_priv, k.sign_pub)
    sig = Ed25519PrivateKey.from_private_bytes(k.sign_priv).sign(b"msg")
    Ed25519PublicKey.from_public_bytes(k.sign_pub).verify(sig, b"msg")


def test_short_passphrase_rejected():
    with pytest.raises(ValueError):
        derive_master("short", owner_salt("kiran"))


def test_short_salt_rejected():
    with pytest.raises(ValueError):
        derive_master(PASS, b"tiny")


def test_wrap_unwrap_round_trip():
    kek = derive_master(PASS, owner_salt("kiran")).kek
    dek = new_dek()
    w = wrap_key(kek, dek)
    assert len(w) == 60 and dek not in w
    assert unwrap_key(kek, w) == dek
    assert wrap_key(kek, dek) != w                   # random nonce per wrap


def test_unwrap_rejects_wrong_kek_and_tampering():
    kek = derive_master(PASS, owner_salt("kiran")).kek
    other = derive_master(PASS, owner_salt("karan")).kek
    w = wrap_key(kek, new_dek())
    with pytest.raises(UnwrapError):
        unwrap_key(other, w)
    with pytest.raises(UnwrapError):
        unwrap_key(kek, w[:-1] + bytes([w[-1] ^ 1]))
    with pytest.raises(UnwrapError):
        unwrap_key(kek, w[:-1])


def test_new_ids_are_random():
    assert new_dek() != new_dek() and len(new_dek()) == 32
    assert new_file_uuid() != new_file_uuid() and len(new_file_uuid()) == 36


def test_production_scrypt_cost_is_used_by_default(monkeypatch):
    monkeypatch.delenv("MINIMOL_SCRYPT_N")
    assert keys._scrypt_n() == 2**17
    t = time.perf_counter()
    derive_master(PASS, owner_salt("kiran"))
    assert time.perf_counter() - t < 10              # expensive, but usable in a demo
