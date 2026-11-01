"""End-to-end test against a running cluster (Merge 2 and Merge 3 gates).

Start 4 nodes, then point the test at them:
    FRESH=1 scripts/run_cluster.sh                     # add DEV_FAKE_CODEC=1 until P1's pipeline lands
    P2P_CLUSTER=http://127.0.0.1:8001,http://127.0.0.1:8002,http://127.0.0.1:8003,http://127.0.0.1:8004 \\
        pytest -q tests/test_cluster.py

The test STOPS TWO NODES (P2P_KILL_CMD, default: kill whatever listens on the node's port),
so restart the cluster afterwards. Skipped when P2P_CLUSTER is not set.
Timings follow node/config.py: dead after 20 s, inventory and repair every 10 s.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import time
import uuid
from urllib.parse import urlparse

import pytest

URLS = [u.strip() for u in os.environ.get("P2P_CLUSTER", "").split(",") if u.strip()]
KILL_CMD = os.environ.get("P2P_KILL_CMD", "kill $(lsof -ti tcp:{port} -sTCP:LISTEN)")

pytestmark = pytest.mark.skipif(len(URLS) < 4, reason="set P2P_CLUSTER to 4 node URLs (scripts/run_cluster.sh)")


def wait_until(check, timeout: float, what: str, interval: float = 0.5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if result := check():
            return result
        time.sleep(interval)
    pytest.fail(f"timed out after {timeout:.0f}s waiting for {what}")


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def kill(url: str) -> None:
    subprocess.run(KILL_CMD.format(port=urlparse(url).port), shell=True, check=True)


def test_upload_kill_download_repair_recover():
    import httpx

    nodes = {u: httpx.Client(base_url=u, timeout=60) for u in URLS}
    first = URLS[0]
    api = nodes[first]

    # 1. every node is up and the first one sees all of them alive
    wait_until(lambda: len([p for p in api.get("/stats").json()["peers"] if p["state"] == "alive"]) >= len(URLS),
               60, "all nodes alive in the first node's peer table")
    url_of = {nodes[u].get("/stats").json()["node_id"]: u for u in URLS}

    # 2. unlock with a fresh owner
    login = {"username": f"cluster-{uuid.uuid4().hex[:8]}", "passphrase": "cluster test passphrase"}
    r = api.post("/recover", json=login)
    if r.status_code == 503:
        pytest.fail(f"node is locked: {r.json()['detail']}. Start the cluster with DEV_FAKE_CODEC=1 until P1 lands.")
    r.raise_for_status()

    # 3. upload: every chunk on 3 distinct hosts
    data = os.urandom(3 * 1024 * 1024 + 4321)
    up = api.post("/files", params={"name": "cluster.bin"}, content=data)
    assert up.status_code == 201, up.text
    up = up.json()
    assert up["status"] == "durable"
    file_uuid = up["file_uuid"]
    m = api.get(f"/files/{file_uuid}/map").json()
    assert m["status"] == "healthy" and all(row["live_hosts"] >= 3 for row in m["chunks"])

    # 4. download matches
    d = api.get(f"/files/{file_uuid}")
    assert d.status_code == 200 and sha(d.content) == sha(data) == d.headers["x-file-sha256"]

    # 5. kill a holder that is not the uploader; download right away (peer not yet marked dead)
    me = api.get("/stats").json()["node_id"]
    holders = [h["node_id"] for h in m["chunks"][0]["holders"]]
    victim = next(n for n in holders if n != me)
    kill(url_of[victim])
    assert sha(api.get(f"/files/{file_uuid}").content) == sha(data)

    # 6. failure detection, then repair back to 3 live hosts per chunk
    wait_until(lambda: any(p["node_id"] == victim and p["state"] == "dead" for p in api.get("/stats").json()["peers"]),
               60, f"{victim} marked dead")
    wait_until(lambda: api.get(f"/files/{file_uuid}/map").json()["status"] == "healthy", 120,
               "repair back to 3 live copies per chunk")

    # 7. a different node recovers the file list from username + passphrase alone
    other = next(u for n, u in url_of.items() if n not in (me, victim))
    rec = nodes[other].post("/recover", json=login).json()
    assert rec["files_restored"] >= 1
    assert sha(nodes[other].get(f"/files/{file_uuid}").content) == sha(data)

    # 8. second failure: kill another original holder; data still downloads
    second = next((n for n in holders if n not in (me, victim)), None) or next(
        n for n in url_of if n not in (me, victim) and url_of[n] != other)
    kill(url_of[second])
    assert sha(api.get(f"/files/{file_uuid}").content) == sha(data)
