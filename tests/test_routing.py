import time

from node.contracts import Peer
from node.routing import (
    hrw_u,
    rank_for_placement,
    rank_for_retrieval,
    repair_leader,
    repair_order,
)

GB = 1024**3


def peer(n, host=None, **kw):
    kw.setdefault("free_bytes", GB)
    return Peer(node_id=n, host_id=host or f"h-{n}", addr=f"10.0.0.{len(n)}:8000", **kw)


def chunk_ids(count):
    return [f"{i:064x}" for i in range(count)]


def test_hrw_u_is_strictly_inside_unit_interval():
    for cid in chunk_ids(500):
        u = hrw_u(cid, "node-a")
        assert 0.0 < u < 1.0


def test_placement_filters_dead_full_and_excluded_hosts():
    peers = [
        peer("a"),
        peer("b", state="dead"),
        peer("c", free_bytes=1024),
        peer("d", host="h-x"),
        peer("e"),
    ]
    ranked = rank_for_placement("ff" * 32, peers, exclude_hosts={"h-x"})
    assert {p.node_id for p in ranked} == {"a", "e"}


def test_placement_never_returns_two_nodes_on_one_host():
    peers = [peer("a", host="laptop1"), peer("b", host="laptop1"), peer("c"), peer("d")]
    for cid in chunk_ids(200):
        hosts = [p.host_id for p in rank_for_placement(cid, peers, set())]
        assert len(hosts) == len(set(hosts))


def test_placement_is_deterministic():
    peers = [peer(n) for n in "abcdef"]
    for cid in chunk_ids(50):
        first = [p.node_id for p in rank_for_placement(cid, peers, set())]
        again = [p.node_id for p in rank_for_placement(cid, list(reversed(peers)), set())]
        assert first == again


def test_slow_tier_never_chosen_while_three_healthy_hosts_exist():
    peers = [peer("a"), peer("b"), peer("c"), peer("slow", tier=2)]
    for cid in chunk_ids(300):
        top3 = [p.node_id for p in rank_for_placement(cid, peers, set())[:3]]
        assert "slow" not in top3


def test_slow_tier_used_as_fallback():
    peers = [peer("a"), peer("b"), peer("slow", tier=2)]
    top3 = [p.node_id for p in rank_for_placement("ab" * 32, peers, set())[:3]]
    assert top3[-1] == "slow"


def test_removing_a_non_winner_does_not_move_chunks():
    peers = [peer(n) for n in "abcdefgh"]
    for cid in chunk_ids(300):
        top3 = [p.node_id for p in rank_for_placement(cid, peers, set())[:3]]
        loser = next(p for p in peers if p.node_id not in top3)
        remaining = [p for p in peers if p is not loser]
        assert [p.node_id for p in rank_for_placement(cid, remaining, set())[:3]] == top3


def test_weight_controls_first_choice_share():
    peers = [peer("light", weight=1.0), peer("heavy", weight=3.0)]
    wins = sum(rank_for_placement(cid, peers, set())[0].node_id == "heavy" for cid in chunk_ids(4000))
    assert abs(wins / 4000 - 0.75) < 0.04


def test_retrieval_prefers_lower_eta():
    fast = peer("fast", rtt_ewma=0.002, bw_ewma=50e6)
    slow = peer("slow", rtt_ewma=0.300, bw_ewma=5e6)
    assert [p.node_id for p in rank_for_retrieval([slow, fast])] == ["fast", "slow"]


def test_retrieval_cooldown_and_suspect_go_last_dead_dropped():
    now = time.monotonic()
    cooled = peer("cooled", rtt_ewma=0.001, bw_ewma=100e6, cooldown_until=now + 60)
    suspect = peer("suspect", state="suspect", rtt_ewma=0.001, bw_ewma=100e6)
    normal = peer("normal", rtt_ewma=0.050, bw_ewma=10e6)
    dead = peer("dead", state="dead")
    order = [p.node_id for p in rank_for_retrieval([cooled, suspect, dead, normal])]
    assert order == ["normal", "suspect", "cooled"]


def test_retrieval_new_peer_gets_median_prior():
    known_fast = peer("k1", rtt_ewma=0.002, bw_ewma=80e6)
    known_slow = peer("k2", rtt_ewma=0.200, bw_ewma=2e6)
    known_mid = peer("k3", rtt_ewma=0.010, bw_ewma=20e6)
    new = peer("new")
    order = [p.node_id for p in rank_for_retrieval([known_slow, new, known_fast, known_mid])]
    assert order[0] == "k1" and order[-1] == "k2"


def test_repair_leader_is_order_independent_member():
    ids = ["n1", "n2", "n3"]
    for cid in chunk_ids(100):
        leader = repair_leader(cid, ids)
        assert leader in ids
        assert leader == repair_leader(cid, list(reversed(ids)))
        assert repair_order(cid, ids)[0] == leader
