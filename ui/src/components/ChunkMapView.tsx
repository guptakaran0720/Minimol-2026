import type { ChunkMap, FileEntry, Peer } from "../api";
import { PeerMark, type Look } from "../identity";

/** The selected file as a block "well": one column per laptop, one row per chunk. */
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
    <section className="tile tile-white tile-list tile-well s4 r2" aria-labelledby="map-title">
      <div className="tile-head">
        <h2 id="map-title" className="tile-title">
          Playfield
        </h2>
        {map && <span className={`badge badge-${map.status}`}>{map.status}</span>}
      </div>
      {!file ? (
        <p className="empty">Pick a file to see which laptops hold each chunk.</p>
      ) : (
        <>
          <p className="muted small">
            <b className="well-file">{file.name}</b> · each row is one encrypted chunk, each column a laptop. Target:{" "}
            {map?.replication ?? 3} copies.
          </p>
          {!map ? (
            <p className="empty">Loading…</p>
          ) : (
            <div className="table-wrap scroll well-wrap">
              <table className="chunkmap well">
                <thead>
                  <tr>
                    <th scope="col">
                      <span className="visually-hidden">Chunk</span>#
                    </th>
                    {columns.map((p) => (
                      <th key={p.node_id} scope="col" className="center" title={p.node_id}>
                        <span className="col-head">
                          <PeerMark look={looks.get(p.node_id)} state={p.state} size="sm" />
                          <span className="mono">{p.node_id.replace(/^laptop-/, "L")}</span>
                        </span>
                      </th>
                    ))}
                    <th scope="col" className="num">
                      <span className="visually-hidden">Live copies</span>HP
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {map.chunks.map((row) => {
                    const held = new Map(row.holders.map((h) => [h.node_id, h.state]));
                    return (
                      <tr key={row.chunk_id} title={row.chunk_id}>
                        <th scope="row" className="muted">
                          {row.index}
                        </th>
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
