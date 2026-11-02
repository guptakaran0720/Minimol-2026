import type { Stats, Timeline } from "../api";
import { clock } from "../identity";

/** Repair and scrub counters. The events themselves are in the timeline tile and the ticker. */
export function Repair({ repair, scrub }: { repair: Stats["repair"]; scrub: Timeline["scrub"] | null }) {
  const last = repair.last_round;
  return (
    <section className="tile tile-white tile-list s7" aria-labelledby="repair-title">
      <div className="tile-head">
        <h2 id="repair-title" className="tile-title">
          Self-repair
        </h2>
        <span className="muted small">every 10 s · this laptop</span>
      </div>
      <dl className="stat-row">
        <div>
          <dt>Copies made</dt>
          <dd>{repair.total_copies}</dd>
        </div>
        <div>
          <dt>Chunks checked</dt>
          <dd>{last?.checked ?? "—"}</dd>
        </div>
        <div>
          <dt>Waiting on suspect</dt>
          <dd>{last?.waiting ?? "—"}</dd>
        </div>
        <div>
          <dt>Degraded</dt>
          <dd className={last?.degraded ? "warn-ink" : ""}>{last?.degraded ?? "—"}</dd>
        </div>
      </dl>
      <div className="tile-head">
        <h3 className="tile-label">Background scrub</h3>
        <span className="muted small">
          {scrub?.last_pass_at ? `last full pass ${clock(scrub.last_pass_at)}` : "re-hashes every chunk on this disk"}
        </span>
      </div>
      {scrub ? (
        <dl className="stat-row">
          <div>
            <dt>Re-hashed</dt>
            <dd>{scrub.checked}</dd>
          </div>
          <div>
            <dt>Passes</dt>
            <dd>{scrub.passes}</dd>
          </div>
          <div>
            <dt>Quarantined</dt>
            <dd className={scrub.quarantined ? "bad-ink" : ""}>{scrub.quarantined}</dd>
          </div>
          <div>
            <dt>Missing</dt>
            <dd className={scrub.missing ? "bad-ink" : ""}>{scrub.missing}</dd>
          </div>
        </dl>
      ) : (
        <p className="empty">Scrub figures appear once this node's timeline answers.</p>
      )}
    </section>
  );
}
