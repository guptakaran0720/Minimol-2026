"""Localhost routes added by main.py: /transfers, /drain, /metrics; plus peer IP/MAC in snapshots."""
import asyncio

import httpx

from node.config import Settings, mac_for_ip
from node.main import create_app

MAC = "aa:bb:cc:00:11:22"


def app_for(tmp_path):
    settings = Settings(node_id="n1", host_id="h1", cluster_key=b"cluster-key-for-tests", data_dir=tmp_path,
                        advertise_addr="10.0.0.1:8000", mdns=False, mac=MAC)
    return create_app(settings)


def get(app, path, method="GET", host="127.0.0.1", **kw):
    async def go():
        transport = httpx.ASGITransport(app=app, client=(host, 1234))
        async with httpx.AsyncClient(transport=transport, base_url="http://n1") as c:
            return await c.request(method, path, **kw)
    return asyncio.run(go())


def test_transfer_log_with_ip_and_mac(tmp_path):
    app = app_for(tmp_path)
    node = app.state.node
    node.peers.heartbeat_ok("10.0.0.2:8000", {"node_id": "n2", "host_id": "h2", "mac": "aa:bb:cc:00:11:33"}, 0.01)
    peer = node.peers.get("n2")
    node.client.on_transfer("upload", peer, "c1" * 32, 1000, 0.05)
    node.client.on_transfer("download", peer, "c2" * 32, 2000, 0.02)
    body = get(app, "/transfers").json()
    assert body["mac"] == MAC
    assert [(t["direction"], t["ip"], t["mac"], t["bytes"]) for t in body["transfers"]] == [
        ("download", "10.0.0.2", "aa:bb:cc:00:11:33", 2000), ("upload", "10.0.0.2", "aa:bb:cc:00:11:33", 1000)]
    only = get(app, "/transfers", params={"chunks": "c1" * 32}).json()["transfers"]
    assert [t["direction"] for t in only] == ["upload"]
    assert get(app, "/transfers", host="10.0.0.9").status_code == 403
    rows = {p["node_id"]: p for p in node.peers.snapshot()}
    assert rows["n2"]["ip"] == "10.0.0.2" and rows["n2"]["mac"] == "aa:bb:cc:00:11:33" and rows["n1"]["mac"] == MAC


def test_drain_routes(tmp_path):
    app = app_for(tmp_path)
    assert get(app, "/drain").json()["draining"] is False
    s = get(app, "/drain", method="POST", json={"draining": True}).json()
    assert s["draining"] is True and app.state.node.peers.me.state == "draining"
    assert get(app, "/drain", method="POST", json={"draining": False}).json()["draining"] is False
    assert get(app, "/drain", method="POST", host="10.0.0.9", json={"draining": True}).status_code == 403


def test_metrics_endpoint(tmp_path):
    app = app_for(tmp_path)
    node = app.state.node
    node.audit_stats["passed"] += 3
    node.client.bytes_sent["n2"] += 4096
    node.events.add("audit_failed", node="n2", chunk="ab12", reason="wrong proof")   # labels named "kind"
    r = get(app, "/metrics")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    text = r.text
    for line in ('minimol_info{node_id="n1",host_id="h1",addr="10.0.0.1:8000",mac="aa:bb:cc:00:11:22"} 1',
                 'minimol_audits_total{outcome="passed"} 3', 'minimol_client_sent_bytes_total{peer="n2"} 4096',
                 'minimol_peer_state{peer="n1",state="alive"} 1', "minimol_store_chunks 0", "minimol_draining 0",
                 "# TYPE minimol_scrub_checked_total counter", 'minimol_events_total{kind="audit_failed"} 1'):
        assert line in text, line
    assert get(app, "/metrics", host="10.0.0.9").status_code == 403


def test_mac_for_ip_reads_the_interface_holding_the_ip(monkeypatch):
    ifconfig = """lo0: flags=8049<UP,LOOPBACK> mtu 16384
\tinet 127.0.0.1 netmask 0xff000000
en0: flags=8863<UP,BROADCAST> mtu 1500
\tether 56:59:35:2f:5c:b8
\tinet 10.10.220.223 netmask 0xffffe000 broadcast 10.10.223.255
en1: flags=8863<UP> mtu 1500
\tether 11:22:33:44:55:66
"""
    monkeypatch.setattr("node.config._run", lambda *cmd: ifconfig if cmd == ("ifconfig",) else "")
    assert mac_for_ip("10.10.220.223") == "56:59:35:2f:5c:b8"
