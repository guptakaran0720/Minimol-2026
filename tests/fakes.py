"""In-memory stand-ins for P1 and P2 so P3 logic is testable before their code lands.

FakeCodec is NOT cryptography: it only preserves the contract's shape
(deterministic blobs per (file, dek, plaintext), chunk_id = sha256(blob)).
"""
from __future__ import annotations

import hashlib
import json
import time

from node.contracts import EncodedChunk, Manifest, MasterKeys, Peer

GB = 1024**3


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class FakeCodec:
    def encode_chunk(self, plain, index, file_uuid, dek):
        blob = dek[:4] + file_uuid.encode()[:8] + plain
        return EncodedChunk(index, sha(blob), blob, len(plain), False)

    def decode_chunk(self, blob, file_uuid, compressed, dek):
        assert blob[:12] == dek[:4] + file_uuid.encode()[:8], "wrong key/file"
        return blob[12:]

    def sha256_hex(self, b):
        return sha(b)

    def derive_master(self, passphrase, salt):
        seed = hashlib.sha256(passphrase.encode() + salt).digest()
        return MasterKeys(kek=seed, sign_priv=seed[::-1], sign_pub=hashlib.sha256(seed).digest())

    def wrap_key(self, kek, dek):
        return bytes(a ^ b for a, b in zip(dek, kek))

    def unwrap_key(self, kek, wrapped):
        return bytes(a ^ b for a, b in zip(wrapped, kek))

    def seal_manifest(self, m, kek):
        d = dict(m.__dict__, wrapped_dek=m.wrapped_dek.hex())
        return b"M" + kek[:4] + json.dumps(d, sort_keys=True).encode()

    def open_manifest(self, blob, kek):
        assert blob[1:5] == kek[:4], "wrong kek"
        d = json.loads(blob[5:])
        d["wrapped_dek"] = bytes.fromhex(d["wrapped_dek"])
        return Manifest(**d)

    def seal_index(self, manifest_ids, version, keys):
        return {"version": version, "ids": list(manifest_ids), "sig": keys.sign_pub.hex()}

    def verify_index(self, record, owner_pub):
        if record.get("sig") != owner_pub.hex():
            raise ValueError("bad signature")
        return record["version"]

    def open_index(self, record, keys):
        return list(record["ids"])


class FakeNetwork:
    """All nodes' chunk stores and index slots, plus failure injection."""

    def __init__(self):
        self.stores: dict[str, dict[str, bytes]] = {}
        self.indexes: dict[str, dict[str, dict]] = {}
        self.down: set[str] = set()
        self.corrupt: set[str] = set()   # these nodes return garbage on GET
        self.full: set[str] = set()      # these nodes reject PUT
        self.puts = 0

    def add_node(self, node_id):
        self.stores.setdefault(node_id, {})
        self.indexes.setdefault(node_id, {})


class FakePeerTable:
    def __init__(self, peers: list[Peer]):
        self.peers = {p.node_id: p for p in peers}
        self.failures: dict[str, int] = {}
        self.transfers: dict[str, int] = {}

    def alive(self):
        return [p for p in self.peers.values() if p.state == "alive"]

    def get(self, node_id):
        return self.peers.get(node_id)

    def record_transfer(self, node_id, nbytes, seconds):
        self.transfers[node_id] = self.transfers.get(node_id, 0) + 1

    def record_failure(self, node_id):
        self.failures[node_id] = self.failures.get(node_id, 0) + 1
        p = self.peers.get(node_id)
        if p:
            p.cooldown_until = time.monotonic() + 15

    def kill(self, net: FakeNetwork, node_id: str, state: str = "dead"):
        net.down.add(node_id)
        self.peers[node_id].state = state


class FakeClient:
    def __init__(self, net: FakeNetwork):
        self.net = net

    def _check(self, peer):
        if peer.node_id in self.net.down:
            raise ConnectionError(f"{peer.node_id} unreachable")

    async def put_chunk(self, peer, chunk_id, blob):
        self._check(peer)
        if peer.node_id in self.net.full or sha(blob) != chunk_id:
            return False
        self.net.puts += 1
        self.net.stores[peer.node_id][chunk_id] = blob
        return True

    async def get_chunk(self, peer, chunk_id):
        self._check(peer)
        blob = self.net.stores[peer.node_id].get(chunk_id)
        if blob is not None and peer.node_id in self.net.corrupt:
            return b"garbage" + blob
        return blob

    async def head_chunk(self, peer, chunk_id):
        self._check(peer)
        return chunk_id in self.net.stores[peer.node_id]

    async def get_inventory(self, peer):
        self._check(peer)
        return list(self.net.stores[peer.node_id])

    async def put_index(self, peer, owner_pub_hex, record):
        self._check(peer)
        slot = self.net.indexes[peer.node_id]
        current = slot.get(owner_pub_hex)
        if current and current["version"] >= record["version"]:
            return False
        slot[owner_pub_hex] = record
        return True

    async def get_index(self, peer, owner_pub_hex):
        self._check(peer)
        return self.net.indexes[peer.node_id].get(owner_pub_hex)


class FakeLocationMap:
    def __init__(self, net: FakeNetwork):
        self.net = net
        self.map: dict[str, set[str]] = {}

    def holders(self, chunk_id):
        return set(self.map.get(chunk_id, set()))

    def note(self, chunk_id, node_id):
        self.map.setdefault(chunk_id, set()).add(node_id)

    def replace_inventory(self, node_id, chunk_ids):
        self.forget(node_id)
        for cid in chunk_ids:
            self.note(cid, node_id)

    def forget(self, node_id):
        for holders in self.map.values():
            holders.discard(node_id)

    def refresh(self):
        """What inventory polling would converge to (dead peers keep their last inventory)."""
        self.map = {}
        for node_id, store in self.net.stores.items():
            for cid in store:
                self.note(cid, node_id)


class FakeStore:
    """One node's own ChunkStore, backed by the shared FakeNetwork."""

    def __init__(self, net: FakeNetwork, node_id: str):
        self.net, self.node_id = net, node_id

    def _s(self):
        return self.net.stores[self.node_id]

    def put(self, chunk_id, blob):
        new = chunk_id not in self._s()
        self._s()[chunk_id] = blob
        return new

    def get(self, chunk_id):
        return self._s().get(chunk_id)

    def has(self, chunk_id):
        return chunk_id in self._s()

    def list_ids(self):
        return list(self._s())

    def used_bytes(self):
        return sum(map(len, self._s().values()))

    def free_bytes(self):
        return GB - self.used_bytes()


def make_cluster(n: int = 4):
    net = FakeNetwork()
    peers = []
    for i in range(n):
        node_id = f"node{i}"
        net.add_node(node_id)
        peers.append(Peer(node_id=node_id, host_id=f"host{i}", addr=f"10.0.0.{i}:8000", free_bytes=GB))
    table = FakePeerTable(peers)
    return net, table, FakeClient(net), FakeLocationMap(net), FakeCodec()
