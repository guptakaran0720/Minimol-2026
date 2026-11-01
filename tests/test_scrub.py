"""Scrub loop: a corrupt chunk is quarantined, logged, and leaves the location map at once."""
import asyncio
import hashlib

from node.chunkstore import DiskChunkStore
from node.events import EventLog
from node.inventory import LocationMap
from node.scrub import scrub_once


def cid(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def test_scrub_once_quarantines_and_updates_map(tmp_path):
    store = DiskChunkStore(tmp_path, quota_bytes=10_000)
    a, b = b"chunk a", b"chunk b"
    store.put(cid(a), a)
    store.put(cid(b), b)
    locations = LocationMap()
    locations.replace_inventory("me", store.list_ids())
    locations.note(cid(b), "peer-1")
    events = EventLog()
    (tmp_path / "chunks" / cid(b)[:2] / cid(b)).write_bytes(b"chunk B")
    asyncio.run(scrub_once(store, locations, "me", events, per_round=10))
    assert locations.holders(cid(b)) == {"peer-1"}        # repair now sees one copy short
    assert locations.holders(cid(a)) == {"me"}
    [e] = events.since(0)
    assert e["kind"] == "chunk_quarantined" and e["chunk"] == cid(b)[:12] and e["node"] == "me"


def test_clean_store_logs_nothing(tmp_path):
    store = DiskChunkStore(tmp_path, quota_bytes=10_000)
    store.put(cid(b"ok"), b"ok")
    events = EventLog()
    asyncio.run(scrub_once(store, LocationMap(), "me", events, per_round=10))
    assert events.since(0) == []
