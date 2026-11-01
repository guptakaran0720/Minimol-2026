import asyncio
import io
import os

from node.contracts import owner_salt
from node.repair import Repairer
from node.transfer import Transfer
from tests.fakes import FakeStore, make_cluster

CHUNK = 1024


def run(coro):
    return asyncio.run(coro)


def cluster(n=5, chunks=12):
    net, table, client, locs, codec = make_cluster(n)
    t = Transfer(codec.derive_master("pw", owner_salt("karan")), codec, table, client, locs, chunk_size=CHUNK)
    data = os.urandom(CHUNK * chunks)
    res = run(t.upload(io.BytesIO(data), "f"))
    return net, table, client, locs, t, data, res


def repairers(net, table, client, locs, **kw):
    return {
        p.node_id: Repairer(p.node_id, p.host_id, FakeStore(net, p.node_id), table, client, locs, **kw)
        for p in table.peers.values()
        if p.node_id not in net.down
    }


def live_hosts(net, table, cid):
    return {table.get(n).host_id for n, s in net.stores.items() if cid in s and n not in net.down}


def all_objects(net):
    return {cid for s in net.stores.values() for cid in s}


def fetch(t, file_uuid):
    out = io.BytesIO()
    run(t.download(file_uuid, out))
    return out.getvalue()


def repair_round(reps):
    async def go():
        return await asyncio.gather(*(r.run_once() for r in reps.values()))
    return run(go())


def test_kill_one_node_repairs_every_chunk_back_to_three_hosts():
    net, table, client, locs, t, data, res = cluster()
    victim = res.chunks[0]["holders"][0]
    table.kill(net, victim)
    locs.refresh()
    stats = repair_round(repairers(net, table, client, locs))
    assert sum(s["copies"] for s in stats) > 0
    for cid in all_objects(net):
        assert len(live_hosts(net, table, cid)) >= 3
    assert fetch(t, res.file_uuid) == data


def test_survives_two_sequential_failures_after_repair():
    net, table, client, locs, t, data, res = cluster()
    first = res.chunks[0]["holders"][0]
    table.kill(net, first)
    locs.refresh()
    repair_round(repairers(net, table, client, locs))
    second = next(n for n in res.chunks[0]["holders"] if n != first)
    table.kill(net, second)
    locs.refresh()
    repair_round(repairers(net, table, client, locs))
    assert fetch(t, res.file_uuid) == data


def test_only_leader_copies_in_first_round():
    net, table, client, locs, t, data, res = cluster(chunks=20)
    table.kill(net, "node0")
    locs.refresh()
    puts_before = net.puts
    repair_round(repairers(net, table, client, locs))
    short_before = sum(1 for cid in all_objects(net) if "node0" in locs.holders(cid))
    # one copy per short object; no duplicate copies from non-leaders
    assert net.puts - puts_before == short_before


def test_racing_repairers_never_under_replicate():
    net, table, client, locs, t, data, res = cluster(chunks=20)
    table.kill(net, "node1")
    locs.refresh()
    repair_round(repairers(net, table, client, locs, takeover_rounds=0))   # everyone acts at once
    for cid in all_objects(net):
        assert 3 <= len(live_hosts(net, table, cid)) <= 4


def test_suspect_holder_delays_repair():
    net, table, client, locs, t, data, res = cluster()
    table.kill(net, "node2", state="suspect")
    locs.refresh()
    stats = repair_round(repairers(net, table, client, locs))
    assert sum(s["copies"] for s in stats) == 0
    assert sum(s["waiting"] for s in stats) > 0


def test_follower_takes_over_after_two_rounds_when_leader_is_silent():
    net, table, client, locs, t, data, res = cluster(chunks=1)
    cid = res.chunks[0]["chunk_id"]
    dead = res.chunks[0]["holders"][0]
    table.kill(net, dead)
    locs.refresh()
    reps = repairers(net, table, client, locs)
    from node.routing import repair_order
    survivors = [n for n in res.chunks[0]["holders"] if n != dead]
    order = repair_order(cid, survivors)
    follower = reps[order[1]]                    # the leader never runs in this test
    # (the follower may also lead repair of the manifest object, so check this chunk only)
    run(follower.run_once())
    assert len(live_hosts(net, table, cid)) == 2       # round 1: leader's turn
    run(follower.run_once())
    assert len(live_hosts(net, table, cid)) == 2       # round 2: still leader's turn
    run(follower.run_once())
    assert len(live_hosts(net, table, cid)) >= 3       # round 3: takeover


def test_only_two_hosts_left_reports_degraded():
    net, table, client, locs, t, data, res = cluster(n=4, chunks=4)
    table.kill(net, "node0")
    table.kill(net, "node1")
    locs.refresh()
    stats = repair_round(repairers(net, table, client, locs, takeover_rounds=0))
    assert sum(s["degraded"] for s in stats) > 0
    assert fetch(t, res.file_uuid) == data


def test_corrupt_local_copy_is_not_spread():
    net, table, client, locs, t, data, res = cluster(chunks=1)
    cid = res.chunks[0]["chunk_id"]
    dead = res.chunks[0]["holders"][0]
    table.kill(net, dead)
    locs.refresh()
    for n in res.chunks[0]["holders"]:
        if n != dead:
            net.stores[n][cid] = b"rotten"
    stats = repair_round(repairers(net, table, client, locs, takeover_rounds=0))
    assert all(net.stores[n].get(cid) != b"rotten" for n in net.stores if n not in res.chunks[0]["holders"])
    assert sum(s["skipped_corrupt"] for s in stats) >= 1
