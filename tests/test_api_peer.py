"""Peer API through the real HttpPeerClient (signed requests), over an in-process ASGI transport."""
import asyncio
import hashlib
import json
from pathlib import Path

import httpx
import pytest

from node import auth, config
from node.api_peer import create_peer_app
from node.chunkstore import DiskChunkStore, IndexStore
from node.config import Settings
from node.contracts import Peer
from node.peer_client import HttpPeerClient
from node.peers import PeerTable

KEY = b"cluster-key-for-tests"
OWNER = "cd" * 32


def fake_verify(record: dict, owner_pub: bytes) -> int:
    if record.get("sig") != "good":
        raise ValueError("bad signature")
    return record["version"]


def make(tmp_path: Path, quota: int = 10 * 1024 * 1024, key: bytes = KEY):
    settings = Settings(node_id="node-a", host_id="host-a", cluster_key=KEY, data_dir=tmp_path,
                        advertise_addr="peer-a:8000", quota_bytes=quota)
    store = DiskChunkStore(tmp_path, quota)
    me = Peer(node_id="node-a", host_id="host-a", addr="peer-a:8000")
    table = PeerTable(me)
    app = create_peer_app(settings, store, IndexStore(tmp_path), table, fake_verify)
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app))
    return store, table, HttpPeerClient("node-b", key, http), me


def run(coro):
    return asyncio.run(coro)


def cid(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def test_chunk_round_trip(tmp_path):
    store, _, client, peer = make(tmp_path)
    blob = b"x" * 1000

    async def go():
        assert await client.put_chunk(peer, cid(blob), blob) is True
        assert await client.put_chunk(peer, cid(blob), blob) is True       # 200 already present
        assert await client.head_chunk(peer, cid(blob)) is True
        assert await client.get_chunk(peer, cid(blob)) == blob
        assert await client.get_inventory(peer) == [cid(blob)]
        assert await client.head_chunk(peer, cid(b"missing")) is False
        assert await client.get_chunk(peer, cid(b"missing")) is None
    run(go())


def raw(client: HttpPeerClient, method: str, path: str, body: bytes = b"", key: bytes = KEY):
    headers = auth.sign_headers(key, "node-b", method, path, body)
    return client.http.request(method, f"http://peer-a:8000{path}", content=body, headers=headers)


def test_status_codes(tmp_path):
    _, _, client, _ = make(tmp_path, quota=1500)

    async def go():
        blob = b"y" * 1000
        assert (await raw(client, "PUT", f"/chunks/{cid(blob)}", blob)).status_code == 201
        assert (await raw(client, "PUT", f"/chunks/{cid(blob)}", blob)).status_code == 200
        assert (await raw(client, "PUT", f"/chunks/{cid(b'a')}", b"b")).status_code == 400   # wrong hash
        assert (await raw(client, "PUT", "/chunks/not-hex", b"b")).status_code == 400
        other = b"z" * 1000
        assert (await raw(client, "PUT", f"/chunks/{cid(other)}", other)).status_code == 507  # quota
        big = b"q" * (config.CHUNK_BODY_MAX + 1)
        assert (await raw(client, "PUT", f"/chunks/{cid(big)}", big)).status_code == 413
        r = await client.http.delete(f"http://peer-a:8000/chunks/{cid(blob)}")
        assert r.status_code == 405                                                           # no DELETE
    run(go())


def test_hmac_rejection(tmp_path):
    _, _, client, peer = make(tmp_path)

    async def go():
        assert (await client.http.get("http://peer-a:8000/health")).status_code == 401       # unsigned
        assert (await raw(client, "GET", "/health", key=b"wrong-key-0123456")).status_code == 401
        headers = auth.sign_headers(KEY, "node-b", "GET", "/health", now=0)                   # stale
        assert (await client.http.get("http://peer-a:8000/health", headers=headers)).status_code == 401
        blob = b"payload"
        headers = auth.sign_headers(KEY, "node-b", "PUT", f"/chunks/{cid(blob)}", blob)
        r = await client.http.put(f"http://peer-a:8000/chunks/{cid(blob)}", content=b"tampered",
                                  headers=headers)
        assert r.status_code == 401
        assert (await client.health(peer.addr))["node_id"] == "node-a"
    run(go())


def test_wrong_cluster_key_client_raises(tmp_path):
    _, _, client, peer = make(tmp_path, key=b"another-cluster-key")
    with pytest.raises(httpx.HTTPStatusError):
        run(client.get_chunk(peer, cid(b"a")))


def test_health_and_peers(tmp_path):
    store, table, client, peer = make(tmp_path)

    async def go():
        await client.put_chunk(peer, cid(b"abc"), b"abc")
        h = await client.health(peer.addr)
        assert h["node_id"] == "node-a" and h["host_id"] == "host-a"
        assert h["used_bytes"] == 3 and h["chunk_count"] == 1
        assert h["free_bytes"] == store.free_bytes()
        assert await client.get_peers(peer) == [{"node_id": "node-a", "host_id": "host-a", "addr": "peer-a:8000"}]
    run(go())


def test_index(tmp_path):
    _, _, client, peer = make(tmp_path)

    async def go():
        assert await client.get_index(peer, OWNER) is None
        assert await client.put_index(peer, OWNER, {"version": 2, "sig": "good"}) is True
        assert await client.put_index(peer, OWNER, {"version": 2, "sig": "good"}) is False   # 409
        assert await client.put_index(peer, OWNER, {"version": 1, "sig": "good"}) is False
        assert await client.get_index(peer, OWNER) == {"version": 2, "sig": "good"}
        body = json.dumps({"version": 9, "sig": "forged"}).encode()
        assert (await raw(client, "PUT", f"/index/{OWNER}", body)).status_code == 401
        assert (await raw(client, "PUT", f"/index/{OWNER}", b"not json")).status_code == 400
        assert (await raw(client, "GET", "/index/..%2F..%2Fsecret")).status_code in (400, 404)
    run(go())


def test_simulated_delay(tmp_path):
    import time

    store, table, client, peer = make(tmp_path)
    settings = Settings(node_id="node-a", host_id="host-a", cluster_key=KEY, data_dir=tmp_path,
                        simulated_delay_ms=200)
    app = create_peer_app(settings, store, IndexStore(tmp_path), table, fake_verify)
    slow = HttpPeerClient("node-b", KEY, httpx.AsyncClient(transport=httpx.ASGITransport(app=app)))
    started = time.monotonic()
    run(slow.health("peer-a:8000"))
    assert time.monotonic() - started >= 0.2


def test_unknown_caller_address_becomes_candidate(tmp_path):
    """A seed learns about nodes that only know it, from their X-Addr header."""
    _, table, client, peer = make(tmp_path)
    client.advertise_addr = "10.0.0.7:8000"
    run(client.health(peer.addr))
    assert table.candidates() == ["10.0.0.7:8000"]
    client.advertise_addr = "bad addr; rm -rf"
    run(client.health(peer.addr))
    assert table.candidates() == ["10.0.0.7:8000"]


def test_unsigned_or_impostor_responses_rejected(tmp_path):
    """A stranger answering /health without the cluster key can't join the peer table."""
    from fastapi import FastAPI

    from node.auth import AuthError

    impostor = FastAPI()

    @impostor.get("/health")
    def h():
        return {"node_id": "evil", "host_id": "evil", "free_bytes": 10**12}

    c = HttpPeerClient("node-b", KEY, httpx.AsyncClient(transport=httpx.ASGITransport(app=impostor)))
    with pytest.raises(AuthError):
        run(c.health("evil:8000"))

    _, _, client, peer = make(tmp_path)
    wrong = Peer(node_id="node-z", host_id="host-a", addr=peer.addr)   # node-a answers, not node-z
    with pytest.raises(AuthError):
        run(client.head_chunk(wrong, cid(b"x")))


def test_replayed_response_rejected(tmp_path):
    """An old signed answer (e.g. 'HEAD 200, I have it') can't be replayed for a new request."""
    from node.auth import AuthError

    store, _, client, peer = make(tmp_path)
    blob = b"held"
    run(client.put_chunk(peer, cid(blob), blob))
    old = run(raw(client, "HEAD", f"/chunks/{cid(blob)}"))
    assert old.status_code == 200 and old.headers["x-resp-sig"]

    class Replay(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            return httpx.Response(200, headers={"x-node": old.headers["x-node"],
                                                "x-resp-sig": old.headers["x-resp-sig"]})

    import time
    time.sleep(1.01)    # a new second -> a new request signature
    c = HttpPeerClient("node-b", KEY, httpx.AsyncClient(transport=Replay()))
    with pytest.raises(AuthError):
        run(c.head_chunk(peer, cid(blob)))


def test_audit_route_proves_possession(tmp_path):
    import hmac as _hmac

    store, _, client, peer = make(tmp_path)
    blob = b"audited bytes"
    run(client.put_chunk(peer, cid(blob), blob))
    nonce = bytes(range(16))
    assert run(client.audit_chunk(peer, cid(blob), nonce)) == _hmac.new(nonce, blob, hashlib.sha256).hexdigest()
    assert run(client.audit_chunk(peer, cid(b"never stored"), nonce)) is None
    bad = json.dumps({"nonce": "zz"}).encode()
    assert run(raw(client, "POST", f"/audit/{cid(blob)}", bad)).status_code == 400
    short = json.dumps({"nonce": "00" * 4}).encode()
    assert run(raw(client, "POST", f"/audit/{cid(blob)}", short)).status_code == 400


def test_health_reports_mac_and_draining(tmp_path):
    _, table, client, peer = make(tmp_path)
    h = run(client.health(peer.addr))
    assert h["draining"] is False and "mac" in h
    table.set_self_draining(True)
    assert run(client.health(peer.addr))["draining"] is True


def test_client_counts_traffic_and_logs_chunk_transfers(tmp_path):
    _, _, client, peer = make(tmp_path)
    moved = []
    client.on_transfer = lambda d, p, c, n, s: moved.append((d, p.node_id, c[:8], n))
    blob = b"z" * 2000
    run(client.put_chunk(peer, cid(blob), blob))
    run(client.get_chunk(peer, cid(blob)))
    run(client.head_chunk(peer, cid(blob)))
    assert moved == [("upload", "node-a", cid(blob)[:8], 2000), ("download", "node-a", cid(blob)[:8], 2000)]
    assert client.bytes_sent["node-a"] >= 2000 and client.bytes_received["node-a"] >= 2000
    assert client.requests[("node-a", "PUT /chunks", "201")] == 1
    assert client.requests[("node-a", "HEAD /chunks", "200")] == 1


def test_distrusted_copy_is_not_believed(tmp_path):
    _, _, client, peer = make(tmp_path)
    blob = b"held"
    run(client.put_chunk(peer, cid(blob), blob))
    assert run(client.head_chunk(peer, cid(blob))) is True
    client.is_distrusted = lambda chunk_id, node_id: node_id == "node-a"
    assert run(client.head_chunk(peer, cid(blob))) is False     # repair places a real copy elsewhere
