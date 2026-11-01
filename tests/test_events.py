"""GET /events: P2 events merged with repair events, newest first, localhost only."""
import asyncio

import httpx

from node.config import Settings
from node.events import EventLog
from node.main import create_app


def test_event_log_since():
    log = EventLog(clock=iter(range(100)).__next__)
    log.add("a")
    second = log.add("b", node="x")
    assert [e["kind"] for e in log.since(0)] == ["a", "b"]
    assert log.since(second["seq"]) == []
    assert second == {"seq": 2, "t": 1, "kind": "b", "node": "x"}


def test_events_route_merges_and_is_localhost_only(tmp_path):
    settings = Settings(node_id="n1", host_id="h1", cluster_key=b"cluster-key-for-tests", data_dir=tmp_path,
                        advertise_addr="127.0.0.1:9", mdns=False)
    app = create_app(settings)
    node = app.state.node
    node.events.add("peer_dead", node="n2", reason="no contact for 20 s")

    class FakeRepairer:
        events = [{"t": node.events.since(0)[0]["t"] + 1, "kind": "copied", "chunk": "ab12", "to": "n3"}]
    app.state.repairer = FakeRepairer()

    async def get(client_host):
        transport = httpx.ASGITransport(app=app, client=(client_host, 1234))
        async with httpx.AsyncClient(transport=transport, base_url="http://n1") as c:
            return await c.get("/events")

    r = asyncio.run(get("127.0.0.1"))
    assert r.status_code == 200
    body = r.json()
    assert [(e["kind"], e["source"]) for e in body["events"]] == [("copied", "repair"), ("peer_dead", "node")]
    assert body["scrub"]["checked"] == 0
    assert asyncio.run(get("10.0.0.9")).status_code == 403
