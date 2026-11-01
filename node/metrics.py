"""GET /metrics: Prometheus text format (localhost only, like the user API).

Everything is read from state the node already keeps: the peer table, the store,
scrub and audit counters, the peer client's traffic counters, the peer API's
served-request counters, P3's repairer, and the event log. Nothing is sampled
or estimated here.
"""
from __future__ import annotations

from collections import Counter


def _esc(v) -> str:
    return str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


class _Out:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.seen: set[str] = set()

    def add(self, name: str, mtype: str, help_: str, value, **labels) -> None:
        if name not in self.seen:
            self.seen.add(name)
            self.lines += [f"# HELP {name} {help_}", f"# TYPE {name} {mtype}"]
        lab = ",".join(f'{k}="{_esc(v)}"' for k, v in labels.items())
        self.lines.append(f"{name}{{{lab}}} {value}" if lab else f"{name} {value}")


def render(node, served: Counter, repairer=None) -> str:
    s, out = node.settings, _Out()
    out.add("minimol_info", "gauge", "This node's identity.", 1,
            node_id=s.node_id, host_id=s.host_id, addr=s.advertise_addr, mac=s.mac or "")
    out.add("minimol_draining", "gauge", "1 while this node is draining.", int(node.drain.active))

    for p in node.peers.all():
        for state in ("alive", "suspect", "dead", "draining"):
            out.add("minimol_peer_state", "gauge", "1 for the peer's current state.", int(p.state == state),
                    peer=p.node_id, state=state)
        out.add("minimol_peer_tier", "gauge", "1 = normal, 2 = slow tier.", p.tier, peer=p.node_id)
        out.add("minimol_peer_rtt_seconds", "gauge", "Smoothed round-trip time.", round(p.rtt_ewma, 6), peer=p.node_id)
        out.add("minimol_peer_bandwidth_bytes_per_second", "gauge", "Smoothed transfer speed.",
                round(p.bw_ewma, 1), peer=p.node_id)
        out.add("minimol_peer_free_bytes", "gauge", "Free quota the peer reports.", p.free_bytes, peer=p.node_id)

    c = node.client
    for (peer, op, outcome), n in sorted(c.requests.items()):
        out.add("minimol_client_requests_total", "counter", "Requests this node sent to peers.", n,
                peer=peer, op=op, outcome=outcome)
    for peer, n in sorted(c.bytes_sent.items()):
        out.add("minimol_client_sent_bytes_total", "counter", "Request body bytes sent to each peer.", n, peer=peer)
    for peer, n in sorted(c.bytes_received.items()):
        out.add("minimol_client_received_bytes_total", "counter", "Response body bytes received from each peer.",
                n, peer=peer)
    for (route, status), n in sorted(served.items()):
        if route == "bytes_out":
            out.add("minimol_served_bytes_total", "counter", "Response body bytes this node served to peers.", n)
        else:
            out.add("minimol_served_requests_total", "counter", "Peer requests this node answered.", n,
                    route=route, status=status)

    st = node.store
    out.add("minimol_store_chunks", "gauge", "Chunks stored on this node.", len(st.list_ids()))
    out.add("minimol_store_used_bytes", "gauge", "Bytes stored.", st.used_bytes())
    out.add("minimol_store_free_bytes", "gauge", "Quota left.", st.free_bytes())
    out.add("minimol_store_quota_bytes", "gauge", "Quota.", st.quota_bytes)
    for key in ("checked", "quarantined", "missing", "passes"):
        out.add(f"minimol_scrub_{key}_total", "counter", f"Background scrub: {key}.", st.scrub_stats[key])
    for outcome in ("passed", "failed", "error", "skipped"):
        out.add("minimol_audits_total", "counter", "Proof-of-storage audits this node ran.",
                node.audit_stats[outcome], outcome=outcome)
    out.add("minimol_audit_distrusted_copies", "gauge", "Copies currently distrusted after a failed audit.",
            node.locations.distrusted_count())
    out.add("minimol_location_map_chunks", "gauge", "Distinct chunks in this node's location map.",
            len(node.locations._by_chunk))
    if repairer is not None:
        out.add("minimol_repair_copies_total", "counter", "Copies this node's repair made.", repairer.total_copies)

    kinds = Counter(e["kind"] for e in node.events.since(0))
    for kind, n in sorted(kinds.items()):
        out.add("minimol_events_total", "counter", "Timeline events by kind (last 500 kept).", n, kind=kind)
    return "\n".join(out.lines) + "\n"
