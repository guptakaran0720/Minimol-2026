import type { Stats } from "../api";
import { clock } from "../identity";

export function Repair({ repair, wide = false }: { repair: Stats["repair"]; wide?: boolean }) {
  const last = repair.last_round;
  return (
    <section className={`tile tile-white tile-list ${wide ? "s12" : "s5"}`} aria-labelledby="repair-title">
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
      {repair.events.length === 0 ? (
        <p className="empty">No repairs yet. Close a laptop's lid to watch its chunks get re-copied.</p>
      ) : (
        <ol className="events">
          {[...repair.events].reverse().map((e, i) => (
            <li key={`${e.t}-${i}`}>
              <time className="mono muted">{clock(e.t)}</time>
              <span>
                {e.kind === "copied" ? (
                  <>
                    copied chunk <span className="mono">{e.chunk}</span> → <span className="mono">{e.to}</span>
                  </>
                ) : (
                  <span className="bad-ink">
                    local copy of <span className="mono">{e.chunk}</span> failed its hash check; not spread
                  </span>
                )}
              </span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
