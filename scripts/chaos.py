"""Chaos run: random crashes and restarts under load, with measured availability.

Starts its own local cluster (default 4 nodes on 127.0.0.1:18101..), so it never
touches a node you already run. For --minutes it:
  - crashes a random node with SIGKILL every 20-40 s (at most --max-down at once)
    and restarts it 15-60 s later with the same data and node id;
  - reads a random file through a random live, unlocked node every second and
    checks its SHA-256;
  - writes a new 512 KiB file through a random live node every 20 s;
  - samples file health (healthy / degraded / unavailable) every 5 s, as seen by a
    node that has been up for at least 15 s (so it has pulled the others' inventories).
At the end it restarts every node, waits for repair to settle, and downloads
every file through every node to count what was lost.

    .venv/bin/python scripts/chaos.py --minutes 10
    .venv/bin/python scripts/chaos.py --minutes 3 --max-down 2 --seed 7

Every number in the report is measured in this run. Counters read from /metrics
restart from zero when a node restarts, so totals marked "at least" undercount.
Results: data/chaos/chaos-<time>.json and .md (git-ignored).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
KEY = "chaos-run-cluster-key-0123"
LOGIN = {"username": "chaos", "passphrase": "chaos run passphrase"}


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class Node:
    def __init__(self, i: int, base_port: int, out: Path):
        self.i, self.port = i, base_port + i
        self.node_id = f"node-{i}"
        self.url = f"http://127.0.0.1:{self.port}"
        self.data = out / self.node_id
        self.log = out / f"{self.node_id}.log"
        self.base_port = base_port
        self.proc: subprocess.Popen | None = None
        self.unlocked = False
        self.started_at = 0.0

    def start(self) -> None:
        env = dict(os.environ, CLUSTER_KEY=KEY, NODE_ID=self.node_id, HOST_ID=f"host-{self.i}",
                   PORT=str(self.port), BIND_HOST="127.0.0.1", ADVERTISE_ADDR=f"127.0.0.1:{self.port}",
                   SEEDS=f"127.0.0.1:{self.base_port + 1}", DATA_DIR=str(self.data), MDNS="0", QUOTA_MB="1024")
        self.proc = subprocess.Popen([sys.executable, "-m", "node.main"], cwd=ROOT, env=env,
                                     stdout=open(self.log, "ab"), stderr=subprocess.STDOUT)
        self.unlocked = False
        self.started_at = time.monotonic()

    def kill(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.send_signal(signal.SIGKILL)
            self.proc.wait()
        self.proc, self.unlocked = None, False

    @property
    def up(self) -> bool:
        return self.proc is not None and self.proc.poll() is None


def wait_until(check, timeout: float, interval: float = 0.5):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            if (r := check()):
                return r
        except httpx.HTTPError:
            pass
        time.sleep(interval)
    return None


def unlock(http: httpx.Client, n: Node) -> bool:
    ok = wait_until(lambda: http.get(f"{n.url}/stats", timeout=2).status_code == 200, 30)
    if not ok:
        return False
    r = http.post(f"{n.url}/recover", json=LOGIN, timeout=60)
    n.unlocked = r.status_code == 200
    return n.unlocked


def percentile(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]


def parse_metrics(text: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for line in text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        name_labels, value = line.rsplit(" ", 1)
        name = re.sub(r"\{.*\}", "", name_labels)
        if name in ("minimol_client_sent_bytes_total", "minimol_client_received_bytes_total"):
            out[name] = out.get(name, 0) + float(value)
        elif name == "minimol_audits_total":
            outcome = re.search(r'outcome="(\w+)"', name_labels).group(1)
            out[f"audits_{outcome}"] = out.get(f"audits_{outcome}", 0) + float(value)
        elif name in ("minimol_repair_copies_total", "minimol_scrub_checked_total", "minimol_scrub_quarantined_total"):
            out[name] = out.get(name, 0) + float(value)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--nodes", type=int, default=4)
    ap.add_argument("--minutes", type=float, default=10)
    ap.add_argument("--max-down", type=int, default=1, help="nodes down at the same time (R=3 tolerates 2)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--base-port", type=int, default=18100)
    ap.add_argument("--files", type=int, default=6, help="files uploaded before the chaos starts")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = ROOT / "data" / "chaos" / stamp
    out.mkdir(parents=True, exist_ok=True)
    nodes = [Node(i, args.base_port, out) for i in range(1, args.nodes + 1)]
    http = httpx.Client(timeout=60)
    files: dict[str, dict] = {}            # file_uuid -> {name, sha, size}
    reads: list[dict] = []
    writes: list[dict] = []
    samples: list[dict] = []
    chaos_log: list[dict] = []
    t0 = time.monotonic()

    def log(msg: str) -> None:
        print(f"[{time.monotonic() - t0:7.1f}s] {msg}", flush=True)

    try:
        for n in nodes:
            n.start()
        alive = wait_until(lambda: sum(p["state"] == "alive" for p in http.get(f"{nodes[0].url}/stats").json()["peers"])
                           == len(nodes), 60)
        if not alive:
            log("cluster did not come up; see logs in " + str(out))
            return 1
        for n in nodes:
            unlock(http, n)
        log(f"{len(nodes)} nodes up and unlocked")

        for k in range(args.files):
            data = os.urandom(2 * 1024 * 1024) if k % 2 else b"".join(
                b"%d,sensor-%d,%.3f,ok\n" % (j, j % 40, j * 0.37) for j in range(60_000 + k))
            r = http.post(f"{nodes[0].url}/files", params={"name": f"seed-{k}.bin"}, content=data)
            r.raise_for_status()
            files[r.json()["file_uuid"]] = {"name": f"seed-{k}.bin", "sha": sha(data), "size": len(data)}
        log(f"uploaded {len(files)} seed files")

        down: dict[int, float] = {}          # node index -> restart at (monotonic)
        next_kill = time.monotonic() + rng.uniform(10, 20)
        next_write = time.monotonic() + 20
        next_sample = time.monotonic()
        end = time.monotonic() + args.minutes * 60
        while time.monotonic() < end:
            now = time.monotonic()
            for i, at in list(down.items()):
                if now >= at:
                    n = nodes[i]
                    n.start()
                    del down[i]
                    chaos_log.append({"t": round(now - t0, 1), "event": "restart", "node": n.node_id})
                    log(f"restart {n.node_id}")
                    unlock(http, n)
            if now >= next_kill:
                ups = [n for n in nodes if n.up]
                if len(down) < args.max_down and len(ups) > 1:
                    victim = rng.choice(ups)
                    victim.kill()
                    down[victim.i - 1] = now + rng.uniform(15, 60)
                    chaos_log.append({"t": round(now - t0, 1), "event": "crash", "node": victim.node_id})
                    log(f"crash {victim.node_id} (down {len(down)})")
                next_kill = now + rng.uniform(20, 40)
            ready = [n for n in nodes if n.up and n.unlocked]
            if ready and files:
                n, uuid = rng.choice(ready), rng.choice(sorted(files))
                started = time.monotonic()
                outcome = "ok"
                try:
                    r = http.get(f"{n.url}/files/{uuid}", timeout=60)
                    if r.status_code == 404:
                        outcome = "not_listed_yet"       # the reader's file list hasn't synced yet
                    elif r.status_code != 200:
                        outcome = f"http_{r.status_code}"
                    elif sha(r.content) != files[uuid]["sha"]:
                        outcome = "corrupt"
                except httpx.HTTPError as e:
                    outcome = f"error_{type(e).__name__}"
                reads.append({"t": round(started - t0, 1), "node": n.node_id, "outcome": outcome,
                              "s": round(time.monotonic() - started, 3), "down": len(down)})
            if now >= next_write and ready:
                n = rng.choice(ready)
                data = os.urandom(512 * 1024)
                name = f"live-{len(writes)}.bin"
                try:
                    r = http.post(f"{n.url}/files", params={"name": name}, content=data, timeout=60)
                    ok = r.status_code == 201
                    if ok:
                        files[r.json()["file_uuid"]] = {"name": name, "sha": sha(data), "size": len(data)}
                    writes.append({"t": round(now - t0, 1), "node": n.node_id, "ok": ok, "status": r.status_code,
                                   "durable": ok and r.json().get("status") == "durable"})
                except httpx.HTTPError as e:
                    writes.append({"t": round(now - t0, 1), "node": n.node_id, "ok": False, "status": type(e).__name__})
                next_write = now + 20
            # Health is each node's own view: a node up for < 15 s hasn't pulled the others'
            # inventories yet and would report files it can still serve as unavailable.
            settled_nodes = [n for n in ready if now - n.started_at >= 15]
            if now >= next_sample and settled_nodes:
                try:
                    st = http.get(f"{rng.choice(settled_nodes).url}/stats", timeout=5).json()["files"]
                    samples.append({"t": round(now - t0, 1), **st, "down": len(down)})
                except httpx.HTTPError:
                    pass
                next_sample = now + 5
            time.sleep(max(0.0, 1.0 - (time.monotonic() - now)))

        log("chaos over: restarting every node and waiting for repair to settle")
        for i in list(down):
            nodes[i].start()
        for n in nodes:
            if not n.unlocked:
                unlock(http, n)
        settle_start = time.monotonic()

        def all_healthy():
            for n in nodes:
                listed = {f["file_uuid"]: f["status"] for f in http.get(f"{n.url}/files", timeout=10).json()}
                if any(listed.get(u) != "healthy" for u in files):
                    return False
            return True
        settled = wait_until(all_healthy, 240, interval=2)
        settle_s = round(time.monotonic() - settle_start, 1)
        log(f"settled: {bool(settled)} after {settle_s}s")

        lost, mismatched = [], []
        for uuid, f in files.items():
            for n in nodes:
                r = http.get(f"{n.url}/files/{uuid}", timeout=60)
                if r.status_code != 200:
                    lost.append({"file": f["name"], "node": n.node_id, "status": r.status_code})
                elif sha(r.content) != f["sha"]:
                    mismatched.append({"file": f["name"], "node": n.node_id})
        metrics: dict[str, float] = {}
        for n in nodes:
            for k, v in parse_metrics(http.get(f"{n.url}/metrics", timeout=10).text).items():
                metrics[k] = metrics.get(k, 0) + v
    finally:
        for n in nodes:
            n.kill()

    ok_reads = [r for r in reads if r["outcome"] == "ok"]
    counted = [r for r in reads if r["outcome"] != "not_listed_yet"]
    reads_while_down = [r for r in counted if r["down"]]
    outcomes: dict[str, int] = {}
    for r in reads:
        outcomes[r["outcome"]] = outcomes.get(r["outcome"], 0) + 1
    report = {
        "run": {"started": stamp, "minutes": args.minutes, "nodes": args.nodes, "max_down": args.max_down,
                "seed": args.seed, "replication": 3},
        "chaos": {"crashes": sum(e["event"] == "crash" for e in chaos_log),
                  "restarts": sum(e["event"] == "restart" for e in chaos_log), "log": chaos_log},
        "reads": {"attempts": len(reads), "counted": len(counted), "ok": len(ok_reads),
                  "availability_pct": round(100 * len(ok_reads) / len(counted), 2) if counted else None,
                  "while_a_node_was_down": len(reads_while_down),
                  "ok_while_a_node_was_down": sum(r["outcome"] == "ok" for r in reads_while_down),
                  "corrupt": outcomes.get("corrupt", 0), "outcomes": outcomes,
                  "latency_s": {"p50": percentile([r["s"] for r in ok_reads], 0.5),
                                "p95": percentile([r["s"] for r in ok_reads], 0.95),
                                "max": max((r["s"] for r in ok_reads), default=None)}},
        "writes": {"attempts": len(writes), "ok": sum(w["ok"] for w in writes),
                   "durable": sum(w.get("durable", False) for w in writes),
                   "availability_pct": round(100 * sum(w["ok"] for w in writes) / len(writes), 2) if writes else None},
        "health_samples": {"count": len(samples),
                           "pct_with_degraded": round(100 * sum(s["degraded"] > 0 for s in samples) / len(samples), 1)
                           if samples else None,
                           "pct_with_unavailable": round(100 * sum(s["unavailable"] > 0 for s in samples) / len(samples), 1)
                           if samples else None},
        "end": {"files": len(files), "settled_healthy": bool(settled), "settle_s": settle_s,
                "lost_downloads": lost, "mismatched_downloads": mismatched,
                "data_lost_files": len({x["file"] for x in lost + mismatched})},
        "counters_at_least": {k: int(v) for k, v in sorted(metrics.items())},
    }
    (out / "report.json").write_text(json.dumps(report, indent=2))
    md = render_md(report, out)
    (out / "report.md").write_text(md)
    print(md)
    return 0 if report["end"]["data_lost_files"] == 0 and report["reads"]["corrupt"] == 0 else 2


def render_md(r: dict, out: Path) -> str:
    rd, wr, en, hs = r["reads"], r["writes"], r["end"], r["health_samples"]
    lat = rd["latency_s"]
    c = r["counters_at_least"]
    return f"""# Chaos run {r['run']['started']}

{r['run']['nodes']} local nodes, {r['run']['minutes']} min, at most {r['run']['max_down']} down at once, R = 3, seed {r['run']['seed']}.
{r['chaos']['crashes']} crashes (SIGKILL), {r['chaos']['restarts']} restarts during the run.

| Measure | Result |
|---|---|
| Reads | {rd['ok']} of {rd['counted']} succeeded (**{rd['availability_pct']}%**); {rd['attempts'] - rd['counted']} skipped because the reader's list hadn't synced yet |
| Reads while a node was down | {rd['ok_while_a_node_was_down']} of {rd['while_a_node_was_down']} |
| Corrupt reads (SHA-256 mismatch) | **{rd['corrupt']}** |
| Read latency (successful) | p50 {lat['p50']} s · p95 {lat['p95']} s · max {lat['max']} s |
| Writes | {wr['ok']} of {wr['attempts']} succeeded ({wr['availability_pct']}%), {wr['durable']} durable (3 copies) at once |
| Health samples with a degraded file | {hs['pct_with_degraded']}% of {hs['count']} |
| Health samples with an unavailable file | {hs['pct_with_unavailable']}% |
| After the run | {en['files']} files; all healthy on every node: {en['settled_healthy']} (after {en['settle_s']} s) |
| **Files lost** | **{en['data_lost_files']}** ({len(en['lost_downloads'])} failed and {len(en['mismatched_downloads'])} mismatched downloads across all nodes) |
| Repair copies (at least) | {c.get('minimol_repair_copies_total', 0)} |
| Audits (at least) | {c.get('audits_passed', 0)} passed, {c.get('audits_failed', 0)} failed |
| Bytes moved between nodes (at least) | {c.get('minimol_client_sent_bytes_total', 0) / 2**20:.1f} MiB sent, {c.get('minimol_client_received_bytes_total', 0) / 2**20:.1f} MiB received |

Read outcomes: {rd['outcomes']}. Raw data and node logs: `{out.relative_to(ROOT)}/`.
"""


if __name__ == "__main__":
    sys.exit(main())
