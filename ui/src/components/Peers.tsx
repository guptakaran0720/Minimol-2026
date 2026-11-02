import type { CSSProperties } from "react";
import { formatBytes, type DrainStatus, type Peer } from "../api";
import type { Look } from "../identity";

function tagFor(p: Peer): string {
  if (p.self) return "YOU";
  if (p.state === "dead") return "K.O.";
  if (p.state === "suspect") return "???";
  if (p.state === "draining") return "DRAIN";
  if (p.tier === 2) return "LAG";
  return "READY";
}

/** Signal strength for the bar under each player: full at 20 ms or less, falling with RTT. */
function signal(p: Peer): number {
  if (p.state === "dead") return 0;
  if (p.self) return 100;
  if (!(p.rtt_ms > 0)) return 60;
  return Math.max(8, Math.min(100, Math.round((20 / p.rtt_ms) * 100)));
}

/** Every laptop as a player card: P1, P2, … in node_id order. */
export function Peers({
  peers,
  looks,
  drain,
  onDrain,
}: {
  peers: Peer[];
  looks: Map<string, Look>;
  wide?: boolean;
  drain?: DrainStatus | null;
  onDrain?: (draining: boolean) => void;
}) {
  const alive = peers.filter((p) => p.state === "alive").length;
  const rows = [...peers].sort((a, b) => a.node_id.localeCompare(b.node_id));
  return (
    <section className="tile tile-white tile-list tile-players s12" aria-labelledby="peers-title">
      <div className="tile-head">
        <h2 id="peers-title" className="tile-title">
          Select player
        </h2>
        <span className="muted small">
          {alive} of {peers.length} alive · refreshed every 2 s
        </span>
      </div>
      <div className="players">
        {rows.map((p, i) => {
          const tone = looks.get(p.node_id)?.tone ?? "blue";
          const style = { "--pc": p.state === "dead" ? "#6f63a8" : `var(--${tone})` } as CSSProperties;
          return (
            <article key={p.node_id} className={`player state-${p.state} ${p.self ? "is-self" : ""}`} style={style}>
              <div className="player-head">
                <span className="player-slot">P{i + 1}</span>
                <span className="player-tag">{tagFor(p)}</span>
              </div>
              <svg className="player-art" width="72" height="54" viewBox="0 0 12 9" shapeRendering="crispEdges" aria-hidden="true">
                <rect x="2" y="0" width="8" height="6" fill="currentColor" />
                <rect x="3" y="1" width="6" height="4" fill="#0c0624" />
                <rect x="4" y="2" width="1" height="1" fill="currentColor" />
                <rect x="7" y="2" width="1" height="1" fill="currentColor" />
                <rect x="5" y="3" width="2" height="1" fill="currentColor" />
                <rect x="0" y="6" width="12" height="2" fill="currentColor" />
              </svg>
              <div>
                <div className="player-name mono">{p.node_id}</div>
                <div className="sub mono">
                  {p.host_id} · IP {p.ip ?? p.addr}
                </div>
                <div className="sub mono">MAC {p.mac ?? "—"}</div>
              </div>
              <dl className="player-stats">
                <div>
                  <dt>Ping</dt>
                  <dd>{p.self || p.state === "dead" ? "—" : `${p.rtt_ms.toFixed(1)} ms`}</dd>
                </div>
                <div>
                  <dt>Speed</dt>
                  <dd>{p.bw_mbps > 0 ? `${p.bw_mbps.toFixed(1)} Mb/s` : "—"}</dd>
                </div>
                <div>
                  <dt>Free</dt>
                  <dd>{formatBytes(p.free_bytes)}</dd>
                </div>
                <div>
                  <dt>Seen</dt>
                  <dd>{p.last_ok_s_ago === undefined ? "—" : `${p.last_ok_s_ago.toFixed(0)} s ago`}</dd>
                </div>
              </dl>
              <div className="hp" role="img" aria-label={`link ${p.state}${p.tier === 2 ? ", slow tier" : ""}`}>
                <span style={{ width: `${signal(p)}%` }} />
              </div>
              {p.self && onDrain && (
                <div className="drain-row">
                  {drain?.draining ? (
                    <>
                      <span className={`small ${drain.safe_to_power_off ? "ok-text" : "muted"}`}>
                        {drain.safe_to_power_off
                          ? "Safe to power off: every chunk is on the other laptops."
                          : `Draining: ${drain.safe_chunks} of ${drain.chunks} chunks safe elsewhere`}
                      </span>
                      <button className="text-btn" onClick={() => onDrain(false)}>
                        Cancel drain
                      </button>
                    </>
                  ) : (
                    <button
                      className="text-btn"
                      onClick={() => onDrain(true)}
                      title="Stop taking new chunks and copy this laptop's chunks to the others before you shut it down"
                    >
                      Drain this laptop
                    </button>
                  )}
                </div>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}
