import asyncio
import os

import pytest

from node.transfer import ChunkUnavailable, NotEnoughPeers, Transfer
from tests.fakes import make_cluster

CHUNK = 1024


def setup(n=4, passphrase="correct horse battery", **kw):
    net, table, client, locs, codec = make_cluster(n, CHUNK)
    keys = codec.derive_master(passphrase, b"salt")
    return net, table, client, locs, codec, Transfer(keys, codec, table, client, locs, **kw)


def run(coro):
    return asyncio.run(coro)


def hosts_of(table, node_ids):
    return [table.get(n).host_id for n in node_ids]


def test_round_trip_three_distinct_hosts():
    net, table, client, locs, codec, t = setup()
    data = os.urandom(CHUNK * 5 + 123)
    res = run(t.upload(data, "log.csv"))
    assert res.status == "durable" and len(res.chunks) == 6
    for c in res.chunks:
        hosts = hosts_of(table, c["holders"])
        assert len(hosts) == 3 == len(set(hosts))
    assert res.replicated_bytes == 3 * res.encoded_bytes
    assert run(t.download(res.file_uuid)) == data


def test_empty_file_and_exact_multiple():
    *_, t = setup()
    empty = run(t.upload(b"", "empty"))
    assert run(t.download(empty.file_uuid)) == b""
    exact = run(t.upload(b"x" * CHUNK * 3, "exact"))
    assert len(exact.chunks) == 3
    assert run(t.download(exact.file_uuid)) == b"x" * CHUNK * 3


def test_delta_sync_sends_only_changed_chunks():
    *_, t = setup()
    v1 = os.urandom(CHUNK * 10)
    first = run(t.upload(v1, "sensor.log"))
    assert first.sent_chunks == 10 and first.reused_chunks == 0
    v2 = v1 + b"new rows appended\n" * 20
    second = run(t.upload(v2, "sensor.log"))
    assert second.file_uuid == first.file_uuid and second.version == 2
    assert second.reused_chunks == 10 and second.sent_chunks == 1
    assert second.sent_bytes < second.encoded_bytes / 5
    assert run(t.download(second.file_uuid)) == v2


def test_download_survives_one_dead_holder():
    net, table, client, locs, codec, t = setup()
    data = os.urandom(CHUNK * 8)
    res = run(t.upload(data, "f"))
    table.kill(net, res.chunks[0]["holders"][0])
    assert run(t.download(res.file_uuid)) == data


def test_download_survives_two_dead_hosts_with_r3():
    net, table, client, locs, codec, t = setup(n=5)
    data = os.urandom(CHUNK * 8)
    res = run(t.upload(data, "f"))
    table.kill(net, "node0")
    table.kill(net, "node1")
    assert run(t.download(res.file_uuid)) == data


def test_suspect_holder_still_tried_after_alive_ones():
    net, table, client, locs, codec, t = setup()
    data = os.urandom(CHUNK * 3)
    res = run(t.upload(data, "f"))
    table.kill(net, "node2", state="suspect")
    assert run(t.download(res.file_uuid)) == data


def test_corrupt_holder_is_skipped_and_penalised():
    net, table, client, locs, codec, t = setup()
    data = os.urandom(CHUNK * 6)
    res = run(t.upload(data, "f"))
    bad = res.chunks[0]["holders"][0]
    net.corrupt.add(bad)
    for p in table.peers.values():                                   # make `bad` the fastest, so it is tried first
        p.rtt_ewma, p.bw_ewma = (0.0001, 1e9) if p.node_id == bad else (0.05, 1e6)
    assert run(t.download(res.file_uuid)) == data
    assert table.failures.get(bad, 0) >= 1


def test_stale_location_map_falls_back_to_asking_everyone():
    net, table, client, locs, codec, t = setup()
    data = os.urandom(CHUNK * 2)
    res = run(t.upload(data, "f"))
    locs.map.clear()
    assert run(t.download(res.file_uuid)) == data


def test_upload_with_two_hosts_is_degraded_not_failed():
    net, table, client, locs, codec, t = setup()
    table.kill(net, "node0")
    table.kill(net, "node1")
    res = run(t.upload(os.urandom(CHUNK * 2), "f"))
    assert res.status == "degraded"
    assert all(len(c["holders"]) == 2 for c in res.chunks)


def test_upload_with_no_peers_raises():
    net, table, client, locs, codec, t = setup(n=2)
    for n in ("node0", "node1"):
        table.kill(net, n)
    with pytest.raises(NotEnoughPeers):
        run(t.upload(b"data", "f"))


def test_all_holders_gone_is_unavailable():
    net, table, client, locs, codec, t = setup(n=3)
    res = run(t.upload(os.urandom(CHUNK), "f"))
    for n in ("node0", "node1", "node2"):
        table.kill(net, n)
    assert t.file_status(res.file_uuid) == "unavailable"
    with pytest.raises(ChunkUnavailable):
        run(t.download(res.file_uuid))


def test_full_peer_is_skipped_for_next_ranked():
    net, table, client, locs, codec, t = setup(n=5)
    net.full.add("node0")
    res = run(t.upload(os.urandom(CHUNK * 4), "f"))
    assert res.status == "durable"
    assert all("node0" not in c["holders"] for c in res.chunks)


def test_recover_on_fresh_device_with_passphrase_only():
    net, table, client, locs, codec, t = setup()
    a = os.urandom(CHUNK * 3)
    b = os.urandom(CHUNK + 7)
    ra = run(t.upload(a, "a.bin"))
    rb = run(t.upload(b, "b.bin"))

    fresh_keys = codec.derive_master("correct horse battery", b"salt")
    fresh = Transfer(fresh_keys, codec, table, client, locs)
    assert run(fresh.recover()) == 2
    assert run(fresh.download(ra.file_uuid)) == a
    assert run(fresh.download(rb.file_uuid)) == b
    assert fresh.index_version == t.index_version


def test_recover_ignores_forged_index_and_wrong_passphrase():
    net, table, client, locs, codec, t = setup()
    run(t.upload(b"secret" * 100, "s"))
    owner = t.keys.sign_pub.hex()
    net.indexes["node0"][owner] = {"version": 999, "ids": ["deadbeef"], "sig": "forged"}

    honest = Transfer(codec.derive_master("correct horse battery", b"salt"), codec, table, client, locs)
    assert run(honest.recover()) == 1

    wrong = Transfer(codec.derive_master("wrong passphrase", b"salt"), codec, table, client, locs)
    assert run(wrong.recover()) == 0


def test_catalog_persists_to_disk(tmp_path):
    net, table, client, locs, codec = make_cluster(4, CHUNK)
    keys = codec.derive_master("pw", b"salt")
    path = tmp_path / "catalog.json"
    t = Transfer(keys, codec, table, client, locs, catalog_path=path)
    res = run(t.upload(b"hello" * 500, "h"))
    reloaded = Transfer(keys, codec, table, client, locs, catalog_path=path)
    assert run(reloaded.download(res.file_uuid)) == b"hello" * 500
    assert reloaded.index_version == t.index_version
