"""Frozen interfaces shared by P1, P2 and P3.

Source of truth for the contracts in docs/TEAM_WORKFLOW.md. Changing anything
here needs approval from P1, P2 and P3. Behaviour is described in
docs/ARCHITECTURE_DECISIONS.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

CHUNK_SIZE = 1024 * 1024
REPLICATION = 3


# ---- P1: pure functions, no networking (node/pipeline.py, keys.py, manifest.py, index.py) ----

@dataclass
class EncodedChunk:
    index: int
    chunk_id: str        # sha256 hex of blob
    blob: bytes          # nonce || ciphertext || tag
    plain_size: int
    compressed: bool


@dataclass
class MasterKeys:
    kek: bytes
    sign_priv: bytes
    sign_pub: bytes


@dataclass
class Manifest:
    file_uuid: str
    name: str
    size: int
    sha256: str          # of the original plaintext file
    wrapped_dek: bytes
    chunks: list[dict]   # {index, chunk_id, plain_size, compressed}
    version: int = 1     # bumps on every re-upload of the same file (delta sync)


class Codec(Protocol):
    """P1's functions, grouped so P3 can inject fakes in tests.

    encode_file uses a synthetic nonce HMAC(dek, flag || plaintext)[:12] and
    AAD = file_uuid || flag, so identical chunks of one file always produce
    identical blobs (delta sync, ARCHITECTURE_DECISIONS.md section 14).
    """
    def encode_file(self, data: bytes, file_uuid: str, dek: bytes) -> list[EncodedChunk]: ...
    def decode_chunk(self, blob: bytes, file_uuid: str, compressed: bool, dek: bytes) -> bytes: ...
    def sha256_hex(self, b: bytes) -> str: ...
    def derive_master(self, passphrase: str, salt: bytes) -> MasterKeys: ...
    def wrap_key(self, kek: bytes, dek: bytes) -> bytes: ...
    def unwrap_key(self, kek: bytes, wrapped: bytes) -> bytes: ...
    def seal_manifest(self, m: Manifest, kek: bytes) -> bytes: ...     # manifest_id = sha256(blob)
    def open_manifest(self, blob: bytes, kek: bytes) -> Manifest: ...
    def seal_index(self, manifest_ids: list[str], version: int, keys: MasterKeys) -> dict: ...
    def verify_index(self, record: dict, owner_pub: bytes) -> int: ...  # version, or raises
    def open_index(self, record: dict, keys: MasterKeys) -> list[str]: ...


# ---- P2: node + network (node/chunkstore.py, peers.py, peer_client.py, inventory.py) ----

class HashMismatch(Exception):
    pass


class QuotaExceeded(Exception):
    pass


class ChunkStore(Protocol):
    def put(self, chunk_id: str, blob: bytes) -> bool: ...   # True if new; raises HashMismatch, QuotaExceeded
    def get(self, chunk_id: str) -> bytes | None: ...
    def has(self, chunk_id: str) -> bool: ...
    def list_ids(self) -> list[str]: ...
    def used_bytes(self) -> int: ...


@dataclass
class Peer:
    node_id: str
    host_id: str                 # failure domain: never two replicas on one host_id
    addr: str                    # "ip:port"
    state: str = "alive"         # alive | suspect | dead
    rtt_ewma: float = 0.0        # seconds; 0 = no samples yet
    bw_ewma: float = 0.0         # bytes/second from real chunk transfers; 0 = no samples yet
    free_bytes: int = 0
    weight: float = 1.0          # static capacity class, always > 0
    tier: int = 1                # 1 healthy, 2 slow (set by peers.py with hysteresis)
    cooldown_until: float = 0.0  # time.monotonic() until which this peer is tried last


class PeerTable(Protocol):
    def alive(self) -> list[Peer]: ...
    def get(self, node_id: str) -> Peer | None: ...
    def record_transfer(self, node_id: str, nbytes: int, seconds: float) -> None: ...
    def record_failure(self, node_id: str) -> None: ...


class PeerClient(Protocol):
    """Every call is HMAC-signed. Connect timeout 1 s, read timeout 5 s.
    Network errors raise; callers treat any exception as a failed transfer."""
    async def put_chunk(self, peer: Peer, chunk_id: str, blob: bytes) -> bool: ...
    async def get_chunk(self, peer: Peer, chunk_id: str) -> bytes | None: ...
    async def head_chunk(self, peer: Peer, chunk_id: str) -> bool: ...
    async def get_inventory(self, peer: Peer) -> list[str]: ...
    async def put_index(self, peer: Peer, owner_pub_hex: str, record: dict) -> bool: ...
    async def get_index(self, peer: Peer, owner_pub_hex: str) -> dict | None: ...


class LocationMap(Protocol):
    """Soft state built from peers' /inventory. May be stale; dead peers stay listed
    until their inventory is dropped, so repair can see the missing copy."""
    def holders(self, chunk_id: str) -> set[str]: ...       # node_ids
    def note(self, chunk_id: str, node_id: str) -> None: ...  # record a copy we just stored


# ---- P3: routing + orchestration (node/routing.py, transfer.py, repair.py) ----
# routing.rank_for_placement(chunk_id, peers, exclude_hosts) -> list[Peer]
# routing.rank_for_retrieval(holders, size) -> list[Peer]
# routing.repair_order(chunk_id, live_holder_ids) -> list[str]   (leader = [0])
# transfer.Transfer.upload(data, name) -> dict
# transfer.Transfer.download(file_uuid) -> bytes
# transfer.Transfer.recover() -> int   (number of files restored from peers)


@dataclass
class UploadResult:
    file_uuid: str
    manifest_id: str
    name: str
    version: int
    original_bytes: int
    encoded_bytes: int       # sum of blob sizes (after compression + encryption)
    sent_bytes: int          # blob bytes actually transferred (delta sync skips unchanged)
    replicated_bytes: int    # sum over chunks of blob size x copies held
    sent_chunks: int
    reused_chunks: int
    status: str              # durable | degraded
    chunks: list[dict] = field(default_factory=list)   # {index, chunk_id, holders}
