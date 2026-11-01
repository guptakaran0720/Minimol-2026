import type { Stats } from "../api";

function ago(t: number): string {
  const s = Math.max(0, Date.now() / 1000 - t);
  return s < 60 ? `${s.toFixed(0)} s ago` : `${(s / 60).toFixed(0)} min ago`;
}

export function Repair({ repair }: { repair: Stats["repair"] }) {
  const last = repair.last_round;
  return (
    <section className="card">
      <header className="card-head">
        <h2>Self-repair</h2>
        <span className="muted">every 10 s · this node</span>
      </header>
      <dl className="metrics compact">
        <div>
          <dt>Copies made</dt>
          <dd className="big">{repair.total_copies}</dd>
        </div>
        <div>
          <dt>Chunks checked</dt>
          <dd>{last?.checked ?? "—"}</dd>
        </div>
        <div>
          <dt>Waiting on suspect peer</dt>
          <dd>{last?.waiting ?? "—"}</dd>
        </div>
        <div>
          <dt>Degraded</dt>
          <dd className={last?.degraded ? "warn" : ""}>{last?.degraded ?? "—"}</dd>
        </div>
      </dl>
      {repair.events.length === 0 ? (
        <p className="empty">No repairs yet. Stop a peer to watch chunks get re-copied.</p>
      ) : (
        <ul className="events">
          {[...repair.events].reverse().map((e, i) => (
            <li key={`${e.t}-${i}`}>
              <span className="muted">{ago(e.t)}</span>{" "}
              {e.kind === "copied" ? (
                <>
                  copied chunk <span className="mono">{e.chunk}</span> → <span className="mono">{e.to}</span>
                </>
              ) : (
                <>
                  local copy of <span className="mono">{e.chunk}</span> failed its hash check; not spread
                </>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
