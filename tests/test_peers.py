import asyncio

from node import config
from node.contracts import Peer
from node.discovery import add_seeds, gossip_once
from node.inventory import LocationMap, inventory_once
from node.peers import PeerTable, heartbeat_once


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class FakeClient:
    """Answers /health, /inventory and /peers for whichever addrs are 'up'."""

    def __init__(self):
        self.up: dict[str, dict] = {}            # addr -> health
        self.inventories: dict[str, list[str]] = {}
        self.peer_lists: dict[str, list[dict]] = {}

    async def health(self, addr):
        if addr not in self.up:
            raise ConnectionError(addr)
        return self.up[addr]

    async def get_inventory(self, peer):
        if peer.addr not in self.up:
            raise ConnectionError(peer.addr)
        return self.inventories.get(peer.node_id, [])

    async def get_peers(self, peer):
        return self.peer_lists.get(peer.node_id, [])


def health(node_id, host_id=None, free=10_000):
    return {"node_id": node_id, "host_id": host_id or f"h-{node_id}", "free_bytes": free}


def setup():
    clock = Clock()
    table = PeerTable(Peer(node_id="me", host_id="h-me", addr="me:1"), clock=clock)
    return clock, table, FakeClient()


def beat(table, client):
    asyncio.run(heartbeat_once(table, client, lambda: 123))


def join(table, client, *names):
    """Bring peers up and confirm them with one heartbeat round."""
    for n in names:
        client.up[f"{n}:1"] = health(n)
        table.add_candidate(f"{n}:1")
    beat(table, client)


def test_self_is_alive_and_in_table():
    _, table, _ = setup()
    assert [p.node_id for p in table.alive()] == ["me"]
    table.record_failure("me")
    assert table.get("me").state == "alive"


def test_seed_becomes_peer_after_heartbeat():
    _, table, client = setup()
    add_seeds(table, ["b:1", "me:1"])
    assert table.candidates() == ["b:1"]
    beat(table, client)                                  # b is down: stays a candidate
    assert table.get("b") is None and table.candidates() == ["b:1"]
    client.up["b:1"] = health("b", free=555)
    beat(table, client)
    b = table.get("b")
    assert b.state == "alive" and b.host_id == "h-b" and b.free_bytes == 555 and b.rtt_ewma > 0
    assert table.candidates() == []
    assert table.me.free_bytes == 123


def test_suspect_then_dead_then_back():
    clock, table, client = setup()
    join(table, client, "b")
    del client.up["b:1"]
    clock.t += 2
    beat(table, client)
    assert table.get("b").state == "alive"               # 1 missed
    clock.t += 2
    beat(table, client)
    assert table.get("b").state == "suspect"             # 2 missed
    assert table.get("b") not in table.alive()
    clock.t += config.DEAD_AFTER_S
    beat(table, client)
    assert table.get("b").state == "dead"
    assert table.get("b") is not None                    # still visible to repair
    join(table, client, "b")
    assert table.get("b").state == "alive"


def test_failed_transfer_suspects_and_cools_down():
    clock, table, client = setup()
    join(table, client, "b")
    table.record_failure("b")
    b = table.get("b")
    assert b.state == "suspect" and b.cooldown_until == clock.t + config.FAILURE_COOLDOWN_S
    table.record_transfer("b", 1024 * 1024, 0.1)         # a successful transfer is contact
    assert b.state == "alive"


def test_transfer_ewma():
    _, table, client = setup()
    join(table, client, "b")
    b = table.get("b")
    table.record_transfer("b", 1_000_000, 1.0)
    assert b.bw_ewma == 1_000_000
    table.record_transfer("b", 1_000_000, 0.5)
    assert abs(b.bw_ewma - (0.3 * 2_000_000 + 0.7 * 1_000_000)) < 1e-6
    rtt = b.rtt_ewma
    table.record_transfer("b", 100, 0.2)                 # small: updates rtt, not bandwidth
    assert b.rtt_ewma != rtt and abs(b.bw_ewma - 1_300_000) < 1e-6


def test_restarted_node_with_new_id_replaces_old():
    _, table, client = setup()
    join(table, client, "b")
    client.up["b:1"] = health("b2")
    beat(table, client)
    assert table.get("b").state == "dead" and table.get("b2").state == "alive"


def test_slow_peer_moves_to_tier_2_and_back():
    clock, table, client = setup()
    join(table, client, "b", "c", "d")
    for n in "bcd":
        table.get(n).rtt_ewma = 0.001
    for n in ("me", "b", "c"):
        table.get(n).bw_ewma = 10e6
    table.get("d").bw_ewma = 0.5e6                       # ~20x slower than the median
    table.update_tiers()
    clock.t += config.SLOW_HOLD_S - 1
    table.update_tiers()
    assert table.get("d").tier == 1                      # not held long enough yet
    clock.t += 1
    table.update_tiers()
    assert table.get("d").tier == 2
    assert all(table.get(n).tier == 1 for n in ("me", "b", "c"))
    table.get("d").bw_ewma = 10e6
    table.update_tiers()
    clock.t += config.SLOW_HOLD_S
    table.update_tiers()
    assert table.get("d").tier == 1


def test_location_map():
    m = LocationMap()
    m.replace_inventory("b", ["x", "y"])
    m.note("x", "c")
    assert m.holders("x") == {"b", "c"} and m.holders("y") == {"b"}
    m.replace_inventory("b", ["y", "z"])
    assert m.holders("x") == {"c"} and m.holders("z") == {"b"}
    m.forget("b")
    assert m.holders("y") == set() and m.holders("x") == {"c"}


def test_inventory_once_keeps_unreachable_peer_entries():
    class Store:
        def list_ids(self):
            return ["mine"]

    _, table, client = setup()
    join(table, client, "b")
    client.inventories["b"] = ["x"]
    locs = LocationMap()
    asyncio.run(inventory_once(locs, table, client, Store()))
    assert locs.holders("x") == {"b"} and locs.holders("mine") == {"me"}
    del client.up["b:1"]
    asyncio.run(inventory_once(locs, table, client, Store()))
    assert locs.holders("x") == {"b"}


def test_gossip_finds_peers_of_peers():
    _, table, client = setup()
    join(table, client, "b")
    client.peer_lists["b"] = [
        {"node_id": "me", "host_id": "h-me", "addr": "me:1"},
        {"node_id": "b", "host_id": "h-b", "addr": "b:1"},
        {"node_id": "c", "host_id": "h-c", "addr": "c:1"},
    ]
    asyncio.run(gossip_once(table, client))
    assert table.candidates() == ["c:1"]
    client.up["c:1"] = health("c")
    beat(table, client)
    assert {p.node_id for p in table.alive()} == {"me", "b", "c"}
