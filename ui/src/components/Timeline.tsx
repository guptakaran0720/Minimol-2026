import type { Timeline as TimelineData } from "../api";
import { describeEvent, eventKey } from "../feed";
import { clock } from "../identity";

/** P2's cluster timeline (GET /events) as a bento tile: newest first, colour per kind. */
export function Timeline({ data, wide = false }: { data: TimelineData | null; wide?: boolean }) {
  const events = data?.events ?? [];
  return (
    <section className={`tile tile-white tile-list ${wide ? "s7" : "s5"}`} aria-labelledby="timeline-title">
      <div className="tile-head">
        <h2 id="timeline-title" className="tile-title">
          Cluster timeline
        </h2>
        <span className="muted small">this laptop's view · newest first</span>
      </div>
      {events.length === 0 ? (
        <p className="empty">Nothing yet. Stop a peer or corrupt a chunk to watch the cluster react.</p>
      ) : (
        <ol className="events timeline">
          {events.map((e) => {
            const { tone, text } = describeEvent(e);
            return (
              <li key={eventKey(e)}>
                <span className={`tl-dot tone-${tone}`} aria-hidden="true" />
                <time className="mono muted">{clock(e.t)}</time>
                <span>{text}</span>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
