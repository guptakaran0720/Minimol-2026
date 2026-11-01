import type { ChunkMap, FileEntry, Peer } from "../api";

export function ChunkMapView({ map, file, peers }: { map: ChunkMap | null; file: FileEntry | undefined; peers: Peer[] }) {
  if (!file) {
    return (
      <section className="card">
        <h2>Chunk map</h2>
        <p className="empty">Select a file to see which peers hold each chunk.</p>
      </section>
    );
  }
  const columns = peers.map((p) => p.node_id);
  return (
    <section className="card">
      <header className="card-head">
        <h2>
          Chunk map <span className="muted">· {file.name}</span>
        </h2>
        {map && <span className={`badge badge-${map.status}`}>{map.status}</span>}
      </header>
      <p className="muted small">
        Each row is one encrypted chunk. A filled cell means that peer holds a copy; the target is {map?.replication ?? 3}{" "}
        copies on distinct hosts.
      </p>
      {!map ? (
        <p className="empty">Loading…</p>
      ) : (
        <div className="table-wrap">
          <table className="chunkmap">
            <thead>
              <tr>
                <th>#</th>
                <th>Chunk</th>
                {columns.map((c) => (
                  <th key={c} className="mono center">
                    {c}
                  </th>
                ))}
                <th className="num">Live copies</th>
              </tr>
            </thead>
            <tbody>
              {map.chunks.map((row) => {
                const held = new Map(row.holders.map((h) => [h.node_id, h.state]));
                return (
                  <tr key={row.chunk_id}>
                    <td>{row.index}</td>
                    <td className="mono" title={row.chunk_id}>
                      {row.chunk_id.slice(0, 10)}…
                    </td>
                    {columns.map((c) => {
                      const state = held.get(c);
                      return (
                        <td key={c} className="center">
                          <span className={`cell ${state ? `cell-${state}` : "cell-none"}`} title={state ? `${c}: ${state}` : ""} />
                        </td>
                      );
                    })}
                    <td className={`num ${row.live_hosts < map.replication ? "warn" : ""}`}>
                      {row.live_hosts}/{map.replication}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
