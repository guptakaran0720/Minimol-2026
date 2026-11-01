"""Graceful drain: no new chunks, peers see 'draining', safe once the others hold every chunk."""
import asyncio
import hashlib

from node.chunkstore import DiskChunkStore
from node.contracts import Peer
from node.drain import Drain
from node.events import EventLog
from node.inventory import LocationMap
from node.peers import PeerTable


def cid(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def setup(tmp_path, others=("b", "c", "d")):
    store = DiskChunkStore(tmp_path, quota_bytes=10_000)
    events = EventLog()                      # one log for the table and the drain, as in main.build_node
    table = PeerTable(Peer(node_id="me", host_id="h-me", addr="me:1"), events=events)
    for n in others:
        table.heartbeat_ok(f"{n}:1", {"node_id": n, "host_id": f"h-{n}"}, 0.001)
    return store, table, LocationMap(), events, Drain()


def test_draining_node_takes_no_new_chunks_but_stays_listed(tmp_path):
    store, table, locs, events, drain = setup(tmp_path)
    drain.start(table, events)
    assert table.me.state == "draining"
    assert "me" not in {p.node_id for p in table.alive()}       # placement skips it
    assert table.get("me") is not None
    drain.stop(table, events)
    assert table.me.state == "alive"
    kinds = [e["kind"] for e in events.since(0) if not e["kind"] == "peer_joined"]
    assert kinds == ["peer_draining", "drain_started", "peer_alive", "drain_cancelled"]


def test_safe_only_when_other_live_hosts_hold_every_chunk(tmp_path):
    store, table, locs, events, drain = setup(tmp_path)
    a, b = b"chunk a", b"chunk b"
    for blob in (a, b):
        store.put(cid(blob), blob)
        locs.note(cid(blob), "me")
    drain.start(table, events)
    s = drain.status(store, locs, table)
    assert s["copies_needed_elsewhere"] == 3 and s["safe_chunks"] == 0 and not s["safe_to_power_off"]
    for n in ("b", "c", "d"):
        locs.note(cid(a), n)
    locs.note(cid(b), "b")
    locs.note(cid(b), "c")
    assert drain.status(store, locs, table)["safe_chunks"] == 1
    asyncio.run(drain.check_once(store, locs, table, events))
    assert "drain_complete" not in [e["kind"] for e in events.since(0)]
    locs.note(cid(b), "d")
    asyncio.run(drain.check_once(store, locs, table, events))
    asyncio.run(drain.check_once(store, locs, table, events))         # announced once
    assert drain.status(store, locs, table)["safe_to_power_off"]
    assert [e["kind"] for e in events.since(0)].count("drain_complete") == 1


def test_with_three_laptops_the_two_others_are_enough(tmp_path):
    store, table, locs, events, drain = setup(tmp_path, others=("b", "c"))
    store.put(cid(b"x"), b"x")
    for n in ("me", "b", "c"):
        locs.note(cid(b"x"), n)
    drain.start(table, events)
    s = drain.status(store, locs, table)
    assert s["copies_needed_elsewhere"] == 2 and s["safe_to_power_off"]


def test_peers_learn_draining_from_health_and_never_place_on_it():
    table = PeerTable(Peer(node_id="me", host_id="h-me", addr="me:1"))
    table.heartbeat_ok("b:1", {"node_id": "b", "host_id": "h-b", "draining": True}, 0.001)
    assert table.get("b").state == "draining" and table.get("b") not in table.alive()
    table.record_transfer("b", 100, 0.01)                         # still serves reads; stays draining
    assert table.get("b").state == "draining"
    table.heartbeat_ok("b:1", {"node_id": "b", "host_id": "h-b", "draining": False}, 0.001)
    assert table.get("b").state == "alive"
