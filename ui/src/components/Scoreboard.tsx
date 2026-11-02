// The arcade score panels beside the playfield. Every number comes from /stats or the
// selected file's chunk map; nothing here is made up.
import type { ChunkMap, Peer, Stats } from "../api";

function Heart({ on }: { on: boolean }) {
  return (
    <svg className={`heart ${on ? "on" : ""}`} width="28" height="24" viewBox="0 0 7 6" shapeRendering="crispEdges" aria-hidden="true">
      <rect x="1" y="0" width="2" height="1" />
      <rect x="4" y="0" width="2" height="1" />
      <rect x="0" y="1" width="7" height="2" />
      <rect x="1" y="3" width="5" height="1" />
      <rect x="2" y="4" width="3" height="1" />
      <rect x="3" y="5" width="1" height="1" />
    </svg>
  );
}

export function Scoreboard({
  stats,
  peers,
  unlocked,
  map,
  wide = false,
}: {
  stats: Stats;
  peers: Peer[];
  unlocked: boolean;
  map: ChunkMap | null;
  wide?: boolean;
}) {
  const alive = peers.filter((p) => p.state === "alive").length;
  const f = stats.files;
  const target = map?.replication ?? 3;
  const lives = map && map.chunks.length ? Math.min(...map.chunks.map((c) => c.live_hosts)) : target;
  const others = peers.filter((p) => !p.self && p.state === "alive" && p.rtt_ms > 0);
  const worst = others.reduce<Peer | null>((m, p) => (!m || p.rtt_ms > m.rtt_ms ? p : m), null);

  return (
    <section className={`scoreboard ${wide ? "s7" : "s3"} r2`} aria-label="Scoreboard">
      <div className="score score-blue">
        <h2 className="score-label">Players</h2>
        <p className="score-value">
          {alive}
          <span className="score-of">/{peers.length}</span>
        </p>
        <p className="score-sub">laptops alive</p>
      </div>
      <div className="score score-yellow">
        <h2 className="score-label">Files safe</h2>
        {unlocked ? (
          <>
            <p className="score-value">
              {f.healthy}
              <span className="score-of">/{f.count}</span>
            </p>
            <p className="score-sub">
              {f.degraded} healing · {f.unavailable} lost
            </p>
          </>
        ) : (
          <p className="score-sub">press start to see them</p>
        )}
      </div>
      <div className="score score-green">
        <h2 className="score-label">Lives</h2>
        <p className="hearts" role="img" aria-label={`${lives} of ${target} copies of every chunk in the selected file`}>
          {Array.from({ length: Math.max(target, lives) }, (_, i) => (
            <Heart key={i} on={i < lives} />
          ))}
        </p>
        <p className="score-sub">copies of the file on the playfield</p>
      </div>
      <div className="score score-red">
        <h2 className="score-label">Respawns</h2>
        <p className="score-value">{stats.repair.total_copies}</p>
        <p className="score-sub">chunks re-copied by this laptop</p>
      </div>
      <div className="score score-violet">
        <h2 className="score-label">Worst ping</h2>
        <p className="score-value score-value-sm">{worst ? `${worst.rtt_ms.toFixed(0)}ms` : "—"}</p>
        <p className="score-sub">{worst ? `${worst.node_id}${worst.tier === 2 ? " · slow tier" : ""}` : "no other laptop yet"}</p>
      </div>
    </section>
  );
}
