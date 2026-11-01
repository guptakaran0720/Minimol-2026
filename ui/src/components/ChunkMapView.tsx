import type { ChunkMap, FileEntry, Peer } from "../api";
import { PeerMark, type Look } from "../identity";

export function ChunkMapView({
  map,
  file,
  peers,
  looks,
}: {
  map: ChunkMap | null;
  file: FileEntry | undefined;
  peers: Peer[];
  looks: Map<string, Look>;
}) {
  const columns = [...peers].sort((a, b) => a.node_id.localeCompare(b.node_id));
  return (
    <section className="tile tile-white tile-list s7" aria-labelledby="map-title">
      <div className="tile-head">
        <h2 id="map-title" className="tile-title">
          Chunk map {file && <span className="tile-title-sub">· {file.name}</span>}
        </h2>
        {map && <span className={`badge badge-${map.status}`}>{map.status}</span>}
      </div>
      {!file ? (
        <p className="empty">Pick a file to see which laptops hold each chunk.</p>
      ) : (
        <>
          <p className="muted small">
            Each row is one encrypted chunk. A filled cell is a copy on that laptop; the target is {map?.replication ?? 3} copies on
            different laptops.
          </p>
          {!map ? (
            <p className="empty">Loading…</p>
          ) : (
            <div className="table-wrap scroll">
              <table className="chunkmap">
                <thead>
                  <tr>
                    <th scope="col">#</th>
                    <th scope="col">Chunk</th>
                    {columns.map((p) => (
                      <th key={p.node_id} scope="col" className="center">
                        <span className="col-head">
                          <PeerMark look={looks.get(p.node_id)} state={p.state} size="sm" />
                          <span className="mono">{p.node_id}</span>
                        </span>
                      </th>
                    ))}
                    <th scope="col" className="num">
                      Live copies
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {map.chunks.map((row) => {
                    const held = new Map(row.holders.map((h) => [h.node_id, h.state]));
                    return (
                      <tr key={row.chunk_id}>
                        <td className="muted">{row.index}</td>
                        <td className="mono" title={row.chunk_id}>
                          {row.chunk_id.slice(0, 10)}…
                        </td>
                        {columns.map((p) => {
                          const state = held.get(p.node_id);
                          const tone = looks.get(p.node_id)?.tone ?? "blue";
                          return (
                            <td key={p.node_id} className="center">
                              <span
                                className={`cell ${state ? `cell-${state} tone-${tone}` : "cell-none"}`}
                                title={state ? `${p.node_id}: ${state}` : `${p.node_id}: no copy`}
                              />
                            </td>
                          );
                        })}
                        <td className={`num ${row.live_hosts < map.replication ? "warn-ink" : ""}`}>
                          {row.live_hosts}/{map.replication}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </section>
  );
}
