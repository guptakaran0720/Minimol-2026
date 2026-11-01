"""Cluster HMAC on every peer request (ARCHITECTURE_DECISIONS.md section 12).

X-Sig = hex HMAC-SHA256(cluster_key, method|path|node_id|ts|sha256(body)),
accepted only within +-30 s of X-Ts.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from collections.abc import Mapping

MAX_SKEW_S = 30


class AuthError(Exception):
    pass


def sign(key: bytes, method: str, path: str, node_id: str, ts: str, body: bytes) -> str:
    msg = "|".join([method.upper(), path, node_id, ts, hashlib.sha256(body).hexdigest()])
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).hexdigest()


def sign_headers(key: bytes, node_id: str, method: str, path: str, body: bytes = b"",
                 now: float | None = None) -> dict[str, str]:
    ts = str(int(time.time() if now is None else now))
    return {"X-Node": node_id, "X-Ts": ts, "X-Sig": sign(key, method, path, node_id, ts, body)}


def verify(key: bytes, method: str, path: str, headers: Mapping[str, str], body: bytes,
           now: float | None = None) -> str:
    """Return the caller's node_id, or raise AuthError."""
    h = {k.lower(): v for k, v in headers.items()}
    node_id, ts, sig = h.get("x-node"), h.get("x-ts"), h.get("x-sig")
    if not (node_id and ts and sig):
        raise AuthError("missing X-Node, X-Ts or X-Sig")
    try:
        ts_val = int(ts)
    except ValueError:
        raise AuthError("bad X-Ts") from None
    now = time.time() if now is None else now
    if abs(now - ts_val) > MAX_SKEW_S:
        raise AuthError("X-Ts outside the +-30 s window")
    if not hmac.compare_digest(sign(key, method, path, node_id, ts, body), sig):
        raise AuthError("bad signature")
    return node_id
