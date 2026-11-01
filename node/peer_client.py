"""HTTP client for the peer API. Implements contracts.PeerClient.

Every call is HMAC-signed. Connect timeout 1 s, read timeout 5 s. Network
errors and unexpected status codes raise; callers treat any exception as a
failed transfer. Expected "no" answers (404, rejected PUT) return None/False.
"""
from __future__ import annotations

import json

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

    async def _request(self, addr: str, method: str, path: str, body: bytes = b"",
                       content_type: str | None = None) -> httpx.Response:
        headers = auth.sign_headers(self.key, self.node_id, method, path, body)
        if self.advertise_addr:
            headers["X-Addr"] = self.advertise_addr
        if content_type:
            headers["Content-Type"] = content_type
        return await self.http.request(method, f"http://{addr}{path}", content=body, headers=headers)

    @staticmethod
    def _unexpected(r: httpx.Response) -> httpx.HTTPStatusError:
        return httpx.HTTPStatusError(f"{r.request.method} {r.request.url.path} -> {r.status_code}",
                                     request=r.request, response=r)

    # ---- contracts.PeerClient ----

    async def put_chunk(self, peer: Peer, chunk_id: str, blob: bytes) -> bool:
        r = await self._request(peer.addr, "PUT", f"/chunks/{chunk_id}", blob, "application/octet-stream")
        if r.status_code in (200, 201):
            return True
        if r.status_code in (400, 413, 507):   # hash mismatch, too big, quota full
            return False
        raise self._unexpected(r)

    async def get_chunk(self, peer: Peer, chunk_id: str) -> bytes | None:
        r = await self._request(peer.addr, "GET", f"/chunks/{chunk_id}")
        if r.status_code == 200:
            return r.content
        if r.status_code == 404:
            return None
        raise self._unexpected(r)

    async def head_chunk(self, peer: Peer, chunk_id: str) -> bool:
        r = await self._request(peer.addr, "HEAD", f"/chunks/{chunk_id}")
        if r.status_code in (200, 404):
            return r.status_code == 200
        raise self._unexpected(r)

    async def get_inventory(self, peer: Peer) -> list[str]:
        r = await self._request(peer.addr, "GET", "/inventory")
        if r.status_code != 200:
            raise self._unexpected(r)
        return r.json()

    async def put_index(self, peer: Peer, owner_pub_hex: str, record: dict) -> bool:
        body = json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
        r = await self._request(peer.addr, "PUT", f"/index/{owner_pub_hex}", body, "application/json")
        if r.status_code == 201:
            return True
        if r.status_code == 409:               # peer already has this version or newer
            return False
        raise self._unexpected(r)

    async def get_index(self, peer: Peer, owner_pub_hex: str) -> dict | None:
        r = await self._request(peer.addr, "GET", f"/index/{owner_pub_hex}")
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
        return r.json()

    async def get_peers(self, peer: Peer) -> list[dict]:
        r = await self._request(peer.addr, "GET", "/peers")
        if r.status_code != 200:
            raise self._unexpected(r)
        return r.json()

    async def aclose(self) -> None:
        await self.http.aclose()
