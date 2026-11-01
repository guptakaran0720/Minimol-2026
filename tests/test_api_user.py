import hashlib
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from node import api_user
from node.api_user import UserState
from node.repair import Repairer
from tests.fakes import FakeStore, make_cluster

CHUNK = 1024
LOGIN = {"username": "karan", "passphrase": "correct horse battery"}


@pytest.fixture
def cluster():
    return make_cluster(4)


def make_client(cluster, tmp_path, hosts=("testclient",), repairer=None):
    net, table, client, locs, codec = cluster
    app = FastAPI()
    app.include_router(api_user.create_router(UserState(
        codec=codec, peers=table, client=client, locations=locs, data_dir=tmp_path,
        repairer=repairer, chunk_size=CHUNK, allowed_hosts=set(hosts), self_id="node0",
    )))
    return TestClient(app)


def test_locked_until_recover(cluster, tmp_path):
    c = make_client(cluster, tmp_path)
    assert c.get("/files").status_code == 401
    assert c.post("/files?name=a", content=b"x").status_code == 401
    stats = c.get("/stats").json()
    assert stats["unlocked"] is False and len(stats["peers"]) == 4


def test_rejects_requests_from_other_machines(cluster, tmp_path):
    c = make_client(cluster, tmp_path, hosts=api_user.LOCAL_HOSTS)
    assert c.get("/stats").status_code == 403


def test_recover_validates_input(cluster, tmp_path):
    c = make_client(cluster, tmp_path)
    assert c.post("/recover", json={"username": "karan", "passphrase": "short"}).status_code == 400
    assert c.post("/recover", json={"username": " ", "passphrase": "long enough phrase"}).status_code == 400


def test_upload_list_map_download(cluster, tmp_path):
    c = make_client(cluster, tmp_path)
    assert c.post("/recover", json=LOGIN).json()["files_restored"] == 0
    data = os.urandom(CHUNK * 5 + 17)
    r = c.post("/files?name=log.csv", content=data)
    assert r.status_code == 201
    up = r.json()
    assert up["original_bytes"] == len(data) and up["status"] == "durable" and up["compression_ratio"] > 0

    files = c.get("/files").json()
    assert [(f["name"], f["status"]) for f in files] == [("log.csv", "healthy")]

    m = c.get(f"/files/{up['file_uuid']}/map").json()
    assert m["status"] == "healthy" and len(m["chunks"]) == 6
    assert all(row["live_hosts"] == 3 for row in m["chunks"])

    d = c.get(f"/files/{up['file_uuid']}")
    assert d.status_code == 200 and d.content == data
    assert d.headers["x-file-sha256"] == hashlib.sha256(data).hexdigest()
    assert 'filename="log.csv"' in d.headers["content-disposition"]


def test_reupload_reports_delta(cluster, tmp_path):
    c = make_client(cluster, tmp_path)
    c.post("/recover", json=LOGIN)
    data = os.urandom(CHUNK * 8)
    c.post("/files?name=s.log", content=data)
    second = c.post("/files?name=s.log", content=data + b"more").json()
    assert second["version"] == 2 and second["reused_chunks"] == 8 and second["sent_chunks"] == 1


def test_upload_size_limit(cluster, tmp_path, monkeypatch):
    monkeypatch.setattr(api_user, "MAX_UPLOAD_BYTES", 100)
    c = make_client(cluster, tmp_path)
    c.post("/recover", json=LOGIN)
    assert c.post("/files?name=big", content=b"x" * 101).status_code == 413

    def chunked():
        yield b"x" * 60
        yield b"x" * 60

    assert c.post("/files?name=big", content=chunked()).status_code == 413
    assert c.get("/files").json() == []


def test_fresh_device_recovers_and_downloads(cluster, tmp_path):
    first = make_client(cluster, tmp_path / "laptop1")
    first.post("/recover", json=LOGIN)
    data = os.urandom(CHUNK * 3)
    file_uuid = first.post("/files?name=thesis.pdf", content=data).json()["file_uuid"]

    fresh = make_client(cluster, tmp_path / "laptop2")
    rec = fresh.post("/recover", json=LOGIN).json()
    assert rec["files_restored"] == 1 and rec["files"][0]["name"] == "thesis.pdf"
    assert fresh.get(f"/files/{file_uuid}").content == data

    stranger = make_client(cluster, tmp_path / "laptop3")
    assert stranger.post("/recover", json={"username": "someone", "passphrase": "correct horse battery"}).json()[
        "files_restored"] == 0


def test_unavailable_and_unknown_files(cluster, tmp_path):
    net, table, *_ = cluster
    c = make_client(cluster, tmp_path)
    c.post("/recover", json=LOGIN)
    file_uuid = c.post("/files?name=f", content=os.urandom(CHUNK)).json()["file_uuid"]
    assert c.get("/files/does-not-exist").status_code == 404
    assert c.get("/files/does-not-exist/map").status_code == 404
    for n in list(table.peers):
        table.kill(net, n)
    assert c.get(f"/files/{file_uuid}/map").json()["status"] == "unavailable"
    assert c.get(f"/files/{file_uuid}").status_code == 503


def test_upload_with_no_live_peers_is_503(cluster, tmp_path):
    net, table, *_ = cluster
    c = make_client(cluster, tmp_path)
    c.post("/recover", json=LOGIN)
    for n in list(table.peers):
        table.kill(net, n)
    assert c.post("/files?name=f", content=b"data").status_code == 503


def test_stats_shows_dead_peers_and_repair(cluster, tmp_path):
    net, table, client, locs, codec = cluster
    rep = Repairer("node0", "host0", FakeStore(net, "node0"), table, client, locs)
    c = make_client(cluster, tmp_path, repairer=rep)
    c.post("/recover", json=LOGIN)
    c.post("/files?name=f", content=os.urandom(CHUNK * 4))
    table.kill(net, "node3")
    stats = c.get("/stats").json()
    assert {p["node_id"]: p["state"] for p in stats["peers"]}["node3"] == "dead"
    assert stats["files"]["count"] == 1
    assert stats["repair"]["total_copies"] == 0
    assert c.post("/files?name=g", content=b"z" * 10).json()["index_acks"] == 3   # node3 is dead


def node_like(cluster, tmp_path):
    """Shape of P2's main.Node, which main.py passes to create_router."""
    net, table, client, locs, codec = cluster
    return SimpleNamespace(settings=SimpleNamespace(data_dir=tmp_path, node_id="node0"),
                           peers=table, client=client, locations=locs)


def client_for_node(node):
    app = FastAPI()
    app.include_router(api_user.create_router(node))
    return app


def test_create_router_from_node_without_p1_is_locked_with_503(cluster, tmp_path, monkeypatch):
    monkeypatch.delenv("DEV_FAKE_CODEC", raising=False)
    monkeypatch.setattr(api_user, "LOCAL_HOSTS", {"testclient"})
    # P1's modules now exist, so simulate a node where they are missing.
    monkeypatch.setattr(api_user, "CODEC_MODULES", {"node.p1_not_installed": ("encode_chunk",)})
    c = TestClient(client_for_node(node_like(cluster, tmp_path)))
    r = c.post("/recover", json=LOGIN)
    assert r.status_code == 503 and "P1" in r.json()["detail"]
    stats = c.get("/stats").json()
    assert stats["node_id"] == "node0" and "not available" in stats["codec"]


def test_create_router_from_node_with_real_p1_codec(cluster, tmp_path, monkeypatch):
    monkeypatch.delenv("DEV_FAKE_CODEC", raising=False)
    monkeypatch.setenv("MINIMOL_SCRYPT_N", "4096")
    monkeypatch.setattr(api_user, "LOCAL_HOSTS", {"testclient"})
    c = TestClient(client_for_node(node_like(cluster, tmp_path)))
    assert c.post("/recover", json=LOGIN).status_code == 200
    assert c.get("/stats").json()["codec"] == "P1 pipeline"
    data = b"2026-11-01T11:30:00,s7,23.4\n" * 40_000 + os.urandom(3000)
    file_uuid = c.post("/files?name=log.csv", content=data).json()["file_uuid"]
    assert c.get(f"/files/{file_uuid}").content == data


def test_create_router_from_node_with_dev_fake_codec(cluster, tmp_path, monkeypatch):
    monkeypatch.setenv("DEV_FAKE_CODEC", "1")
    monkeypatch.setattr(api_user, "LOCAL_HOSTS", {"testclient"})
    c = TestClient(client_for_node(node_like(cluster, tmp_path)))
    assert c.post("/recover", json=LOGIN).status_code == 200
    data = os.urandom(3000)
    file_uuid = c.post("/files?name=x", content=data).json()["file_uuid"]
    assert c.get(f"/files/{file_uuid}").content == data
    assert c.get("/stats").json()["codec"].startswith("FAKE")
    assert (Path(tmp_path) / "user").is_dir()


def test_sync_loop_picks_up_files_uploaded_elsewhere():
    import asyncio
    from node.contracts import owner_salt
    from node.transfer import Transfer
    net, table, client, locs, codec = make_cluster(4)
    keys = codec.derive_master(LOGIN["passphrase"], owner_salt(LOGIN["username"]))
    here = Transfer(keys, codec, table, client, locs, chunk_size=CHUNK)
    elsewhere = Transfer(keys, codec, table, client, locs, chunk_size=CHUNK)

    async def scenario():
        await here.recover()
        task = asyncio.create_task(api_user.sync_forever(here, 0.01))
        import io
        res = await elsewhere.upload(io.BytesIO(b"hello" * 400), "x.txt")
        await asyncio.sleep(0.1)
        task.cancel()
        return res.file_uuid

    file_uuid = asyncio.run(scenario())
    assert file_uuid in here.catalog


def test_logout_locks_and_forgets_the_local_list(cluster, tmp_path):
    c = make_client(cluster, tmp_path)
    c.post("/recover", json=LOGIN)
    c.post("/files?name=a.txt", content=b"hello" * 100)
    assert list((tmp_path).glob("catalog-*.json"))
    r = c.post("/logout").json()
    assert r == {"logged_out": True, "username": "karan"}
    assert c.get("/files").status_code == 401 and c.get("/stats").json()["unlocked"] is False
    assert not list((tmp_path).glob("catalog-*.json"))
    assert c.post("/recover", json=LOGIN).json()["files_restored"] == 1   # nothing lost on the peers


def test_delete_route(cluster, tmp_path):
    net = cluster[0]
    c = make_client(cluster, tmp_path)
    c.post("/recover", json=LOGIN)
    file_uuid = c.post("/files?name=gone.bin", content=os.urandom(3000)).json()["file_uuid"]
    r = c.delete(f"/files/{file_uuid}")
    assert r.status_code == 200 and r.json()["pending_objects"] == 0 and r.json()["copies_deleted"] >= 3
    assert c.get("/files").json() == []
    assert c.delete(f"/files/{file_uuid}").status_code == 404
    assert sum(len(s) for s in net.stores.values()) == 0


def test_preview_is_inline_and_safe(cluster, tmp_path):
    c = make_client(cluster, tmp_path)
    c.post("/recover", json=LOGIN)
    ids = {n: c.post(f"/files?name={n}", content=b"<script>alert(1)</script>" if n.endswith(".html") else b"%PDF-1.4 x").json()["file_uuid"]
           for n in ("page.html", "doc.pdf")}
    html = c.get(f"/files/{ids['page.html']}?inline=true")
    assert html.headers["content-type"].startswith("text/plain")
    assert "sandbox" in html.headers["content-security-policy"]
    assert html.headers["content-disposition"].startswith("inline")
    assert html.headers["x-content-type-options"] == "nosniff"
    pdf = c.get(f"/files/{ids['doc.pdf']}?inline=true")
    assert pdf.headers["content-type"] == "application/pdf" and "content-security-policy" not in pdf.headers
    plain = c.get(f"/files/{ids['doc.pdf']}")
    assert plain.headers["content-disposition"].startswith("attachment")
