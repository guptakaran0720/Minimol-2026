// Turns successive polls into a short log of what changed, for the live ticker.
// Repair events come from the node; peer, tier and file changes are spotted here by
// comparing each poll with the previous one.
import { useEffect, useRef, useState } from "react";
import type { FileEntry, Stats, UploadResult } from "./api";
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

export function useClusterFeed(stats: Stats | null, files: FileEntry[] | null, upload: UploadResult | null) {
  const [items, setItems] = useState<FeedItem[]>([]);
  const peersBefore = useRef<Map<string, { state: string; tier: number }> | null>(null);
  const filesBefore = useRef<Map<string, { status: string; version: number }> | null>(null);
  const seenRepairs = useRef(new Set<string>());
  const lastUpload = useRef<UploadResult | null>(null);

  const push = (fresh: FeedItem[]) => {
    if (fresh.length === 0) return;
    setItems((old) => {
      const known = new Set(old.map((i) => i.key));
      const add = fresh.filter((i) => !known.has(i.key));
      return [...add, ...old].sort((a, b) => b.t - a.t).slice(0, KEEP);
    });
  };

  useEffect(() => {
    if (!stats) return;
    const now = Date.now() / 1000;
    const fresh: FeedItem[] = [];

    for (const e of stats.repair.events) {
      const key = `r-${e.t}-${e.chunk}-${e.to ?? ""}`;
      if (seenRepairs.current.has(key)) continue;
      seenRepairs.current.add(key);
      fresh.push(
        e.kind === "copied"
          ? { key, t: e.t, tone: "green", text: `chunk ${e.chunk.slice(0, 12)} re-copied → ${e.to}` }
          : { key, t: e.t, tone: "red", text: `local copy of ${e.chunk.slice(0, 12)} failed its hash check` },
      );
    }

    const prev = peersBefore.current;
    const next = new Map(stats.peers.map((p) => [p.node_id, { state: p.state, tier: p.tier }]));
    if (prev) {
      for (const p of stats.peers) {
        const was = prev.get(p.node_id);
        const key = (what: string) => `p-${p.node_id}-${what}-${Math.floor(now)}`;
        if (!was) {
          fresh.push({ key: key("joined"), t: now, tone: "blue", text: `${p.node_id} joined the cluster` });
          continue;
        }
        if (was.state !== p.state) {
          if (p.state === "dead")
            fresh.push({ key: key("dead"), t: now, tone: "red", text: `${p.node_id} is dead · no heartbeat for 20 s` });
          else if (p.state === "suspect")
            fresh.push({ key: key("suspect"), t: now, tone: "yellow", text: `${p.node_id} missed heartbeats · repair waits` });
          else fresh.push({ key: key("back"), t: now, tone: "blue", text: `${p.node_id} is back` });
        }
        if (was.tier !== p.tier && p.state === "alive") {
          fresh.push(
            p.tier === 2
              ? { key: key("slow"), t: now, tone: "yellow", text: `${p.node_id} moved to the slow tier · ${p.rtt_ms.toFixed(0)} ms` }
              : { key: key("fast"), t: now, tone: "blue", text: `${p.node_id} is fast again` },
          );
        }
      }
    }
    peersBefore.current = next;
    push(fresh);
  }, [stats]);

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

  return items;
}
