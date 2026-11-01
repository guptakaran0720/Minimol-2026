"""Proof-of-storage audits: an honest holder passes; a missing or altered copy is distrusted."""
import asyncio
import hashlib
import hmac
import random
from collections import Counter

from node.chunkstore import DiskChunkStore
from node.contracts import Peer
from node.events import EventLog
from node.inventory import LocationMap
from node.peers import PeerTable
from node.audit import audit_once


def cid(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


class AuditClient:
    """Answers audits from a dict of what each peer 'really' holds."""

    def __init__(self, holdings: dict[str, dict[str, bytes]], down: set[str] = frozenset()):
        self.holdings, self.down, self.asked = holdings, down, []

    async def audit_chunk(self, peer, chunk_id, nonce):
        self.asked.append((peer.node_id, chunk_id))
        if peer.node_id in self.down:
            raise ConnectionError(peer.node_id)
        blob = self.holdings.get(peer.node_id, {}).get(chunk_id)
        return None if blob is None else hmac.new(nonce, blob, hashlib.sha256).hexdigest()


def setup(tmp_path, blob=b"the real chunk bytes"):
    store = DiskChunkStore(tmp_path, quota_bytes=10_000)
    store.put(cid(blob), blob)
    clock = Clock()
    table = PeerTable(Peer(node_id="me", host_id="h-me", addr="me:1"))
    for n in ("b", "c"):
        table.heartbeat_ok(f"{n}:1", {"node_id": n, "host_id": f"h-{n}"}, 0.001)
    locs = LocationMap(clock=clock)
    for n in ("me", "b", "c"):
        locs.note(cid(blob), n)
    return store, table, locs, clock, blob


def run_audits(store, locs, table, client, rounds=10):
    events, stats = EventLog(), Counter()
    for i in range(rounds):
        asyncio.run(audit_once(store, locs, table, client, events, 1, stats, random.Random(i)))
    return events, stats


def test_honest_holders_pass(tmp_path):
    store, table, locs, _, blob = setup(tmp_path)
    client = AuditClient({"b": {cid(blob): blob}, "c": {cid(blob): blob}})
    events, stats = run_audits(store, locs, table, client)
    assert stats["passed"] == 10 and stats["failed"] == 0
    assert {n for n, _ in client.asked} == {"b", "c"}          # never audits itself
    assert locs.holders(cid(blob)) == {"me", "b", "c"} and events.since(0) == []


def test_missing_copy_is_distrusted_then_expires(tmp_path):
    store, table, locs, clock, blob = setup(tmp_path)
    client = AuditClient({"b": {cid(blob): blob}, "c": {}})   # c lists the chunk but doesn't have it
    events, stats = run_audits(store, locs, table, client, rounds=20)
    assert stats["failed"] >= 1
    assert locs.holders(cid(blob)) == {"me", "b"}              # repair now sees one copy short
    assert locs.distrusted(cid(blob), "c")
    [e] = [e for e in events.since(0)][:1]
    assert e["kind"] == "audit_failed" and e["node"] == "c" and "doesn't hold" in e["reason"]
    clock.t += 121                                             # AUDIT_DISTRUST_S later it is audited afresh
    assert locs.holders(cid(blob)) == {"me", "b", "c"}


def test_altered_copy_fails_and_a_later_pass_restores_trust(tmp_path):
    store, table, locs, _, blob = setup(tmp_path)
    client = AuditClient({"b": {cid(blob): blob}, "c": {cid(blob): b"the real chunk byteZ"}})
    events, stats = run_audits(store, locs, table, client, rounds=20)
    assert "copy differs" in [e for e in events.since(0)][0]["reason"]
    assert "c" not in locs.holders(cid(blob))
    client.holdings["c"][cid(blob)] = blob                     # c re-stored a good copy
    locs.trust(cid(blob), "c")
    assert "c" in locs.holders(cid(blob))


def test_corrupt_local_copy_never_accuses_a_peer(tmp_path):
    store, table, locs, _, blob = setup(tmp_path)
    (tmp_path / "chunks" / cid(blob)[:2] / cid(blob)).write_bytes(b"rotten here")
    client = AuditClient({"b": {}, "c": {}})
    events, stats = run_audits(store, locs, table, client)
    assert stats["skipped"] == 10 and stats["failed"] == 0 and client.asked == []


def test_unreachable_peer_is_an_error_not_a_failure(tmp_path):
    store, table, locs, _, blob = setup(tmp_path)
    client = AuditClient({"b": {cid(blob): blob}, "c": {cid(blob): blob}}, down={"b", "c"})
    events, stats = run_audits(store, locs, table, client)
    assert stats["error"] == 10 and stats["failed"] == 0
    assert locs.holders(cid(blob)) == {"me", "b", "c"}
