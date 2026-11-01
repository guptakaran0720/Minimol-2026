import { formatBytes, type Peer } from "../api";
import { PeerMark, type Look } from "../identity";

export function Peers({ peers, looks, wide = false }: { peers: Peer[]; looks: Map<string, Look>; wide?: boolean }) {
  const alive = peers.filter((p) => p.state === "alive").length;
  const rows = [...peers].sort((a, b) => a.node_id.localeCompare(b.node_id));
  return (
    <section className={`tile tile-white tile-list ${wide ? "s12" : "s7"}`} aria-labelledby="peers-title">
      <div className="tile-head">
        <h2 id="peers-title" className="tile-title">
          Peers
        </h2>
        <span className="muted small">
          {alive} of {peers.length} alive
        </span>
      </div>
      <div className="table-wrap">
        <table className="peers">
          <thead>
            <tr>
              <th scope="col">Node</th>
              <th scope="col">State</th>
              <th scope="col" className="num">
                RTT
              </th>
              <th scope="col" className="num">
                Bandwidth
              </th>
              <th scope="col" className="num">
                Free
              </th>
              <th scope="col" className="num">
                Last seen
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => (
              <tr key={p.node_id} className={`row-${p.state}`}>
                <td>
                  <span className="node-cell">
                    <PeerMark look={looks.get(p.node_id)} state={p.state} />
                    <span>
                      <span className="mono node-name">{p.node_id}</span>
                      {p.self && <span className="tag tag-ink">this laptop</span>}
                      {p.tier === 2 && (
                        <span className="tag tag-warn" title="Estimated fetch time above 3× the cluster median for 30 s">
                          slow tier
                        </span>
                      )}
                      <span className="sub mono">
                        {p.host_id} · {p.addr}
                      </span>
                    </span>
                  </span>
                </td>
                <td>
                  <span className={`badge badge-${p.state}`}>{p.state}</span>
                </td>
                <td className="num">{p.self || p.state === "dead" ? "—" : `${p.rtt_ms.toFixed(1)} ms`}</td>
                <td className="num">{p.bw_mbps > 0 ? `${p.bw_mbps.toFixed(1)} Mb/s` : "—"}</td>
                <td className="num">{formatBytes(p.free_bytes)}</td>
                <td className="num">{p.last_ok_s_ago === undefined ? "—" : `${p.last_ok_s_ago.toFixed(0)} s ago`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
