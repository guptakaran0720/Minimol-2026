"""Reproducible benchmarks for the numbers we show on stage (P3; P4 copies results into docs/RESULTS.md).

Every number printed comes from a run of this script. Nothing is assumed or filled in.

Live mode (real cluster, run on the uploader's laptop against its own node):
    python -m bench.bench --target http://127.0.0.1:8001 --username karan --passphrase '...' \\
        --slow-node node3 [--reps 5] [--kill-node node2 [--kill-cmd 'kill $(cat data/{node}/pid)']]
  * Start the slow node with SIMULATED_DELAY_MS=300 and say on stage that the delay is simulated.
  * --kill-node is the last step: it stops a node and times detection and repair.

Simulated mode (in-process fakes with modelled link delays, no compression):
    python -m bench.bench --sim
  Checks that the script and the strategies work end to end. Its timings describe the
  model, NOT the system: never present them as measurements.

Metric definitions (ARCHITECTURE_DECISIONS.md, docs/TEAM_WORKFLOW.md):
  compression_ratio     = encoded bytes / original bytes        (lower is better; includes 28 B/chunk GCM overhead)
  replication_overhead  = replicated bytes / encoded bytes       (3.0 when every chunk has 3 copies)
  stored_vs_original    = replicated bytes / original bytes
  throughput MB/s       = original bytes / elapsed seconds / 2^20, client-measured end to end
  delta_sent_fraction   = bytes sent on re-upload / original bytes of the new version
  slow_node_share       = chunks placed on the slow node / all chunks
Each timed step runs --reps times; we report median, min and max.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import random
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

MB = 1024 * 1024


# ---------- test data ----------

def make_csv(size: int, seed: int = 1) -> bytes:
    """Sensor-log CSV: the compressible case."""
    rng = random.Random(seed)
    lines, total, t = ["timestamp,sensor_id,temperature_c,humidity_pct,status"], 0, 1_700_000_000
    while total < size:
        t += rng.randint(1, 5)
        line = (f"{t},S{rng.randint(1, 40):03d},{rng.uniform(18, 32):.2f},"
                f"{rng.uniform(30, 80):.1f},{rng.choice(('OK', 'OK', 'OK', 'WARN'))}")
        lines.append(line)
        total += len(line) + 1
    return ("\n".join(lines) + "\n").encode()[:size]


def make_random(size: int, seed: int = 2) -> bytes:
    """Random bytes: stand-in for already-compressed data (JPEG/ZIP). Pass --file for a real one."""
    return random.Random(seed).randbytes(size)


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def summary(xs: list[float]) -> dict:
    return {"median": statistics.median(xs), "min": min(xs), "max": max(xs), "n": len(xs)} if xs else {}


def mbps(nbytes: int, seconds: float) -> float:
    return nbytes / MB / seconds if seconds > 0 else float("inf")


# ---------- backends ----------

class LiveBackend:
    label = "live"

    def __init__(self, target: str, username: str, passphrase: str, kill_cmd: str | None):
        import httpx

        self.http = httpx.Client(base_url=target, timeout=600)
        self.kill_cmd = kill_cmd
        r = self.http.post("/recover", json={"username": username, "passphrase": passphrase})
        r.raise_for_status()

    def upload(self, data: bytes, name: str, placement: str = "tiered") -> tuple[dict, float]:
        t0 = time.perf_counter()
        r = self.http.post("/files", params={"name": name, "placement": placement}, content=data)
        elapsed = time.perf_counter() - t0
        r.raise_for_status()
        return r.json(), elapsed

    def download(self, file_uuid: str, retrieval: str = "eta") -> tuple[bytes, float]:
        t0 = time.perf_counter()
        r = self.http.get(f"/files/{file_uuid}", params={"retrieval": retrieval})
        elapsed = time.perf_counter() - t0
        r.raise_for_status()
        return r.content, elapsed

    def peers(self) -> list[dict]:
        return self.http.get("/stats").json()["peers"]

    def file_map(self, file_uuid: str) -> dict:
        return self.http.get(f"/files/{file_uuid}/map").json()

    def kill_and_wait_healthy(self, file_uuid: str, node: str, timeout: float = 300) -> dict:
        if self.kill_cmd:
            subprocess.run(self.kill_cmd.format(node=node), shell=True, check=True)
        else:
            input(f"\n>>> Stop node {node} now (Ctrl-C it or close the lid), then press Enter... ")
        t0 = time.perf_counter()
        detected = repaired = None
        while time.perf_counter() - t0 < timeout:
            now = time.perf_counter() - t0
            if detected is None and any(p["node_id"] == node and p["state"] == "dead" for p in self.peers()):
                detected = now
            if detected is not None and self.file_map(file_uuid)["status"] == "healthy":
                repaired = now
                break
            time.sleep(0.5)
        return {"detected_dead_s": detected, "fully_repaired_s": repaired, "timeout_s": timeout}


class SimBackend:
    """In-process cluster: fakes from tests/fakes.py plus per-node link delays."""
    label = "simulated"

    def __init__(self, nodes: int = 5, slow_node: str = "node4", slow_rtt: float = 0.3,
                 rtt: float = 0.002, bw: float = 50 * MB):
        from node.contracts import owner_salt
        from node.repair import Repairer
        from node.transfer import Transfer
        from tests.fakes import FakeClient, FakePeerTable, FakeStore, make_cluster

        class DelayedClient(FakeClient):
            def __init__(self, net, links):
                super().__init__(net)
                self.links = links

            async def _wait(self, peer, nbytes):
                link_rtt, link_bw = self.links[peer.node_id]
                await asyncio.sleep(link_rtt + nbytes / link_bw)

            async def put_chunk(self, peer, chunk_id, blob, delete_hash=None):
                await self._wait(peer, len(blob))
                return await super().put_chunk(peer, chunk_id, blob, delete_hash)

            async def get_chunk(self, peer, chunk_id):
                blob = await super().get_chunk(peer, chunk_id)
                await self._wait(peer, len(blob or b""))
                return blob

            async def head_chunk(self, peer, chunk_id):
                await self._wait(peer, 0)
                return await super().head_chunk(peer, chunk_id)

        class SimPeerTable(FakePeerTable):
            """Models P2's peer table: heartbeat RTT, EWMA bandwidth from transfers, slow tier."""

            def record_transfer(self, node_id, nbytes, seconds):
                super().record_transfer(node_id, nbytes, seconds)
                p = self.peers[node_id]
                sample = nbytes / max(seconds, 1e-6)
                p.bw_ewma = sample if p.bw_ewma == 0 else 0.7 * p.bw_ewma + 0.3 * sample

        self.loop = asyncio.new_event_loop()
        net, table, _, locs, codec = make_cluster(nodes)
        links = {n: ((slow_rtt if n == slow_node else rtt), bw) for n in table.peers}
        table = SimPeerTable(list(table.peers.values()))
        median_rtt = statistics.median(r for r, _ in links.values())
        for p in table.peers.values():
            p.rtt_ewma = links[p.node_id][0]                         # what heartbeats would report
            p.tier = 2 if p.rtt_ewma > 3 * median_rtt else 1         # P2's slow-tier rule
        self.net, self.table, self.locs = net, table, locs
        self.client = DelayedClient(net, links)
        keys = codec.derive_master("simulated passphrase", owner_salt("bench"))
        self.transfer = Transfer(keys, codec, table, self.client, locs)
        self._repairer = lambda p: Repairer(p.node_id, p.host_id, FakeStore(net, p.node_id), table, self.client, locs)

    def _run(self, coro):
        return self.loop.run_until_complete(coro)

    def upload(self, data: bytes, name: str, placement: str = "tiered") -> tuple[dict, float]:
        from dataclasses import asdict

        t0 = time.perf_counter()
        res = self._run(self.transfer.upload(io.BytesIO(data), name, placement))
        return asdict(res), time.perf_counter() - t0

    def download(self, file_uuid: str, retrieval: str = "eta") -> tuple[bytes, float]:
        out = io.BytesIO()
        t0 = time.perf_counter()
        self._run(self.transfer.download(file_uuid, out, retrieval))
        return out.getvalue(), time.perf_counter() - t0

    def peers(self) -> list[dict]:
        return [{"node_id": p.node_id, "state": p.state, "tier": p.tier} for p in self.table.peers.values()]

    def file_map(self, file_uuid: str) -> dict:
        return {"status": self.transfer.file_status(file_uuid), "chunks": self.transfer.chunk_map(file_uuid)}

    def kill_and_wait_healthy(self, file_uuid: str, node: str, timeout: float = 30) -> dict:
        """Sim has no wall clock for detection: the node is marked dead at once and we
        count repair rounds (each round = the 10 s repair interval in the real config)."""
        self.table.kill(self.net, node)
        self.locs.refresh()
        rounds = 0
        while self.transfer.file_status(file_uuid) != "healthy" and rounds < 10:
            rounds += 1
            reps = [self._repairer(p) for p in self.table.alive()]

            async def one_round():
                await asyncio.gather(*(r.run_once() for r in reps))

            self._run(one_round())
        return {"repair_rounds": rounds, "healthy": self.transfer.file_status(file_uuid) == "healthy"}


# ---------- experiments ----------

def bench_files(b, datasets: dict[str, bytes], reps: int, run_id: str) -> dict:
    out = {}
    for label, data in datasets.items():
        ups, downs, last = [], [], None
        for r in range(reps):
            res, up_s = b.upload(data, f"bench-{label}-{run_id}-{r}")
            got, down_s = b.download(res["file_uuid"])
            if sha(got) != sha(data):
                raise SystemExit(f"{label}: downloaded bytes do not match the original")
            ups.append(up_s)
            downs.append(down_s)
            last = res
        out[label] = {
            "original_bytes": len(data),
            "encoded_bytes": last["encoded_bytes"],
            "replicated_bytes": last["replicated_bytes"],
            "compression_ratio": last["encoded_bytes"] / len(data) if data else None,
            "replication_overhead": last["replicated_bytes"] / last["encoded_bytes"] if last["encoded_bytes"] else None,
            "stored_vs_original": last["replicated_bytes"] / len(data) if data else None,
            "upload_s": summary(ups),
            "download_s": summary(downs),
            "upload_MBps": mbps(len(data), statistics.median(ups)),
            "download_MBps": mbps(len(data), statistics.median(downs)),
            "sha256_match": True,
        }
    return out


def bench_delta(b, size: int, run_id: str) -> dict:
    v1 = make_csv(size, seed=7)
    v2 = v1 + make_csv(max(size // 100, 1), seed=8)          # append ~1% new rows
    name = f"bench-delta-{run_id}"
    b.upload(v1, name)
    second, up_s = b.upload(v2, name)
    got, _ = b.download(second["file_uuid"])
    return {
        "v1_bytes": len(v1), "v2_bytes": len(v2),
        "v2_sent_bytes": second["sent_bytes"],
        "v2_sent_chunks": second["sent_chunks"], "v2_reused_chunks": second["reused_chunks"],
        "delta_sent_fraction": second["sent_bytes"] / len(v2),
        "v2_upload_s": up_s,
        "sha256_match": sha(got) == sha(v2),
    }


def placement_counts(res: dict) -> dict[str, int]:
    counts: dict[str, int] = {}
    for c in res["chunks"]:
        for n in c["holders"]:
            counts[n] = counts.get(n, 0) + 1
    return dict(sorted(counts.items()))


def wait_for_slow_tier(b, slow: str, timeout: float = 120) -> dict:
    """P2 moves a peer to tier 2 only after its ETA stays > 3x the median for 30 s,
    and ETA needs real transfer samples, so give it time before the placement A/B."""
    t0 = time.perf_counter()
    while True:
        tier = next((p.get("tier") for p in b.peers() if p["node_id"] == slow), None)
        waited = time.perf_counter() - t0
        if tier == 2 or waited >= timeout:
            return {"slow_node_tier": tier, "waited_s": round(waited, 1)}
        b.upload(make_random(2 * MB, seed=int(waited)), f"bench-warmup-{int(waited)}")   # generate transfer samples
        time.sleep(2)


def bench_placement(b, data: bytes, slow: str | None, reps: int, run_id: str) -> dict:
    out = {"warmup": wait_for_slow_tier(b, slow)} if slow else {}
    for strategy in ("tiered", "random"):
        shares, downs, counts = [], [], {}
        for r in range(reps):
            res, _ = b.upload(data, f"bench-place-{strategy}-{run_id}-{r}", placement=strategy)
            counts = placement_counts(res)
            total = sum(len(c["holders"]) for c in res["chunks"])
            shares.append(counts.get(slow, 0) / total if slow and total else 0.0)
            _, down_s = b.download(res["file_uuid"], "eta")
            downs.append(down_s)
        out[strategy] = {"slow_node_share": summary(shares), "download_s": summary(downs),
                         "copies_per_node_last_run": counts}
    return out


def bench_retrieval(b, data: bytes, reps: int, run_id: str) -> dict:
    # Place with the random baseline so the slow node really holds chunks; otherwise
    # tiered placement keeps it empty and there is nothing for retrieval to route around.
    res, _ = b.upload(data, f"bench-retrieval-{run_id}", placement="random")
    times = {"eta": [], "random": []}
    for r in range(reps):
        for strategy in (("eta", "random") if r % 2 == 0 else ("random", "eta")):   # alternate to cancel drift
            got, s = b.download(res["file_uuid"], strategy)
            if sha(got) != sha(data):
                raise SystemExit("retrieval A/B: downloaded bytes do not match the original")
            times[strategy].append(s)
    eta, rnd = statistics.median(times["eta"]), statistics.median(times["random"])
    return {"eta_s": summary(times["eta"]), "random_s": summary(times["random"]),
            "median_speedup": rnd / eta if eta > 0 else None}


def bench_repair(b, data: bytes, node: str, run_id: str) -> dict:
    res, _ = b.upload(data, f"bench-repair-{run_id}")
    held = sum(node in c["holders"] for c in res["chunks"])
    outcome = b.kill_and_wait_healthy(res["file_uuid"], node)
    got, _ = b.download(res["file_uuid"])
    return {"killed": node, "chunks_that_lost_a_copy": held, **outcome, "sha256_match_after": sha(got) == sha(data)}


# ---------- report ----------

def fmt(x, digits=3):
    if x is None:
        return "—"
    if isinstance(x, dict):
        return f"{x['median']:.{digits}f} ({x['min']:.{digits}f}–{x['max']:.{digits}f})" if x else "—"
    if isinstance(x, float):
        return f"{x:.{digits}f}"
    return str(x)


def report(r: dict) -> str:
    m = r["meta"]
    lines = [f"## Benchmark results ({m['mode']}, {m['started']})", ""]
    if m["mode"] == "simulated":
        lines += ["> **Simulated:** in-process fakes with modelled links and no compression. "
                  "These numbers check the script; they are not measurements of the system.", ""]
    lines += [f"Reps: {m['reps']}. Times are median (min–max) seconds. Slow node: {m['slow_node'] or '—'}.", "",
              "### Files", "",
              "| Data | Original MB | Ratio | Stored/original | Upload s | Download s | Up MB/s | Down MB/s | SHA-256 |",
              "|---|---|---|---|---|---|---|---|---|"]
    for label, f in r.get("files", {}).items():
        lines.append(f"| {label} | {f['original_bytes'] / MB:.2f} | {fmt(f['compression_ratio'])} | "
                     f"{fmt(f['stored_vs_original'])} | {fmt(f['upload_s'])} | {fmt(f['download_s'])} | "
                     f"{fmt(f['upload_MBps'], 1)} | {fmt(f['download_MBps'], 1)} | {'match' if f['sha256_match'] else 'MISMATCH'} |")
    if d := r.get("delta"):
        lines += ["", "### Delta sync (append ~1%)", "",
                  "| v2 MB | Sent MB | Sent fraction | Chunks sent / reused | SHA-256 |", "|---|---|---|---|---|",
                  f"| {d['v2_bytes'] / MB:.2f} | {d['v2_sent_bytes'] / MB:.3f} | {fmt(d['delta_sent_fraction'], 4)} | "
                  f"{d['v2_sent_chunks']} / {d['v2_reused_chunks']} | {'match' if d['sha256_match'] else 'MISMATCH'} |"]
    if p := r.get("placement"):
        w = p.get("warmup", {})
        lines += ["", "### Placement A/B: tiered vs random", "",
                  f"Slow node tier before the A/B: {w.get('slow_node_tier', '—')} (waited {w.get('waited_s', 0)} s).", "",
                  "| Strategy | Share of copies on slow node | Download s | Copies per node (last run) |", "|---|---|---|---|"]
        for s, v in p.items():
            if s == "warmup":
                continue
            lines.append(f"| {s} | {fmt(v['slow_node_share'])} | {fmt(v['download_s'])} | {v['copies_per_node_last_run']} |")
    if q := r.get("retrieval"):
        lines += ["", "### Retrieval A/B: ETA ordering vs random holder (file placed randomly)", "",
                  "| ETA s | Random s | Median speedup |", "|---|---|---|",
                  f"| {fmt(q['eta_s'])} | {fmt(q['random_s'])} | {fmt(q['median_speedup'], 2)}× |"]
    if k := r.get("repair"):
        lines += ["", "### Kill a node and repair", "", "```", json.dumps(k, indent=2), "```"]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--target", help="this laptop's node, e.g. http://127.0.0.1:8001")
    mode.add_argument("--sim", action="store_true", help="in-process simulation (not real measurements)")
    ap.add_argument("--username")
    ap.add_argument("--passphrase")
    ap.add_argument("--slow-node", help="node started with SIMULATED_DELAY_MS (sim default: node4)")
    ap.add_argument("--kill-node", help="stop this node at the end and time detection + repair")
    ap.add_argument("--kill-cmd", help="shell command that stops {node}; otherwise you are prompted")
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--csv-mb", type=float, default=None, help="compressible CSV size (live 20, sim 4)")
    ap.add_argument("--random-mb", type=float, default=None, help="incompressible size (live 5, sim 2)")
    ap.add_argument("--file", action="append", default=[], help="extra real file to measure (e.g. a JPEG)")
    ap.add_argument("--skip", action="append", default=[],
                    choices=["files", "delta", "placement", "retrieval", "repair"])
    ap.add_argument("--out", type=Path, default=Path("bench/results"))
    args = ap.parse_args(argv)

    if args.sim:
        backend = SimBackend()
        slow = args.slow_node or "node4"
        kill = args.kill_node or "node0"
        csv_mb, rnd_mb = args.csv_mb or 4, args.random_mb or 2
    else:
        if not (args.username and args.passphrase):
            ap.error("--target needs --username and --passphrase")
        backend = LiveBackend(args.target, args.username, args.passphrase, args.kill_cmd)
        slow, kill = args.slow_node, args.kill_node
        csv_mb, rnd_mb = args.csv_mb or 20, args.random_mb or 5

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    datasets = {"csv": make_csv(int(csv_mb * MB)), "random": make_random(int(rnd_mb * MB))}
    for path in args.file:
        datasets[Path(path).name] = Path(path).read_bytes()

    results: dict = {"meta": {"mode": backend.label, "started": run_id, "reps": args.reps,
                              "slow_node": slow, "peers": backend.peers()}}
    steps = [
        ("files", lambda: bench_files(backend, datasets, args.reps, run_id)),
        ("delta", lambda: bench_delta(backend, int(csv_mb * MB), run_id)),
        ("placement", lambda: bench_placement(backend, datasets["csv"], slow, args.reps, run_id) if slow else None),
        ("retrieval", lambda: bench_retrieval(backend, datasets["csv"], args.reps, run_id) if slow else None),
        ("repair", lambda: bench_repair(backend, datasets["csv"], kill, run_id) if kill else None),
    ]
    for name, step in steps:
        if name in args.skip:
            continue
        print(f"[bench] {name}...", file=sys.stderr, flush=True)
        if (value := step()) is not None:
            results[name] = value

    args.out.mkdir(parents=True, exist_ok=True)
    stem = args.out / f"{backend.label}-{run_id}"
    stem.with_suffix(".json").write_text(json.dumps(results, indent=2))
    md = report(results)
    stem.with_suffix(".md").write_text(md)
    print(md)
    print(f"[bench] saved {stem}.json and {stem}.md", file=sys.stderr)
    return results


if __name__ == "__main__":
    main()
