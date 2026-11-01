// The small bento tiles: one number each, read from /stats.
import type { Peer, Stats } from "../api";
import { PeerMark, type Look } from "../identity";

export function PeersTile({ peers, looks }: { peers: Peer[]; looks: Map<string, Look> }) {
  const alive = peers.filter((p) => p.state === "alive").length;
  return (
    <section className="tile tile-white s4" aria-labelledby="peers-tile">
      <div className="tile-head">
        <h2 id="peers-tile" className="tile-label">
          Peers alive
        </h2>
        <span className="muted small">every 2 s</span>
      </div>
      <div className="tile-foot">
        <span className="figure">
          {alive}
          <span className="figure-of">/{peers.length}</span>
        </span>
        <span className="marks">
          {[...peers]
            .sort((a, b) => a.node_id.localeCompare(b.node_id))
            .slice(0, 8)
            .map((p) => (
              <PeerMark key={p.node_id} look={looks.get(p.node_id)} state={p.state} title={`${p.node_id}: ${p.state}`} />
            ))}
        </span>
      </div>
    </section>
  );
}

export function HealthTile({ stats, unlocked }: { stats: Stats; unlocked: boolean }) {
  const f = stats.files;
  return (
    <section className="tile tile-yellow s3" aria-labelledby="health-tile">
      <h2 id="health-tile" className="pill pill-white">
        Files healthy
      </h2>
      {unlocked ? (
        <div>
          <span className="figure">
            {f.healthy}
            <span className="figure-of">/{f.count}</span>
          </span>
          <p className="tile-sub">
            <span className={f.degraded ? "warn-ink" : ""}>{f.degraded} degraded</span> ·{" "}
            <span className={f.unavailable ? "bad-ink" : ""}>{f.unavailable} unavailable</span>
          </p>
        </div>
      ) : (
        <p className="tile-sub">Unlock to see how your files are doing.</p>
      )}
    </section>
  );
}

export function LinkTile({ peers, looks }: { peers: Peer[]; looks: Map<string, Look> }) {
  const others = peers.filter((p) => !p.self).sort((a, b) => a.node_id.localeCompare(b.node_id));
  const live = others.filter((p) => p.state === "alive" && p.rtt_ms > 0);
  const slowest = live.reduce<Peer | null>((m, p) => (!m || p.rtt_ms > m.rtt_ms ? p : m), null);
  const slowTier = others.filter((p) => p.tier === 2 && p.state === "alive");
  const top = Math.max(1, ...live.map((p) => p.rtt_ms));

  return (
    <section className="tile tile-white s4" aria-labelledby="link-tile">
      <h2 id="link-tile" className="tile-label">
        Slowest link
      </h2>
      {slowest ? (
        <>
          <p className="figure-line">
            <span className="figure figure-md">{slowest.rtt_ms.toFixed(1)}</span>
            <span className="muted">ms · {slowest.node_id}</span>
          </p>
          <div
            className="bars"
            role="img"
            aria-label={live.map((p) => `${p.node_id} ${p.rtt_ms.toFixed(1)} ms`).join(", ")}
          >
            {others.map((p) => (
              <span key={p.node_id} className="bar-col" title={`${p.node_id}: ${p.state === "alive" ? `${p.rtt_ms.toFixed(1)} ms` : p.state}`}>
                <span
                  className={`bar tone-${looks.get(p.node_id)?.tone ?? "blue"} ${p.state !== "alive" ? "bar-off" : ""}`}
                  style={{ height: `${p.state === "alive" ? Math.max(10, (p.rtt_ms / top) * 100) : 10}%` }}
                />
              </span>
            ))}
          </div>
          <p className="muted small">
            {slowTier.length
              ? `${slowTier.map((p) => p.node_id).join(", ")} ${slowTier.length === 1 ? "is" : "are"} in the slow tier: new chunks skip ${slowTier.length === 1 ? "it" : "them"} while faster laptops have room.`
              : "Every live peer is in the fast tier."}
          </p>
        </>
      ) : (
        <p className="muted small">No other laptop has answered yet. Start one with SEEDS pointing at this laptop's IP.</p>
      )}
    </section>
  );
}

export function RepairTile({ repair }: { repair: Stats["repair"] }) {
  const last = repair.last_round;
  return (
    <section className="tile tile-green tile-center s3" aria-labelledby="repair-tile">
      <span className="ring">
        <span className="figure figure-md">{repair.total_copies}</span>
        <span className="ring-unit">{repair.total_copies === 1 ? "copy" : "copies"}</span>
      </span>
      <h2 id="repair-tile" className="tile-label">
        re-made by this laptop
      </h2>
      <p className="tile-sub">{last ? `${last.checked ?? 0} chunks checked last round` : "first check within 10 s"}</p>
    </section>
  );
}

export function RecoveryTile({ username, codec }: { username: string | null; codec: string }) {
  const fake = codec.startsWith("FAKE");
  return (
    <section className="tile tile-ink s4" aria-labelledby="recovery-tile">
      <h2 id="recovery-tile" className="tile-label">
        Recovery
      </h2>
      <p className="tile-statement">
        {username ? (
          <>
            Lost this laptop? Type <b>{username}</b> and your passphrase on any other one. Every file comes back.
          </>
        ) : (
          <>Your keys never leave this laptop. They are re-derived from your username and passphrase.</>
        )}
      </p>
      <p className={`tile-foot-note ${fake ? "warn-on-ink" : ""}`}>
        {fake ? "DEV codec: chunks are NOT encrypted" : `crypto: ${codec}`}
      </p>
    </section>
  );
}
