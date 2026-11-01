"""HTTP client for the peer API. Implements contracts.PeerClient.

Every call is HMAC-signed, and every response must carry a valid response
signature from the node we meant to reach (auth.verify_response). Connect
timeout 1 s, read timeout 5 s. Network errors, bad signatures and unexpected
status codes raise; callers treat any exception as a failed transfer.
Expected "no" answers (404, rejected PUT) return None/False.

It also keeps per-peer traffic counters (for /metrics), reports every chunk it
moves to `on_transfer` (for the per-file Logs), and refuses to believe a peer's
"I have it" for a copy that failed a proof-of-storage audit (`is_distrusted`).
"""
from __future__ import annotations

import json
import time
from collections import Counter
from collections.abc import Callable

import httpx

from node import auth, config
from node.contracts import Peer


class HttpPeerClient:
    def __init__(self, node_id: str, cluster_key: bytes, http: httpx.AsyncClient | None = None,
                 advertise_addr: str = ""):
        self.node_id = node_id
        self.key = cluster_key
        self.advertise_addr = advertise_addr   # sent as X-Addr so the peer can find us back
        self.http = http or httpx.AsyncClient(
            timeout=httpx.Timeout(config.READ_TIMEOUT_S, connect=config.CONNECT_TIMEOUT_S),
            limits=httpx.Limits(max_connections=64, max_keepalive_connections=16),
        )
        # (peer, op, outcome) -> count; peer -> bytes. "peer" is the node_id, or the addr before we know it.
        self.requests: Counter[tuple[str, str, str]] = Counter()
        self.bytes_sent: Counter[str] = Counter()
        self.bytes_received: Counter[str] = Counter()
        # on_transfer(direction, peer, chunk_id, nbytes, seconds); set by main.py
        self.on_transfer: Callable[[str, Peer, str, int, float], None] | None = None
        # is_distrusted(chunk_id, node_id): True while that copy is under a failed audit
        self.is_distrusted: Callable[[str, str], bool] = lambda chunk_id, node_id: False

    async def _request(self, target: Peer | str, method: str, path: str, body: bytes = b"",
                       content_type: str | None = None) -> httpx.Response:
        """target is a Peer (its node_id must sign the answer) or a bare addr (any member may)."""
        addr, expect = (target.addr, target.node_id) if isinstance(target, Peer) else (target, None)
        who, op = expect or addr, f"{method} /{path.split('/')[1]}"
        headers = auth.sign_headers(self.key, self.node_id, method, path, body)
        if self.advertise_addr:
            headers["X-Addr"] = self.advertise_addr
        if content_type:
            headers["Content-Type"] = content_type
        try:
            r = await self.http.request(method, f"http://{addr}{path}", content=body, headers=headers)
        except Exception:
            self.requests[(who, op, "error")] += 1
            raise
        self.bytes_sent[who] += len(body)
        self.bytes_received[who] += len(r.content)
        self.requests[(who, op, str(r.status_code))] += 1
        if r.status_code == 401:               # it rejected our signature; 401s are never signed
            raise self._unexpected(r)
        responder = auth.verify_response(self.key, r.status_code, headers["X-Sig"], r.headers, r.content)
        if expect is not None and responder != expect:
            raise auth.AuthError(f"{addr} answered as {responder}, expected {expect}")
        return r

    @staticmethod
    def _unexpected(r: httpx.Response) -> httpx.HTTPStatusError:
        return httpx.HTTPStatusError(f"{r.request.method} {r.request.url.path} -> {r.status_code}",
                                     request=r.request, response=r)

    # ---- contracts.PeerClient ----

    def _moved(self, direction: str, peer: Peer, chunk_id: str, nbytes: int, started: float) -> None:
        if self.on_transfer is not None:
            self.on_transfer(direction, peer, chunk_id, nbytes, time.monotonic() - started)

    async def put_chunk(self, peer: Peer, chunk_id: str, blob: bytes) -> bool:
        started = time.monotonic()
        r = await self._request(peer, "PUT", f"/chunks/{chunk_id}", blob, "application/octet-stream")
        if r.status_code in (200, 201):
            self._moved("upload", peer, chunk_id, len(blob), started)
            return True
        if r.status_code in (400, 413, 507):   # hash mismatch, too big, quota full
            return False
        raise self._unexpected(r)

    async def get_chunk(self, peer: Peer, chunk_id: str) -> bytes | None:
        started = time.monotonic()
        r = await self._request(peer, "GET", f"/chunks/{chunk_id}")
        if r.status_code == 200:
            self._moved("download", peer, chunk_id, len(r.content), started)
            return r.content
        if r.status_code == 404:
            return None
        raise self._unexpected(r)

    async def head_chunk(self, peer: Peer, chunk_id: str) -> bool:
        r = await self._request(peer, "HEAD", f"/chunks/{chunk_id}")
        if r.status_code in (200, 404):
            # A copy that just failed our audit doesn't count, whatever the peer says,
            # so repair places a real copy somewhere else.
            return r.status_code == 200 and not self.is_distrusted(chunk_id, peer.node_id)
        raise self._unexpected(r)

    async def audit_chunk(self, peer: Peer, chunk_id: str, nonce: bytes) -> str | None:
        """Ask peer for HMAC-SHA256(nonce, its copy). None if it says it doesn't hold the chunk."""
        body = json.dumps({"nonce": nonce.hex()}).encode()
        r = await self._request(peer, "POST", f"/audit/{chunk_id}", body, "application/json")
        if r.status_code == 200:
            return r.json()["proof"]
        if r.status_code == 404:
            return None
        raise self._unexpected(r)

    async def get_inventory(self, peer: Peer) -> list[str]:
        r = await self._request(peer, "GET", "/inventory")
        if r.status_code != 200:
            raise self._unexpected(r)
        return r.json()

    async def put_index(self, peer: Peer, owner_pub_hex: str, record: dict) -> bool:
        body = json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
        r = await self._request(peer, "PUT", f"/index/{owner_pub_hex}", body, "application/json")
        if r.status_code == 201:
            return True
        if r.status_code == 409:               # peer already has this version or newer
            return False
        raise self._unexpected(r)

    async def get_index(self, peer: Peer, owner_pub_hex: str) -> dict | None:
        r = await self._request(peer, "GET", f"/index/{owner_pub_hex}")
        if r.status_code == 200:
            return r.json()
        if r.status_code == 404:
            return None
        raise self._unexpected(r)

    # ---- membership (used by peers.py and discovery.py) ----

    async def health(self, addr: str) -> dict:
        r = await self._request(addr, "GET", "/health")
        if r.status_code != 200:
            raise self._unexpected(r)
        health = r.json()
        if health.get("node_id") != r.headers["x-node"]:
            raise auth.AuthError("/health body names a different node than its signature")
        return health

    async def get_peers(self, peer: Peer) -> list[dict]:
        r = await self._request(peer, "GET", "/peers")
        if r.status_code != 200:
            raise self._unexpected(r)
        return r.json()

    async def aclose(self) -> None:
        await self.http.aclose()
