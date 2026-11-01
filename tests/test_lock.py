"""Locked files: only the device whose MAC uploaded the file may download or replace it."""
import asyncio
import io

import pytest

from node.contracts import Manifest, owner_salt
from node.keys import derive_master
from node.manifest import ManifestError, _to_json, open_manifest, seal_manifest
from node.transfer import FileLocked, Transfer
from tests.fakes import make_cluster

MAC_A, MAC_B = "aa:bb:cc:dd:ee:01", "aa:bb:cc:dd:ee:02"


def run(coro):
    return asyncio.run(coro)


def laptops():
    """Two laptops, same login, same cluster: each Transfer is one laptop's node."""
    net, table, client, locs, codec = make_cluster(4)
    keys = codec.derive_master("team passphrase", owner_salt("team"))
    a = Transfer(keys, codec, table, client, locs, chunk_size=1024, device_mac=MAC_A)
    b = Transfer(keys, codec, table, client, locs, chunk_size=1024, device_mac=MAC_B)
    return a, b


def download(t, file_uuid):
    out = io.BytesIO()
    run(t.download(file_uuid, out))
    return out.getvalue()


def test_locked_file_downloads_only_on_the_uploading_device():
    a, b = laptops()
    data = b"secret report " * 300
    r = run(a.upload(io.BytesIO(data), "report.pdf", lock=True))
    assert download(a, r.file_uuid) == data
    run(b.recover())                                     # same login: b sees the file in its list...
    [f] = b.list_files()
    assert f["lock_mac"] == MAC_A and f["locked_here"] is False
    with pytest.raises(FileLocked):                      # ...but can't open it
        download(b, r.file_uuid)
    assert a.list_files()[0]["locked_here"] is True


def test_other_device_cannot_replace_a_locked_file():
    a, b = laptops()
    run(a.upload(io.BytesIO(b"v1" * 600), "notes.txt", lock=True))
    with pytest.raises(FileLocked):
        run(b.upload(io.BytesIO(b"overwrite" * 100), "notes.txt"))
    run(a.recover())
    assert a.list_files()[0]["version"] == 1


def test_lock_is_kept_on_new_versions_and_owner_can_unlock():
    a, b = laptops()
    run(a.upload(io.BytesIO(b"v1" * 600), "plan.txt", lock=True))
    r2 = run(a.upload(io.BytesIO(b"v2" * 600), "plan.txt"))          # lock omitted: kept
    run(b.recover())
    with pytest.raises(FileLocked):
        download(b, r2.file_uuid)
    r3 = run(a.upload(io.BytesIO(b"v3" * 600), "plan.txt", lock=False))
    run(b.recover())
    assert download(b, r3.file_uuid) == b"v3" * 600


def test_unlocked_files_are_open_to_every_device():
    a, b = laptops()
    r = run(a.upload(io.BytesIO(b"shared" * 200), "shared.txt"))
    run(b.recover())
    assert download(b, r.file_uuid) == b"shared" * 200 and b.list_files()[0]["lock_mac"] == ""


def test_locking_needs_a_device_mac():
    net, table, client, locs, codec = make_cluster(4)
    keys = codec.derive_master("p" * 12, owner_salt("u"))
    t = Transfer(keys, codec, table, client, locs, chunk_size=1024, device_mac="")
    with pytest.raises(FileLocked):
        run(t.upload(io.BytesIO(b"x" * 10), "x", lock=True))


def manifest(lock=""):
    return Manifest(file_uuid="u", name="n", size=5, sha256="a" * 64, wrapped_dek=b"k" * 60,
                    chunks=[{"index": 0, "chunk_id": "b" * 64, "plain_size": 5, "compressed": False}], lock_mac=lock)


def test_real_manifest_carries_the_lock_sealed_and_authenticated():
    kek = derive_master("p" * 12, owner_salt("u")).kek
    assert open_manifest(seal_manifest(manifest(MAC_A), kek), kek).lock_mac == MAC_A
    assert open_manifest(seal_manifest(manifest(), kek), kek).lock_mac == ""
    assert b"lock_mac" not in _to_json(manifest())      # unlocked manifests keep their exact old format
    with pytest.raises(ManifestError):
        seal_manifest(manifest("not-a-mac"), kek)


def test_other_device_cannot_delete_a_locked_file_but_the_owner_can():
    a, b = laptops()
    r = run(a.upload(io.BytesIO(b"keep me" * 200), "keep.txt", lock=True))
    run(b.recover())
    with pytest.raises(FileLocked):
        run(b.delete_file(r.file_uuid))
    run(a.recover())
    assert [f["name"] for f in a.list_files()] == ["keep.txt"]
    run(a.delete_file(r.file_uuid))
    assert a.list_files() == []
