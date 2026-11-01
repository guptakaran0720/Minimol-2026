import type { ClusterEvent, Timeline as TimelineData } from "../api";

function clock(t: number): string {
  return new Date(t * 1000).toLocaleTimeString([], { hour12: false });
}

function tone(e: ClusterEvent): string {
  if (e.kind === "peer_dead" || e.kind === "chunk_quarantined" || e.kind === "chunk_missing" || e.kind === "corrupt_local")
    return "bad";
  if (e.kind === "peer_suspect" || e.kind === "peer_slow") return "warn";
  if (e.kind === "copied" || e.kind === "peer_alive" || e.kind === "peer_joined" || e.kind === "peer_fast") return "ok";
  return "";
}

function describe(e: ClusterEvent) {
  const node = <span className="mono">{e.node}</span>;
  const chunk = <span className="mono">{e.chunk}</span>;
  switch (e.kind) {
    case "node_started":
      return <>{node} started with {e.chunks} chunks on disk</>;
    case "peer_joined":
      return <>{node} joined ({e.addr})</>;
    case "peer_suspect":
      return <>{node} is suspect: {e.reason}</>;
    case "peer_dead":
      return <>{node} is dead: {e.reason}</>;
    case "peer_alive":
      return <>{node} is back ({e.previous} → alive)</>;
    case "peer_slow":
      return <>{node} moved to the slow tier (no new chunks)</>;
    case "peer_fast":
      return <>{node} is fast again (back to tier 1)</>;
    case "chunk_quarantined":
      return <>chunk {chunk} on {node} failed its hash check: quarantined, repair will restore it</>;
    case "chunk_missing":
      return <>chunk {chunk} vanished from {node}'s disk</>;
    case "copied":
      return <>repair copied chunk {chunk} → <span className="mono">{e.to}</span></>;
    case "corrupt_local":
      return <>repair skipped a corrupt local copy of {chunk}</>;
    default:
      return <>{e.kind}</>;
  }
}

export function Timeline({ data }: { data: TimelineData | null }) {
  const events = data?.events ?? [];
  const scrub = data?.scrub;
  return (
    <section className="card">
      <header className="card-head">
        <h2>Cluster timeline</h2>
        {scrub && (
          <span className="muted">
            scrub: {scrub.checked} checked · {scrub.passes} passes · {scrub.quarantined} quarantined
          </span>
        )}
      </header>
      {events.length === 0 ? (
        <p className="empty">Nothing yet. Stop a peer or corrupt a chunk to watch the cluster react.</p>
      ) : (
        <ul className="events timeline">
          {events.map((e) => (
            <li key={`${e.source}-${e.seq ?? ""}-${e.t}-${e.kind}`} className={`tl-${tone(e)}`}>
              <span className="muted mono">{clock(e.t)}</span> {describe(e)}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
