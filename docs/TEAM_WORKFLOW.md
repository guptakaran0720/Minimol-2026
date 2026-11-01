# Team Workflow: 3 Builders + 1 Explainer

Goal: three people build in parallel without touching each other's files. A fourth person turns every finished part into explanations, demo material and judge answers. The design itself is in [ARCHITECTURE_DECISIONS.md](ARCHITECTURE_DECISIONS.md).

## Roles and file ownership

**Rule:** only the owner edits a file. If you need a change in someone else's file, message the owner or open an issue. The only shared file is `node/contracts.py`, covered in the next section.

| Person | Role | Owns | Tests owned |
|---|---|---|---|
| **P1** | Crypto & data | `node/pipeline.py`, `node/keys.py`, `node/manifest.py`, `node/index.py`; after hour 4: `ui/index.html` | `tests/test_pipeline.py`, `tests/test_keys.py`, `tests/test_manifest.py` |
| **P2** | Node & network | `node/config.py`, `node/auth.py`, `node/chunkstore.py`, `node/peer_client.py`, `node/api_peer.py`, `node/peers.py`, `node/inventory.py`, `node/main.py`, `node/discovery.py`, `scripts/run_cluster.sh` | `tests/test_chunkstore.py`, `tests/test_auth.py`, `tests/test_peers.py` |
| **P3** | Routing, transfer & repair | `node/routing.py`, `node/transfer.py`, `node/repair.py`, `node/api_user.py`, `bench/bench.py` | `tests/test_routing.py`, `tests/test_repair.py`, `tests/test_cluster.py` |
| **P4** | Explanation & demo | `docs/explain/*`, `docs/DEMO_SCRIPT.md`, `docs/JUDGE_QA.md`, `docs/RESULTS.md`, `docs/SLIDES.md`, `README.md` | Runs the full test suite and `bench.py` at every merge; owns the results table |

## Hour 0 (all four together, 30 min): freeze the contracts

Do these in order:

1. Create the venv and install:
   ```bash
   pip install -r requirements.txt pytest
   ```
2. Download wheels in case the internet dies later:
   ```bash
   pip download -r requirements.txt -d wheels/
   ```
3. On **every laptop**, allow Python through the firewall. From another laptop, run `curl http://<ip>:8000/health`.
4. Write `node/contracts.py` together: the dataclasses and function signatures below, with the bodies left as `...`. After this, **contracts.py is frozen.** Any change needs a PR approved by P1, P2 and P3.

### Python contracts

```python
# ---- P1: pure functions, no networking ----
@dataclass
class EncodedChunk:
    index: int; chunk_id: str; blob: bytes; plain_size: int; compressed: bool

def encode_file(data: bytes, file_uuid: str, dek: bytes) -> list[EncodedChunk]: ...
def decode_chunk(blob: bytes, file_uuid: str, index: int, compressed: bool, dek: bytes) -> bytes: ...
def sha256_hex(b: bytes) -> str: ...

@dataclass
class MasterKeys:
    kek: bytes; sign_priv: bytes; sign_pub: bytes

def derive_master(passphrase: str, salt: bytes) -> MasterKeys: ...
def wrap_key(kek: bytes, dek: bytes) -> bytes: ...
def unwrap_key(kek: bytes, wrapped: bytes) -> bytes: ...

@dataclass
class Manifest:
    file_uuid: str; name: str; size: int; sha256: str; wrapped_dek: bytes
    chunks: list[dict]          # {index, chunk_id, plain_size, compressed}

def seal_manifest(m: Manifest, kek: bytes) -> bytes: ...          # encrypted blob; manifest_id = sha256(blob)
def open_manifest(blob: bytes, kek: bytes) -> Manifest: ...
def seal_index(manifest_ids: list[str], version: int, keys: MasterKeys) -> dict: ...   # signed record
def verify_index(record: dict, owner_pub: bytes) -> int: ...      # returns version or raises
def open_index(record: dict, keys: MasterKeys) -> list[str]: ...

# ---- P2: node + network ----
class ChunkStore:               # atomic write, quota
    def put(self, chunk_id: str, blob: bytes) -> bool: ...     # raises HashMismatch, QuotaExceeded
    def get(self, chunk_id: str) -> bytes | None: ...
    def has(self, chunk_id: str) -> bool: ...
    def list_ids(self) -> list[str]: ...
    def used_bytes(self) -> int: ...

@dataclass
class Peer:
    node_id: str; host_id: str; addr: str; state: str        # alive | suspect | dead
    rtt_ewma: float; bw_ewma: float; free_bytes: int
    weight: float; tier: int; cooldown_until: float

class PeerTable:
    def alive(self) -> list[Peer]: ...
    def get(self, node_id: str) -> Peer | None: ...
    def record_transfer(self, node_id: str, nbytes: int, seconds: float) -> None: ...
    def record_failure(self, node_id: str) -> None: ...

class PeerClient:               # every call is HMAC-signed; connect timeout 1 s, read timeout 5 s
    async def put_chunk(self, peer: Peer, chunk_id: str, blob: bytes) -> bool: ...
    async def get_chunk(self, peer: Peer, chunk_id: str) -> bytes | None: ...
    async def head_chunk(self, peer: Peer, chunk_id: str) -> bool: ...
    async def get_inventory(self, peer: Peer) -> list[str]: ...
    async def put_index(self, peer: Peer, owner_pub_hex: str, record: dict) -> bool: ...
    async def get_index(self, peer: Peer, owner_pub_hex: str) -> dict | None: ...

class LocationMap:
    def holders(self, chunk_id: str) -> set[str]: ...          # node_ids

# ---- P3: routing + orchestration ----
def rank_for_placement(chunk_id: str, peers: list[Peer], exclude_hosts: set[str]) -> list[Peer]: ...
def rank_for_retrieval(holders: list[Peer]) -> list[Peer]: ...
def repair_leader(chunk_id: str, live_holder_ids: list[str]) -> str: ...
async def upload(data: bytes, name: str) -> dict: ...          # {file_uuid, manifest_id, original, stored, chunks:[{chunk_id, holders}], status}
async def download(file_uuid: str) -> bytes: ...
```

### HTTP API contract

**Peer API (P2):** every route needs the HMAC headers `X-Node`, `X-Ts`, `X-Sig`.

| Method | Path | Response |
|---|---|---|
| GET | `/health` | `{node_id, host_id, free_bytes, used_bytes, chunk_count, uptime_s}` |
| GET | `/peers` | `[{node_id, host_id, addr}]` (gossip) |
| PUT | `/chunks/{id}` | 201 new, 200 already present, 400 hash mismatch, 413 too big, 507 quota full |
| GET | `/chunks/{id}` | raw bytes, or 404 |
| HEAD | `/chunks/{id}` | 200 or 404 |
| GET | `/inventory` | `[chunk_id, ...]` |
| PUT | `/index/{owner_pub}` | 201; 409 if the version is not newer; 401 bad signature |
| GET | `/index/{owner_pub}` | signed record, or 404 |

There is **no** DELETE route.

**User API (P3):** bound to `127.0.0.1` only.

| Method | Path |
|---|---|
| POST | `/files` |
| GET | `/files` |
| GET | `/files/{uuid}` |
| GET | `/files/{uuid}/map` |
| GET | `/stats` |
| POST | `/recover` (body: `{passphrase}`) |

## How each builder works without waiting on the others

- **P1:** pure functions, no dependencies. Fully testable from minute 30.
- **P2:** chunkstore and peer API first. Test with `curl` and `pytest` + `httpx.AsyncClient`.
- **P3:** starts against **fakes**. Create `tests/fakes.py` with an in-memory `PeerTable`, a `PeerClient` backed by a dict, and a static `LocationMap`. Routing and repair logic is unit-tested on the fakes. Swap in the real classes at Merge 2.

## Timeline and merge points (start = 11:00)

| Time | P1 | P2 | P3 | P4 | Merge gate (must pass) |
|---|---|---|---|---|---|
| 11:00–11:30 | Hour 0 together | ← | ← | ← | `uvicorn node.main:app` shows `/health` on every laptop |
| 11:30–13:30 | pipeline + keys + manifest + tests | config, auth, chunkstore, peer API | routing + fakes + routing tests | Explain docs 00 (overview) and 01 (pipeline) drafts; glossary | **Merge 1 @13:30:** pipeline round-trip tests pass; wrong-hash PUT → 400; HMAC rejection test passes |
| 13:30–15:00 | index sign/verify + rollback test | peer_client, peers (heartbeat, EWMA), `run_cluster.sh` | transfer.upload/download, api_user | Explain 02 (storage node), 03 (routing); start `RESULTS.md` | **Merge 2 @15:00:** 4 local processes; upload 20 MB → download → SHA-256 matches |
| 15:00–15:30 | Multi-laptop test, together | ← | ← | ← | Same test passes across 3–4 real laptops |
| 15:30–17:00 | `ui/index.html` (peers, chunk map, file list, repair counter) | inventory map, gossip, suspect/dead states | download fallback, tiered placement, ETA ordering, `bench.py` | Explain 04 (failure detection), 05 (routing proof); runs first bench | **Merge 3 @17:00:** kill a node mid-download and it still succeeds; delayed node gets 0 new chunks |
| 17:00–18:30 | `/recover` flow with P3 (P1 writes the key/index parts) | mDNS (optional), quota/413 tests | repair loop + leader takeover + repair tests | Explain 06 (repair), 07 (recovery), 08 (security); `DEMO_SCRIPT.md` | **Merge 4 @18:30:** after a kill, all chunks back to 3 live copies; fresh node recovers files from the passphrase |
| **18:30** | **FEATURE FREEZE**: only bug fixes after this | ← | ← | ← | Freeze holds only if Merges 1–3 pass; otherwise cut per the list below |
| 18:30–19:30 | Bug fixes | Bug fixes | Final bench runs (5 reps) | Fills `RESULTS.md` with **measured** numbers only | — |
| 19:30–20:30 | Rehearsal ×2 on real laptops; record a backup video | ← | ← | P4 runs the rehearsal and times every step | Demo runs twice without code changes |
| 20:30–21:00 | Slides review | ← | ← | `SLIDES.md` final, `JUDGE_QA.md` final | — |

**Cut order if behind:** hedged reads → `/recover` → mDNS → dashboard polish. **Never cut** kill-a-node download or repair.

## Git workflow

1. Branches: `p1/<topic>`, `p2/<topic>`, `p3/<topic>`, `p4/<topic>`. Never commit straight to `main` after Hour 0.
2. Small PRs, at least one per merge window. Rebase on `main` before opening:
   ```bash
   git pull --rebase origin main
   ```
3. CI (`.github/workflows/ci.yml`) must be green before merging. The owner merges their own PR after one teammate glances at it.
4. At each merge gate, P4 pulls `main`, runs `pytest` and the cluster script, and posts **pass/fail** to the team chat.
5. `node/contracts.py` changes need approval from P1, P2 and P3.

## P4: the explainer's job

P4 writes one explanation doc within **45 minutes** of each module merging, in `docs/explain/NN-name.md`, using this template:

```markdown
# <Part name>
**One line:** what it does.
**Analogy:** everyday comparison (1–2 sentences).
**How it works:** 3–6 numbered steps, matching the real code (link file:line).
**Why this design:** decision → strongest counter → our defense (link ARCHITECTURE_DECISIONS.md section).
**Evidence:** test name(s) + measured number from RESULTS.md (no invented numbers).
**Limits:** what it does NOT do; what is planned.
**Judge questions:** 3 likely questions, each with a 2-sentence answer and the follow-up.
```

| File | Covers | Ready after |
|---|---|---|
| `00-overview.md` | Problem, architecture diagram, demo story | Hour 0 |
| `01-pipeline.md` | Chunking, compression, encryption, hashing | Merge 1 |
| `02-storage-node.md` | Chunk store, atomic writes, quotas, peer API, HMAC | Merge 1 |
| `03-placement.md` | Tiered rendezvous hashing, distinct hosts | Merge 2 |
| `04-failure-detection.md` | Heartbeats, suspect/dead, timeouts | Merge 3 |
| `05-retrieval-routing.md` | ETA ranking, A/B benchmark proof | Merge 3 |
| `06-repair.md` | Leader election, idempotent PUT, degraded state | Merge 4 |
| `07-recovery-and-keys.md` | Passphrase → keys, signed index, new device | Merge 4 |
| `08-security.md` | Threat table and what AES-GCM does and doesn't protect | Merge 4 |

P4 also owns:
- **`RESULTS.md`:** benchmark table filled only from `bench.py` output, as the median of 5 runs plus min/max.
- **`DEMO_SCRIPT.md`:** the timed 5-minute script with a recovery plan for every step.
- **`JUDGE_QA.md`:** at least 100 questions. P4 asks each builder 5 hard questions about their module at every merge and records the answers.
- **`SLIDES.md`:**
  1. Problem
  2. Architecture
  3. Routing proof (A/B numbers)
  4. Failure + repair timeline
  5. Honest limits and roadmap
- The **backup video** and the **plan B** of running a 4-process cluster on one laptop.

## Fallback plans

| Problem | Fallback |
|---|---|
| No internet | Install from `wheels/` |
| mDNS blocked | Seed list + gossip (always on) |
| Firewall blocks port 8000 | Allow Python in the OS firewall; try port 8080; plan B: local cluster |
| One laptop missing | Run 2 nodes on one laptop **with different host_id**, and say so |
| Laptops can't reach each other | `scripts/run_cluster.sh` on one laptop; state it on stage |
| Repair not finished | Demo replica fallback only; show repair as "planned" |
| Dashboard broken | `curl /stats \| python -m json.tool` + terminal logs |
| Live demo fails | Play the backup video, then show test output |
