"""Node settings, read from environment variables.

Required: CLUSTER_KEY (shared secret, at least 16 characters).
Everything else has a default; see Settings.from_env.
"""
from __future__ import annotations

import ipaddress
import os
import re
import socket
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path

HEARTBEAT_INTERVAL_S = 2.0
SUSPECT_AFTER_MISSED = 2
DEAD_AFTER_S = 20.0
INVENTORY_INTERVAL_S = 10.0
GOSSIP_INTERVAL_S = 5.0
SCRUB_INTERVAL_S = 1.0       # scrub SCRUB_PER_S chunks every second
AUDIT_INTERVAL_S = 5.0       # challenge AUDIT_PER_ROUND remote copies every 5 s
AUDIT_DISTRUST_S = 120.0     # a copy that failed an audit is not counted for this long
DRAIN_CHECK_INTERVAL_S = 5.0
CONNECT_TIMEOUT_S = 1.0
READ_TIMEOUT_S = 5.0
FAILURE_COOLDOWN_S = 15.0
EWMA_ALPHA = 0.3
SLOW_FACTOR = 3.0            # tier 2 when ETA > 3x cluster median ...
SLOW_HOLD_S = 30.0           # ... for this long (and the same to come back)

CHUNK_BODY_MAX = 1024 * 1024 + 64
INDEX_BODY_MAX = 1024 * 1024
MIN_CLUSTER_KEY_LEN = 16


class ConfigError(Exception):
    pass


def lan_ip() -> str:
    """Best guess at this machine's LAN address (no packets are sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


@dataclass
class Settings:
    node_id: str
    host_id: str                  # failure domain; two nodes on one laptop must share it
    cluster_key: bytes
    data_dir: Path
    port: int = 8000
    bind_host: str = "0.0.0.0"
    advertise_addr: str = ""      # "ip:port" other nodes use to reach us
    seeds: list[str] = field(default_factory=list)
    quota_bytes: int = 2 * 1024**3
    weight: float = 1.0
    simulated_delay_ms: int = 0
    mdns: bool = True
    scrub_per_s: int = 8         # chunks re-hashed per second; 0 turns scrubbing off
    audit_per_round: int = 2     # remote copies challenged every AUDIT_INTERVAL_S; 0 turns audits off
    mac: str = ""                # this machine's MAC (of the interface holding ADVERTISE_ADDR's IP)
    # Extra client networks allowed to use the user API besides localhost. Only for
    # Docker, where published ports arrive from the bridge gateway. Never a LAN range.
    user_api_allow: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = field(default_factory=list)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Settings:
        env = dict(os.environ if env is None else env)
        key = env.get("CLUSTER_KEY", "")
        if len(key) < MIN_CLUSTER_KEY_LEN:
            raise ConfigError(f"CLUSTER_KEY must be set and at least {MIN_CLUSTER_KEY_LEN} characters")
        port = int(env.get("PORT", "8000"))
        data_dir = Path(env.get("DATA_DIR", f"data/node-{port}"))
        weight = float(env.get("WEIGHT", "1.0"))
        if weight <= 0:
            raise ConfigError("WEIGHT must be > 0")
        return cls(
            node_id=env.get("NODE_ID") or _persistent_node_id(data_dir),
            host_id=env.get("HOST_ID") or socket.gethostname(),
            cluster_key=key.encode("utf-8"),
            data_dir=data_dir,
            port=port,
            bind_host=env.get("BIND_HOST", "0.0.0.0"),
            advertise_addr=env.get("ADVERTISE_ADDR") or f"{lan_ip()}:{port}",
            seeds=[s.strip() for s in env.get("SEEDS", "").split(",") if s.strip()],
            quota_bytes=int(float(env.get("QUOTA_MB", "2048")) * 1024 * 1024),
            weight=weight,
            simulated_delay_ms=int(env.get("SIMULATED_DELAY_MS", "0")),
            mdns=env.get("MDNS", "1") not in ("0", "false", "no", ""),
            scrub_per_s=int(env.get("SCRUB_PER_S", "8")),
            audit_per_round=int(env.get("AUDIT_PER_ROUND", "2")),
            user_api_allow=[ipaddress.ip_network(n.strip(), strict=False)
                            for n in env.get("USER_API_ALLOW", "").split(",") if n.strip()],
        ).with_mac(env.get("MAC_ADDR", ""))

    def with_mac(self, override: str = "") -> Settings:
        ip = self.advertise_addr.rsplit(":", 1)[0]
        self.mac = override.lower() or mac_for_ip(ip) or ""
        return self


_MAC_RE = re.compile(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}")


def _run(*cmd: str) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=2).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def mac_for_ip(ip: str) -> str | None:
    """MAC address of the network interface that holds `ip`, or None if it can't be found.

    macOS/BSD: parse `ifconfig`. Linux: `ip -o addr` for the interface, then sysfs.
    Fallback: uuid.getnode(), unless it returned a random number (multicast bit set).
    """
    out = _run("ifconfig")
    for block in re.split(r"\n(?=\S)", out):
        if re.search(rf"\binet {re.escape(ip)}\b", block) and (m := re.search(r"\bether ([0-9a-f:]{17})", block)):
            return m.group(1)
    for line in _run("ip", "-o", "addr").splitlines():
        parts = line.split()
        if len(parts) > 3 and parts[3].split("/")[0] == ip:
            try:
                mac = Path(f"/sys/class/net/{parts[1]}/address").read_text().strip()
                if _MAC_RE.fullmatch(mac) and mac != "00:00:00:00:00:00":
                    return mac
            except OSError:
                pass
    node = uuid.getnode()
    if not node >> 40 & 1:                       # bit set = uuid made the number up
        return ":".join(f"{node >> s & 0xFF:02x}" for s in range(40, -1, -8))
    return None


def _persistent_node_id(data_dir: Path) -> str:
    """Keep the same node_id across restarts so peers' location maps stay valid."""
    path = data_dir / "node_id"
    if path.exists():
        return path.read_text().strip()
    data_dir.mkdir(parents=True, exist_ok=True)
    node_id = f"n-{uuid.uuid4().hex[:12]}"
    path.write_text(node_id)
    return node_id


LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}


def user_api_client_ok(host: str | None, allow: list) -> bool:
    """Localhost always; otherwise only addresses inside USER_API_ALLOW."""
    if not host:
        return False
    if host in LOCAL_HOSTS:
        return True
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(addr in net for net in allow)
