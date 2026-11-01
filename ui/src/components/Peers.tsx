import { formatBytes, type Peer } from "../api";

export function Peers({ peers }: { peers: Peer[] }) {
  const alive = peers.filter((p) => p.state === "alive").length;
  return (
    <section className="card">
      <header className="card-head">
        <h2>Peers</h2>
        <span className="muted">
          {alive} of {peers.length} alive
        </span>
      </header>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Node</th>
              <th>State</th>
              <th className="num">RTT</th>
              <th className="num">Bandwidth</th>
              <th className="num">Free</th>
              <th className="num">Last seen</th>
            </tr>
          </thead>
          <tbody>
            {peers.map((p) => (
              <tr key={p.node_id} className={`row-${p.state}`}>
                <td>
                  <span className="mono">{p.node_id}</span>
                  {p.self && <span className="tag">this node</span>}
                  {p.tier === 2 && <span className="tag tag-warn" title="Estimated fetch time above 3× the cluster median for 30 s">slow tier</span>}
                  <div className="sub mono">
                    {p.host_id} · {p.addr}
                  </div>
                </td>
                <td>
                  <span className={`dot dot-${p.state}`} /> {p.state}
                </td>
                <td className="num">{p.self ? "—" : `${p.rtt_ms.toFixed(1)} ms`}</td>
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
