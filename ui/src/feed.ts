// What the live ticker and the timeline tile say. Cluster events (peers joining,
// going suspect or dead, tier moves, scrub finds, repair copies) come from the
// node's GET /events. File status changes and this laptop's uploads are spotted
// here by comparing each poll with the previous one.
import { useEffect, useRef, useState } from "react";
import type { ClusterEvent, FileEntry, Stats, Timeline, UploadResult } from "./api";
import { formatBytes } from "./api";
import type { Tone } from "./identity";

export interface FeedItem {
  key: string;
  t: number; // unix seconds
  tone: Tone;
  text: string;
}

const KEEP = 12;

export function squeeze(original: number, encoded: number): string {
  if (original <= 0 || encoded <= 0 || encoded >= original) return "stored as-is";
  const factor = original / encoded;
  if (factor >= 2) return `${Math.round(factor).toLocaleString()}× smaller`;
  return `${Math.round((1 - encoded / original) * 100)}% smaller`;
}

export function eventKey(e: ClusterEvent): string {
  return `${e.source}-${e.seq ?? ""}-${e.t}-${e.kind}-${e.chunk ?? ""}`;
}

/** One line of plain text and a colour for a node or repair event. */
export function describeEvent(e: ClusterEvent): { tone: Tone; text: string } {
  const chunk = e.chunk?.slice(0, 12);
  switch (e.kind) {
    case "node_started":
      return { tone: "blue", text: `${e.node} started with ${e.chunks ?? 0} chunks on disk` };
    case "peer_joined":
      return { tone: "blue", text: `${e.node} joined${e.addr ? ` from ${e.addr}` : ""}` };
    case "peer_suspect":
      return { tone: "yellow", text: `${e.node} is suspect · ${e.reason ?? "missed heartbeats"}` };
    case "peer_dead":
      return { tone: "red", text: `${e.node} is dead · ${e.reason ?? "no contact"}` };
    case "peer_alive":
      return { tone: "green", text: `${e.node} is back${e.previous ? ` (was ${e.previous})` : ""}` };
    case "peer_slow":
      return { tone: "yellow", text: `${e.node} moved to the slow tier · no new chunks` };
    case "peer_fast":
      return { tone: "green", text: `${e.node} is fast again` };
    case "chunk_quarantined":
      return { tone: "red", text: `chunk ${chunk} on ${e.node} failed its hash check · quarantined, repair restores it` };
    case "chunk_missing":
      return { tone: "red", text: `chunk ${chunk} vanished from ${e.node}'s disk` };
    case "copied":
      return { tone: "green", text: `repair copied chunk ${chunk} → ${e.to}` };
    case "corrupt_local":
      return { tone: "red", text: `repair skipped a corrupt local copy of ${chunk}` };
    default:
      return { tone: "blue", text: e.kind.replace(/_/g, " ") };
  }
}

export function useClusterFeed(
  timeline: Timeline | null,
  stats: Stats | null,
  files: FileEntry[] | null,
  upload: UploadResult | null,
): FeedItem[] {
  const [local, setLocal] = useState<FeedItem[]>([]);
  const filesBefore = useRef<Map<string, { status: string; version: number }> | null>(null);
  const lastUpload = useRef<UploadResult | null>(null);

  const push = (fresh: FeedItem[]) => {
    if (fresh.length === 0) return;
    setLocal((old) => {
      const known = new Set(old.map((i) => i.key));
      return [...fresh.filter((i) => !known.has(i.key)), ...old].sort((a, b) => b.t - a.t).slice(0, KEEP);
    });
  };

  useEffect(() => {
    if (!files) return;
    const now = Date.now() / 1000;
    const fresh: FeedItem[] = [];
    const prev = filesBefore.current;
    const mine = lastUpload.current;
    if (prev) {
      for (const f of files) {
        const was = prev.get(f.file_uuid);
        const key = (what: string) => `f-${f.file_uuid}-${what}-${f.version}`;
        const justUploaded = mine?.file_uuid === f.file_uuid && mine.version === f.version;
        if ((!was || was.version !== f.version) && !justUploaded) {
          fresh.push({ key: key("new"), t: now, tone: "blue", text: `${f.name} v${f.version} arrived from another laptop` });
        } else if (was && was.status !== f.status) {
          const tone = f.status === "healthy" ? "green" : f.status === "degraded" ? "yellow" : "red";
          fresh.push({ key: `${key(f.status)}-${Math.floor(now)}`, t: now, tone, text: `${f.name} is ${f.status}` });
        }
      }
    }
    filesBefore.current = new Map(files.map((f) => [f.file_uuid, { status: f.status, version: f.version }]));
    push(fresh);
  }, [files]);

  useEffect(() => {
    if (!upload || upload === lastUpload.current) return;
    lastUpload.current = upload;
    const total = upload.sent_chunks + upload.reused_chunks;
    const sent = upload.reused_chunks > 0 ? `${upload.sent_chunks} of ${total} chunks sent` : `${total} chunk${total === 1 ? "" : "s"} sent`;
    push([
      {
        key: `u-${upload.file_uuid}-${upload.version}`,
        t: Date.now() / 1000,
        tone: "blue",
        text: `${upload.name} v${upload.version} saved · ${formatBytes(upload.original_bytes)}, ${squeeze(upload.original_bytes, upload.encoded_bytes)} · ${sent}`,
      },
    ]);
  }, [upload]);

  // Prefer the node's timeline; fall back to /stats repair events if /events is unreachable.
  const cluster: ClusterEvent[] =
    timeline?.events ?? (stats?.repair.events ?? []).map((e) => ({ ...e, source: "repair" as const }));
  const remote = cluster.slice(0, KEEP).map((e) => ({ key: eventKey(e), t: e.t, ...describeEvent(e) }));
  return [...remote, ...local].sort((a, b) => b.t - a.t).slice(0, KEEP);
}
