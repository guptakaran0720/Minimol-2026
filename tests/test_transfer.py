import asyncio
import time
import io
import os

import pytest

from node.contracts import owner_salt
from node.transfer import ChunkUnavailable, IntegrityError, NotEnoughPeers, Transfer
from tests.fakes import make_cluster

CHUNK = 1024
USER, PASS = "karan", "correct horse battery"


def run(coro):
    return asyncio.run(coro)


def keys_for(codec, user=USER, passphrase=PASS):
    return codec.derive_master(passphrase, owner_salt(user))


def setup(n=4, **kw):
    net, table, client, locs, codec = make_cluster(n)
    t = Transfer(keys_for(codec), codec, table, client, locs, chunk_size=CHUNK, **kw)
    return net, table, client, locs, codec, t


def up(t, data, name):
    return run(t.upload(io.BytesIO(data), name))


def down(t, file_uuid):
    out = io.BytesIO()
    run(t.download(file_uuid, out))
    return out.getvalue()


class Trickle(io.RawIOBase):
    """A stream that returns at most 100 bytes per read, like a socket."""

    def __init__(self, data):
        self.buf = io.BytesIO(data)

    def readable(self):
        return True

    def read(self, n=-1):
        return self.buf.read(min(n, 100) if n and n > 0 else 100)


def hosts_of(table, node_ids):
    return [table.get(n).host_id for n in node_ids]


def test_round_trip_three_distinct_hosts():
    net, table, client, locs, codec, t = setup()
    data = os.urandom(CHUNK * 5 + 123)
    res = up(t, data, "log.csv")
    assert res.status == "durable" and len(res.chunks) == 6
    for c in res.chunks:
        hosts = hosts_of(table, c["holders"])
        assert len(hosts) == 3 == len(set(hosts))
    assert res.replicated_bytes == 3 * res.encoded_bytes
    assert res.original_bytes == len(data)
    assert down(t, res.file_uuid) == data


def test_download_returns_manifest():
    *_, t = setup()
    res = up(t, b"abc" * 1000, "m")
    out = io.BytesIO()
    manifest = run(t.download(res.file_uuid, out))
    assert manifest.file_uuid == res.file_uuid and manifest.size == 3000


def test_empty_file_and_exact_multiple():
    *_, t = setup()
    empty = up(t, b"", "empty")
    assert down(t, empty.file_uuid) == b""
    exact = up(t, b"x" * CHUNK * 3, "exact")
    assert len(exact.chunks) == 3
    assert down(t, exact.file_uuid) == b"x" * CHUNK * 3


def test_short_reads_keep_fixed_chunk_boundaries():
    *_, t = setup()
    data = os.urandom(CHUNK * 4 + 10)
    first = up(t, data, "trickle")
    second = run(t.upload(Trickle(data + b"tail"), "trickle"))
    assert [c["chunk_id"] for c in second.chunks[:4]] == [c["chunk_id"] for c in first.chunks[:4]]
    assert second.reused_chunks == 4
    assert down(t, second.file_uuid) == data + b"tail"


def test_upload_keeps_at_most_parallel_chunks_in_flight():
    *_, t = setup(parallel=3)
    in_flight, peak = 0, 0
    original = t._store_object

    async def tracked(*args):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        try:
            await asyncio.sleep(0.001)
            return await original(*args)
        finally:
            in_flight -= 1

    t._store_object = tracked
    up(t, os.urandom(CHUNK * 20), "big")
    assert peak <= 3


def test_delta_sync_sends_only_changed_chunks():
    *_, t = setup()
    v1 = os.urandom(CHUNK * 10)
    first = up(t, v1, "sensor.log")
    assert first.sent_chunks == 10 and first.reused_chunks == 0
    v2 = v1 + b"new rows appended\n" * 20
    second = up(t, v2, "sensor.log")
    assert second.file_uuid == first.file_uuid and second.version == 2
    assert second.reused_chunks == 10 and second.sent_chunks == 1
    assert second.sent_bytes < second.encoded_bytes / 5
    assert down(t, second.file_uuid) == v2


def test_delta_sync_in_place_edit_and_shrink():
    *_, t = setup()
    v1 = bytearray(os.urandom(CHUNK * 6))
    up(t, bytes(v1), "f")
    v1[CHUNK * 2 + 5] ^= 0xFF                      # flip one byte in chunk 2
    edited = up(t, bytes(v1), "f")
    assert edited.sent_chunks == 1 and edited.reused_chunks == 5
    shrunk = up(t, bytes(v1[: CHUNK * 3 + 50]), "f")
    assert shrunk.version == 3 and shrunk.reused_chunks == 3 and shrunk.sent_chunks == 1
    assert down(t, shrunk.file_uuid) == bytes(v1[: CHUNK * 3 + 50])


def test_index_keeps_one_manifest_per_file():
    net, table, client, locs, codec, t = setup()
    up(t, b"a" * 3000, "same")
    res = up(t, b"b" * 3000, "same")
    up(t, b"c" * 10, "other")
    record = net.indexes["node0"][t.keys.sign_pub.hex()]
    assert len(record["ids"]) == 2 and res.manifest_id in record["ids"]


def test_download_survives_one_dead_holder():
    net, table, client, locs, codec, t = setup()
    data = os.urandom(CHUNK * 8)
    res = up(t, data, "f")
    table.kill(net, res.chunks[0]["holders"][0])
    assert down(t, res.file_uuid) == data


def test_download_survives_two_dead_hosts_with_r3():
    net, table, client, locs, codec, t = setup(n=5)
    data = os.urandom(CHUNK * 8)
    res = up(t, data, "f")
    table.kill(net, "node0")
    table.kill(net, "node1")
    assert down(t, res.file_uuid) == data


def test_suspect_holder_still_tried_after_alive_ones():
    net, table, client, locs, codec, t = setup()
    data = os.urandom(CHUNK * 3)
    res = up(t, data, "f")
    table.kill(net, "node2", state="suspect")
    assert down(t, res.file_uuid) == data


def test_corrupt_holder_is_skipped_and_penalised():
    net, table, client, locs, codec, t = setup()
    data = os.urandom(CHUNK * 6)
    res = up(t, data, "f")
    bad = res.chunks[0]["holders"][0]
    net.corrupt.add(bad)
    for p in table.peers.values():                                   # make `bad` the fastest, so it is tried first
        p.rtt_ewma, p.bw_ewma = (0.0001, 1e9) if p.node_id == bad else (0.05, 1e6)
    assert down(t, res.file_uuid) == data
    assert table.failures.get(bad, 0) >= 1


def test_whole_file_hash_mismatch_raises():
    net, table, client, locs, codec, t = setup()
    res = up(t, os.urandom(CHUNK * 2), "f")
    real = codec.decode_chunk
    codec.decode_chunk = lambda *a: real(*a)[:-1] + b"?"
    with pytest.raises(IntegrityError):
        down(t, res.file_uuid)


def test_stale_location_map_falls_back_to_asking_everyone():
    net, table, client, locs, codec, t = setup()
    data = os.urandom(CHUNK * 2)
    res = up(t, data, "f")
    locs.map.clear()
    assert down(t, res.file_uuid) == data


def test_upload_with_two_hosts_is_degraded_not_failed():
    net, table, client, locs, codec, t = setup()
    table.kill(net, "node0")
    table.kill(net, "node1")
    res = up(t, os.urandom(CHUNK * 2), "f")
    assert res.status == "degraded"
    assert all(len(c["holders"]) == 2 for c in res.chunks)


def test_upload_with_no_peers_raises():
    net, table, client, locs, codec, t = setup(n=2)
    for n in ("node0", "node1"):
        table.kill(net, n)
    with pytest.raises(NotEnoughPeers):
        up(t, b"data", "f")


def test_all_holders_gone_is_unavailable():
    net, table, client, locs, codec, t = setup(n=3)
    res = up(t, os.urandom(CHUNK), "f")
    for n in ("node0", "node1", "node2"):
        table.kill(net, n)
    assert t.file_status(res.file_uuid) == "unavailable"
    with pytest.raises(ChunkUnavailable):
        down(t, res.file_uuid)


def test_full_peer_is_skipped_for_next_ranked():
    net, table, client, locs, codec, t = setup(n=5)
    net.full.add("node0")
    res = up(t, os.urandom(CHUNK * 4), "f")
    assert res.status == "durable"
    assert all("node0" not in c["holders"] for c in res.chunks)


def test_recover_on_fresh_device_with_username_and_passphrase():
    net, table, client, locs, codec, t = setup()
    a = os.urandom(CHUNK * 3)
    b = os.urandom(CHUNK + 7)
    ra = up(t, a, "a.bin")
    rb = up(t, b, "b.bin")

    fresh = Transfer(keys_for(codec), codec, table, client, locs, chunk_size=CHUNK)
    assert run(fresh.recover()) == 2
    assert down(fresh, ra.file_uuid) == a
    assert down(fresh, rb.file_uuid) == b
    assert fresh.index_version == t.index_version


def test_recover_ignores_forged_index_wrong_passphrase_and_other_user():
    net, table, client, locs, codec, t = setup()
    up(t, b"secret" * 100, "s")
    owner = t.keys.sign_pub.hex()
    net.indexes["node0"][owner] = {"version": 999, "ids": ["deadbeef"], "sig": "forged"}

    honest = Transfer(keys_for(codec), codec, table, client, locs, chunk_size=CHUNK)
    assert run(honest.recover()) == 1
    wrong_pass = Transfer(keys_for(codec, passphrase="wrong"), codec, table, client, locs)
    assert run(wrong_pass.recover()) == 0
    other_user = Transfer(keys_for(codec, user="hridya"), codec, table, client, locs)
    assert run(other_user.recover()) == 0


def test_catalog_persists_to_disk(tmp_path):
    net, table, client, locs, codec = make_cluster(4)
    path = tmp_path / "catalog.json"
    t = Transfer(keys_for(codec), codec, table, client, locs, catalog_path=path, chunk_size=CHUNK)
    res = up(t, b"hello" * 500, "h")
    reloaded = Transfer(keys_for(codec), codec, table, client, locs, catalog_path=path, chunk_size=CHUNK)
    assert down(reloaded, res.file_uuid) == b"hello" * 500
    assert reloaded.index_version == t.index_version


class StallingClient:
    """Wraps a FakeClient; GETs from `stalled` nodes hang for `stall_s`."""

    def __init__(self, inner, stalled, stall_s):
        self.inner, self.stalled, self.stall_s = inner, set(stalled), stall_s
        self.cancelled = 0

    def __getattr__(self, name):
        return getattr(self.inner, name)

    async def get_chunk(self, peer, chunk_id):
        if peer.node_id in self.stalled:
            try:
                await asyncio.sleep(self.stall_s)
            except asyncio.CancelledError:
                self.cancelled += 1
                raise
        return await self.inner.get_chunk(peer, chunk_id)


def stalled_setup(hedge):
    net, table, client, locs, codec, t = setup()
    data = os.urandom(CHUNK * 4)
    res = up(t, data, "f")
    # node0 looks fastest on paper (stale estimate), so it is tried first, but it hangs.
    for p in table.peers.values():
        p.rtt_ewma, p.bw_ewma = (0.0001, 1e9) if p.node_id == "node0" else (0.002, 50e6)
    stalling = StallingClient(client, {"node0"}, stall_s=1.0)
    t2 = Transfer(t.keys, codec, table, stalling, locs, chunk_size=CHUNK, hedge=hedge)
    t2.catalog, t2.index_version = t.catalog, t.index_version
    return t2, stalling, data, res


def test_hedged_read_beats_a_stalled_holder():
    t, stalling, data, res = stalled_setup(hedge=True)
    started = time.perf_counter()
    assert down(t, res.file_uuid) == data
    assert time.perf_counter() - started < 0.6
    assert t.hedges_fired >= 1 and stalling.cancelled >= 1


def test_without_hedging_a_stalled_holder_costs_the_full_stall():
    t, stalling, data, res = stalled_setup(hedge=False)
    started = time.perf_counter()
    assert down(t, res.file_uuid) == data
    assert time.perf_counter() - started >= 1.0
    assert t.hedges_fired == 0


def test_random_baseline_is_never_hedged():
    t, stalling, data, res = stalled_setup(hedge=True)
    out = io.BytesIO()
    run(t.download(res.file_uuid, out, "random"))
    assert out.getvalue() == data and t.hedges_fired == 0


def test_recover_skips_a_manifest_no_peer_can_serve():
    net, table, client, locs, codec, t = setup()
    a = up(t, os.urandom(CHUNK * 2), "a.bin")
    b = up(t, os.urandom(CHUNK * 2), "b.bin")
    for store in net.stores.values():          # every copy of a's manifest is gone
        store.pop(a.manifest_id, None)
    fresh = Transfer(keys_for(codec), codec, table, client, locs, chunk_size=CHUNK)
    assert run(fresh.recover()) == 1
    assert fresh.unrecovered == [a.manifest_id]
    assert list(fresh.catalog) == [b.file_uuid]


def test_upload_reports_how_many_peers_took_the_index():
    net, table, client, locs, codec, t = setup()
    up(t, b"x" * 3000, "a")
    assert t.last_index_acks == 4
    owner = t.keys.sign_pub.hex()
    for slot in net.indexes.values():           # another device publishes a newer list mid-upload
        slot[owner] = {"version": 10**6, "ids": [], "sig": owner}

    async def no_sync():                        # the race: our pre-upload sync ran just before that
        return 0
    t.recover = no_sync
    up(t, b"y" * 3000, "b")
    assert t.last_index_acks == 0



def two_laptops():
    net, table, client, locs, codec, t1 = setup()
    t2 = Transfer(keys_for(codec), codec, table, client, locs, chunk_size=CHUNK)
    return net, codec, t1, t2


def test_second_laptop_sees_a_new_file_after_sync():
    net, codec, t1, t2 = two_laptops()
    assert run(t2.recover()) == 0                # unlocked before anything was uploaded
    data = os.urandom(CHUNK * 3)
    res = up(t1, data, "notes.pdf")
    assert res.file_uuid not in t2.catalog
    assert run(t2.recover()) == 1                # what the 15 s sync loop does
    assert down(t2, res.file_uuid) == data


def test_sync_only_fetches_manifests_it_does_not_have():
    net, codec, t1, t2 = two_laptops()
    up(t1, b"a" * 3000, "a")
    up(t1, b"b" * 3000, "b")
    run(t2.recover())
    calls = []
    original = t2._load_manifest

    async def counting(mid, *args):
        calls.append(mid)
        return await original(mid, *args)

    t2._load_manifest = counting
    up(t1, b"c" * 3000, "c")
    assert run(t2.recover()) == 3
    assert len(calls) == 1


def test_upload_keeps_files_from_other_laptops_in_the_index():
    net, codec, t1, t2 = two_laptops()
    run(t2.recover())
    up(t1, b"from laptop 1" * 300, "one")
    up(t2, b"from laptop 2" * 300, "two")       # t2 never synced in between
    fresh = Transfer(keys_for(codec), codec, *two_laptops_parts(t1))
    assert run(fresh.recover()) == 2


def two_laptops_parts(t):
    return t.peers, t.client, t.locations


def test_reupload_from_another_laptop_reuses_the_file_and_key():
    net, codec, t1, t2 = two_laptops()
    data = os.urandom(CHUNK * 4)
    first = up(t1, data, "log.csv")
    second = up(t2, data + b"tail", "log.csv")   # t2 syncs before uploading
    assert second.file_uuid == first.file_uuid and second.version == 2
    assert second.reused_chunks == 4
