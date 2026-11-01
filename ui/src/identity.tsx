// Gives every peer a stable colour and shape so it reads the same in every tile,
// the ticker, the chunk map and the peers table.
import type { Peer, PeerState } from "./api";

export type Tone = "blue" | "red" | "yellow" | "green";
export type Shape = "square" | "circle" | "leaf";

const TONES: Tone[] = ["blue", "red", "yellow", "green"];
const SHAPES: Shape[] = ["square", "circle", "leaf"];

export interface Look {
  tone: Tone;
  shape: Shape;
}

/** node_id -> look, assigned in node_id order so it does not change between polls. */
export function peerLooks(peers: Peer[]): Map<string, Look> {
  const ids = peers.map((p) => p.node_id).sort();
  return new Map(ids.map((id, i) => [id, { tone: TONES[i % TONES.length], shape: SHAPES[i % SHAPES.length] }]));
}

export function PeerMark({
  look,
  state = "alive",
  size = "md",
  title,
}: {
  look: Look | undefined;
  state?: PeerState | "unknown";
  size?: "sm" | "md" | "lg";
  title?: string;
}) {
  const l = look ?? { tone: "blue", shape: "square" };
  return (
    <span
      className={`mark mark-${size} shape-${l.shape} tone-${l.tone} state-${state}`}
      title={title}
      aria-hidden={title ? undefined : true}
      role={title ? "img" : undefined}
      aria-label={title}
    />
  );
}

export function clock(t: number): string {
  return new Date(t * 1000).toLocaleTimeString([], { hour12: false });
}
