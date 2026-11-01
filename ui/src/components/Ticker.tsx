import type { FeedItem } from "../feed";
import { clock, type Tone } from "../identity";

export interface TickerLine {
  text: string;
  tone: Tone;
}

/** The tilted black band: live status first, then the newest cluster events. Pauses on hover. */
export function Ticker({ status, items }: { status: TickerLine[]; items: FeedItem[] }) {
  const lines = [
    ...status.map((s, i) => ({ key: `status-${i}`, t: null as number | null, ...s })),
    ...items.map((i) => ({ key: i.key, t: i.t as number | null, text: i.text, tone: i.tone })),
  ];
  const chars = lines.reduce((n, l) => n + l.text.length + 10, 0);
  const seconds = Math.max(20, Math.round(chars * 0.16));

  const run = (copy: boolean) => (
    <ul className="ticker-run" aria-hidden={copy || undefined}>
      {lines.map((l) => (
        <li key={l.key}>
          {l.t !== null && <time className="mono">{clock(l.t)}</time>}
          <span>{l.text}</span>
          <span className={`ticker-dot tone-${l.tone}`} aria-hidden="true" />
        </li>
      ))}
    </ul>
  );

  return (
    <section className="ticker" aria-label="Live cluster events">
      <div className="ticker-track" style={{ animationDuration: `${seconds}s` }}>
        {run(false)}
        {run(true)}
      </div>
    </section>
  );
}
