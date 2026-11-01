import base64
import copy
import hashlib
import json

import pytest

from node.contracts import owner_salt
from node.index import InvalidIndex, latest_valid, open_index, seal_index, verify_index
from node.keys import CryptoError, derive_master

PASS = "correct horse battery staple"


@pytest.fixture(autouse=True)
def fast_scrypt(monkeypatch):
    monkeypatch.setenv("MINIMOL_SCRYPT_N", str(2**12))


@pytest.fixture
def kiran():
    return derive_master(PASS, owner_salt("kiran"))


@pytest.fixture
def karan():
    return derive_master(PASS, owner_salt("karan"))


def ids(n):
    return [hashlib.sha256(str(i).encode()).hexdigest() for i in range(n)]


def test_round_trip_and_version(kiran):
    rec = seal_index(ids(3), 7, kiran)
    assert verify_index(rec, kiran.sign_pub) == 7
    assert sorted(open_index(rec, kiran)) == sorted(ids(3))
    json.dumps(rec)                                    # must travel over HTTP as JSON


def test_empty_index(kiran):
    assert open_index(seal_index([], 1, kiran), kiran) == []


def test_fresh_laptop_reads_index(kiran):
    rec = seal_index(ids(2), 1, kiran)
    fresh = derive_master(PASS, owner_salt("kiran"))  # only username + passphrase
    assert sorted(open_index(rec, fresh)) == sorted(ids(2))


def test_other_owner_rejected(kiran, karan):
    rec = seal_index(ids(2), 1, kiran)
    with pytest.raises(InvalidIndex):
        verify_index(rec, karan.sign_pub)
    with pytest.raises(InvalidIndex):
        open_index(rec, karan)


@pytest.mark.parametrize("field", ["blob", "sig"])
def test_tampered_record_rejected(kiran, field):
    rec = seal_index(ids(2), 3, kiran)
    raw = bytearray(base64.b64decode(rec[field]))
    raw[-1] ^= 1
    rec[field] = base64.b64encode(bytes(raw)).decode()
    with pytest.raises(InvalidIndex):
        verify_index(rec, kiran.sign_pub)


def test_version_cannot_be_raised_by_a_peer(kiran):
    """A peer bumping the version to win 'highest version' must fail the signature."""
    rec = seal_index(ids(2), 3, kiran)
    forged = dict(rec, version=99)
    with pytest.raises(InvalidIndex):
        verify_index(forged, kiran.sign_pub)


@pytest.mark.parametrize(
    "bad",
    [{}, {"format": 2}, {"version": True}, {"version": 0}, {"version": "3"}, {"owner_pub": "zz"}, {"sig": "!!"}],
)
def test_malformed_records_rejected(kiran, bad):
    rec = seal_index(ids(1), 3, kiran)
    rec = {} if bad == {} else dict(rec, **bad)
    with pytest.raises(InvalidIndex):
        verify_index(rec, kiran.sign_pub)
    assert issubclass(InvalidIndex, CryptoError)


def test_rollback_defence_picks_highest_valid(kiran, karan):
    v1 = seal_index(ids(1), 1, kiran)
    v2 = seal_index(ids(2), 2, kiran)
    v3 = seal_index(ids(3), 3, kiran)
    forged = dict(copy.deepcopy(v2), version=50)       # peer lies about the version
    stranger = seal_index(ids(1), 60, karan)           # validly signed, wrong owner
    answers = [v1, None, forged, v3, stranger, v2]
    best = latest_valid(answers, kiran.sign_pub)
    assert best is v3
    assert sorted(open_index(best, kiran)) == sorted(ids(3))


def test_latest_valid_none_when_nothing_verifies(kiran, karan):
    assert latest_valid([None, seal_index(ids(1), 1, karan)], kiran.sign_pub) is None


def test_seal_rejects_bad_input(kiran):
    with pytest.raises(ValueError):
        seal_index(ids(1), 0, kiran)
    with pytest.raises(ValueError):
        seal_index(["not-a-hash"], 1, kiran)
    with pytest.raises(ValueError):
        seal_index(ids(1) * 2, 1, kiran)
